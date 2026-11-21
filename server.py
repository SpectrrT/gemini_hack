"""Wordless prototype server.  Run:  .venv/bin/python server.py   then open http://localhost:5119

WORDLESS_TAPE=replay  no key and no network: everything comes from recorded answers (the default if the
                      tape exists and no key is set).
WORDLESS_TAPE=auto    recorded answers where they exist, the live API otherwise.
WORDLESS_PUBLIC_URL   what the keep-the-card QR code points at (default http://<this machine's LAN address>:<port>).
WORDLESS_HOST         address to listen on (default 0.0.0.0 so a phone can open the card; other machines can
                      only read the card pages, everything else answers 403 to them).
"""
import base64
import io
import json
import os
import socket
import tempfile
import threading
import time
import uuid
from pathlib import Path

import segno
from flask import Flask, Response, abort, jsonify, render_template_string, request, send_file, send_from_directory

from wordless import baseline, card as cards
from wordless import config, evalrun, follow, gemini, table, teach, video
from wordless.signs_routes import bp as signs_bp

app = Flask(__name__, static_folder=None)
app.config["MAX_CONTENT_LENGTH"] = 200 * 1024 * 1024
WEB = config.ROOT / "web"
app.register_blueprint(signs_bp)      # fast sequences: /signs
jobs = {}
tally_lock = threading.Lock()
TALLY = config.RUNS / "tally.json"


def has_key():
    try:
        gemini.api_key()
        return True
    except gemini.ApiError:
        return False


# ---------------------------------------------------------------- who may ask what
LOCAL = ("127.0.0.1", "::1", "::ffff:127.0.0.1")
PUBLIC_PATHS = ("/print/card/", "/cards/", "/qr/")


@app.before_request
def only_the_card_leaves_this_machine():
    """The server listens on the LAN so a phone can open the card from its QR code. Anything else
    (camera sessions, uploads, calls that spend the key) is for this machine only."""
    if request.remote_addr not in LOCAL and not request.path.startswith(PUBLIC_PATHS):
        return jsonify({"error": "only the printable card is served to other devices"}), 403


def lan_address():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as k:
            k.connect(("10.255.255.255", 1))            # no packet is sent; this only picks the outgoing interface
            return k.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def public_url():
    u = os.environ.get("WORDLESS_PUBLIC_URL", "").strip().rstrip("/")
    return u or f"http://{lan_address()}:{int(os.environ.get('PORT', 5119))}"


def card_url(cid):
    return f"{public_url()}/print/card/{cid}"


@app.get("/")
def index():
    return send_from_directory(WEB, "index.html")


@app.get("/web/<path:name>")
def web(name):
    return send_from_directory(WEB, name)


@app.get("/api/status")
def status():
    return jsonify({"tape_mode": gemini.mode(), "has_key": has_key(), "models": config.MODELS, "cards": cards.list_cards(), "public_url": public_url(),
                    "rule": {"min_conf": config.MIN_CONF, "min_mass": config.MIN_MASS, "unsure_mass": config.UNSURE_MASS, "run_gap": config.RUN_GAP}})


# ---------------------------------------------------------------- cards
@app.get("/api/cards/<cid>")
def card_json(cid):
    try:
        c = cards.load(cid)
    except FileNotFoundError:
        abort(404)
    c["recordings"] = follow.recordings_for(c)
    return jsonify(c)


@app.get("/cards/<cid>/<name>")
def card_file(cid, name):
    return send_from_directory(cards.card_dir(cid), name, max_age=0)


@app.get("/video/<rec>.mp4")
def rec_video(rec):
    p = video.find_video(rec)
    if not p:
        abort(404)
    return send_file(p, mimetype="video/mp4", conditional=True)


