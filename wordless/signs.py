"""Frame-by-frame checking: the reference data and sessions behind the fast path (see fast.py).

A kit is a vocabulary plus the sequences made from it:
  signs      each taught by one photo of the person holding the pose (the reference), redrawn as a panel
  sequences  named, ordered lists of signs ("open, turn, press", a hand-signal phrase, a handshake)

A session watches a camera or a clip at several frames a second. Every frame is ONE Decisions API question:
reference sheet + this frame -> which sign, with probabilities. `decode` turns the answers into the signs
performed and names the known sequence (or says what was wrong: missing, extra or swapped sign).

Nothing here knows what the signs mean. Anything that is a short series of distinct, holdable poses fits.
"""
import concurrent.futures as cf
import io
import json
import math
import threading
import time
import uuid

from PIL import Image, ImageDraw

from . import card as cards
from . import config, decode, gemini, video

CELL = (480, 360)
NONE_KEY = "other"            # the catch-all choice, named as the Decisions API guide asks
FRAME_SIDE = 640                 # frames are downsized to this before they are sent
MAX_INFLIGHT = 24                # frames waiting for an answer; beyond this new frames are dropped, not queued
IDLE_END_S = 1.6                 # a pause this long after the last sign ends the sequence (live)
_pool = cf.ThreadPoolExecutor(MAX_INFLIGHT)
_draw_pool = cf.ThreadPoolExecutor(6)
_kit_lock = threading.Lock()
_sessions = {}

DRAW_PROMPT = ("Redraw this photo as one panel of a wordless instruction sheet: clean black line art on a white "
               "background, uniform outlines.\n"
               "Before you draw, decide what carries this step: which hands, fingers, arms and objects a person must "
               "copy to repeat it. Draw ONLY those, large and centred, and leave everything else out.\n"
               "- Hands and fingers: draw only the hands that are doing the step, in the exact pose from the photo. "
               "Leave out a hand that is in the photo but only resting or waiting. Never draw a hand, a finger or an arm "
               "that is not visible in the photo, and never more than two hands. End each arm in open lines at the "
               "wrist or forearm unless the arm's position is part of the step.\n"
               "- The person: no portrait. No facial features, hair, clothing details, jewellery or body outline. Only "
               "if the step depends on where the hands are relative to the head or chest, add that part as one plain, "
               "featureless outline (an empty oval for a head) so the position can be read.\n"
               "- Objects: only the ones the hands touch or act on. Do not add objects.\n"
               "No shading, no colour, no background, no letters, no numbers, no words.")


def draw_prompt(name="", look=""):
    """DRAW_PROMPT plus what the step is, so the image model can tell what matters in the photo."""
    what = " ".join(x.strip() for x in (name, look) if x and x.strip())
    if not what:
        return DRAW_PROMPT
    # Told the step, the image model drew what the words say (a hand reaching in from nowhere) instead of the photo.
    return DRAW_PROMPT + ("\nThe step this panel teaches is given below. Use it ONLY to choose which of the things visible in the "
                          "photo to keep. The photo is the truth: if the step mentions a hand, an object or a movement that the "
                          "photo does not show, do not draw it. Never write the step.\nStep: " + what)


# ---------------------------------------------------------------- kits
def kit_dir(kid):
    return config.CARDS / kid


def load(kid):
    p = kit_dir(kid) / "kit.json"
    if not p.exists():
        raise FileNotFoundError(f"no kit '{kid}'")
    return json.loads(p.read_text())


def save(kit):
    d = kit_dir(kit["id"])
    d.mkdir(parents=True, exist_ok=True)
    tmp = d / "kit.tmp"
    tmp.write_text(json.dumps(kit, indent=1))
    tmp.replace(d / "kit.json")
    return kit


