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

NAME_PROMPT = """You are watching one person demonstrate something once so that someone else can repeat it.
It may be a hands-on task with objects (steps of several seconds each) or a quick series of hand, arm or body
poses (each held for a second or less). List every DISTINCT step or pose you can see, in the order it first
appears. If the same pose or action happens again later, do not list it twice. Do not invent anything you
cannot see, and give no timestamps.
Answer with JSON only: [{"name": "<2 to 6 words>", "look": "<what it looks like: hands, fingers, arms, objects, position; one sentence>"}]"""


def _name(b, clip):
    def call():
        parts = [gemini.inline(clip.read_bytes(), "video/mp4"), {"text": NAME_PROMPT}]
        try:                                         # naming is easy for the model: low thinking keeps the wait short
            d = gemini.generate(config.MODELS["hydrogen"], parts,
                                {"responseMimeType": "application/json", "thinkingConfig": {"thinkingLevel": "low"}}, tries=1)
        except gemini.ApiError as e:
            if e.status != 400:
                raise
            d = gemini.generate(config.MODELS["hydrogen"], parts, {"responseMimeType": "application/json"})
        return {"poses": gemini.json_of(d), "lat": d["_latency"]}
    r = gemini.taped(b.key("poses"), call)
    poses = []
    for k, p in enumerate(r["poses"] if isinstance(r["poses"], list) else []):
        name = str(p.get("name") or p.get("action") or "").strip()
        if name:
            poses.append({"id": f"p{k + 1:02d}", "name": name, "look": str(p.get("look") or p.get("done_when") or "").strip()})
    if not poses:
        raise ValueError("Hydrogen saw no steps in the clip")
    b.emit("name", "done", f"{len(poses)} distinct steps seen" + (f" in {r['lat']} s" if r.get("lat") else ""),
           steps=[p["name"] for p in poses])
    return poses


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

    poses = b.stage("name", lambda: _name(b, clip))
    ids = [p["id"] for p in poses]

    def locate():
        answers = _all(lambda i: _label_frame(poses, frames[i].read_bytes(), b.key("frame", f"{i:05d}")), len(frames))
        failed = sum(a is None for a in answers)
        if failed > max(2, len(frames) // 5):
            raise gemini.ApiError(-1, f"{failed} of {len(frames)} frames got no answer")
        probs = [a["probs"] if a else None for a in answers]
        segs = decode.segments(probs, times, ids)
        if not segs:
            raise ValueError("no step could be found in the clip: hold each step a little longer and keep it in view")
        for s in segs:                               # the clearest frame of each occurrence
            inside = [i for i, t in enumerate(times) if s["start"] <= t <= s["end"] and probs[i]]
            s["frame"] = max(inside, key=lambda i: probs[i].get(s["label"], 0.0))
        found = {s["label"] for s in segs}
        lost = [p["name"] for p in poses if p["id"] not in found]
        b.emit("locate", "done", f"{len(segs)} steps in order, {len(found)} distinct" +
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
        pick = list(range(0, len(frames), 2 if fps > 2.5 else 1))        # every other frame is enough to check the card
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

    def finish(self, wait_s=3.0, backfill_s=6.0):
        if self.verdict is not None:
            return self.verdict
        res = super().finish(wait_s=wait_s, backfill_s=max(backfill_s, 0.0))
        seen = [s["label"] for s in res["seen"]]
        marks, extra, got = self._marks(seen, final=True)
        name = {g["id"]: g["name"] for g in self.kit["signs"]}
        num = lambda sid: f"step {self.step_ids.index(sid) + 1}"
        skipped = [sid for sid in self.step_ids if marks[sid] in ("skipped", "wrong")]
        unsure = []
        if res["frames"] and res["missing_frames"] > res["frames"] * 0.2:      # too many frames unanswered to say "never"
            unsure, skipped = skipped, []
        parts = []
        for sid in skipped:
            parts.append(f"{num(sid)} was {name.get(got[sid], '?')}, not {name[self.card['steps'][self.step_ids.index(sid)]['pose']]}"
                         if sid in got else f"{num(sid)} never happened")
        if unsure:
            parts.append("not sure about " + ", ".join(num(s) for s in unsure))
        if extra:
            parts.append("extra: " + ", ".join(name.get(x, x) for x in extra))
        if res["missing_frames"]:
            parts.append(f"{res['missing_frames']} frames got no answer")
        if not seen:
            parts = ["nothing recognised"]
        v = {"seen": [sid for sid in self.step_ids if marks[sid] == "seen"], "unsure": unsure, "skipped": skipped,
             "extra": extra, "wrong": got, "order_violations": [], "scores": {}, "thresholds": {},
             "windows": res["frames"] - res["missing_frames"], "missing_windows": [], "review": None,
             "clean": bool(seen) and not skipped and not unsure and not extra,
             "performed": [name.get(x, x) for x in seen], "latency": res.get("latency"),
             "text": "; ".join(parts) if parts else f"all {len(self.step_ids)} steps seen, in order"}
        self.verdict = v
        return v
