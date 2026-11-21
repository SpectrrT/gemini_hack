"""The fast path: show it once, at any speed, with any number of steps; then check someone several times a second.

Teach (`build`): one clip in, a card out. Nobody names anything or says how many steps there are.
  name      Hydrogen watches the clip and lists the distinct steps or poses it sees
  locate    Decisions API labels every frame (several a second); code turns the labels into the steps
            performed, in order, and picks each one's clearest frame
  draw      the image model redraws each clearest frame as a line-art panel
  selftest  the finished card is asked to follow its own teaching clip

Follow (`Session`): every camera frame is one Decisions question (reference sheet + frame -> which step).
`decode` turns the answers into the steps performed and lines them up against the card: each step is seen,
never happened, or was something else; extra steps are named. A step held for half a second is enough.

The card it writes is an ordinary card (card.json, same fields the page and print view use) marked "fast",
with the frame-by-frame reference data next to it (kit.json, see signs.py).
"""
import concurrent.futures as cf
import json
import time

from . import card as cards
from . import config, decode, gemini, signs, video
from . import follow as follow_mod
from .teach import Build

MAX_FRAMES = 420          # teaching frames sent to the Decisions API (a long clip is sampled more thinly)
TEACH_FPS = 5.0
OTHER = "other"

REVIEW_PROMPT = """The image is a numbered reference sheet: each numbered picture is one step or pose of a routine.
The video shows a person, possibly a different person in a different place, doing the routine. Watch the whole
video and list, in the order performed, the number of every reference picture the person clearly performs.
If they perform the same one again later, list its number again. Leave out transitions and anything that is
not on the sheet. Judge by hands, fingers, arms and objects, not by the background.
Answer with JSON only: {"performed": [<number>, ...]}"""

NAME_PROMPT = """You are watching one person demonstrate something once so that someone else can repeat it.
It may be a hands-on task with objects (steps of several seconds each) or a quick series of hand, arm or body
poses (each held for a second or less, one straight after another). Watch closely: quick poses are easy to miss.
1. "steps": every DISTINCT step or pose, each listed once. Do not list resting, waiting, hands down or out of
   view, or the movement between poses. Do not invent anything you cannot see.
   A small action IS a step even when almost nothing else moves: a press, a tap, a twist, a pinch, a flick of a
   switch, a change of hand shape with the arm still. List it if the person does it on purpose.
2. "order": what the person actually does from start to finish, as a list of step names in the order performed.
   If a step or pose is done again later, its name appears again.
Give no timestamps. Answer with JSON only:
{"steps": [{"name": "<2 to 6 words>", "look": "<what it looks like: hands, fingers, arms, objects, position; one sentence>"}], "order": ["<name>", ...]}"""


def _slowed(b, clip, dur):
    """A slowed copy of a short clip for the naming model. It samples video about once a second, so poses held
    for half a second fell between its samples (measured: 2 of 6 named at 0.45 s a pose). Slowed 4x, each pose
    spans about two of its samples."""
    factor = 4 if dur <= 20 else 2 if dur <= 45 else 1
    if factor == 1:
        return clip, 1
    slow = b.dir / "teach_slow.mp4"
    video._run(["-i", str(clip), "-an", "-vf", f"setpts={factor}*PTS,fps=8,scale=-2:360", "-c:v", "libx264", "-preset", "veryfast",
                "-crf", "30", "-pix_fmt", "yuv420p", str(slow)])
    return slow, factor


