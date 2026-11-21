"""The whole-clip review rule (follow.apply_review): the one call decides "never happened"; the card can only
turn that into "not sure"."""
from wordless import follow

CARD = {"id": "c", "steps": [{"id": f"s0{k}", "action": f"step {k}"} for k in (1, 2, 3, 4)]}


def card_verdict(seen, unsure, skipped):
    return {"seen": list(seen), "unsure": list(unsure), "skipped": list(skipped), "order_violations": [], "clean": False}


def test_performed_step_the_card_missed_is_cleared():
    v = follow.apply_review(CARD, card_verdict(["s01", "s02"], ["s03"], ["s04"]), {"skipped": [], "lat": 9.0})
    assert v["seen"] == ["s01", "s02", "s03", "s04"] and not v["unsure"] and not v["skipped"] and v["clean"]
    assert v["review"]["cleared"] == ["s04", "s03"] and v["card_verdict"]["skipped"] == ["s04"]
    assert "whole-clip review cleared panel 4, panel 3" in follow.verdict_text(CARD, v)


def test_both_agree_it_never_happened():
    v = follow.apply_review(CARD, card_verdict(["s01", "s02", "s03"], [], ["s04"]), {"skipped": ["s04"]})
    assert v["skipped"] == ["s04"] and follow.verdict_text(CARD, v) == "panel 4 never happened"


def test_disagreement_is_not_sure_never_a_false_alarm():
    v = follow.apply_review(CARD, card_verdict(["s01", "s02", "s03", "s04"], [], []), {"skipped": ["s02"]})
    assert v["unsure"] == ["s02"] and not v["skipped"] and v["review"]["doubted"] == ["s02"]


def test_review_that_could_not_run_leaves_the_card_verdict():
    v = follow.apply_review(CARD, card_verdict(["s01"], [], ["s02", "s03", "s04"]), {"error": "no answer in 45 s"})
    assert v["skipped"] == ["s02", "s03", "s04"] and v["review"]["ok"] is False
    assert follow.verdict_text(CARD, v).endswith("(whole-clip review did not run)")
    v = follow.apply_review(CARD, card_verdict(["s01"], [], ["s02"]), None)
    assert v["review"] is None and v["skipped"] == ["s02"]
