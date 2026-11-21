from wordless.tracker import Tracker, own_thresholds


def feed(tr, seq):
    for i, (s, c) in enumerate(seq):
        tr.add(i, s, c)


def test_seen_needs_a_run_not_a_blip():
    tr = Tracker(["a", "b"])
    feed(tr, [("a", 0.9), ("a", 0.9), (None, 0.8), ("b", 0.5), (None, 0.8)])
    v = tr.verdict()
    assert v["seen"] == ["a"] and v["skipped"] == ["b"] and not v["clean"]


def test_unsure_band():
    tr = Tracker(["a"])
    feed(tr, [("a", 0.6), ("a", 0.5)])           # mass 1.1: between 0.9 and 1.6
    assert tr.verdict()["unsure"] == ["a"] and tr.verdict()["skipped"] == []


def test_low_confidence_windows_do_not_count():
    tr = Tracker(["a"])
    feed(tr, [("a", 0.4)] * 10)
    assert tr.verdict()["skipped"] == ["a"]


def test_run_tolerates_a_gap_of_two_but_not_more():
    tr = Tracker(["a"])
    feed(tr, [("a", 0.8), (None, 0.9), (None, 0.9), ("a", 0.8)])
    assert tr.score("a")[0] == 1.6
    tr = Tracker(["a"])
    feed(tr, [("a", 0.8), (None, 0.9), (None, 0.9), (None, 0.9), ("a", 0.8)])
    assert tr.score("a")[0] == 0.8


def test_order_violation_only_on_links():
    seq = [("b", 0.9), ("b", 0.9), ("a", 0.9), ("a", 0.9)]
    free = Tracker(["a", "b"])
    feed(free, seq)
    assert free.verdict()["order_violations"] == [] and free.verdict()["clean"]
    linked = Tracker(["a", "b"], links=[("a", "b")])
    feed(linked, seq)
    assert linked.verdict()["order_violations"] == [["a", "b"]]


def test_backfill_out_of_order_gives_same_verdict():
    seq = [("a", 0.9), ("a", 0.8), (None, 0.7), ("b", 0.9), ("b", 0.9)]
    t1, t2 = Tracker(["a", "b"]), Tracker(["a", "b"])
    feed(t1, seq)
    for i in (4, 0, 3, 1, 2):
        t2.add(i, *seq[i])
    assert t1.verdict() == t2.verdict()


def test_optional_steps_are_never_reported_missing():
    tr = Tracker(["a", "b"], optional=["b"])
    feed(tr, [("a", 0.9), ("a", 0.9)])
    assert tr.verdict()["skipped"] == [] and tr.verdict()["clean"]


def test_own_thresholds_are_clamped():
    assert own_thresholds({"a": 10.0, "b": 2.4, "c": 1.0, "d": 0}) == {"a": 1.6, "b": 1.2, "c": 0.9}
