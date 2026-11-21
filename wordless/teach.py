"""Teaching clip -> card.

  1 prepare   normalise the clip, cut 2 s windows                               (local)
  2 name      Hydrogen watches the clip and names the steps                     (gemini-4-hydrogen)
  3 locate    Decisions API labels every window; code picks each step's keyframe (gemini-decision-1)
  4 plan      Argon marks setup steps, order links, end-state questions         (gemini-4-argon)
  5 draw      each keyframe becomes a line-art panel, all in parallel           (image model)
  6 letters   Decisions API rejects panels that contain writing; redraw         (gemini-decision-1)
  7 selftest  the card must recognise each step in its own teaching clip        (gemini-decision-1)

Hydrogen is never asked for timestamps (they drift, measured). In replay mode a stage with no recorded
answer is reported as "not recorded" and the build goes on without it.
"""
import concurrent.futures as cf
import json
import shutil
import time
from pathlib import Path

from . import card as cards
from . import checker, config, gemini, video
from .tracker import Tracker, SEEN, own_thresholds

NAME_PROMPT = """You are watching one person demonstrate a short hands-on task once, so that someone else can repeat it.
List the distinct physical steps in the order they happen. A step is one action with one tool or object
(for example "wipe the mat with the cloth"). Do not split one continuous action into several steps and do not
invent steps you cannot see. Give no timestamps.
Answer with JSON only: [{"action": "<imperative sentence, at most 12 words>", "done_when": "<what is visibly true when it is finished>"}]"""

PLAN_PROMPT = """These are the steps of a short hands-on routine, named from a video of one person doing it once.
A picture card will be made from them and used to check that another person does every step.
Steps:
%s
Decide, for each step:
- "setup": true if it is only fetching, unpacking or arranging things before the real work (it will be left off the card).
- "trace_question": if the finished step leaves a result that is visible in a photo taken at the very end,
  one yes/no question that is true only when the step was done; otherwise null.
Also list "links": pairs [a, b] of step ids where a MUST physically come before b (b is impossible or pointless
without a). Do not add a link just because the demonstrator happened to do a first.
Answer with JSON only: {"steps": [{"id": "...", "setup": false, "trace_question": null}], "links": [["s01", "s02"]]}"""

DRAW_PROMPT = """Redraw this photo as one panel of a wordless assembly-instruction sheet: clean black line art on a white
background, uniform outlines, no shading and no colour. Keep the same viewpoint and the same hand pose.
Show only the hands and the objects they act on; leave out background clutter. Add one bold curved arrow
that shows the motion. Do not draw any letters, words, numbers, labels or logos anywhere."""

REDRAW_SUFFIX = " The previous attempt contained writing. Replace every printed label with a plain blank surface."


