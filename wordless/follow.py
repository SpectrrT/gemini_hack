"""Follow sessions: someone works from the card while windows are labelled and the tracker fills in.

Two sources of windows:
  live     the browser posts two webcam stills a second; every still and answer is saved under runs/<sid>/,
           so any live session can be replayed later (the announced fallback at the table).
  replay   a recording (a video file cut into 2 s clips, or an earlier live session) is fed through the SAME
           checker and tracker at a chosen speed.
The verdict is always computed from the full buffer when the session is finished (windows whose call
failed or is still in flight are asked again first). A window that stays unanswered is listed, and a step it
could be hiding is reported as "not sure", never as "never happened". Panels turning green while the task
runs are display only.

Live cadence: one question per 2 s (two stills a second apart, pairs do not overlap). That is the protocol
the two-still measurement and the frozen cut-offs refer to.
"""
import concurrent.futures as cf
import json
import threading
import time
import uuid

from . import card as cards
from . import checker, config, gemini, video
from .tracker import Tracker

_sessions = {}
_pool = cf.ThreadPoolExecutor(6)


def get(sid):
    return _sessions[sid]


class Session:
    def __init__(self, card, source, recording=None, use_own_thresholds=False, review=None):
        self.id = time.strftime("%H%M%S-") + uuid.uuid4().hex[:4]
        self.card, self.source, self.recording = card, source, recording
        thr = card.get("thresholds") if use_own_thresholds else None
        self.tracker = Tracker(cards.step_ids(card), links=card.get("links", []), thresholds=thr)
        self.dir = config.RUNS / self.id
        self.lock = threading.Lock()
        self.pending = {}            # window index -> future
        self.errors = {}             # window index -> message
        self.stills = {}             # window index -> [jpeg, jpeg] (live only, for back-fill)
        self.answers = {}
        self.total = None            # number of windows, when known (replay)
        self.done = False
        self.verdict = None
        self.fatal = None
        self.review = config.REVIEW if review is None else review
        self.started = time.time()
        _sessions[self.id] = self

    # ------------------------------------------------------------ feeding
    def _record(self, i, fn):
        try:
            a = fn()
        except gemini.NoCredit:
            with self.lock:
                self.errors[i] = "no credit"
                self.fatal = "The API key has no credit (HTTP 402). Top it up, or switch to replay."
            return
        except (gemini.ApiError, gemini.TapeMiss) as e:
            with self.lock:
                self.errors[i] = str(e)[:200]
            return
        except Exception as e:      # anything else must not vanish inside a pool thread
            with self.lock:
                self.errors[i] = f"{type(e).__name__}: {e}"[:200]
            return
        if self.done:               # an answer that lands after the verdict does not change it
            return
        with self.lock:
            self.errors.pop(i, None)
            self.answers[i] = a
            self.tracker.add(i, a["step"], a["conf"])

    def add_stills(self, i, stills):
        """Live: label window i from two webcam stills. Returns at once; the answer lands when it lands."""
        self.dir.mkdir(parents=True, exist_ok=True)
        for k, s in enumerate(stills):
            (self.dir / f"{i:04d}_{k}.jpg").write_bytes(s)
        key = f"follow/{self.card['id']}/{self.id}/still/{i:04d}"
        fut = _pool.submit(self._record, i, lambda: checker.classify_stills(self.card, stills, key=key))
        with self.lock:
            self.stills[i] = stills
            self.pending[i] = fut

    def add_window(self, i, kind, clip=None):
        """Replay: label window i of a recording (kind 'card' = card + clip, 'still' = saved live stills)."""
        rec = self.recording
        key = f"follow/{self.card['id']}/{rec}/{kind}/{i:04d}"
        if kind == "still":
            src = config.RUNS / rec
            fn = lambda: checker.classify_stills(self.card, lambda: [(src / f"{i:04d}_{k}.jpg").read_bytes() for k in (0, 1)], key=key, tries=3)
        else:
            fn = lambda: checker.classify_clip(self.card, (lambda: clip.read_bytes()) if clip else None, key=key)
        self._record(i, fn)

    def _second_opinion(self, timeout=config.REVIEW_TIMEOUT_S):
        """One Hydrogen call on the whole clip (the file, or this live session's saved stills)."""
        from . import baseline
        rec = self.recording if self.source == "replay" else self.id
        if self.review == "tape":                           # a recorded run played back: saved answer only, no call
            return gemini.tape.get_json(f"baseline/hydrogen/{self.card['id']}/{rec}")
        if self.source == "live" and len(self.stills) < 2:
            return None
        fut = _pool.submit(baseline.hydrogen_one_call, self.card, rec)
        try:
            return fut.result(timeout=timeout)
        except cf.TimeoutError:
            return {"error": f"no answer in {timeout:.0f} s"}
        except gemini.TapeMiss:
            return None                                     # replay mode and never recorded: nothing to add
        except Exception as e:
            return {"error": f"{type(e).__name__}: {e}"[:160]}

    # ------------------------------------------------------------ reading
    def state(self):
        with self.lock:
            step, conf = self.tracker.current()
            return {
                "id": self.id, "card": self.card["id"], "source": self.source, "recording": self.recording,
                "panels": self.tracker.panel_states(), "now": step, "now_conf": conf,
                "windows": len(self.answers), "total": self.total, "errors": len(self.errors),
                "waiting": sum(1 for f in list(self.pending.values()) if not f.done()),
                "done": self.done, "verdict": self.verdict, "fatal": self.fatal,
                "timeline": [[i, a["step"], a["conf"]] for i, a in sorted(self.answers.items())][-400:],
            }

    def finish(self, wait_s=4.0, backfill_s=10.0):
        """Back-fill, then compute the verdict from every buffered window. Safe to call twice."""
        with self.lock:
            if self.done:
                return self.verdict
        cf.wait(list(self.pending.values()), timeout=wait_s)
        if self.source == "live" and not self.fatal:
            with self.lock:                                 # failed, or still in flight: ask again, briefly
                todo = sorted(i for i in self.stills if i not in self.answers)
            t0 = time.time()
            for i in todo:
                if self.fatal or time.time() - t0 > backfill_s:
                    break
                if i in self.answers:
                    continue
                key = f"follow/{self.card['id']}/{self.id}/still/{i:04d}"
                self._record(i, lambda i=i: checker.classify_stills(self.card, self.stills[i], key=key, timeout=5, tries=1))
        second = self._second_opinion() if self.review and not self.fatal else None
        with self.lock:
            asked = set(self.stills) | set(self.errors) | set(self.pending)
            missing = sorted(asked - set(self.answers))
            v = self.tracker.verdict()
            v["missing_windows"] = missing
            apply_review(self.card, v, second, optional=self.tracker.optional)
            if missing:                                     # could the unanswered windows be hiding the step?
                for sid in list(v["skipped"]):
                    what_if = Tracker(self.tracker.step_ids, thresholds=self.tracker.thresholds)
                    what_if.obs = dict(self.tracker.obs)
                    for i in missing:
                        what_if.add(i, sid, 0.85)
                    if self.fatal or what_if.state(sid) != "skipped":
                        v["skipped"].remove(sid)
                        v["unsure"].append(sid)
                v["clean"] = False
            v["text"] = verdict_text(self.card, v)
            self.verdict, self.done = v, True
            answers = {str(i): a for i, a in sorted(self.answers.items())}
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / "session.json").write_text(json.dumps({
            "id": self.id, "card": self.card["id"], "source": self.source, "recording": self.recording,
            "seconds": round(time.time() - self.started, 1), "verdict": v, "answers": answers}, indent=1))
        return v


