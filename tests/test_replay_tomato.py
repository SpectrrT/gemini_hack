"""The answers recorded against the real API must keep giving the numbers reported in
research/feasibility/FINDINGS.md when they go through today's code (tracker, card, eval)."""
import os
from pathlib import Path

import pytest

from wordless import card as cards, config, evalrun

ROOT = Path(__file__).resolve().parent.parent
pytestmark = pytest.mark.skipif(not (ROOT / "cards" / "tomato" / "card.json").exists(),
                                reason="run scripts/import_tomato_fixture.py first")


@pytest.fixture(autouse=True)
def replay(monkeypatch, tmp_path):
    monkeypatch.setenv("WORDLESS_TAPE", "replay")
    monkeypatch.setattr(config, "RUNS", tmp_path / "runs")      # keep test sessions out of the real runs folder


def rows():
    res = evalrun.run("tomato", ["12_10", "12_43"], str(config.FIXTURES / "tomato" / "labels.json"), text=True, hydrogen=True)
    return {r["recording"]: r for r in res["rows"]}


def test_card_has_the_nine_panels_that_were_tested():
    c = cards.load("tomato")
    assert cards.step_ids(c) == ["s02", "s03", "s05", "s07", "s08", "s09", "s10", "s11", "s12"]
    assert (cards.card_dir("tomato") / "sheet.jpg").exists()


def test_clean_recording_all_steps_found_no_false_alarm():
    r = rows()["12_10"]["card"]
    assert (r["found"], r["performed"], r["false_alarms"], r["unsure"]) == (9, 9, [], [])
    assert r["window_acc"] == [60, 81]


def test_error_recording_all_four_skips_flagged_no_false_alarm():
    r = rows()["12_43"]
    assert r["truth_skipped"] == ["s09", "s10", "s11", "s12"]
    assert (r["card"]["skips_caught"], r["card"]["skips_total"], r["card"]["false_alarms"]) == (4, 4, [])
    assert r["card"]["window_acc"] == [18, 22]


def test_text_only_checker_matches_the_recorded_scoring_under_the_frozen_rule():
    """FINDINGS.md: text-only flagged 4/4 plus 2 false alarms; the card flagged 4/4 with none."""
    r = rows()["12_43"]
    assert r["text_only"]["frozen_rule"]["skips_caught"] == 4 and len(r["text_only"]["frozen_rule"]["false_alarms"]) == 2
    assert r["card"]["frozen_rule"] == {"skips_caught": 4, "false_alarms": []}


def test_unrecorded_baseline_is_reported_as_such_not_invented():
    assert rows()["12_43"]["hydrogen_one_call"] is None
