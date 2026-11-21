"""Fast sequences: from one answer per frame to "which sequence was performed".

Pure code, no API. The model answers one question per frame ("which sign is this?", with probabilities);
this module turns the stream of answers into a list of signs, and compares that list with known sequences.

  smooth    Viterbi over the frame answers: a label is kept only if staying on it explains the frames
            better than switching, so a single wrong frame does not create a sign.
  segments  runs of the same label become signs, with start, end and mean probability.
  align     edit distance with a trace: which signs matched, which were wrong, missing or extra.
  rank      every known sequence scored against what was seen.

A frame is a dict {label: probability}; None means the frame got no answer and carries no evidence.
"""
import math

NONE = "none"

STAY = 0.80          # probability of keeping the same label from one frame to the next
FLOOR = 0.02         # probability given to a label the model did not mention
MIN_FRAMES = 2       # a sign must hold for at least this many frames
MIN_CONF = 0.45      # and reach this mean probability
MERGE_GAP_S = 0.45   # two runs of one sign closer than this are one sign (a flicker, not a repeat)


def smooth(frames, labels, stay=STAY, floor=FLOOR):
    """Most likely label per frame. `labels` excludes NONE; it is added as a state."""
    states = list(labels) + [NONE]
    n = len(states)
    if not frames:
        return []
    ln_stay = math.log(stay)
    ln_move = math.log((1 - stay) / max(n - 1, 1))

    def emit(f):
        if f is None:
            return [0.0] * n
        return [math.log(max(float(f.get(s, 0.0)), floor)) for s in states]

    score = emit(frames[0])
    back = []
    for f in frames[1:]:
        e = emit(f)
        best_prev = max(range(n), key=score.__getitem__)
        jump = score[best_prev] + ln_move
        new, ptr = [], []
        for k in range(n):
            keep = score[k] + ln_stay
            if keep >= jump or best_prev == k:
                new.append(keep + e[k])
                ptr.append(k)
            else:
                new.append(jump + e[k])
                ptr.append(best_prev)
        score = new
        back.append(ptr)
    k = max(range(n), key=score.__getitem__)
    path = [k]
    for ptr in reversed(back):
        k = ptr[k]
        path.append(k)
    return [states[k] for k in reversed(path)]


def segments(frames, times, labels, min_frames=MIN_FRAMES, min_conf=MIN_CONF, merge_gap=MERGE_GAP_S, **kw):
    """Signs seen, in order: [{"label", "start", "end", "frames", "conf"}]. Pauses (NONE) are dropped."""
    path = smooth(frames, labels, **kw)
    runs = []
    for i, lab in enumerate(path):
        if runs and runs[-1]["label"] == lab:
            runs[-1]["idx"].append(i)
        else:
            runs.append({"label": lab, "idx": [i]})
    out = []
    for r in runs:
        if r["label"] == NONE:
            continue
        answered = [frames[i] for i in r["idx"] if frames[i] is not None]
        if len(answered) < min_frames:
            continue
        conf = sum(float(f.get(r["label"], 0.0)) for f in answered) / len(answered)
        if conf < min_conf:
            continue
        seg = {"label": r["label"], "start": times[r["idx"][0]], "end": times[r["idx"][-1]],
               "frames": len(answered), "conf": round(conf, 3)}
        if out and out[-1]["label"] == seg["label"] and seg["start"] - out[-1]["end"] <= merge_gap:
            prev = out[-1]
            total = prev["frames"] + seg["frames"]
            prev["conf"] = round((prev["conf"] * prev["frames"] + seg["conf"] * seg["frames"]) / total, 3)
            prev["end"], prev["frames"] = seg["end"], total
        else:
            out.append(seg)
    return out


def align(seen, target):
    """Edit distance between two label lists, with the trace.
    Returns (distance, ops); each op is {"op": match|wrong|missing|extra, "want": label|None, "got": label|None,
    "pos": 1-based position in target (None for extra)}."""
    a, b = list(seen), list(target)
    d = [[0] * (len(b) + 1) for _ in range(len(a) + 1)]
    for i in range(len(a) + 1):
        d[i][0] = i
    for j in range(len(b) + 1):
        d[0][j] = j
    for i in range(1, len(a) + 1):
        for j in range(1, len(b) + 1):
            d[i][j] = min(d[i - 1][j - 1] + (a[i - 1] != b[j - 1]), d[i - 1][j] + 1, d[i][j - 1] + 1)
    ops, i, j = [], len(a), len(b)
    while i or j:
        if i and j and d[i][j] == d[i - 1][j - 1] + (a[i - 1] != b[j - 1]):
            ops.append({"op": "match" if a[i - 1] == b[j - 1] else "wrong", "want": b[j - 1], "got": a[i - 1], "pos": j})
            i, j = i - 1, j - 1
        elif j and d[i][j] == d[i][j - 1] + 1:
            ops.append({"op": "missing", "want": b[j - 1], "got": None, "pos": j})
            j -= 1
        else:
            ops.append({"op": "extra", "want": None, "got": a[i - 1], "pos": None})
            i -= 1
    return d[len(a)][len(b)], ops[::-1]


def progress(seen, target):
    """While the person is still going: how far into `target` are they, and with how many errors so far?
    Returns (signs of target covered, errors). Free end: the rest of target is not counted as missing."""
    a, b = list(seen), list(target)
    row = list(range(len(b) + 1))
    for i in range(1, len(a) + 1):
        new = [i]
        for j in range(1, len(b) + 1):
            new.append(min(row[j - 1] + (a[i - 1] != b[j - 1]), row[j] + 1, new[j - 1] + 1))
        row = new
    j = min(range(len(b) + 1), key=lambda j: (row[j], -j))
    return j, row[j]


def rank(seen, sequences, done=True):
    """Score every known sequence against the signs seen. sequences: [{"id", "name", "signs": [...]}].
    done=False ranks by progress so far (live); done=True by full edit distance (verdict)."""
    out = []
    for s in sequences:
        if done:
            dist, ops = align(seen, s["signs"])
            out.append({"id": s["id"], "name": s["name"], "distance": dist, "length": len(s["signs"]),
                        "exact": dist == 0, "ops": ops,
                        "score": round(1 - dist / max(len(s["signs"]), len(seen), 1), 3)})
        else:
            covered, errors = progress(seen, s["signs"])
            out.append({"id": s["id"], "name": s["name"], "covered": covered, "errors": errors, "length": len(s["signs"]),
                        "score": round((covered - errors) / max(len(s["signs"]), 1), 3)})
    out.sort(key=lambda r: (-r["score"], r["length"]))
    return out


def verdict(seen, sequences, max_errors=1):
    """Which known sequence was performed? Exact match, a near miss (named, with what went wrong), or none."""
    ranked = rank(seen, sequences, done=True)
    best = ranked[0] if ranked else None
    tie = bool(best and len(ranked) > 1 and ranked[1]["distance"] == best["distance"] and not best["exact"])
    if not seen:
        kind = "nothing"
    elif best and best["exact"]:
        kind = "exact"
    elif best and best["distance"] <= max_errors and not tie:
        kind = "near"
    else:
        kind = "unknown"
    return {"kind": kind, "best": best if kind in ("exact", "near") else None, "ranked": ranked[:5], "seen": list(seen)}
