"""The live "you skipped this" alert must never cry wolf. No API here: answers are injected frame by frame,
in order and out of order, and the state is read after every single answer, as the page would poll it."""
import random

import pytest

from wordless import decode

FPS = 8.0
POSES = ["a", "b", "c", "d"]


def answer(label, p=0.9):
    rest = (1 - p) / 4
    probs = {x: rest for x in POSES + [decode.NONE]}
    probs[label] = p
    return {"probs": probs, "top": label, "conf": p, "lat": 0.5}


def make(sandbox, sequence):
    from wordless import card as cards, fast, signs
    kit = {"id": "t", "title": "t", "kind": "signs", "next": 9, "signs": [{"id": x, "name": x.upper(), "ref": f"{x}.jpg"} for x in POSES],
           "sequences": [{"id": "routine", "name": "t", "signs": list(sequence)}]}
    signs.save(kit)
    card = {"id": "t", "title": "t", "fast": True, "links": [],
            "steps": [{"id": f"q{n + 1:02d}", "pose": x, "action": x.upper(), "done_when": "", "panel": f"{x}.jpg", "keyframe": f"{x}.jpg"}
                      for n, x in enumerate(sequence)]}
    cards.save(card)
    s = fast.Session(card)
    s.tick = 0.0
    s._clock = lambda: s.tick                    # test clock: advances 1/8 s with every answer that lands
    return s


def script(*parts):
    """[(label, frames, probability)] -> list of per-frame answers."""
    out = []
    for label, n, *p in parts:
        out += [answer(label, p[0] if p else 0.9)] * n
    return out


def feed(s, frames, order=None, watch=None):
    """Frames exist from the start (the camera took them); answers land in `order`. `watch(state)` after each."""
    for i in range(len(frames)):
        s.times[i] = i / FPS
    for i in (order if order is not None else range(len(frames))):
        s.answers[i] = frames[i]
        s.tick += 1 / FPS
        if watch:
            watch(s.state())
    for _ in range(8):                           # the page keeps polling for a second after the last answer
        s.tick += 1 / FPS
        st = s.state()
        if watch:
            watch(st)
    return st


def states(st):
    return [st["panels"][q]["state"] for q in sorted(st["panels"])]


PAUSE = (decode.NONE, 3)


def test_skip_is_called_only_after_the_next_step_is_proven_and_has_held(sandbox):
    s = make(sandbox, "abcd")
    seen_alerts = []
    frames = script(PAUSE, ("a", 8), PAUSE, ("c", 12), PAUSE)
    watch = lambda st: seen_alerts.append((st["windows"], st["alert"] and st["alert"]["step"]))
    st = feed(s, frames, watch=watch)
    assert states(st) == ["seen", "missed", "seen", "pending"]
    assert st["alert"] == {"step": "q02", "kind": "missed"} and st["next"] == "q04"
    first = next(n for n, a in seen_alerts if a)
    c_starts = 3 + 8 + 3
    assert first >= c_starts + 3 + int(0.6 * FPS) - 1, "alert came before the next step was proven and had held"
    assert first <= c_starts + 12, "alert should come while the next step is still being done"
    assert all(a in (None, "q02") for _, a in seen_alerts)


def test_two_frames_of_the_next_step_are_not_proof(sandbox):
    s = make(sandbox, "abcd")
    st = feed(s, script(("a", 8), PAUSE, ("c", 2)))
    assert st["alert"] is None and "missed" not in states(st)


def test_a_weakly_seen_next_step_is_not_proof(sandbox):
    s = make(sandbox, "abcd")
    st = feed(s, script(("a", 8), PAUSE, ("c", 12, 0.42)))
    assert st["alert"] is None and "missed" not in states(st)


def test_no_alert_while_earlier_frames_are_still_waiting_for_answers(sandbox):
    s = make(sandbox, "abcd")
    frames = script(("a", 8), ("b", 6), ("c", 12))
    late = list(range(8, 14))                                   # b's frames: their answers arrive last
    order = [i for i in range(len(frames)) if i not in late]
    alerts = []
    for i in range(len(frames)):
        s.times[i] = i / FPS
    for i in order:
        s.answers[i] = frames[i]
        s.tick += 1.0                            # even after a long wait
        alerts.append(s.state()["alert"])
    assert not any(alerts), "b's frames were still in flight: nothing may be called missed"
    for i in late:
        s.answers[i] = frames[i]
        s.tick += 1.0
        alerts.append(s.state()["alert"])
    st = s.state()
    assert not any(alerts) and states(st)[:3] == ["seen", "seen", "seen"]


def test_going_back_to_do_the_skipped_step_clears_the_alert(sandbox):
    s = make(sandbox, "abcd")
    st = feed(s, script(("a", 8), PAUSE, ("c", 12), PAUSE))
    assert st["alert"]["step"] == "q02"
    s2 = make(sandbox, "abcd")
    st = feed(s2, script(("a", 8), PAUSE, ("c", 12), PAUSE, ("b", 8), PAUSE))
    # both were done, in the other order: no alert stays up, nothing is called missed
    assert st["alert"] is None and "missed" not in states(st) and "wrong" not in states(st)
    v = s2.finish(wait_s=0, backfill_s=-1)
    assert v["out_of_order"] and "q02" not in v["skipped"] and "q03" not in v["skipped"] and v["skipped"] == ["q04"]