# ---------------------------------------------------------------- teach
@app.post("/api/teach")
def teach_start():
    """multipart: video=<file>, title=...   or JSON {"from_tape": "<card id>"} to rebuild a taped card."""
    jid = uuid.uuid4().hex[:8]
    job = {"id": jid, "events": [], "done": False, "card": None, "error": None}
    jobs[jid] = job
    if request.files.get("video"):
        f = request.files["video"]
        title = request.form.get("title") or "Routine"
        tmp = Path(tempfile.mkdtemp()) / ("upload" + (Path(f.filename or "").suffix or ".webm"))
        f.save(tmp)
        args = dict(video_path=tmp, card_id=cards.new_id(title), title=title)
    else:
        cid = (request.get_json(silent=True) or {}).get("from_tape")
        if not cid:
            abort(400, "send a video file or {from_tape: card id}")
        if gemini.mode() != "replay":
            abort(400, "Rebuilding from recorded answers only works in replay mode (WORDLESS_TAPE=replay).")
        old = cards.load(cid)
        args = dict(video_path=None, card_id=cid, title=old.get("title", cid))
        job["keep"] = {k: old[k] for k in ("sheet_as_sent", "label_map", "source") if k in old}

    def run():
        try:
            c = teach.build(emit=job["events"].append, **args)
            job["card"] = c["id"]
        except Exception as e:  # shown in the UI; the build log has the stage that failed
            job["error"] = f"{type(e).__name__}: {e}"[:300]
        finally:
            if job.get("keep"):             # fields a rebuild must not lose, even if it failed part-way
                try:
                    c = cards.load(args["card_id"])
                    c.update(job["keep"])
                    cards.save(c)
                except FileNotFoundError:
                    pass
        job["done"] = True
    threading.Thread(target=run, daemon=True).start()
    return jsonify({"job": jid})


@app.get("/api/jobs/<jid>")
def job_state(jid):
    if jid not in jobs:
        abort(404)
    j = jobs[jid]
    return jsonify({k: j[k] for k in ("id", "events", "done", "card", "error")})


# ---------------------------------------------------------------- follow
def _session(sid):
    try:
        return follow.get(sid)
    except KeyError:
        abort(404)


# The demo shell keeps a little state of its own per session (deadline, baseline, labels); wordless/follow.py
# knows nothing about it.
SHELL = {}
UNREACHED = "not reached before the deadline"
LIVE_BASELINE = "baseline needs the whole clip: not available live"


def _taped_windows(card, rec):
    """How many of a recording's windows already have a recorded answer (card + clip, or two stills)."""
    return max(gemini.tape.count(f"follow/{card['id']}/{rec}/{kind}") for kind in ("card", "still"))


def _shell(s, input_label, from_tape, deadline_s, recorded=None):
    try:
        deadline_s = max(0.0, float(deadline_s or 0))
    except (TypeError, ValueError):
        deadline_s = 0.0
    sh = {"input": input_label, "from_tape": from_tape, "deadline_s": deadline_s, "deadline_hit": False,
          "stopped_at": None, "recorded": recorded, "baseline": None, "t0": time.time()}
    SHELL[s.id] = sh
    if deadline_s:
        t = threading.Timer(deadline_s, _force_finish, [s])
        t.daemon = True
        t.start()
    return sh


def _force_finish(s):
    """The hard deadline: finish now from what is buffered. Never waits for a call that is in flight."""
    sh = SHELL.setdefault(s.id, {})
    if s.done:
        return
    sh["deadline_hit"], sh["stopped_at"] = True, round(time.time() - sh.get("t0", s.started), 1)
    if s.source == "replay" and s.total:
        with s.lock:                    # windows the run never reached count as unanswered, so a step they
            for i in range(s.total):    # could be hiding is "not sure", not "never happened"
                if i not in s.answers:
                    s.errors.setdefault(i, UNREACHED)
    s.finish(wait_s=0, backfill_s=-1)
    if s.source == "replay" and not s.fatal:
        s.fatal = "Stopped at the deadline."            # ends the loop that feeds the recording


