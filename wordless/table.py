"""Table prep: record the test clips before any API credit exists, then run the table gate (G2) in one go.

Clips are saved as <name>.mp4 in the table video folder (a folder the replay path already searches), with
their answer key in table.json next to them:

  teach        the teaching run
  follow       a second run; truth is "right" (nothing skipped) or "skip" with the skipped step number

Step numbers are the kit's own (step 2 = the second thing the person does). The gate checks that the card
built from the teaching clip has the same number of panels before it trusts that mapping.
"""
import json
import os
import re
import shutil
import threading
import time
from pathlib import Path

from . import card as cards
from . import config, follow, gemini, teach, video

lock = threading.Lock()
gate_lock = threading.Lock()          # held for the whole of run_gate
BUSY = "the table test is running; wait for it to finish"
PREFIX = "t_"                      # table clips: t_teach, t_right_1, t_skip2_1 ...
GATE_CARD = "table"


def folder():
    d = config.VIDEO_DIRS[-1]
    d.mkdir(parents=True, exist_ok=True)
    return d


def _manifest_path():
    return folder() / "table.json"


def load():
    p = _manifest_path()
    m = json.loads(p.read_text()) if p.exists() else {}
    m.setdefault("kit_steps", 4)
    m.setdefault("clips", {})
    m["clips"] = {k: v for k, v in m["clips"].items() if (folder() / f"{k}.mp4").exists()}
    return m


def _save(m):
    p = _manifest_path()
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(m, indent=1))
    os.replace(tmp, p)


def set_kit_steps(n):
    n = int(n)
    if not 2 <= n <= 9:
        raise ValueError("a kit has 2 to 9 steps")
    with lock:
        m = load()
        stale = sorted(k for k, c in m["clips"].items() if c["truth"] == "skip" and c["skip"] > n)
        if stale:
            raise ValueError(f"delete the clips that skip a step above {n} first: {', '.join(stale)}")
        m["kit_steps"] = n
        _save(m)
    return m


def _name(m, role, truth, skip):
    if role == "teach":
        return PREFIX + "teach"
    stem = PREFIX + ("right" if truth == "right" else f"skip{skip}")
    k = 1
    while f"{stem}_{k}" in m["clips"]:
        k += 1
    return f"{stem}_{k}"


def _forget(name, role):
    """Drop taped answers that were given for a clip that has now changed."""
    root = gemini.tape.root
    if role == "teach":                # a new card: every follow answer was given against the old sheet
        shutil.rmtree(root / "teach" / GATE_CARD, ignore_errors=True)
        shutil.rmtree(root / "follow" / GATE_CARD, ignore_errors=True)
        shutil.rmtree(root / "baseline" / "hydrogen" / GATE_CARD, ignore_errors=True)
    else:
        shutil.rmtree(root / "follow" / GATE_CARD / name, ignore_errors=True)
        (root / "baseline" / "hydrogen" / GATE_CARD / f"{name}.json").unlink(missing_ok=True)   # the whole-clip answer too


def pace(marks, seconds):
    """Step durations from the 'next step' marks tapped while recording: marks[k] is the second step k+1
    started. Returns [{"step", "seconds", "short"}]; short = under the 6 s a step needs for 3 windows."""
    if not marks:
        return []
    ends = list(marks[1:]) + [seconds]
    return [{"step": k + 1, "seconds": round(e - s, 1), "short": (e - s) < 6.0} for k, (s, e) in enumerate(zip(marks, ends))]


def save_clip(src, role, truth=None, skip=None, marks=None):
    """Normalise an uploaded clip into the table folder and record its answer key. Returns its entry."""
    if role not in ("teach", "follow"):
        raise ValueError("role must be teach or follow")
    if role == "follow":
        if truth not in ("right", "skip"):
            raise ValueError("a follow clip needs truth: right or skip")
        skip = int(skip) if truth == "skip" else None
    else:
        truth = skip = None
    marks = sorted(round(float(x), 2) for x in (marks or []))
    if gate_lock.locked():
        raise ValueError(BUSY)
    with lock:
        m = load()
        if truth == "skip" and not 1 <= skip <= m["kit_steps"]:
            raise ValueError(f"skipped step must be 1 to {m['kit_steps']}")
        name = _name(m, role, truth, skip)
        tmp = folder() / f".{name}.part.mp4"
        try:
            video.normalize(src, tmp)
            seconds = round(video.duration(tmp), 1)
            if seconds < 4:
                raise ValueError(f"the clip is only {seconds} s long")
            os.replace(tmp, folder() / f"{name}.mp4")
            _forget(name, role)
        finally:
            tmp.unlink(missing_ok=True)
        marks = [x for x in marks if x < seconds]
        m["clips"][name] = {"name": name, "role": role, "truth": truth, "skip": skip, "seconds": seconds,
                            "marks": marks, "pace": pace(marks, seconds), "time": time.strftime("%H:%M:%S")}
        _save(m)
        return m["clips"][name]


def delete_clip(name):
    if not re.fullmatch(PREFIX + r"[a-z0-9_]+", name):
        raise ValueError("not a table clip")
    if gate_lock.locked():
        raise ValueError(BUSY)
    with lock:
        m = load()
        gone = m["clips"].pop(name, None)
        _forget(name, gone["role"] if gone else ("teach" if name == PREFIX + "teach" else "follow"))
        (folder() / f"{name}.mp4").unlink(missing_ok=True)
        _save(m)
    return m


