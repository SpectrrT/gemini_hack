"""The demo shell in server.py: hard deadline, status numbers, baseline beside ours, QR export, recorded runs.
Against tests/fake_gemini.py, like the other live-path tests: this proves the plumbing, not the models."""
import json
import threading
import time

import pytest

import server
from wordless import config, follow, gemini, teach

COLOURS = ["red", "green", "blue", "yellow"]


@pytest.fixture
def card(fake_api, sandbox):
    clip = fake_api.colour_clip(sandbox / "teach.mp4", COLOURS)
    return teach.build(clip, card_id="colours", title="Colour cards")


@pytest.fixture
def client():
    return server.app.test_client()


def wait_for(fn, seconds=20):
    t = time.time()
    while time.time() - t < seconds:
        v = fn()
        if v:
            return v
        time.sleep(0.05)
    raise AssertionError("timed out")


def state(client, sid):
    return client.get(f"/api/follow/{sid}").get_json()


def test_file_run_reports_status_and_the_baseline_beside_the_verdict(card, client, fake_api, sandbox):
    fake_api.colour_clip(sandbox / "videos" / "skip.mp4", ["red", "blue", "yellow"])
    s = client.post("/api/follow/replay", json={"card": "colours", "recording": "skip", "speed": 0, "deadline_s": 60}).get_json()
    assert s["shell"]["mode"] == "LIVE" and s["shell"]["input"] == "recording skip"
    done = wait_for(lambda: (lambda x: x if x["done"] and x["shell"]["baseline"]["state"] != "running" else None)(state(client, s["id"])))
    sh = done["shell"]
    assert done["verdict"]["text"] == "panel 2 never happened" and not sh["deadline_hit"]
    assert sh["questions"] == done["windows"] > 0 and sh["last_call_s"] is not None
    assert sh["baseline"]["state"] == "done" and sh["baseline"]["skipped"] == ["s02"]
    assert sh["baseline"]["text"] == "panel 2 never happened"


def test_tape_only_run_is_labelled_replay_and_says_the_baseline_was_not_recorded(card, client, fake_api, sandbox, monkeypatch):
    fake_api.colour_clip(sandbox / "videos" / "clean.mp4", COLOURS)
    follow.replay(card, "clean", speed=0, block=True, review=False)      # card answers on tape, no whole-clip answer
    monkeypatch.setenv("WORDLESS_TAPE", "replay")
    s = client.post("/api/follow/replay", json={"card": "colours", "recording": "clean", "speed": 0}).get_json()
    done = wait_for(lambda: (lambda x: x if x["done"] and x["shell"]["baseline"]["state"] != "running" else None)(state(client, s["id"])))
    assert done["shell"]["mode"] == "REPLAY" and done["verdict"]["clean"]
    assert done["shell"]["baseline"]["state"] == "none" and "not recorded" in done["shell"]["baseline"]["text"]


def test_deadline_finishes_a_run_whose_calls_hang(card, client, monkeypatch):
    """Every Decisions call stalls for longer than the deadline: the session still ends on time and accuses nobody."""
    release = threading.Event()
    def decide(blocks, questions, **k):
        release.wait(30)
        raise gemini.ApiError(-1, "network: timed out")
    monkeypatch.setattr(gemini, "decide", decide)
    s = client.post("/api/follow/live", json={"card": "colours", "deadline_s": 0.6}).get_json()
    assert s["shell"]["baseline"]["text"] == "baseline needs the whole clip: not available live"
    import base64, io
    from PIL import Image
    buf = io.BytesIO(); Image.new("RGB", (64, 36), "red").save(buf, "JPEG")
    still = "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
    for i in range(3):
        assert client.post(f"/api/follow/{s['id']}/frame", json={"i": i, "stills": [still, still]}).status_code == 200
    t = time.time()
    done = wait_for(lambda: (lambda x: x if x["done"] else None)(state(client, s["id"])), seconds=5)
    release.set()
    assert time.time() - t < 3
    assert done["shell"]["deadline_hit"] and done["shell"]["stopped_at"] >= 0.6
    assert done["verdict"]["skipped"] == [] and done["verdict"]["missing_windows"] == [0, 1, 2]
    assert done["shell"]["questions"] == 3