def _baseline_done(card, h):
    nums = [cards.panel_number(card, x) for x in h["skipped"]]
    text = ("panel " + ", ".join(map(str, nums)) + " never happened") if nums else f"all {len(card['steps'])} panels performed"
    return {"state": "done", "skipped": h["skipped"], "text": text, "lat": h.get("lat")}


def _start_baseline(s, rec):
    sh = SHELL[s.id]
    sh["baseline"] = {"state": "running", "t0": time.time()}

    def run():
        t0 = time.time()
        try:
            out = _baseline_done(s.card, baseline.hydrogen_one_call(s.card, rec))
        except gemini.TapeMiss:
            out = {"state": "none", "text": "baseline not recorded for this recording (replay mode makes no API calls)"}
        except FileNotFoundError:
            out = {"state": "none", "text": "baseline needs the video file: none found for this recording"}
        except gemini.NoCredit:
            out = {"state": "error", "text": "baseline failed: the API key has no credit"}
        except Exception as e:
            out = {"state": "error", "text": f"baseline failed: {type(e).__name__}: {e}"[:160]}
        out["took"] = round(time.time() - t0, 1)
        sh["baseline"] = out
    threading.Thread(target=run, daemon=True).start()


def _state(s):
    st = s.state()
    sh = SHELL.get(s.id)
    if not sh:
        return st
    with s.lock:
        asked = len(s.answers) + len([i for i, why in s.errors.items() if i not in s.answers and why != UNREACHED])
        asked += sum(1 for i, f in list(s.pending.items()) if not f.done() and i not in s.answers and i not in s.errors)
        last = s.answers[max(s.answers)].get("lat") if s.answers else None
    b = sh["baseline"]
    if b and b["state"] == "running":
        b = {"state": "running", "text": f"baseline still running ({time.time() - b['t0']:.0f} s)"}
    st["shell"] = {"mode": "REPLAY" if sh["from_tape"] else "LIVE", "input": sh["input"], "questions": asked, "last_call_s": last,
                   "deadline_s": sh["deadline_s"], "deadline_hit": sh["deadline_hit"], "stopped_at": sh["stopped_at"],
                   "elapsed": round(time.time() - sh["t0"], 1), "recorded": sh["recorded"],
                   "baseline": b or {"state": "none", "text": LIVE_BASELINE}, "card_url": card_url(s.card["id"])}
    return st


@app.post("/api/follow/replay")
def follow_replay():
    d = request.get_json()
    c = cards.load(d["card"])
    rec = d["recording"]
    try:
        s = follow.replay(c, rec, speed=float(d.get("speed", 8)), use_own_thresholds=bool(d.get("own_thresholds")))
    except FileNotFoundError as e:
        abort(400, str(e))
    from_tape = gemini.mode() == "replay" or (gemini.mode() == "auto" and _taped_windows(c, rec) >= (s.total or 1))
    _shell(s, f"recording {rec}", from_tape, d.get("deadline_s"))
    _start_baseline(s, rec)             # in parallel with the card checker, so it is ready by the verdict
    return jsonify(_state(s))


@app.post("/api/follow/live")
def follow_live():
    d = request.get_json()
    if gemini.mode() == "replay":
        abort(400, "The server is in replay mode (no API calls). Restart with WORDLESS_TAPE=auto and a funded key for live checks.")
    s = follow.Session(cards.load(d["card"]), "live", use_own_thresholds=bool(d.get("own_thresholds")))
    _shell(s, "live camera", False, d.get("deadline_s"))
    return jsonify(_state(s))


# ---- recorded runs: the announced fallback (R key). Fed from saved answers only, so it never touches the network.
def _when(ts):
    return time.strftime("%H:%M" if time.localtime(ts)[:3] == time.localtime()[:3] else "%b %d %H:%M", time.localtime(ts))