def readiness(m=None):
    """What the gate still needs. Empty list = ready (apart from a funded key)."""
    m = m or load()
    clips = list(m["clips"].values())
    need = []
    if not any(c["role"] == "teach" for c in clips):
        need.append("a teaching run")
    if not any(c["truth"] == "right" for c in clips):
        need.append("a follow run done right")
    skipped = {c["skip"] for c in clips if c["truth"] == "skip"}
    if len(skipped) < 2:
        need.append(f"follow runs that skip two different steps (have {len(skipped)})")
    return need


def judge(truth_skipped, flagged, unsure, violations=()):
    """Outcome of one trial with a known answer. truth_skipped: step id or None ('do it right').
    A reported order violation is an accusation too: the sealed deck has no order cards."""
    if truth_skipped is None:
        return "false alarm" if flagged or violations else "abstained" if unsure else "correct"
    if violations:
        return "wrong"
    if flagged == [truth_skipped]:
        return "correct"
    if not flagged and truth_skipped in unsure:
        return "abstained"
    return "wrong" if flagged else "missed"


def run_gate(emit=None, out_path=None):
    if not gate_lock.acquire(blocking=False):
        raise ValueError("the table test is already running")
    try:
        return _run_gate(emit, out_path)
    finally:
        gate_lock.release()


def _run_gate(emit=None, out_path=None):
    """Gate G2 on the recorded table clips: build the card from the teaching run, replay every follow clip
    through the checker, score against the answer key. Needs the live API (or everything on tape)."""
    emit = emit or (lambda e: None)
    m = load()
    need = readiness(m)
    if need:
        raise ValueError("not ready: still need " + "; ".join(need))
    t0 = time.time()
    card = teach.build(folder() / f"{PREFIX}teach.mp4", card_id=GATE_CARD, title="Table routine", emit=emit)
    build_s = round(time.time() - t0, 1)
    ids = cards.step_ids(card)
    res = {"card": card["id"], "time": time.strftime("%H:%M:%S"), "tape_mode": gemini.mode(), "kit_steps": m["kit_steps"],
           "panels": len(ids), "clip_to_card_s": build_s, "self_test": card.get("self_test"), "rows": [], "problems": []}
    mapped = len(ids) == m["kit_steps"]
    if not mapped:
        res["problems"].append(f"the card has {len(ids)} panels but the kit has {m['kit_steps']} steps: "
                               "skipped-step answers cannot be scored, only false alarms on clean runs")
    if build_s > 40:
        res["problems"].append(f"clip to card took {build_s} s (bar: 40 s)")
    for c in sorted((c for c in m["clips"].values() if c["role"] == "follow"), key=lambda c: c["name"]):
        emit({"stage": "follow", "state": "running", "detail": c["name"]})
        s = follow.replay(card, c["name"], speed=0, block=True)
        if s.fatal and "402" in s.fatal:              # out of credit part-way: keep the last result, say so
            raise gemini.NoCredit(402, s.fatal)
        row = {"clip": c["name"], "truth": c["truth"], "skip": c["skip"], "seconds": c["seconds"], "fatal": s.fatal,
               "windows": len(s.answers), "failed_windows": len(s.errors)}
        stale = c["truth"] == "skip" and mapped and c["skip"] > len(ids)
        if stale:
            res["problems"].append(f"{c['name']} skips step {c['skip']} but the kit has {len(ids)} steps: not scored, delete it")
        if s.fatal:                                   # cut short: not a verdict, do not score it
            row["outcome"] = "error"
            res["problems"].append(f"{c['name']}: {s.fatal}")
        elif s.verdict:
            v = s.verdict
            truth = None if c["truth"] == "right" else (ids[c["skip"] - 1] if mapped and not stale else "?")
            row.update(verdict=v["text"], flagged=[cards.panel_number(card, x) for x in v["skipped"]],
                       unsure=[cards.panel_number(card, x) for x in v["unsure"]], scores=v.get("scores"),
                       outcome="unscored" if truth == "?" else judge(truth, v["skipped"], v["unsure"], v["order_violations"]))
            real = set() if truth in (None, "?") else {truth}
            row["false_never_happened"] = sorted(cards.panel_number(card, x) for x in set(v["skipped"]) - real) if truth != "?" else None
        else:
            row["outcome"] = "error"
        res["rows"].append(row)
        emit({"stage": "follow", "state": "done", "detail": f"{c['name']}: {row['fatal'] or row.get('verdict')} -> {row['outcome']}"})
    rows = res["rows"]
    res["correct"] = sum(r["outcome"] == "correct" for r in rows)
    res["of"] = len(rows)
    res["false_never_happened"] = sum(len(r.get("false_never_happened") or []) for r in rows)
    res["passed"] = bool(rows) and mapped and res["correct"] == len(rows) and not res["false_never_happened"] and build_s <= 40
    out = Path(out_path) if out_path else config.RUNS / "gate_g2.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, indent=1))
    emit({"stage": "gate", "state": "done", "detail": f"{res['correct']}/{res['of']} verdicts right, "
          f"{res['false_never_happened']} false 'never happened', clip to card {build_s} s -> {'PASS' if res['passed'] else 'FAIL'}"})
    return res


def sealed_deck(steps, copies=1):
    """The sealed cards for one table: half 'do it right', half 'skip step k' (each step equally often)."""
    steps, copies = int(steps), int(copies)
    deck = []
    for _ in range(copies):
        deck += [{"sealed": "skip", "step": k} for k in range(1, steps + 1)]
        deck += [{"sealed": "right", "step": None} for _ in range(steps)]
    for n, c in enumerate(deck, 1):
        c["no"] = n
    return deck