def apply_review(card, v, second, optional=()):
    """Whole-clip review (rule "review" in docs/EVAL.md). The window checker confuses look-alike steps, so on
    its own it reported performed steps as "never happened". One Hydrogen call on the whole clip now decides:
      it says performed                      -> seen
      it says not performed, card saw it     -> not sure
      it says not performed, card did not    -> never happened
    `second` is {"skipped": [...], "lat": s}, or {"error": text} / None when the review could not run; the
    card's own verdict then stands and the verdict says so."""
    v["card_verdict"] = {"seen": list(v["seen"]), "unsure": list(v["unsure"]), "skipped": list(v["skipped"])}
    if not second:
        v["review"] = None
        return v
    if "error" in second:
        v["review"] = {"ok": False, "error": second["error"]}
        return v
    not_done = set(second["skipped"])
    card_seen = set(v["seen"])
    seen, unsure, skipped = [], [], []
    for sid in cards.step_ids(card):
        if sid not in not_done:
            seen.append(sid)
        elif sid in optional:
            continue
        elif sid in card_seen:
            unsure.append(sid)
        else:
            skipped.append(sid)
    before = v["card_verdict"]
    v["review"] = {"ok": True, "model": config.MODELS["hydrogen"], "lat": second.get("lat"),
                   "cleared": [s for s in before["skipped"] + before["unsure"] if s in seen],
                   "doubted": [s for s in unsure if s in card_seen]}
    order = {sid: n for n, sid in enumerate(v["seen"])}           # keep the order the card saw them in
    v["seen"] = sorted(seen, key=lambda s: order.get(s, len(order)))
    v["unsure"], v["skipped"] = unsure, skipped
    v["order_violations"] = [p for p in v["order_violations"] if p[0] in card_seen and p[1] in card_seen]
    v["clean"] = not skipped and not unsure and not v["order_violations"]
    return v