def recorded_runs(card, exclude=None, prefer=None):
    """Runs that can be played back with the network off: saved live sessions (newest first), then taped recordings."""
    out = []
    for p in config.RUNS.glob("*/session.json") if config.RUNS.is_dir() else []:
        try:
            j = json.loads(p.read_text())
        except (OSError, ValueError):
            continue
        if j.get("card") != card["id"] or j.get("source") != "live" or not j.get("answers") or j.get("id") == exclude:
            continue
        ts = p.stat().st_mtime
        out.append({"recording": j["id"], "ts": ts, "input": "live camera", "windows": len(j["answers"]),
                    "label": f"Recorded run from {_when(ts)} on live camera"})
    out.sort(key=lambda r: -r["ts"])
    taped, d = [], gemini.tape.root / "follow" / card["id"]
    for p in sorted(d.iterdir()) if d.is_dir() else []:
        files = [f for kind in ("card", "still") for f in (p / kind).glob("*.json")]
        if not files or p.name == exclude or any(r["recording"] == p.name for r in out):
            continue
        ts = max(f.stat().st_mtime for f in files)
        taped.append({"recording": p.name, "ts": ts, "input": f"recording {p.name}", "windows": _taped_windows(card, p.name),
                      "label": f"Recorded run (answers saved {_when(ts)}) on recording {p.name}"})
    taped.sort(key=lambda r: r["recording"] != prefer)
    return out + taped


def _saved_answers(card, rec):
    """({window: answer}, windows that had no answer in the original run)."""
    p = config.RUNS / rec / "session.json"
    if p.exists():
        j = json.loads(p.read_text())
        if j.get("answers"):
            return {int(k): a for k, a in j["answers"].items()}, list((j.get("verdict") or {}).get("missing_windows") or [])
    for kind in ("card", "still"):
        d = gemini.tape.root / "follow" / card["id"] / rec / kind
        if d.is_dir():
            return {int(f.stem): json.loads(f.read_text()) for f in d.glob("*.json")}, []
    return {}, []


@app.get("/api/recorded/<cid>")
def recorded_list(cid):
    try:
        c = cards.load(cid)
    except FileNotFoundError:
        abort(404)
    return jsonify(recorded_runs(c))


@app.post("/api/follow/recorded")
def follow_recorded():
    """{"card", "recording"?, "prefer"?, "exclude"?, "speed", "deadline_s"} -> a session fed from saved answers."""
    d = request.get_json()
    c = cards.load(d["card"])
    runs = recorded_runs(c, exclude=d.get("exclude"), prefer=d.get("prefer"))
    run = next((r for r in runs if r["recording"] == d.get("recording")), runs[0] if runs else None)
    if not run:
        abort(400, "No recorded run for this card yet. Finish one follow session first.")
    answers, missing = _saved_answers(c, run["recording"])
    speed = float(d.get("speed") or 8)
    s = follow.Session(c, "replay", recording=run["recording"])
    s.total = len(answers) + len([i for i in missing if i not in answers])
    sh = _shell(s, run["input"], True, d.get("deadline_s"), recorded=run["label"])
    h = gemini.tape.get_json(f"baseline/hydrogen/{c['id']}/{run['recording']}")     # saved answer only: no call is made here
    sh["baseline"] = _baseline_done(c, h) if h else {"state": "none", "text": "baseline was not recorded for this run"}

    def feed():
        try:
            for i in sorted(answers):
                if s.done or s.fatal:
                    break
                s._record(i, lambda a=answers[i]: a)
                time.sleep(config.WINDOW_S / speed if speed > 0 else 0)
            with s.lock:
                if not s.done:
                    for i in missing:                   # unanswered then, unanswered now: the verdict stays the same
                        if i not in s.answers:
                            s.errors[i] = "no answer in the recorded run"
        finally:
            s.finish(wait_s=0)
    threading.Thread(target=feed, daemon=True).start()
    return jsonify(_state(s))


@app.post("/api/follow/<sid>/deadline")
def follow_deadline(sid):
    """The page's own clock asks for the hard stop (the server's timer normally got there first)."""
    s = _session(sid)
    _force_finish(s)
    return jsonify(_state(s))


