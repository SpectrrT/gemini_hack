"""End-to-end run of the LIVE code path against tests/fake_gemini.py (a local server with the measured
request/response shapes and a colour rule for 'vision'). Proves the plumbing, not the models."""
import base64
import io
import json
import time

import pytest
from PIL import Image

from wordless import card as cards, config, follow, gemini, teach, video


def still(colour):
    buf = io.BytesIO()
    Image.new("RGB", (640, 360), colour).save(buf, "JPEG")
    return buf.getvalue()


@pytest.fixture
def taught(fake_api, sandbox):
    clip = fake_api.colour_clip(sandbox / "teach.mp4", ["red", "green", "blue", "yellow"])
    events = []
    card = teach.build(clip, card_id="colours", title="Colour cards", emit=events.append)
    return card, events, fake_api


def test_teach_builds_a_card_from_a_clip(taught):
    card, events, fake = taught
    assert [s["action"] for s in card["steps"]] == [f"Hold up the {c} card." for c in ("red", "green", "blue", "yellow")]
    assert card["self_test"]["recognised"] == 4 and card["self_test"]["of"] == 4
    assert card["links"] == [["s01", "s04"]]
    assert set(card["thresholds"]) == {"s01", "s02", "s03", "s04"}
    d = cards.card_dir("colours")
    for s in card["steps"]:
        assert (d / s["panel"]).stat().st_size > 500 and (d / s["keyframe"]).stat().st_size > 500
    assert Image.open(d / "sheet.jpg").size == (800, 450)          # 4 panels -> 2 x 2 grid
    last = {e["stage"]: e["state"] for e in events}
    assert last == {k: "done" for k in ("prepare", "name", "locate", "plan", "draw", "letters", "selftest", "card")}
    assert fake.calls["bad"] == []                                  # no request was rejected as malformed


def test_follow_a_recording_clean_and_with_a_skipped_step(taught, sandbox):
    card, _, fake = taught
    fake.colour_clip(sandbox / "videos" / "clean.mp4", ["red", "green", "blue", "yellow"])
    fake.colour_clip(sandbox / "videos" / "skip.mp4", ["red", "blue", "yellow"])
    fake.colour_clip(sandbox / "videos" / "swap.mp4", ["yellow", "green", "blue", "red"])
    v = follow.replay(card, "clean", speed=0, block=True).verdict
    assert v["clean"] and v["seen"] == ["s01", "s02", "s03", "s04"] and v["text"] == "all 4 panels seen"
    v = follow.replay(card, "skip", speed=0, block=True).verdict
    assert v["skipped"] == ["s02"] and v["text"] == "panel 2 never happened"
    v = follow.replay(card, "swap", speed=0, block=True).verdict
    assert v["order_violations"] == [["s01", "s04"]] and "panel 4 came before panel 1" in v["text"]
    assert fake.calls["bad"] == []


def test_recorded_answers_replay_without_the_api(taught, sandbox, monkeypatch):
    card, _, fake = taught
    fake.colour_clip(sandbox / "videos" / "skip.mp4", ["red", "blue", "yellow"])
    first = follow.replay(card, "skip", speed=0, block=True).verdict
    monkeypatch.setenv("WORDLESS_TAPE", "replay")
    monkeypatch.setenv("GEMINI_BASE_URL", "http://127.0.0.1:9")    # nothing listens here
    before = fake.calls["decisions"]
    again = follow.replay(card, "skip", speed=0, block=True).verdict
    assert again == first and fake.calls["decisions"] == before


def test_live_stills_through_the_http_server_then_tally_and_baseline(taught, sandbox, monkeypatch):
    card, _, fake = taught
    import server
    monkeypatch.setattr(server, "TALLY", sandbox / "runs" / "tally.json")
    c = server.app.test_client()
    sid = c.post("/api/follow/live", json={"card": "colours"}).get_json()["id"]
    seq = ["black"] * 2 + ["red"] * 4 + ["black"] * 2 + ["blue"] * 4 + ["black"] * 2 + ["yellow"] * 4 + ["black"]   # green skipped
    enc = lambda col: "data:image/jpeg;base64," + base64.b64encode(still(fake.COLOURS.get(col, (0, 0, 0)))).decode()
    for i in range(1, len(seq)):
        assert c.post(f"/api/follow/{sid}/frame", json={"i": i - 1, "stills": [enc(seq[i - 1]), enc(seq[i])]}).status_code == 200
    s = c.post(f"/api/follow/{sid}/finish", json={}).get_json()
    assert s["done"] and s["verdict"]["skipped"] == ["s02"] and s["verdict"]["missing_windows"] == []
    assert s["windows"] == len(seq) - 1
    # every still was saved, so the session can be replayed later (the table fallback)
    assert len(list((config.RUNS / sid).glob("*_0.jpg"))) == len(seq) - 1
    assert sid in [r["id"] for r in follow.recordings_for(card)]
    again = follow.replay(card, sid, speed=0, block=True).verdict
    assert again["skipped"] == ["s02"]
    # sealed card flipped: it said "skip panel 2"
    row = c.post("/api/tally", json={"session": sid, "sealed": "skip", "step": "s02"}).get_json()
    assert row["card_checker"] == "correct"
    for _ in range(50):
        rows = c.get("/api/tally").get_json()
        if rows[0]["hydrogen_one_call"] != "pending":
            break
        time.sleep(0.1)
    assert rows[0]["hydrogen_one_call"] == "correct"
    assert fake.calls["bad"] == []


def test_no_credit_is_reported_not_swallowed(fake_api, sandbox, monkeypatch):
    clip = fake_api.colour_clip(sandbox / "teach.mp4", ["red", "green"])
    monkeypatch.setenv("GEMINI_API_KEY", "broke")
    events = []
    with pytest.raises(gemini.NoCredit):
        teach.build(clip, card_id="broke", emit=events.append)
    assert events[-1]["state"] == "failed" and "402" in events[-1]["detail"]


def test_a_failed_window_is_backfilled_or_listed(taught, sandbox, monkeypatch):
    card, _, fake = taught
    s = follow.Session(card, "live")
    real = gemini.decide
    state = {"n": 0}
    def flaky(*a, **k):
        state["n"] += 1
        if state["n"] == 1:
            raise gemini.ApiError(-1, "network: timed out")
        return real(*a, **k)
    monkeypatch.setattr(gemini, "decide", flaky)
    red = still(fake.COLOURS["red"])
    for i in range(3):
        s.add_stills(i, [red, red])
    v = s.finish()
    assert len(s.answers) == 3 and v["missing_windows"] == [] and "s01" in v["seen"]