def test_same_picture_before_and_after_a_gap_is_not_proof(sandbox):
    # card: a, b, a, c. Seeing "a" twice may be ONE a with a flicker in the middle, so it proves nothing about b.
    s = make(sandbox, "abac")
    st = feed(s, script(("a", 8), (decode.NONE, 6), ("a", 8)))
    assert st["alert"] is None and "missed" not in states(st)
    # ...but a different later step does prove it
    st = feed(make(sandbox, "abac"), script(("a", 8), (decode.NONE, 6), ("a", 8), PAUSE, ("c", 12)))
    assert st["alert"] and st["alert"]["step"] == "q02"


def test_wrong_step_in_place_is_gated_the_same_way(sandbox):
    s = make(sandbox, "abcd")
    st = feed(s, script(("a", 8), PAUSE, ("d", 2)))
    assert st["alert"] is None and set(states(st)) <= {"seen", "pending"}


@pytest.mark.parametrize("seed", range(40))
def test_clean_run_never_alerts_whatever_order_the_answers_arrive_in(sandbox, seed):
    rng = random.Random(seed)
    s = make(sandbox, "abcd")
    hold = lambda: rng.randint(4, 12)
    frames = script(PAUSE, ("a", hold(), rng.uniform(0.6, 0.95)), (decode.NONE, rng.randint(0, 4)), ("b", hold(), rng.uniform(0.6, 0.95)),
                    (decode.NONE, rng.randint(0, 4)), ("c", hold(), rng.uniform(0.6, 0.95)), (decode.NONE, rng.randint(0, 4)),
                    ("d", hold(), rng.uniform(0.6, 0.95)), PAUSE)
    # answers arrive late and out of order, like real network calls: each frame's answer lands up to 16 frames late
    order = sorted(range(len(frames)), key=lambda i: i + rng.uniform(0, 16))
    bad = []
    st = feed(s, frames, order=order, watch=lambda st: bad.append(st["alert"]) if st["alert"] else None)
    assert not bad, f"false alert in a clean run: {bad[:2]}"
    assert states(st) == ["seen"] * 4 and st["alert"] is None
    assert s.finish(wait_s=0, backfill_s=-1)["clean"]


@pytest.mark.parametrize("seed", range(40))
def test_real_skip_is_always_called_and_only_that_step(sandbox, seed):
    rng = random.Random(1000 + seed)
    skip = rng.choice("bc")
    s = make(sandbox, "abcd")
    parts = [PAUSE]
    for x in "abcd":
        if x != skip:
            parts += [(x, rng.randint(6, 12), rng.uniform(0.65, 0.95)), (decode.NONE, rng.randint(0, 4))]
    frames = script(*parts, PAUSE)
    order = sorted(range(len(frames)), key=lambda i: i + rng.uniform(0, 16))
    alerts = set()
    st = feed(s, frames, order=order, watch=lambda st: alerts.add(st["alert"]["step"]) if st["alert"] else None)
    want = {"b": "q02", "c": "q03"}[skip]
    assert alerts == {want}, f"expected only {want}, got {alerts}"
    assert st["alert"] == {"step": want, "kind": "missed"}


@pytest.mark.parametrize("seed", range(60))
def test_noisy_clean_run_never_alerts(sandbox, seed):
    """Every step is done; about one frame in eight is misread as some other step, answers arrive out of order."""
    rng = random.Random(5000 + seed)
    s = make(sandbox, "abcd")
    parts = [PAUSE]
    for x in "abcd":
        parts += [(x, rng.randint(5, 12), rng.uniform(0.6, 0.95)), (decode.NONE, rng.randint(0, 4))]
    frames = script(*parts, PAUSE)
    for i in range(len(frames)):
        if rng.random() < 0.125:
            frames[i] = answer(rng.choice(POSES + [decode.NONE]), rng.uniform(0.45, 0.75))
    order = sorted(range(len(frames)), key=lambda i: i + rng.uniform(0, 16))
    bad = []
    feed(s, frames, order=order, watch=lambda st: bad.append(st["alert"]) if st["alert"] else None)
    assert not bad, f"false alert in a clean (noisy) run: {bad[:2]}"


def test_frames_that_never_get_an_answer_block_the_alert(sandbox):
    """b's frames failed (network): b may well have been done, so nothing is announced live."""
    s = make(sandbox, "abcd")
    frames = script(("a", 8), ("b", 6), ("c", 12), PAUSE)
    lost = set(range(8, 14))
    bad = []
    feed(s, frames, order=[i for i in range(len(frames)) if i not in lost], watch=lambda st: bad.append(st["alert"]) if st["alert"] else None)
    assert not bad


def test_alert_is_gone_once_the_run_is_finished(sandbox):
    s = make(sandbox, "abcd")
    st = feed(s, script(("a", 8), PAUSE, ("c", 12), PAUSE))
    assert st["alert"]
    v = s.finish(wait_s=0, backfill_s=-1)
    assert s.state()["alert"] is None and v["skipped"] == ["q02", "q04"]