@app.post("/api/follow/<sid>/frame")
def follow_frame(sid):
    s = _session(sid)
    d = request.get_json()
    stills = [base64.b64decode(x.split(",", 1)[-1]) for x in d["stills"]]
    s.add_stills(int(d["i"]), stills)
    return jsonify({"ok": True})


@app.get("/api/follow/<sid>")
def follow_state(sid):
    return jsonify(_state(_session(sid)))


@app.post("/api/follow/<sid>/finish")
def follow_finish(sid):
    s = _session(sid)
    if s.source == "live":          # a replay finishes itself when its last window is in
        s.finish()
    return jsonify(_state(s))


# ---------------------------------------------------------------- sealed-card tally
def _load_tally():
    return json.loads(TALLY.read_text()) if TALLY.exists() else []


def _save_tally(rows):
    TALLY.parent.mkdir(parents=True, exist_ok=True)
    tmp = TALLY.with_suffix(".tmp")
    tmp.write_text(json.dumps(rows, indent=1))
    os.replace(tmp, TALLY)


judge = table.judge


@app.get("/api/tally")
def tally_get():
    with tally_lock:
        return jsonify(_load_tally())


@app.post("/api/tally")
def tally_add():
    """{"session": id, "sealed": "right" | "skip", "step": "<step id>"} entered after the sealed card is flipped."""
    d = request.get_json()
    s = _session(d["session"])
    if not s.verdict:
        abort(400, "finish the session first")
    truth = d.get("step") if d.get("sealed") == "skip" else None
    row = {"id": uuid.uuid4().hex[:6], "time": time.strftime("%H:%M:%S"), "session": s.id, "card": s.card["id"],
           "sealed": d.get("sealed"), "truth_skipped": truth, "truth_panel": cards.panel_number(s.card, truth) if truth else None,
           "verdict": s.verdict["text"],
           "source": s.source,
           "card_checker": judge(truth, s.verdict["skipped"], s.verdict["unsure"], s.verdict["order_violations"]),
           "hydrogen_one_call": "pending"}
    with tally_lock:        # one row per session: logging again corrects the earlier entry
        _save_tally([r for r in _load_tally() if r["session"] != s.id] + [row])

    def base():     # the one-call baseline on the very same trial, in the background
        try:
            h = baseline.hydrogen_one_call(s.card, s.id if s.source == "live" else s.recording)
            out = judge(truth, h["skipped"], [])
        except gemini.TapeMiss:
            out = "not recorded"
        except Exception as e:
            out = f"error: {type(e).__name__}"
        with tally_lock:
            rows = _load_tally()
            for r in rows:
                if r["id"] == row["id"]:
                    r["hydrogen_one_call"] = out
            _save_tally(rows)
    threading.Thread(target=base, daemon=True).start()
    return jsonify(row)


# ---------------------------------------------------------------- table prep (works with no key)
def _table_state():
    m = table.load()
    gate = config.RUNS / "gate_g2.json"
    return {"kit_steps": m["kit_steps"], "clips": sorted(m["clips"].values(), key=lambda c: c["time"]),
            "need": table.readiness(m), "can_run": gemini.mode() != "replay" and has_key(),
            "last_gate": json.loads(gate.read_text()) if gate.exists() else None}


@app.get("/api/table")
def table_get():
    return jsonify(_table_state())


@app.post("/api/table/kit")
def table_kit():
    try:
        table.set_kit_steps((request.get_json() or {}).get("steps"))
    except (TypeError, ValueError) as e:
        abort(400, str(e))
    return jsonify(_table_state())