def list_kits():
    out = []
    if config.CARDS.is_dir():
        for p in sorted(config.CARDS.glob("*/kit.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            k = json.loads(p.read_text())
            out.append({"id": k["id"], "title": k["title"], "signs": len(k["signs"]), "sequences": len(k["sequences"])})
    return out


def new(title="Signs"):
    return save({"id": cards.new_id(title), "title": title, "kind": "signs", "signs": [], "sequences": [], "next": 1})


def sign_ids(kit):
    return [s["id"] for s in kit["signs"]]


def sign(kit, sid):
    return next(s for s in kit["signs"] if s["id"] == sid)


def add_sign(kid, name, image, draw=True):
    """Teach one sign from one photo. Re-teaching a name replaces its photo."""
    jpeg = cards.to_jpeg(image, max_side=640)
    with _kit_lock:
        kit = load(kid)
        old = next((s for s in kit["signs"] if s["name"].lower() == name.strip().lower()), None)
        if old:
            s = old
            s.pop("panel", None)
        else:
            s = {"id": f"g{kit['next']}", "name": name.strip() or f"sign {kit['next']}"}
            kit["next"] += 1
            kit["signs"].append(s)
        s["ref"] = f"ref_{s['id']}.jpg"
        s["v"] = s.get("v", 0) + 1
        (kit_dir(kid) / s["ref"]).write_bytes(jpeg)
        compose(kit)
        save(kit)
    if draw and gemini.mode() != "replay":
        _draw_pool.submit(draw_panel, kid, s["id"], s["v"])
    return kit


def remove_sign(kid, sid):
    with _kit_lock:
        kit = load(kid)
        kit["signs"] = [s for s in kit["signs"] if s["id"] != sid]
        kit["sequences"] = [q for q in kit["sequences"] if sid not in q["signs"]]
        if kit["signs"]:
            compose(kit)
        return save(kit)


def set_sequence(kid, name, signs, seq_id=None):
    """Add or replace a named sequence. `signs` may be sign ids or sign names."""
    with _kit_lock:
        kit = load(kid)
        by_name = {s["name"].lower(): s["id"] for s in kit["signs"]}
        ids = set(sign_ids(kit))
        resolved = []
        for x in signs:
            sid = x if x in ids else by_name.get(str(x).strip().lower())
            if not sid:
                raise ValueError(f"sequence '{name}': no sign called '{x}' in this kit")
            resolved.append(sid)
        if not resolved:
            raise ValueError("a sequence needs at least one sign")
        seq_id = seq_id or cards.slug(name) or uuid.uuid4().hex[:6]
        kit["sequences"] = [q for q in kit["sequences"] if q["id"] != seq_id]
        kit["sequences"].append({"id": seq_id, "name": name.strip(), "signs": resolved})
        return save(kit)


def remove_sequence(kid, seq_id):
    with _kit_lock:
        kit = load(kid)
        kit["sequences"] = [q for q in kit["sequences"] if q["id"] != seq_id]
        return save(kit)


def compose(kit, cell=CELL):
    """Numbered grid of the reference photos: the image the checker compares every frame with."""
    d = kit_dir(kit["id"])
    n = len(kit["signs"])
    cols = min(n, 4) if n != 5 and n != 6 else 3
    rows = math.ceil(n / cols)
    line = 3
    sheet = Image.new("RGB", (cols * cell[0], rows * cell[1]), "black")
    draw = ImageDraw.Draw(sheet)
    font = cards._font(30)
    for k, s in enumerate(kit["signs"]):
        x, y = (k % cols) * cell[0], (k // cols) * cell[1]
        ref = cards.fit(Image.open(d / s["ref"]), (cell[0] - 2 * line, cell[1] - 2 * line))
        sheet.paste(ref, (x + line, y + line))
        draw.rectangle([x + line + 4, y + line + 4, x + line + 48, y + line + 48], fill="black")
        draw.text((x + line + 26, y + line + 26), str(k + 1), fill="white", font=font, anchor="mm")
    for k in range(n, cols * rows):
        x, y = (k % cols) * cell[0], (k // cols) * cell[1]
        draw.rectangle([x + line, y + line, x + cell[0] - line - 1, y + cell[1] - line - 1], fill="white")
    sheet.save(d / "sheet.jpg", quality=90)
    kit["sheet_v"] = kit.get("sheet_v", 0) + 1
    return d / "sheet.jpg"


def sheet_bytes(kit):
    return (kit_dir(kit["id"]) / "sheet.jpg").read_bytes()


def draw_panel(kid, sid, version):
    """Reference photo -> line-art panel (the picture shown to the next person). Runs in the background."""
    try:
        photo = (kit_dir(kid) / f"ref_{sid}.jpg").read_bytes()
        sign = next((x for x in load(kid)["signs"] if x["id"] == sid), None) or {}
        d = gemini.generate(config.MODELS["image"], [gemini.inline(photo, "image/jpeg"),
                                                     {"text": draw_prompt(sign.get("name", ""), sign.get("look", ""))}],
                            {"responseModalities": ["IMAGE"]})
        art = cards.to_jpeg(gemini.image_of(d), max_side=640)
    except Exception as e:                      # the photo stays as the picture; say why
        art, err = None, f"{type(e).__name__}: {e}"[:160]
    with _kit_lock:
        kit = load(kid)
        s = next((x for x in kit["signs"] if x["id"] == sid), None)
        if not s or s.get("v") != version:      # re-taught or removed meanwhile
            return
        if art:
            s["panel"] = f"panel_{sid}_{version}.jpg"
            (kit_dir(kid) / s["panel"]).write_bytes(art)
            s.pop("panel_error", None)
        else:
            s["panel_error"] = err
        save(kit)


def picture(kit, sid):
    """File shown for a sign: the drawn panel when it exists, else the reference photo."""
    s = sign(kit, sid)
    return kit_dir(kit["id"]) / (s.get("panel") or s["ref"])


def from_card(card, kid=None):
    """A routine card as a kit: its steps are the signs, the card order is the one sequence. Lets the fast
    frame-by-frame path check a routine with short steps."""
    kid = kid or card["id"] + "-fast"
    d = kit_dir(kid)
    d.mkdir(parents=True, exist_ok=True)
    kit = {"id": kid, "title": card.get("title", card["id"]), "kind": "signs", "signs": [], "sequences": [], "next": 1,
           "from_card": card["id"]}
    src = cards.card_dir(card["id"])
    for s in card["steps"]:
        g = {"id": s["id"], "name": s["action"], "ref": f"ref_{s['id']}.jpg"}
        photo = src / (s.get("keyframe") or s["panel"])
        (d / g["ref"]).write_bytes(photo.read_bytes())
        if (src / s["panel"]).exists():
            g["panel"] = f"panel_{s['id']}.jpg"
            (d / g["panel"]).write_bytes((src / s["panel"]).read_bytes())
        kit["signs"].append(g)
    kit["sequences"] = [{"id": "routine", "name": kit["title"], "signs": [s["id"] for s in card["steps"]]}]
    compose(kit)
    return save(kit)


# ---------------------------------------------------------------- the question
def classify(kit, frame_jpeg, key=None, timeout=6, tries=1):
    """Which sign is in this frame? Returns {"probs": {sign id | "none": p}, "top", "conf", "lat"}."""
    def call():
        crit = {f"p{k + 1}": f"picture {k + 1}: {s['name']}" for k, s in enumerate(kit["signs"])}
        crit[NONE_KEY] = "none of the pictures: hands down or out of view, moving between poses, or a different pose"
        q = {"sign": {"type": "choice", "criteria": crit,
                      "instructions": "The first image is a numbered reference sheet of poses. The second image is one camera frame of a "
                                      "person, possibly a different person in a different place. Which numbered pose are they holding in "
                                      "the frame? Compare hands, fingers and arms, not the background."}}
        blocks = [gemini.text_block("REFERENCE SHEET:"), gemini.image_block(sheet_bytes(kit)),
                  gemini.text_block("FRAME:"), gemini.image_block(frame_jpeg() if callable(frame_jpeg) else frame_jpeg)]
        res = gemini.decide(blocks, q, timeout=timeout, tries=tries, gap=config.SIGNS_MIN_GAP_S)
        a = res["answers"].get("sign") or {}
        if "choice" not in a:
            raise gemini.ApiError(200, "answer without a choice: " + str(res["answers"])[:200])
        ids = sign_ids(kit)
        conv = lambda lab: decode.NONE if lab == NONE_KEY else ids[int(lab[1:]) - 1]
        probs = {conv(k): round(v, 3) for k, v in (a.get("probabilities") or {}).items() if v > 0.01}
        top = conv(a["choice"])
        probs.setdefault(top, round(a.get("confidence", 0.5), 3))
        return {"probs": probs, "top": top, "conf": round(a.get("confidence", probs[top]), 3), "lat": res["latency"]}
    return gemini.taped(key, call)


# ---------------------------------------------------------------- sessions
def get(sid):
    return _sessions[sid]


class Session:
    """One person performing in front of the camera (or a clip). mode 'identify': which known sequence was it?
    mode 'follow': they are following `target`; say which sign was wrong, missing or extra."""

    def __init__(self, kit, mode="identify", target=None, source="live", name=None):
        self.id = name or (time.strftime("%H%M%S-") + uuid.uuid4().hex[:4])
        self.kit, self.mode, self.source = kit, mode, source
        self.target = next((q for q in kit["sequences"] if q["id"] == target), None) if target else None
        if mode == "follow" and not self.target:
            raise ValueError("follow mode needs a known sequence")
        self.dir = config.RUNS / self.id
        self.lock = threading.Lock()
        self.times, self.answers, self.errors, self.pending = {}, {}, {}, {}
        self.dropped = 0
        self.lat = []
        self.started = time.time()
        self.done, self.result, self.fatal = False, None, None
        _sessions[self.id] = self

    def key(self, i):
        return f"signs/{self.kit['id']}/{self.id}/{i:05d}"

    def _ask(self, i, jpeg, **kw):
        try:
            a = classify(self.kit, jpeg, key=self.key(i), **kw)
        except gemini.NoCredit:
            with self.lock:
                self.errors[i] = "no credit"
                self.fatal = "The API key has no credit (HTTP 402)."
            return
        except Exception as e:
            with self.lock:
                self.errors[i] = f"{type(e).__name__}: {e}"[:200]
            return
        with self.lock:
            if self.done:
                return
            self.errors.pop(i, None)
            self.answers[i] = a
            self.lat.append(a["lat"])

    def add_frame(self, i, t, image, wait=False, **kw):
        """Frame i taken t seconds after the start. Returns at once; the answer lands when it lands."""
        i = int(i)
        with self.lock:
            if self.done:
                return False
            inflight = sum(1 for f in self.pending.values() if not f.done())
            if inflight >= MAX_INFLIGHT and not wait:
                self.dropped += 1                # the camera is faster than the answers: skip, never queue
                return False
            self.times[i] = float(t)
        jpeg = cards.to_jpeg(image, max_side=FRAME_SIDE, quality=80)
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / f"f_{i:05d}.jpg").write_bytes(jpeg)
        fut = _pool.submit(self._ask, i, jpeg, **kw)
        with self.lock:
            self.pending[i] = fut
        return True

    # ------------------------------------------------------------ reading
    def _decoded(self):
        idx = sorted(self.times)
        frames = [self.answers[i]["probs"] if i in self.answers else None for i in idx]
        times = [self.times[i] for i in idx]
        return decode.segments(frames, times, sign_ids(self.kit)), idx, frames, times

    def _public(self, segs):
        names = {s["id"]: s["name"] for s in self.kit["signs"]}
        return [dict(s, name=names.get(s["label"], s["label"])) for s in segs]

    def state(self):
        with self.lock:
            segs, idx, frames, times = self._decoded()
            seen = [s["label"] for s in segs]
            last = max(self.answers) if self.answers else None
            now = self.answers[last] if last is not None else None
            seqs = [self.target] if self.target else self.kit["sequences"]
            idle = None
            if segs and times:
                answered = [self.times[i] for i in self.answers]
                idle = round(max(answered) - segs[-1]["end"], 2) if answered else None
            lat = sorted(self.lat)
            return {
                "id": self.id, "kit": self.kit["id"], "mode": self.mode, "source": self.source,
                "target": self.target["id"] if self.target else None,
                "seen": self._public(segs), "now": now and {"top": now["top"], "conf": now["conf"]},
                "candidates": decode.rank(seen, seqs, done=False),
                "frames": len(self.times), "answered": len(self.answers), "errors": len(self.errors), "dropped": self.dropped,
                "waiting": sum(1 for f in self.pending.values() if not f.done()),
                "latency": lat[len(lat) // 2] if lat else None,
                "idle": idle, "should_end": bool(idle is not None and idle >= IDLE_END_S),
                "seconds": round(time.time() - self.started, 1),
                "done": self.done, "result": self.result, "fatal": self.fatal,
            }

    def finish(self, wait_s=4.0, backfill_s=8.0):
        """Wait for answers in flight, ask failed frames once more, then name the sequence. Safe to call twice."""
        with self.lock:
            if self.done:
                return self.result
        cf.wait(list(self.pending.values()), timeout=wait_s)
        if not self.fatal and self.source != "replay" and backfill_s > 0:
            with self.lock:
                todo = sorted(i for i in self.times if i not in self.answers)
            t0 = time.time()
            futs = []
            for i in todo:
                p = self.dir / f"f_{i:05d}.jpg"
                if p.exists():
                    futs.append(_pool.submit(self._ask, i, p.read_bytes(), timeout=5, tries=2))
            cf.wait(futs, timeout=max(0.0, backfill_s - (time.time() - t0)))
        with self.lock:
            segs, idx, frames, times = self._decoded()
            seen = [s["label"] for s in segs]
            names = {s["id"]: s["name"] for s in self.kit["signs"]}
            if self.mode == "follow":
                dist, ops = decode.align(seen, self.target["signs"])
                res = {"kind": "exact" if dist == 0 else "errors", "distance": dist, "ops": ops,
                       "best": {"id": self.target["id"], "name": self.target["name"], "ops": ops, "distance": dist}}
            else:
                res = decode.verdict(seen, self.kit["sequences"])
            res["seen"] = self._public(segs)
            res["missing_frames"] = len(self.times) - len(self.answers)
            res["frames"] = len(self.times)
            res["text"] = result_text(res, names, self.mode)
            lat = sorted(self.lat)
            res["latency"] = lat[len(lat) // 2] if lat else None
            self.result, self.done = res, True
            log = {"id": self.id, "kit": self.kit["id"], "mode": self.mode, "source": self.source,
                   "target": self.target["id"] if self.target else None, "seconds": round(time.time() - self.started, 1),
                   "result": res, "frames": [[i, self.times[i], self.answers.get(i)] for i in idx]}
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / "signs.json").write_text(json.dumps(log, indent=1))
        return res


def result_text(res, names, mode):
    n = lambda sid: names.get(sid, sid)

    def problems(ops):
        out = []
        for o in ops:
            if o["op"] == "wrong":
                out.append(f"sign {o['pos']} was {n(o['got'])}, expected {n(o['want'])}")
            elif o["op"] == "missing":
                out.append(f"sign {o['pos']} ({n(o['want'])}) never happened")
            elif o["op"] == "extra":
                out.append(f"extra sign {n(o['got'])}")
        return "; ".join(out)

    if not res["seen"]:
        return "no sign seen"
    if res["kind"] == "exact":
        return res["best"]["name"] + (": every sign in order" if mode == "follow" else "")
    if res["kind"] in ("near", "errors"):
        return f"{res['best']['name']}: {problems(res['best']['ops'])}"
    return "no known sequence: " + ", ".join(s["name"] for s in res["seen"])


# ---------------------------------------------------------------- from a file
def run_video(kit, path, fps=4.0, mode="identify", target=None, name=None, workers=12):
    """Score a recorded clip through the same path as the camera. Blocks; returns the finished session."""
    s = Session(kit, mode=mode, target=target, source="file", name=name)
    tmp = config.RUNS / "_frames" / s.id
    frames = video.frames(path, tmp, fps=fps)
    for i, p in enumerate(frames):
        s.add_frame(i, i / fps, p.read_bytes(), wait=True, timeout=12, tries=3)
        while sum(1 for f in list(s.pending.values()) if not f.done()) >= workers:
            time.sleep(0.02)
    s.finish(wait_s=30)
    return s


def replay_session(kit, sid, mode="identify", target=None):
    """Re-score a saved session from its frames (and taped answers, so it works with the network off)."""
    src = config.RUNS / sid
    log = json.loads((src / "signs.json").read_text())
    s = Session(kit, mode=mode, target=target, source="replay", name=f"{sid}-r{uuid.uuid4().hex[:3]}")
    s.key = lambda i: f"signs/{kit['id']}/{sid}/{i:05d}"       # the answers recorded for the original session
    for i, t, _ in log["frames"]:
        p = src / f"f_{i:05d}.jpg"
        s.add_frame(i, t, p.read_bytes() if p.exists() else _blank(), wait=True, timeout=12, tries=3)
    s.finish(wait_s=30)
    return s


def _blank():
    buf = io.BytesIO()
    Image.new("RGB", (64, 48), "black").save(buf, "JPEG")
    return buf.getvalue()
