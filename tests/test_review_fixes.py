"""Regression tests for defects found by the code review of the first version."""
import io
import threading
import time

import pytest
from PIL import Image

import server
from wordless import baseline, card as cards, follow, gemini, teach


def still(colour):
    buf = io.BytesIO()
    Image.new("RGB", (640, 360), colour).save(buf, "JPEG")
    return buf.getvalue()


@pytest.fixture
def card(fake_api, sandbox):
    clip = fake_api.colour_clip(sandbox / "teach.mp4", ["red", "green", "blue", "yellow"])
    return teach.build(clip, card_id="colours", title="Colour cards")


def test_one_overloaded_window_does_not_kill_the_build(fake_api, sandbox, monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda s: None)          # skip the real back-off
    clip = fake_api.colour_clip(sandbox / "teach.mp4", ["red", "green"])
    fake_api.faults["decisions_503"] = 2                        # two 503s, then the retry succeeds
    c = teach.build(clip, card_id="flaky")
    assert len(c["steps"]) == 2


def test_image_refusal_is_retried(fake_api, sandbox, monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda s: None)
    clip = fake_api.colour_clip(sandbox / "teach.mp4", ["red", "green"])
    fake_api.faults["image_no_image"] = 1
    c = teach.build(clip, card_id="refused")
    assert len(c["steps"]) == 2 and c["panels_not_drawn"] == []


def test_image_model_that_never_draws_falls_back_to_the_photo(fake_api, sandbox, monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda s: None)
    clip = fake_api.colour_clip(sandbox / "teach.mp4", ["red", "green"])
    fake_api.faults["image_no_image"] = 99
    events = []
    c = teach.build(clip, card_id="nodraw", emit=events.append)
    assert len(c["steps"]) == 2 and sorted(c["panels_not_drawn"]) == ["s01", "s02"]
    assert any("keyframe photo" in e["detail"] for e in events)


def test_windows_still_unanswered_at_finish_never_become_never_happened(card, fake_api, monkeypatch):
    """The last step's calls hang: the verdict must say 'not sure' and list the windows, not accuse."""
    real = gemini.decide
    hang = threading.Event()
    def decide(blocks, questions, **k):
        if hang.is_set():
            raise gemini.ApiError(-1, "network: timed out")
        return real(blocks, questions, **k)
    monkeypatch.setattr(gemini, "decide", decide)
    s = follow.Session(card, "live", review=False)      # this test is about the window logic alone
    seq = ["red"] * 3 + ["green"] * 3 + ["blue"] * 3
    for i, col in enumerate(seq):
        s.add_stills(i, [still(fake_api.COLOURS[col])] * 2)
    import concurrent.futures as cf
    cf.wait(list(s.pending.values()))
    hang.set()
    for i in range(9, 12):                                      # yellow: never answered
        s.add_stills(i, [still(fake_api.COLOURS["yellow"])] * 2)
    v = s.finish(wait_s=1, backfill_s=1)
    assert v["missing_windows"] == [9, 10, 11]
    assert v["skipped"] == [] and v["unsure"] == ["s04"] and not v["clean"]
    assert "3 windows got no answer" in v["text"]


def test_a_single_lost_window_cannot_hide_a_whole_step(card, fake_api, monkeypatch):
    """One unanswered window is not enough evidence to excuse a step that was truly skipped."""
    real = gemini.decide
    def decide(blocks, questions, **k):
        if threading.current_thread().name == "lose-me":
            raise gemini.ApiError(400, "bad request")           # not retryable
        return real(blocks, questions, **k)
    monkeypatch.setattr(gemini, "decide", decide)
    s = follow.Session(card, "live")
    seq = ["red"] * 3 + ["green"] * 3 + ["black"] + ["yellow"] * 3     # blue skipped; window 6 will be lost
    for i, col in enumerate(seq):
        if i == 6:
            s.stills[i] = [still((0, 0, 0))] * 2                # posted, but its call fails now and at back-fill
            s.errors[i] = "lost"
        else:
            s.add_stills(i, [still(fake_api.COLOURS[col])] * 2)
    threading.current_thread().name = "lose-me"                 # the back-fill runs on this thread
    try:
        v = s.finish(wait_s=5, backfill_s=2)
    finally:
        threading.current_thread().name = "MainThread"
    assert v["missing_windows"] == [6] and v["skipped"] == ["s03"] and v["unsure"] == []


def test_finish_is_idempotent_and_replay_ignores_done_button(card, fake_api, sandbox):
    fake_api.colour_clip(sandbox / "videos" / "clean.mp4", ["red", "green", "blue", "yellow"])
    s = follow.replay(card, "clean", speed=0, block=True)
    first = dict(s.verdict)
    assert s.finish() == first
    c = server.app.test_client()
    assert c.post(f"/api/follow/{s.id}/finish", json={}).get_json()["verdict"]["text"] == first["text"]


def test_judge_counts_order_accusations_and_tally_keeps_one_row_per_session(card, fake_api, sandbox, monkeypatch):
    assert server.judge(None, [], [], [["s01", "s04"]]) == "false alarm"
    assert server.judge("s02", ["s02"], [], [["s01", "s04"]]) == "wrong"
    assert server.judge("s02", ["s02"], []) == "correct"
    assert server.judge("s02", [], ["s02"]) == "abstained"
    assert server.judge("s02", [], []) == "missed"
    monkeypatch.setattr(server, "TALLY", sandbox / "runs" / "tally.json")
    s = follow.Session(card, "live")
    for i in range(3):
        s.add_stills(i, [still(fake_api.COLOURS["red"])] * 2)
    s.finish()
    c = server.app.test_client()
    c.post("/api/tally", json={"session": s.id, "sealed": "right"})
    c.post("/api/tally", json={"session": s.id, "sealed": "skip", "step": "s02"})
    rows = c.get("/api/tally").get_json()
    assert len(rows) == 1 and rows[0]["sealed"] == "skip" and rows[0]["truth_panel"] == 2


def test_baseline_answer_must_cover_every_step(card, fake_api, monkeypatch):
    def gen(answer):
        monkeypatch.setattr(gemini, "generate", lambda *a, **k: {"candidates": [{"content": {"parts": [{"text": answer}]}}], "_latency": 0.1})
    def fake_video(run_dir, dst):
        dst.write_bytes(b"x")
        return dst
    monkeypatch.setattr(baseline, "stills_to_video", fake_video)
    s = follow.Session(card, "live")
    s.dir.mkdir(parents=True)
    gen('{"performed": ["S01: red", "s02"], "not_performed": ["s03", "s04:"]}')
    assert baseline.hydrogen_one_call(card, s.id)["skipped"] == ["s03", "s04"]
    import shutil
    shutil.rmtree(gemini.tape.root / "baseline")                # forget the taped answer
    gen('{"performed": ["rinse"], "not_performed": []}')        # ids it does not recognise: refuse to score
    with pytest.raises(ValueError):
        baseline.hydrogen_one_call(card, s.id)


def test_rebuild_from_tape_is_refused_outside_replay_mode(card, fake_api):
    r = server.app.test_client().post("/api/teach", json={"from_tape": "colours"})
    assert r.status_code == 400