@app.post("/api/table/clips")
def table_clip():
    """multipart: video=<file>, role=teach|follow, truth=right|skip, skip=<step number>, marks=<JSON list of seconds>."""
    f = request.files.get("video")
    if not f:
        abort(400, "send a video file")
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / ("upload" + (Path(f.filename or "").suffix or ".webm"))
        f.save(src)
        try:
            marks = json.loads(request.form.get("marks") or "[]")
            clip = table.save_clip(src, request.form.get("role"), request.form.get("truth"), request.form.get("skip"), marks)
        except (TypeError, ValueError) as e:
            abort(400, str(e))
        except RuntimeError as e:                       # ffmpeg could not read the upload
            abort(400, f"could not read the clip: {e}"[:300])
    return jsonify({"clip": clip, **_table_state()})


@app.post("/api/table/clips/<name>/delete")
def table_clip_delete(name):
    try:
        table.delete_clip(name)
    except ValueError as e:
        abort(400, str(e))
    return jsonify(_table_state())


@app.post("/api/table/gate")
def table_gate():
    if gemini.mode() == "replay" or not has_key():
        abort(400, "The table test needs the live API: a funded key, and the server started without WORDLESS_TAPE=replay.")
    need = table.readiness()
    if need:
        abort(400, "Not ready: still need " + "; ".join(need) + ".")
    jid = uuid.uuid4().hex[:8]
    job = {"id": jid, "events": [], "done": False, "card": None, "error": None}
    jobs[jid] = job

    def run():
        try:
            job["result"] = table.run_gate(emit=job["events"].append)
            job["card"] = job["result"]["card"]
        except gemini.NoCredit:
            job["error"] = "The API key ran out of credit (HTTP 402) part-way. The clips are saved; run the test again after topping up."
        except Exception as e:
            job["error"] = f"{type(e).__name__}: {e}"[:300]
        job["done"] = True
    threading.Thread(target=run, daemon=True).start()
    return jsonify({"job": jid})


PRINT_CSS = """
  :root { color-scheme:light; } * { box-sizing:border-box; } body { margin:0; background:#fff; font:14px/1.4 -apple-system, "Helvetica Neue", Arial, sans-serif; color:#111; }
  .bar { padding:10px 16px; background:#fff3c4; border-bottom:2px solid #111; } .bar button { font:inherit; font-weight:700; padding:6px 14px; }
  @media print { .bar { display:none; } }
  @page { margin:10mm; }
"""

PRINT_CARD = """<!doctype html><meta charset="utf-8"><title>{{ card.title }}</title><style>""" + PRINT_CSS + """
  .sheet { padding:8mm; } .grid { display:grid; grid-template-columns:repeat({{ cols }}, 1fr); gap:5mm; }
  .p { position:relative; border:1.2mm solid #111; break-inside:avoid; } .p img { width:100%; display:block; aspect-ratio:16/9; object-fit:contain; background:#fff; }
  .p span { position:absolute; left:0; top:0; background:#111; color:#fff; font-weight:800; font-size:7mm; line-height:1; padding:1.5mm 3mm; }
  .foot { margin-top:5mm; display:flex; justify-content:space-between; align-items:flex-end; gap:6mm; color:#555; font-size:3.4mm; }
  .keep { display:flex; align-items:center; gap:3mm; break-inside:avoid; } .keep img { width:26mm; height:26mm; display:block; }
  .keep b { color:#111; font-size:4mm; display:block; }
</style>
<div class="bar"><button onclick="print()">Print</button> Landscape fits best. The panels carry no words; the footer is for the judge.</div>
<div class="sheet"><div class="grid">
{% for s in card.steps %}<div class="p"><img src="/cards/{{ card.id }}/{{ s.panel }}"><span>{{ loop.index }}</span></div>{% endfor %}
</div><div class="foot"><span>{{ card.title }} · {{ card.steps|length }} panels · drawn from one filmed demonstration<br>{{ tested }}</span>
<span class="keep"><img src="/qr/card/{{ card.id }}.svg" alt="QR code for this card"><span><b>Keep this card</b>scan to open it<br>{{ url }}</span></span></div></div>"""