def _name(b, clip, dur=0.0):
    def call():
        shown, factor = _slowed(b, clip, dur) if dur else (clip, 1)
        note = f"\n(The video is played at 1/{factor} speed so that quick poses are visible.)" if factor > 1 else ""
        parts = [gemini.inline(shown.read_bytes(), "video/mp4"), {"text": NAME_PROMPT + note}]
        try:                                         # Carbon: it separates look-alike poses better, and was faster here
            d = gemini.generate(config.MODELS["carbon"], parts, {"responseMimeType": "application/json"}, timeout=90, tries=1)
            model = config.MODELS["carbon"]
        except gemini.NoCredit:
            raise
        except gemini.ApiError:                      # Carbon unavailable or too slow: Hydrogen names the steps instead
            d = gemini.generate(config.MODELS["hydrogen"], parts, {"responseMimeType": "application/json"})
            model = config.MODELS["hydrogen"]
        return {"poses": gemini.json_of(d), "lat": d["_latency"], "model": model}
    r = gemini.taped(b.key("poses"), call)
    raw = r["poses"]
    listed = raw.get("steps") if isinstance(raw, dict) else raw
    poses = []
    for k, p in enumerate(listed if isinstance(listed, list) else []):
        name = str(p.get("name") or p.get("action") or "").strip()
        if name:
            poses.append({"id": f"p{k + 1:02d}", "name": name, "look": str(p.get("look") or p.get("done_when") or "").strip()})
    if not poses:
        raise ValueError("the model saw no steps in the clip")
    by_name = {p["name"].lower(): p["id"] for p in poses}
    order = [by_name[str(x).strip().lower()] for x in (raw.get("order") or [] if isinstance(raw, dict) else []) if str(x).strip().lower() in by_name]
    if not all(p["id"] in order for p in poses):     # no usable order given: None, and the frames decide the order
        order = None
    b.emit("name", "done", f"{len(poses)} distinct steps seen" + (f", {len(order)} performed" if order else "") +
           (f" in {r['lat']} s" if r.get("lat") else "") + (f" by {r['model']}" if r.get("model") else ""),
           steps=[p["name"] for p in poses])
    return poses, order


def _label_frame(poses, jpeg, key):
    """Teaching only: which of the named steps is in this frame? No reference picture exists yet, so by words."""
    def call():
        crit = {p["id"]: f"{p['name']}: {p['look']}" for p in poses}
        crit[OTHER] = "none of these: moving between steps, reaching, hands down or out of view, idle"
        q = {"step": {"type": "choice", "criteria": crit,
                      "instructions": "One frame from a video of a person demonstrating a routine. Which step or pose is shown in this frame?"}}
        res = gemini.decide([gemini.image_block(jpeg)], q, timeout=15, tries=3, gap=config.SIGNS_MIN_GAP_S)
        a = res["answers"].get("step") or {}
        if "choice" not in a:
            raise gemini.ApiError(200, "answer without a choice: " + str(res["answers"])[:200])
        probs = {(decode.NONE if k == OTHER else k): round(v, 3) for k, v in (a.get("probabilities") or {}).items() if v > 0.01}
        top = decode.NONE if a["choice"] == OTHER else a["choice"]
        probs.setdefault(top, round(a.get("confidence", 0.5), 3))
        return {"probs": probs, "lat": res["latency"]}
    return gemini.taped(key, call)


def _all(fn, n, workers=16):
    """fn(i) for every i, in parallel; a failed item is None."""
    def one(i):
        try:
            return fn(i)
        except gemini.NoCredit:
            raise
        except (gemini.ApiError, gemini.TapeMiss):
            return None
    with cf.ThreadPoolExecutor(workers) as ex:
        return list(ex.map(one, range(n)))