def verdict_text(card, v):
    num = lambda sid: f"panel {cards.panel_number(card, sid)}"
    parts = []
    if v["skipped"]:
        parts.append(", ".join(num(s) for s in v["skipped"]) + " never happened")
    if v["unsure"]:
        parts.append("not sure about " + ", ".join(num(s) for s in v["unsure"]))
    for a, b in v["order_violations"]:
        parts.append(f"{num(b)} came before {num(a)}")
    if v.get("missing_windows"):
        parts.append(f"{len(v['missing_windows'])} windows got no answer")
    rv = v.get("review")
    tail = ""
    if rv and rv.get("ok") and rv["cleared"]:
        tail = " (whole-clip review cleared " + ", ".join(num(s) for s in rv["cleared"]) + ")"
    elif rv and not rv.get("ok"):
        tail = " (whole-clip review did not run)"
    if not parts:
        return f"all {len(v['seen'])} panels seen" + tail
    return "; ".join(parts) + tail


# ---------------------------------------------------------------- replay
def recording_windows(card, rec, workdir=None):
    """Where a recording's windows come from. Returns (kind, window indices, list of clip paths or None)."""
    live = config.RUNS / rec
    if live.is_dir() and list(live.glob("*_0.jpg")):
        return "still", sorted(int(p.name[:4]) for p in live.glob("*_0.jpg")), None
    vid = video.find_video(rec)
    taped = gemini.tape.count(f"follow/{card['id']}/{rec}/card")
    if vid and gemini.mode() != "replay":
        clips = video.cut_windows(vid, (workdir or config.RUNS / "_windows") / rec)
        return "card", list(range(len(clips))), clips
    if taped:
        return "card", list(range(taped)), None
    still = gemini.tape.root / "follow" / card["id"] / rec / "still"
    if still.is_dir():                                     # a live session whose stills are gone but answers are taped
        return "still", sorted(int(p.stem) for p in still.glob("*.json")), None
    raise FileNotFoundError(f"recording '{rec}': no video file and nothing on tape for card '{card['id']}'")


def replay(card, rec, speed=8.0, use_own_thresholds=False, block=False, review=None):
    """Feed a recording through the checker at `speed` x real time (0 = as fast as possible)."""
    kind, idx, clips = recording_windows(card, rec)
    s = Session(card, "replay", recording=rec, use_own_thresholds=use_own_thresholds, review=review)
    s.total = len(idx)

    def run():
        try:
            for n, i in enumerate(idx):
                t = time.time()
                s.add_window(i, kind, clips[n] if clips else None)
                if s.fatal:
                    break
                if speed:
                    time.sleep(max(0.0, config.WINDOW_S / speed - (time.time() - t)))
        except Exception as e:
            s.fatal = f"replay stopped: {type(e).__name__}: {e}"[:200]
        finally:
            s.finish(wait_s=0)

    if block:
        run()
    else:
        threading.Thread(target=run, daemon=True).start()
    return s


def recordings_for(card):
    """Recordings that can be replayed for this card: taped ones, video files, and saved live sessions."""
    out = {}
    d = gemini.tape.root / "follow" / card["id"]
    if d.is_dir():
        for p in sorted(d.iterdir()):
            if (p / "card").is_dir() or (p / "still").is_dir():
                out[p.name] = {"id": p.name, "on_tape": True, "video": bool(video.find_video(p.name)),
                               "kind": "card" if (p / "card").is_dir() else "still"}
    if gemini.mode() != "replay":            # video files that can be scored with live calls
        for folder in config.VIDEO_DIRS:
            for p in sorted(folder.glob("*.mp4")) if folder.is_dir() else []:
                out.setdefault(p.stem, {"id": p.stem, "on_tape": False, "video": True, "kind": "card"})
    return list(out.values())
