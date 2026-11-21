"""Wordless prototype server.  Run:  .venv/bin/python server.py   then open http://localhost:5119

WORDLESS_TAPE=replay  no key and no network: everything comes from recorded answers (the default if the
                      tape exists and no key is set).
WORDLESS_TAPE=auto    recorded answers where they exist, the live API otherwise.
"""
import base64
import json
import os
import tempfile
import threading
import time
import uuid
from pathlib import Path

from flask import Flask, abort, jsonify, render_template_string, request, send_file, send_from_directory

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


@app.get("/")
def index():
    return send_from_directory(WEB, "index.html")


@app.get("/web/<path:name>")
def web(name):
    return send_from_directory(WEB, name)


@app.get("/api/status")
def status():
    return jsonify({"tape_mode": gemini.mode(), "has_key": has_key(), "models": config.MODELS, "cards": cards.list_cards(),
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


@app.post("/api/follow/replay")
def follow_replay():
    d = request.get_json()
    c = cards.load(d["card"])
    try:
        s = follow.replay(c, d["recording"], speed=float(d.get("speed", 8)), use_own_thresholds=bool(d.get("own_thresholds")))
    except FileNotFoundError as e:
        abort(400, str(e))
    return jsonify(s.state())


@app.post("/api/follow/live")
def follow_live():
    d = request.get_json()
    if gemini.mode() == "replay":
        abort(400, "The server is in replay mode (no API calls). Restart with WORDLESS_TAPE=auto and a funded key for live checks.")
    s = follow.Session(cards.load(d["card"]), "live", use_own_thresholds=bool(d.get("own_thresholds")))
    return jsonify(s.state())


@app.post("/api/follow/<sid>/frame")
def follow_frame(sid):
    s = _session(sid)
    d = request.get_json()
    stills = [base64.b64decode(x.split(",", 1)[-1]) for x in d["stills"]]
    s.add_stills(int(d["i"]), stills)
    return jsonify({"ok": True})


@app.get("/api/follow/<sid>")
def follow_state(sid):
    return jsonify(_session(sid).state())


@app.post("/api/follow/<sid>/finish")
def follow_finish(sid):
    s = _session(sid)
    if s.source == "live":          # a replay finishes itself when its last window is in
        s.finish()
    return jsonify(s.state())


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
  .foot { margin-top:5mm; display:flex; justify-content:space-between; color:#555; font-size:3.4mm; }
</style>
<div class="bar"><button onclick="print()">Print</button> Landscape fits best. The panels carry no words; the footer is for the judge.</div>
<div class="sheet"><div class="grid">
{% for s in card.steps %}<div class="p"><img src="/cards/{{ card.id }}/{{ s.panel }}"><span>{{ loop.index }}</span></div>{% endfor %}
</div><div class="foot"><span>{{ card.title }} · {{ card.steps|length }} panels · drawn from one filmed demonstration</span><span>{{ tested }}</span></div></div>"""

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
    return render_template_string(PRINT_CARD, card=c, cols=2 if n == 4 else min(n, 3), tested=tested)


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
    app.run(host="127.0.0.1", port=port, threaded=True)