PRINT_SEALED = """<!doctype html><meta charset="utf-8"><title>Sealed cards</title><style>""" + PRINT_CSS + """
  .deck { display:grid; grid-template-columns:repeat(2, 1fr); gap:0; padding:6mm; }
  .c { border:0.4mm dashed #777; height:62mm; padding:6mm; display:flex; flex-direction:column; justify-content:center; align-items:center; text-align:center; break-inside:avoid; }
  .c b { font-size:11mm; line-height:1.1; } .c small { color:#666; margin-top:4mm; font-size:3.6mm; } .c i { align-self:flex-start; font-style:normal; color:#999; font-size:3.2mm; }
</style>
<div class="bar"><button onclick="print()">Print</button> Cut along the dashes, fold each card shut, shuffle. {{ deck|length }} cards: half "do it right", half skip one step.</div>
<div class="deck">{% for c in deck %}<div class="c"><i>card {{ c.no }}</i>
{% if c.sealed == 'right' %}<b>Do it right</b><small>Do every step on the sheet.</small>{% else %}<b>Skip step {{ c.step }}</b><small>Do every other step. Do not pretend to do step {{ c.step }}.</small>{% endif %}
<small>Keep this card face down until the verdict is on screen.</small></div>{% endfor %}</div>"""


@app.get("/print/card/<cid>")
def print_card(cid):
    try:
        c = cards.load(cid)
    except FileNotFoundError:
        abort(404)
    n = len(c["steps"])
    st = c.get("self_test") or {}
    tested = f"self-test: {st['recognised']}/{st['of']} panels recognised in the teaching clip" if "recognised" in st else ""
    return render_template_string(PRINT_CARD, card=c, cols=2 if n == 4 else min(n, 3), tested=tested, url=card_url(cid))


@app.get("/qr/card/<cid>.svg")
def qr_card(cid):
    """QR code that opens the printable card. The host is WORDLESS_PUBLIC_URL, else this machine's LAN address."""
    if not (cards.card_dir(cid) / "card.json").exists():
        abort(404)
    buf = io.BytesIO()
    segno.make(card_url(cid), error="m").save(buf, kind="svg", scale=6, border=2, dark="#111", light="#fff")
    return Response(buf.getvalue(), mimetype="image/svg+xml", headers={"Cache-Control": "no-store"})


@app.get("/print/sealed")
def print_sealed():
    try:
        steps, copies = int(request.args.get("steps", table.load()["kit_steps"])), int(request.args.get("copies", 1))
        if not (2 <= steps <= 9 and 1 <= copies <= 4):
            raise ValueError
    except ValueError:
        abort(400, "steps 2 to 9, copies 1 to 4")
    return render_template_string(PRINT_SEALED, deck=table.sealed_deck(steps, copies))


# ---------------------------------------------------------------- eval
@app.post("/api/eval")
def eval_run():
    d = request.get_json()
    c = cards.load(d["card"])
    if "label_map" not in c:
        abort(400, "this card has no label map (public labelled recordings exist only for the tomato card)")
    recs = d.get("recordings") or [r["id"] for r in follow.recordings_for(c) if r["kind"] == "card"]
    res = evalrun.run(d["card"], recs, str(config.FIXTURES / "tomato" / "labels.json"), text=True, hydrogen=True)
    for r in res["rows"]:
        r["truth_panels"] = [cards.panel_number(c, s) for s in r["truth_skipped"]]
    return jsonify(res)


@app.errorhandler(400)
def bad(e):
    return jsonify({"error": e.description}), 400


if __name__ == "__main__":
    if "WORDLESS_TAPE" not in os.environ and not has_key():
        os.environ["WORDLESS_TAPE"] = "replay"
    port = int(os.environ.get("PORT", 5119))
    print(f"Wordless on http://localhost:{port}  (tape mode: {gemini.mode()}, key: {'yes' if has_key() else 'no'})")
    print(f"Keep-the-card QR codes point at {public_url()}  (set WORDLESS_PUBLIC_URL to change)")
    app.run(host=os.environ.get("WORDLESS_HOST", "0.0.0.0"), port=port, threaded=True)