def build(video_path, card_id=None, title="Routine", emit=None):
    """Teaching clip -> fast card. Returns the card."""
    card_id = card_id or cards.new_id(title)
    b = Build(card_id, title, emit)

    b.emit("prepare", "running")
    clip = video.normalize(video_path, b.dir / "teach.mp4")
    dur = video.duration(clip)
    fps = max(1.0, min(TEACH_FPS, MAX_FRAMES / max(dur, 1.0)))
    frames = video.frames(clip, b.dir / "frames", fps=fps)
    times = [i / fps for i in range(len(frames))]
    b.emit("prepare", "done", f"{dur:.1f} s clip, {len(frames)} frames at {fps:.1f} a second")

    poses, order = b.stage("name", lambda: _name(b, clip, dur))
    ids = [p["id"] for p in poses]

    def locate():
        answers = _all(lambda i: _label_frame(poses, frames[i].read_bytes(), b.key("frame", f"{i:05d}")), len(frames))
        failed = sum(a is None for a in answers)
        if failed > max(2, len(frames) // 5):
            raise gemini.ApiError(-1, f"{failed} of {len(frames)} frames got no answer")
        probs = [a["probs"] if a else None for a in answers]
        free = decode.segments(probs, times, ids)
        # The model that watched the clip says WHAT happened and in what order; the frames only say WHERE.
        # Left to themselves the frame answers dropped quick or look-alike steps the model had named.
        segs = decode.force(probs, times, order) if order else None
        how = "placed by the named order"
        if not segs and {s["label"] for s in free} == set(ids):
            segs, how = free, "order read from the frames"          # no order was named, but the frames found every step
        if not segs:                                                 # never drop a named step: place them in the order listed
            segs, how = decode.force(probs, times, ids), "placed in the order listed"
        if not segs:
            raise ValueError(f"the clip has too few frames ({len(frames)}) for the {len(ids)} steps seen in it: record a slightly longer clip")
        for s in segs:                               # the clearest frame of each occurrence
            inside = [i for i, t in enumerate(times) if s["start"] <= t <= s["end"]]
            s["frame"] = max(inside, key=lambda i: (probs[i] or {}).get(s["label"], 0.0))
        found = {s["label"] for s in segs}
        lost = [p["name"] for p in poses if p["id"] not in found]
        name_of = {p["id"]: p["name"] for p in poses}
        weak = [name_of[s["label"]] for s in segs if s["conf"] < 0.2]
        b.emit("locate", "done", f"{len(segs)} steps in order, {len(found)} distinct, {how}" +
               (f" (the frames alone found {len(free)})" if order and len(free) != len(segs) else "") +
               (f"; weakly seen: {', '.join(weak)}" if weak else "") +
               (f"; not found and left out: {', '.join(lost)}" if lost else "") +
               (f"; {failed} frames unanswered" if failed else ""))
        return segs
    segs = b.stage("locate", locate)

    # one reference photo per distinct step: its most confident occurrence
    best = {}
    for s in segs:
        if s["label"] not in best or s["conf"] > best[s["label"]]["conf"]:
            best[s["label"]] = s
    kit_signs = []
    for p in poses:
        if p["id"] not in best:
            continue
        ref = f"kf_{p['id']}.jpg"
        (b.dir / ref).write_bytes(cards.to_jpeg(frames[best[p["id"]]["frame"]].read_bytes(), max_side=640))
        kit_signs.append({"id": p["id"], "name": p["name"], "look": p["look"], "ref": ref, "v": 1})

    def draw():
        def one(i):
            g = kit_signs[i]
            def call():
                d = gemini.generate(config.MODELS["image"], [gemini.inline((b.dir / g["ref"]).read_bytes(), "image/jpeg"),
                                                             {"text": signs.DRAW_PROMPT}], {"responseModalities": ["IMAGE"]})
                return cards.to_jpeg(gemini.image_of(d), max_side=640)
            return gemini.taped(b.key("panel", g["id"]), call, kind="bytes")
        arts = _all(one, len(kit_signs), workers=6)
        for g, art in zip(kit_signs, arts):
            g["panel"] = f"pn_{g['id']}.jpg"
            (b.dir / g["panel"]).write_bytes(art or (b.dir / g["ref"]).read_bytes())      # the photo if it could not be drawn
        missing = sum(a is None for a in arts)
        b.emit("draw", "done", f"{len(arts) - missing} panels drawn" + (f", {missing} kept as photos" if missing else ""))
    drawing = cf.ThreadPoolExecutor(1).submit(b.stage, "draw", draw, True)     # while the self-test runs below

    sequence = [s["label"] for s in segs]
    kit = {"id": card_id, "title": title, "kind": "signs", "signs": kit_signs, "next": len(kit_signs) + 1,
           "sequences": [{"id": "routine", "name": title, "signs": sequence}]}
    signs.compose(kit)                               # the reference sheet is made of the photos, not the drawings

    self_test = {}

    def selftest():                                  # the card follows its own teaching clip
        quick = min(s["end"] - s["start"] for s in segs) < 1.2             # quick steps need every frame; slow ones every other
        pick = list(range(0, len(frames), 1 if quick or fps <= 2.5 else 2))
        answers = _all(lambda k: signs.classify(kit, frames[pick[k]].read_bytes(), key=b.key("self", f"{pick[k]:05d}"), timeout=15, tries=3), len(pick))
        got = [s["label"] for s in decode.segments([a["probs"] if a else None for a in answers], [times[i] for i in pick], ids)]
        dist, ops = decode.align(got, sequence)
        ok = sum(o["op"] == "match" for o in ops)
        self_test.update({"recognised": ok, "of": len(sequence), "distance": dist})
        b.emit("selftest", "done", f"the card recognised {ok} of {len(sequence)} steps in its own clip")
    b.stage("selftest", selftest, optional=True)
    drawing.result()
    for g in kit_signs:
        g.setdefault("panel", g["ref"])
    signs.save(kit)

    by_id = {g["id"]: g for g in kit_signs}
    card = {"id": card_id, "title": title, "created": time.strftime("%Y-%m-%d %H:%M:%S"), "source": "camera", "fast": True,
            "clip_seconds": round(dur, 1), "frames": len(frames), "fps": round(fps, 2), "links": [],
            "poses": {g["id"]: {"name": g["name"], "panel": g["panel"], "photo": g["ref"]} for g in kit_signs},
            "steps": [{"id": f"q{n + 1:02d}", "pose": s["label"], "action": by_id[s["label"]]["name"],
                       "done_when": by_id[s["label"]]["look"], "panel": by_id[s["label"]]["panel"], "keyframe": by_id[s["label"]]["ref"],
                       "start_s": round(s["start"], 2), "end_s": round(s["end"], 2), "seconds": round(s["end"] - s["start"] + 1 / fps, 2)}
                      for n, s in enumerate(segs)]}
    if self_test:
        card["self_test"] = self_test
    cards.save(card)
    cards.compose_sheet(card)

    shortest = min(s["seconds"] for s in card["steps"])
    b.emit("card", "done", f"card ready: {len(card['steps'])} steps in {time.time() - b.t0:.0f} s (shortest step {shortest:.1f} s)")
    (b.dir / "build_log.json").write_text(json.dumps(b.events, indent=1))
    return card


# ---------------------------------------------------------------- follow
class Session(signs.Session):
    """A person following a fast card. Looks like follow.Session to the server (state, finish, verdict)."""

    def __init__(self, card, source="live"):
        super().__init__(signs.load(card["id"]), mode="follow", target="routine", source=source)
        self.card, self.recording, self.total, self.verdict = card, None, None, None
        self.step_ids = cards.step_ids(card)
        self.want = list(self.target["signs"])
        follow_mod._sessions[self.id] = self

    def _marks(self, seen, final):
        """Per card step: seen / wrong / pending (or skipped once final). Also the extra steps performed."""
        if final:
            _, ops = decode.align(seen, self.want)
        else:
            covered, _ = decode.progress(seen, self.want)
            _, ops = decode.align(seen, self.want[:covered])
        marks, extra, got = {sid: ("skipped" if final else "pending") for sid in self.step_ids}, [], {}
        for o in ops:
            if o["op"] == "match":
                marks[self.step_ids[o["pos"] - 1]] = "seen"
            elif o["op"] == "wrong":
                marks[self.step_ids[o["pos"] - 1]] = "wrong"
                got[self.step_ids[o["pos"] - 1]] = o["got"]
            elif o["op"] == "extra":
                extra.append(o["got"])
        if final:
            # A step done at a different point in the run was done: call it "moved", not "never happened".
            # (People do loose tasks in their own order; on 16 cooking recordings strict order gave 31 false
            # "never happened", order-free 12. See docs/EVAL.md, "Frame by frame".)
            pose = {sid: st["pose"] for sid, st in zip(self.step_ids, self.card["steps"])}
            spare = list(extra) + list(got.values())
            for sid in self.step_ids:
                if marks[sid] in ("skipped", "wrong") and pose[sid] in spare:
                    spare.remove(pose[sid])
                    marks[sid] = "moved"
                    got.pop(sid, None)
            for sid in list(got):                    # a "wrong" whose stand-in was really another step done early or late
                if got[sid] in spare:
                    spare.remove(got[sid])
                else:
                    marks[sid] = "skipped"
                    del got[sid]
            extra = spare
        return marks, extra, got

    def state(self):
        st = super().state()
        seen = [s["label"] for s in st["seen"]]
        conf = {}
        marks, extra, _ = self._marks(seen, final=False)
        with self.lock:
            last = max(self.answers) if self.answers else None
            now = self.answers[last] if last is not None else None
            timeline = [[i, None if a["top"] == decode.NONE else a["top"], a["conf"]] for i, a in sorted(self.answers.items())][-400:]
        now_step = None
        if now and now["top"] != decode.NONE:        # the next card step that shows this picture
            pending = [sid for sid, s in zip(self.step_ids, self.card["steps"]) if s["pose"] == now["top"] and marks[sid] != "seen"]
            anyone = [sid for sid, s in zip(self.step_ids, self.card["steps"]) if s["pose"] == now["top"]]
            now_step = (pending or anyone or [None])[0]
        covered = sum(m == "seen" or m == "wrong" for m in marks.values())
        finished = covered >= len(self.step_ids) and st["idle"] is not None and st["idle"] >= 0.6
        return {
            "id": self.id, "card": self.card["id"], "source": self.source, "recording": None, "fast": True,
            "panels": {sid: {"state": marks[sid], "mass": conf.get(sid, 0)} for sid in self.step_ids},
            "now": now_step, "now_conf": now["conf"] if now else 0.0,
            "windows": st["answered"], "total": None, "errors": st["errors"], "waiting": st["waiting"], "dropped": st["dropped"],
            "strip": st["seen"], "extra": extra, "latency": st["latency"],
            "should_end": bool(st["should_end"] or finished),
            "done": self.done, "verdict": self.verdict, "fatal": self.fatal, "timeline": timeline,
        }

    def _review(self):
        """Carbon watches the saved frames of the whole run next to the reference sheet and lists what was performed."""
        import subprocess
        import tempfile
        from pathlib import Path
        frames = sorted(self.dir.glob("f_*.jpg"))
        if len(frames) < 3:
            return None
        with self.lock:
            span = max(self.times.values()) - min(self.times.values()) if self.times else 0
        rate = max(1.0, min(10.0, (len(frames) - 1) / span)) if span > 0 else 5.0
        ids = signs.sign_ids(self.kit)

        def call():
            with tempfile.TemporaryDirectory() as tmp:
                clip = Path(tmp) / "run.mp4"
                subprocess.run([video.ffmpeg(), "-hide_banner", "-loglevel", "error", "-y", "-framerate", f"{rate:.2f}", "-pattern_type", "glob",
                                "-i", str(self.dir / "f_*.jpg"), "-c:v", "libx264", "-pix_fmt", "yuv420p", "-vf", "scale=-2:360", str(clip)], check=True)
                d = gemini.generate(config.MODELS["carbon"], [gemini.inline(signs.sheet_bytes(self.kit), "image/jpeg"),
                                                              gemini.inline(clip.read_bytes(), "video/mp4"), {"text": REVIEW_PROMPT}],
                                    {"responseMimeType": "application/json"}, timeout=config.FAST_REVIEW_TIMEOUT_S, tries=1)
            out = gemini.json_of(d)
            nums = out.get("performed") if isinstance(out, dict) else out
            performed = [ids[int(n) - 1] for n in nums or [] if str(n).strip().lstrip("-").isdigit() and 1 <= int(n) <= len(ids)]
            return {"ok": True, "performed": performed, "lat": d["_latency"], "model": config.MODELS["carbon"]}
        fut = signs._pool.submit(gemini.taped, f"review/carbon/{self.kit['id']}/{self.id}", call)
        try:
            return fut.result(timeout=config.FAST_REVIEW_TIMEOUT_S + 5)
        except Exception as e:                       # no answer in time, or an unreadable one: the frame answers stand
            return {"ok": False, "error": f"{type(e).__name__}: {e}"[:160]}

    def finish(self, wait_s=3.0, backfill_s=6.0):
        if self.verdict is not None:
            return self.verdict
        res = super().finish(wait_s=wait_s, backfill_s=max(backfill_s, 0.0))
        by_frames = [s["label"] for s in res["seen"]]
        review = self._review() if (config.FAST_REVIEW and backfill_s >= 0 and self.source == "live" and not self.fatal) else None
        seen = review["performed"] if review and "performed" in review else by_frames
        marks, extra, got = self._marks(seen, final=True)
        doubted = []
        if seen is not by_frames:                    # the frame answers can turn the review's "never happened" into "not sure"
            frame_marks, _, _ = self._marks(by_frames, final=True)
            for sid in self.step_ids:
                if marks[sid] in ("skipped", "wrong") and frame_marks[sid] in ("seen", "moved"):
                    marks[sid] = "doubt"
                    got.pop(sid, None)
                    doubted.append(sid)
        name = {g["id"]: g["name"] for g in self.kit["signs"]}
        num = lambda sid: f"step {self.step_ids.index(sid) + 1}"
        skipped = [sid for sid in self.step_ids if marks[sid] in ("skipped", "wrong")]
        moved = [sid for sid in self.step_ids if marks[sid] == "moved"]
        unsure = list(doubted)
        if seen is by_frames and res["frames"] and res["missing_frames"] > res["frames"] * 0.2:   # too many frames unanswered to say "never"
            unsure, skipped = unsure + skipped, []
        parts = []
        for sid in skipped:
            parts.append(f"{num(sid)} was {name.get(got[sid], '?')}, not {name[self.card['steps'][self.step_ids.index(sid)]['pose']]}"
                         if sid in got else f"{num(sid)} never happened")
        if unsure:
            parts.append("not sure about " + ", ".join(num(s) for s in unsure))
        if moved:
            parts.append(", ".join(num(s) for s in moved) + " done out of order")
        if extra:
            parts.append("extra: " + ", ".join(name.get(x, x) for x in extra))
        if not seen:
            parts = ["nothing recognised"]
        elif not parts:
            parts = [f"all {len(self.step_ids)} steps seen, in order"]
        if res["missing_frames"] and seen is by_frames:
            parts.append(f"{res['missing_frames']} frames got no answer")
        if review and "error" in review:
            parts.append("whole-run review did not answer")
        v = {"seen": [sid for sid in self.step_ids if marks[sid] == "seen"], "unsure": unsure, "skipped": skipped,
             "out_of_order": moved, "extra": extra, "wrong": got, "order_violations": [], "scores": {}, "thresholds": {},
             "windows": res["frames"] - res["missing_frames"], "missing_windows": [],
             "review": review and {k: review[k] for k in ("ok", "model", "lat", "error") if k in review},
             "by_frames": [name.get(x, x) for x in by_frames],
             "clean": bool(seen) and not skipped and not unsure and not extra and not moved,
             "performed": [name.get(x, x) for x in seen], "latency": res.get("latency"),
             "text": "; ".join(parts)}
        self.verdict = v
        return v


def saved_runs(card):
    """Finished live runs of this fast card that can be played back with the network off, newest first."""
    out = []
    for p in config.RUNS.glob("*/signs.json") if config.RUNS.is_dir() else []:
        try:
            j = json.loads(p.read_text())
        except (OSError, ValueError):
            continue
        if j.get("kit") == card["id"] and j.get("source") == "live" and j.get("frames"):
            out.append({"recording": j["id"], "ts": p.stat().st_mtime, "frames": len(j["frames"])})
    return sorted(out, key=lambda r: -r["ts"])


def replay_saved(card, run_id, speed=1.0):
    """A new session fed from a saved run's answers at `speed` x real time. Returns it at once."""
    import threading
    log = json.loads((config.RUNS / run_id / "signs.json").read_text())
    s = Session(card, source="replay")
    s.recording, s.total = run_id, len(log["frames"])

    def feed():
        t0 = time.time()
        try:
            for i, t, a in log["frames"]:
                if s.done or s.fatal:
                    break
                if speed > 0:
                    time.sleep(max(0.0, t0 + t / speed - time.time()))
                with s.lock:
                    s.times[int(i)] = float(t)
                    if a:
                        s.answers[int(i)] = a
                        s.lat.append(a.get("lat", 0))
        finally:
            s.finish(wait_s=0)
    threading.Thread(target=feed, daemon=True).start()
    return s


def one_call(session, timeout=90):
    """The simple baseline on the same run: ONE Hydrogen call on the saved frames with the step list.
    Returns {"skipped": [card step ids], "lat": seconds}. Recorded on tape, so it is asked once per run."""
    import subprocess
    import tempfile
    from pathlib import Path
    from .baseline import PROMPT
    card, d = session.card, config.RUNS / (session.recording or session.id)
    ids = cards.step_ids(card)

    def call():
        frames = sorted(d.glob("f_*.jpg"))
        if len(frames) < 3:
            raise FileNotFoundError(f"no saved frames for run {d.name}")
        with session.lock:
            span = max(session.times.values()) - min(session.times.values()) if session.times else 0
        rate = max(1.0, min(10.0, (len(frames) - 1) / span)) if span > 0 else 8.0
        with tempfile.TemporaryDirectory() as tmp:
            clip = Path(tmp) / "run.mp4"
            subprocess.run([video.ffmpeg(), "-hide_banner", "-loglevel", "error", "-y", "-framerate", f"{rate:.2f}", "-pattern_type", "glob",
                            "-i", str(d / "f_*.jpg"), "-c:v", "libx264", "-pix_fmt", "yuv420p", "-vf", "scale=-2:360", str(clip)], check=True)
            listing = "\n".join(f"- {s['id']}: {s['action']} ({s['done_when']})" for s in card["steps"])
            r = gemini.generate(config.MODELS["hydrogen"], [gemini.inline(clip.read_bytes(), "video/mp4"), {"text": PROMPT % listing}],
                                {"responseMimeType": "application/json"}, timeout=timeout, tries=1)
        out = gemini.json_of(r)
        if not isinstance(out, dict):
            raise ValueError("unparseable baseline answer: " + str(out)[:160])
        norm = lambda v: {str(x).strip().lower() for x in ([k for k, on in v.items() if on] if isinstance(v, dict) else v or [])} & set(ids)
        performed, not_performed = norm(out.get("performed")), norm(out.get("not_performed"))
        return {"skipped": [i for i in ids if i in not_performed or i not in performed], "lat": r["_latency"]}
    return gemini.taped(f"baseline/hydrogen/{card['id']}/{d.name}", call)