def test_deadline_on_a_recording_marks_unreached_windows_not_sure(card, client, fake_api, sandbox):
    fake_api.colour_clip(sandbox / "videos" / "clean.mp4", COLOURS)
    s = client.post("/api/follow/replay", json={"card": "colours", "recording": "clean", "speed": 0.5, "deadline_s": 0.5}).get_json()
    done = wait_for(lambda: (lambda x: x if x["done"] else None)(state(client, s["id"])), seconds=8)
    assert done["shell"]["deadline_hit"] and done["verdict"]["skipped"] == []
    assert done["verdict"]["missing_windows"] and done["shell"]["questions"] == done["windows"] < done["total"]
    # asking for the hard stop again changes nothing
    again = client.post(f"/api/follow/{s['id']}/deadline").get_json()
    assert again["verdict"] == done["verdict"]


def test_qr_points_at_the_public_url_and_the_print_page_shows_it(card, client, monkeypatch):
    monkeypatch.setenv("WORDLESS_PUBLIC_URL", "https://wordless.example/")
    assert server.card_url("colours") == "https://wordless.example/print/card/colours"
    r = client.get("/qr/card/colours.svg")
    assert r.status_code == 200 and r.mimetype == "image/svg+xml" and b"<svg" in r.data
    page = client.get("/print/card/colours").get_data(as_text=True)
    assert "/qr/card/colours.svg" in page and "https://wordless.example/print/card/colours" in page
    assert client.get("/qr/card/nope.svg").status_code == 404
    monkeypatch.delenv("WORDLESS_PUBLIC_URL")
    monkeypatch.setenv("PORT", "5999")
    assert server.public_url() == f"http://{server.lan_address()}:5999"


def test_other_devices_get_the_card_and_nothing_else(card, client):
    phone = {"REMOTE_ADDR": "192.168.1.50"}
    assert client.get("/print/card/colours", environ_base=phone).status_code == 200
    assert client.get("/qr/card/colours.svg", environ_base=phone).status_code == 200
    assert client.get(f"/cards/colours/{card['steps'][0]['panel']}", environ_base=phone).status_code == 200
    assert client.get("/", environ_base=phone).status_code == 403
    assert client.get("/api/status", environ_base=phone).status_code == 403
    assert client.post("/api/follow/live", json={"card": "colours"}, environ_base=phone).status_code == 403


def test_recorded_run_plays_back_with_no_network(card, client, fake_api, sandbox, monkeypatch):
    fake_api.colour_clip(sandbox / "videos" / "skip.mp4", ["red", "blue", "yellow"])
    first = follow.replay(card, "skip", speed=0, block=True)
    # a saved live session beats a taped recording
    d = config.RUNS / "101500-abcd"
    d.mkdir(parents=True)
    (d / "session.json").write_text(json.dumps({"id": "101500-abcd", "card": "colours", "source": "live",
                                                "verdict": {"missing_windows": []}, "answers": {str(i): a for i, a in first.answers.items()}}))
    def no_network(*a, **k):
        raise AssertionError("a recorded run must not call the API")
    monkeypatch.setattr(gemini, "_post", no_network)
    runs = client.get("/api/recorded/colours").get_json()
    assert runs[0]["recording"] == "101500-abcd" and "skip" in [r["recording"] for r in runs]
    assert runs[0]["label"].startswith("Recorded run from ") and runs[0]["label"].endswith(" on live camera")
    s = client.post("/api/follow/recorded", json={"card": "colours", "speed": 0}).get_json()
    assert s["shell"]["mode"] == "REPLAY" and s["shell"]["recorded"] == runs[0]["label"]
    done = wait_for(lambda: (lambda x: x if x["done"] else None)(state(client, s["id"])))
    assert done["verdict"]["text"] == "panel 2 never happened" and done["windows"] == len(first.answers)
    # the run that was just cut short is skipped; the taped recording is next
    s = client.post("/api/follow/recorded", json={"card": "colours", "speed": 0, "exclude": "101500-abcd", "prefer": "skip"}).get_json()
    assert s["shell"]["recorded"].endswith(" on recording skip")
    assert wait_for(lambda: (lambda x: x if x["done"] else None)(state(client, s["id"])))["verdict"]["text"] == "panel 2 never happened"