def label_windows(fn, n, workers):
    """Label windows 0..n-1 in parallel. A window whose call fails counts as "none"; more than 10% failing aborts."""
    def one(i):
        try:
            return fn(i)
        except (gemini.NoCredit, gemini.TapeMiss):
            raise
        except gemini.ApiError:
            return {"step": None, "conf": 0.0, "failed": True}
    with cf.ThreadPoolExecutor(workers) as ex:
        labels = list(ex.map(one, range(n)))
    failed = sum(1 for a in labels if a.get("failed"))
    if failed > max(1, n // 10):
        raise gemini.ApiError(-1, f"{failed} of {n} windows failed")
    return labels, failed


class Build:
    def __init__(self, card_id, title, emit=None):
        self.id, self.title = card_id, title
        self.dir = cards.card_dir(card_id)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.events = []
        self._emit = emit
        self.t0 = time.time()

    def emit(self, stage, state, detail="", **data):
        ev = {"stage": stage, "state": state, "detail": detail, "t": round(time.time() - self.t0, 1), **data}
        self.events.append(ev)
        if self._emit:
            self._emit(ev)

    def key(self, *parts):
        return "/".join(("teach", self.id) + tuple(str(p) for p in parts))

    def stage(self, name, fn, optional=False):
        """Run one stage. Optional stages may be missing from the tape or fail without stopping the build."""
        self.emit(name, "running")
        try:
            out = fn()
            return out
        except gemini.TapeMiss as e:
            if not optional:
                self.emit(name, "failed", f"not on tape: {e}")
                raise
            self.emit(name, "skipped", "not recorded on tape")
        except gemini.NoCredit:
            self.emit(name, "failed", "API key has no credit (HTTP 402)")
            raise
        except (gemini.ApiError, ValueError, KeyError) as e:
            if not optional:
                self.emit(name, "failed", str(e)[:200])
                raise
            self.emit(name, "skipped", f"failed, continuing without it: {str(e)[:160]}")
        return None


def build(video_path, card_id=None, title="Routine", emit=None, workers=3):
    """Build a card from a teaching clip. video_path may be None in replay mode if every answer is on tape."""
    card_id = card_id or cards.new_id(title)
    b = Build(card_id, title, emit)

    # 1 ---------------------------------------------------------------- prepare
    b.emit("prepare", "running")
    clip, windows = None, []
    if video_path:
        clip = video.normalize(video_path, b.dir / "teach.mp4")
        windows = video.cut_windows(clip, b.dir / "windows")
        n = len(windows)
        dur = round(video.duration(clip), 1)
    else:
        n = gemini.tape.count(b.key("locate"))
        dur = n * config.WINDOW_S
        if not n:
            raise gemini.TapeMiss("no teaching clip given and no recorded windows for card " + card_id)
    b.emit("prepare", "done", f"{dur} s clip, {n} windows" + ("" if clip else " (no video file; answers from tape)"))
    win_bytes = lambda i: (lambda: windows[i].read_bytes())

    # 2 ---------------------------------------------------------------- name (Hydrogen)
    def name():
        def call():
            d = gemini.generate(config.MODELS["hydrogen"],
                                [gemini.inline(clip.read_bytes(), "video/mp4"), {"text": NAME_PROMPT}],
                                {"responseMimeType": "application/json"})
            return {"steps": gemini.json_of(d), "lat": d["_latency"]}
        r = gemini.taped(b.key("steps"), call)
        named = [{"id": f"s{k + 1:02d}", "action": s["action"].strip(), "done_when": s.get("done_when", "").strip()}
                 for k, s in enumerate(r["steps"])]
        if not named:
            raise ValueError("Hydrogen named no steps")
        b.emit("name", "done", f"{len(named)} steps named" + (f" in {r['lat']} s" if r.get("lat") else ""),
               steps=[s["action"] for s in named])
        return named
    named = b.stage("name", name)

    # 3 ---------------------------------------------------------------- locate (Decisions API)
    def locate():
        labels, failed = label_windows(
            lambda i: checker.classify_clip_text(named, win_bytes(i) if windows else None, key=b.key("locate", f"{i:04d}")), n, workers)
        tr = Tracker([s["id"] for s in named], unsure_mass=config.UNSURE_MASS)
        for i, a in enumerate(labels):
            tr.add(i, a["step"], a["conf"])
        found = {}
        for s in named:
            mass, centre = tr.score(s["id"])
            if not mass:        # Hydrogen saw the step, so one window at MIN_CONF or better is enough to place it
                continue
            run = max(tr.runs(s["id"]), key=lambda r: sum(tr.obs[j][1] for j in r))
            best = max(run, key=lambda j: tr.obs[j][1])            # most confident window of the heaviest run
            alt = sorted(run, key=lambda j: -tr.obs[j][1])[1:2]    # runner-up, used if the panel fails its self-test
            found[s["id"]] = {"window": best, "alt_window": alt[0] if alt else None, "mass": round(mass, 2),
                              "start_s": run[0] * config.WINDOW_S, "end_s": (run[-1] + 1) * config.WINDOW_S}
        lats = sorted(a["lat"] for a in labels if a.get("lat"))
        b.emit("locate", "done", f"{len(found)} of {len(named)} steps located in {n} windows"
               + (f", median {lats[len(lats) // 2]} s per call" if lats else "") + (f", {failed} windows failed" if failed else ""))
        return found
    found = b.stage("locate", locate)
    located = sorted((s for s in named if s["id"] in found), key=lambda s: found[s["id"]]["start_s"])
    if not located:
        b.emit("locate", "failed", "no step could be located in the clip")
        raise ValueError("no step could be located in the teaching clip")

    def keyframe(sid, window, tag=""):
        def call():
            p = video.frame_at(clip, window * config.WINDOW_S + config.WINDOW_S / 2, b.dir / "tmp_kf.jpg")
            return Path(p).read_bytes()
        data = gemini.taped(b.key("keyframe", sid + tag), call, kind="bytes") if clip else gemini.tape.get_bytes(b.key("keyframe", sid + tag))
        if data is None:
            raise gemini.TapeMiss(b.key("keyframe", sid + tag))
        (b.dir / f"kf_{sid}.jpg").write_bytes(data)
        return data

    fallbacks = []

    def draw(sid, kf, tag="", extra=""):
        def call():
            for attempt in range(3):                    # a reply with no image (refusal, safety block) is retried
                try:
                    d = gemini.generate(config.MODELS["image"], [gemini.inline(kf, "image/jpeg"), {"text": DRAW_PROMPT + extra}],
                                        {"responseModalities": ["IMAGE"]})
                    return cards.to_jpeg(gemini.image_of(d))
                except gemini.NoCredit:
                    raise
                except gemini.ApiError as e:
                    if attempt == 2 or e.status not in (200, 429, 500, 502, 503, 504, -1):
                        raise
                    time.sleep(1 + attempt)
        try:
            data = gemini.taped(b.key("panel", sid + tag), call, kind="bytes")
        except gemini.NoCredit:
            raise
        except gemini.ApiError as e:                    # last resort: the photo itself, so the card still exists
            fallbacks.append(sid)
            b.emit("draw", "running", f"panel {sid} could not be drawn ({str(e)[:80]}); using the keyframe photo")
            data = kf
        (b.dir / f"pn_{sid}.jpg").write_bytes(data)
        return data

    # 4 + 5 ------------------------------------------------------------ plan (Argon) while panels are drawn
    def plan():
        def call():
            listing = "\n".join(f"- {s['id']}: {s['action']} (done when: {s['done_when']})" for s in located)
            d = gemini.generate(config.MODELS["argon"], [{"text": PLAN_PROMPT % listing}], {"responseMimeType": "application/json"})
            out = gemini.json_of(d)
            out["lat"] = d["_latency"]
            return out
        return gemini.taped(b.key("plan"), call)

    b.emit("draw", "running", f"{len(located)} panels in parallel")
    t_draw = time.time()
    with cf.ThreadPoolExecutor(max(len(located), 1) + 1) as ex:
        plan_f = ex.submit(lambda: b.stage("plan", plan, optional=True))
        kfs = {s["id"]: keyframe(s["id"], found[s["id"]]["window"]) for s in located}
        draw_f = {s["id"]: ex.submit(draw, s["id"], kfs[s["id"]]) for s in located}
        panels, draw_err = {}, {}
        for sid, f in draw_f.items():
            try:
                panels[sid] = f.result()
            except gemini.NoCredit:
                b.emit("draw", "failed", "API key has no credit (HTTP 402)")
                raise
            except gemini.TapeMiss as e:
                draw_err[sid] = e                       # fatal only if the step ends up on the card
        pl = plan_f.result()
    b.emit("draw", "done", f"{len(panels)} panels in {round(time.time() - t_draw, 1)} s"
           + (f"; {len(fallbacks)} are keyframe photos because drawing failed" if fallbacks else ""))

    setup, trace, links = set(), {}, []
    if pl:
        ids = {s["id"] for s in located}
        for s in pl.get("steps", []):
            if s.get("id") in ids:
                if s.get("setup"):
                    setup.add(s["id"])
                if s.get("trace_question"):
                    trace[s["id"]] = s["trace_question"]
        if len(setup) == len(located):      # never let the planner empty the card
            setup = set()
        links = [l for l in pl.get("links", []) if len(l) == 2 and l[0] in ids - setup and l[1] in ids - setup and l[0] != l[1]]
        b.emit("plan", "done", f"{len(setup)} setup steps left off, {len(links)} order links, {len(trace)} end-state questions"
               + (f" ({pl['source']})" if pl.get("source") else ""))
    on_card = [s for s in located if s["id"] not in setup]
    for s in on_card:
        if s["id"] in draw_err:
            b.emit("draw", "failed", f"panel {s['id']}: {str(draw_err[s['id']])[:160]}")
            raise draw_err[s["id"]]

    # 6 ---------------------------------------------------------------- letters gate (Decisions API)
    lettered = []

    def letters():
        redrawn = 0
        for s in on_card:
            sid = s["id"]
            for attempt in range(3):
                tag = f".r{attempt}" if attempt else ""
                p = checker.has_letters(panels[sid], key=b.key("letters", sid + tag))["p"]
                if p < 0.5:
                    break
                if attempt == 2:
                    lettered.append(sid)                # two redraws did not remove the writing
                    break
                panels[sid] = draw(sid, kfs[sid], tag=f".r{attempt + 1}", extra=REDRAW_SUFFIX)
                redrawn += 1
        b.emit("letters", "done", f"{len(on_card)} panels checked, {redrawn} redrawn"
               + (f", {len(lettered)} still contain writing" if lettered else ""))
        return True
    b.stage("letters", letters, optional=True)

    card = {
        "id": card_id, "title": title, "created": time.strftime("%Y-%m-%d %H:%M:%S"), "source": "built from a teaching clip",
        "clip_seconds": dur, "windows": n,
        "steps": [{"id": s["id"], "action": s["action"], "done_when": s["done_when"], "panel": f"pn_{s['id']}.jpg",
                   "keyframe": f"kf_{s['id']}.jpg", "trace_question": trace.get(s["id"]), **found[s["id"]]} for s in on_card],
        "named_steps": named,
        "dropped": [{"id": s["id"], "action": s["action"], "reason": "setup step" if s["id"] in setup else "not found in the clip"}
                    for s in named if s["id"] not in {x["id"] for x in on_card}],
        "links": links, "plan_source": (pl or {}).get("source", "argon" if pl else None),
        "thresholds": {}, "self_test": None, "panels_with_writing": lettered, "panels_not_drawn": fallbacks,
    }
    cards.save(card)
    cards.compose_sheet(card)

    # 7 ---------------------------------------------------------------- self-test (Decisions API)
    def selftest():
        def run_round(rnd):
            labels, _ = label_windows(
                lambda i: checker.classify_clip(card, win_bytes(i) if windows else None, key=b.key("selftest", f"r{rnd}", f"{i:04d}")), n, workers)
            tr = Tracker(cards.step_ids(card))
            for i, a in enumerate(labels):
                tr.add(i, a["step"], a["conf"])
            own = {sid: round(tr.score(sid)[0], 2) for sid in cards.step_ids(card)}
            ok = [sid for sid in own if tr.state(sid) == SEEN]
            # only a panel the card does not recognise at all is worth redrawing; a short step that lands in
            # the "not sure" band is normal and is handled by its per-panel cut-off
            lost = [sid for sid in own if tr.state(sid) == "skipped"]
            return {"recognised": len(ok), "of": len(own), "own_scores": own, "round": rnd, "failed": lost}

        first = run_round(0)
        b.emit("selftest", "running" if first["failed"] else "done",
               f"the card recognises {first['recognised']} of {first['of']} steps in its own teaching clip",
               recognised=first["recognised"], of=first["of"])
        if not first["failed"]:
            return first
        old = {sid: (panels[sid], (b.dir / f"kf_{sid}.jpg").read_bytes()) for sid in first["failed"]}
        for sid in first["failed"]:                     # repair: another keyframe if there is one, then redraw
            alt = found[sid].get("alt_window")
            kf = keyframe(sid, alt, tag=".alt") if alt is not None else kfs[sid]
            panels[sid] = draw(sid, kf, tag=".selftest")
        cards.compose_sheet(card)
        second = run_round(1)
        if second["recognised"] <= first["recognised"]:  # the repair did not help: put the first panels back
            for sid, (pn, kf) in old.items():
                panels[sid] = pn
                (b.dir / f"pn_{sid}.jpg").write_bytes(pn)
                (b.dir / f"kf_{sid}.jpg").write_bytes(kf)
            cards.compose_sheet(card)
            b.emit("selftest", "done", f"redraw did not help; kept the first panels: {first['recognised']} of {first['of']} recognised",
                   recognised=first["recognised"], of=first["of"])
            return first
        b.emit("selftest", "done", f"after one redraw the card recognises {second['recognised']} of {second['of']} steps",
               recognised=second["recognised"], of=second["of"])
        return second
    st = b.stage("selftest", selftest, optional=True)
    if st:
        card["self_test"] = st
        card["thresholds"] = own_thresholds(st["own_scores"])
        cards.save(card)

    shutil.rmtree(b.dir / "windows", ignore_errors=True)
    (b.dir / "tmp_kf.jpg").unlink(missing_ok=True)
    (b.dir / "build_log.json").write_text(json.dumps(b.events, indent=1))
    b.emit("card", "done", f"card ready: {len(card['steps'])} panels in {round(time.time() - b.t0, 1)} s", card=card_id)
    return card
