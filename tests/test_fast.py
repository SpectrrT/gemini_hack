"""The fast path end to end against the fake API: one clip in (any number of steps, a repeat included), a card
out, then a person checked frame by frame. The fake "sees" by colour."""
import base64
import io

import pytest
from PIL import Image

COL = {"red": (200, 30, 30), "green": (30, 170, 60), "blue": (30, 60, 200), "yellow": (220, 200, 40), "dark": (10, 10, 10)}


def jpeg(colour):
    buf = io.BytesIO()
    Image.new("RGB", (320, 240), COL[colour]).save(buf, "JPEG")
    return buf.getvalue()


@pytest.fixture
def card(fake_api, sandbox):
    from wordless import fast
    clip = fake_api.colour_clip(sandbox / "teach.mp4", ["red", "green", "red", "blue"], seconds=1, gap=1)
    events = []
    c = fast.build(clip, title="Colours", emit=events.append)
    c["_events"] = events
    return c


def perform(card, colours, per=3):
    from wordless import fast
    s = fast.Session(card)
    i = 0
    for col in colours:
        for _ in range(per):
            s.add_frame(i, i / 5.0, jpeg(col), wait=True, timeout=10, tries=2)
            i += 1
    return s, s.finish(wait_s=20)


def test_card_is_built_with_no_step_count_given(card):
    assert card["fast"] and len(card["steps"]) == 4                       # red, green, red again, blue
    poses = [s["pose"] for s in card["steps"]]
    assert poses[0] == poses[2] and len(set(poses)) == 3
    assert all(s["seconds"] <= 1.6 for s in card["steps"])                # one-second steps were found
    assert card["self_test"] == {"recognised": 4, "of": 4, "distance": 0}
    stages = {e["stage"]: e["state"] for e in card["_events"]}
    assert stages == {"prepare": "done", "name": "done", "locate": "done", "draw": "done", "selftest": "done", "card": "done"}


def test_follow_clean_skipped_wrong_and_extra(card):
    _, v = perform(card, ["dark", "red", "green", "dark", "red", "blue", "dark"])
    assert v["clean"] and v["text"] == "all 4 steps seen, in order", v
    _, v = perform(card, ["red", "dark", "red", "blue"])                  # green left out
    assert v["skipped"] == ["q02"] and v["text"] == "step 2 never happened", v
    _, v = perform(card, ["red", "yellow", "dark", "red", "blue"])        # yellow is not on the card: nothing seen there
    assert v["skipped"] == ["q02"]
    _, v = perform(card, ["red", "blue", "dark", "red", "blue"])          # blue where green should be
    assert v["skipped"] == ["q02"] and "step 2 was" in v["text"] and v["wrong"]["q02"]
    _, v = perform(card, ["red", "green", "dark", "red", "blue", "green"])
    assert not v["clean"] and v["extra"] and v["text"].startswith("extra:")
    _, v = perform(card, ["green", "red", "dark", "red", "blue"])         # every step done, the first two swapped
    assert not v["skipped"] and v["out_of_order"] and "done out of order" in v["text"] and not v["clean"], v


def test_saved_run_plays_back_with_no_network(card, monkeypatch):
    import time
    import server
    from wordless import fast, gemini
    s, v = perform(card, ["red", "dark", "red", "blue"])
    assert fast.saved_runs(card)[0]["recording"] == s.id

    def no_network(*a, **k):
        raise AssertionError("a recorded run must not call the API")
    monkeypatch.setattr(gemini, "_post", no_network)
    c = server.app.test_client()
    runs = c.get(f"/api/recorded/{card['id']}").get_json()
    assert runs and runs[0]["recording"] == s.id and runs[0]["label"].startswith("Recorded run from ")
    st = c.post("/api/follow/recorded", json={"card": card["id"], "speed": 50}).get_json()
    assert st["fast"] and st["shell"]["mode"] == "REPLAY"
    for _ in range(100):
        done = c.get(f"/api/follow/{st['id']}").get_json()
        if done["done"]:
            break
        time.sleep(0.05)
    assert done["verdict"]["text"] == v["text"] == "step 2 never happened", done["verdict"]


def test_live_state_lights_steps_in_order(card):
    from wordless import fast
    s = fast.Session(card)
    for i in range(6):
        s.add_frame(i, i / 5.0, jpeg("red" if i < 3 else "green"), wait=True, timeout=10, tries=2)
    import concurrent.futures as cf
    cf.wait(list(s.pending.values()))
    st = s.state()
    assert st["fast"] and [st["panels"][q]["state"] for q in ("q01", "q02", "q03", "q04")] == ["seen", "seen", "pending", "pending"]
    assert st["now"] == "q02" and not st["done"]
    assert st["next"] == "q03"                                            # the guide shows the third step now
    assert set(st["evidence"]) == {"q01", "q02"} and st["evidence"]["q01"].startswith(f"/runs/{s.id}/f_0000")
    import server
    assert server.app.test_client().get(st["evidence"]["q02"]).status_code == 200
    v = s.finish(wait_s=20)
    assert set(v["evidence"]) == {"q01", "q02"} and v["skipped"] == ["q03", "q04"]


def test_http_teach_and_follow(fake_api, sandbox):
    import time
    import server
    c = server.app.test_client()
    clip = fake_api.colour_clip(sandbox / "t.mp4", ["blue", "yellow"], seconds=1, gap=1)
    jid = c.post("/api/teach", data={"video": (io.BytesIO(clip.read_bytes()), "t.mp4"), "title": "Two"}).get_json()["job"]
    for _ in range(200):
        j = c.get(f"/api/jobs/{jid}").get_json()
        if j["done"]:
            break
        time.sleep(0.1)
    assert j["card"] and not j["error"], j
    card = c.get(f"/api/cards/{j['card']}").get_json()
    assert card["fast"] and len(card["steps"]) == 2 and c.get(f"/cards/{card['id']}/{card['steps'][0]['panel']}").status_code == 200
    assert c.get(f"/print/card/{card['id']}").status_code == 200
    st = c.post("/api/follow/live", json={"card": card["id"], "deadline_s": 60}).get_json()
    assert st["fast"] and st["shell"]["mode"] == "LIVE"
    data = lambda col: "data:image/jpeg;base64," + base64.b64encode(jpeg(col)).decode()
    for i, col in enumerate(["blue"] * 10 + ["yellow"] * 10):     # 2 s each: the fake's one-call baseline samples once a second
        assert c.post(f"/api/follow/{st['id']}/frame", json={"i": i, "t": i / 5, "image": data(col)}).get_json()["ok"]
    done = c.post(f"/api/follow/{st['id']}/finish", json={}).get_json()
    assert done["done"] and done["verdict"]["clean"] and done["shell"]["questions"] == 20, done
    # the one-call baseline runs on the same frames and lands beside our verdict
    for _ in range(100):
        b = c.get(f"/api/follow/{st['id']}").get_json()["shell"]["baseline"]
        if b["state"] != "running":
            break
        time.sleep(0.1)
    assert b["state"] == "done" and b["skipped"] == [] and b["text"] == "all 2 steps performed", b
    # the trial is logged with what really happened (the person did it right), baseline scored on the same trial
    row = c.post("/api/tally", json={"session": st["id"], "sealed": "right"}).get_json()
    assert row["card_checker"] == "correct"
    for _ in range(100):
        rows = c.get("/api/tally").get_json()
        if rows[-1]["hydrogen_one_call"] != "pending":
            break
        time.sleep(0.1)
    assert rows[-1]["hydrogen_one_call"] == "correct", rows[-1]
    assert c.get("/signs").status_code == 404


def test_whole_run_review_decides_and_frames_can_only_add_doubt(card, monkeypatch):
    from wordless import config, fast
    monkeypatch.setattr(config, "FAST_REVIEW", True)
    poses = [s["pose"] for s in card["steps"]]                            # red, green, red, blue
    # frames miss green (shown too briefly), the review saw it: cleared
    monkeypatch.setattr(fast.Session, "_review", lambda self: {"ok": True, "performed": poses, "model": "carbon", "lat": 9})
    _, v = perform(card, ["red", "dark", "red", "blue"])
    assert v["clean"] and v["by_frames"] != v["performed"] and v["review"]["ok"], v
    # frames saw every step, the review says green never happened: not sure, never a flat "never happened"
    monkeypatch.setattr(fast.Session, "_review", lambda self: {"ok": True, "performed": [poses[0], poses[2], poses[3]]})
    _, v = perform(card, ["red", "green", "dark", "red", "blue"])
    assert v["unsure"] == ["q02"] and not v["skipped"] and "not sure about step 2" in v["text"], v
    # both agree it never happened
    _, v = perform(card, ["red", "dark", "red", "blue"])
    assert v["skipped"] == ["q02"] and v["text"] == "step 2 never happened", v
    # the review fails: the frame answers stand, and the verdict says so
    monkeypatch.setattr(fast.Session, "_review", lambda self: {"ok": False, "error": "TimeoutError"})
    _, v = perform(card, ["red", "dark", "red", "blue"])
    assert v["skipped"] == ["q02"] and v["text"].endswith("whole-run review did not answer"), v


def test_hydrogen_second_vote_confirms_or_softens_what_the_frames_flagged(card):
    """card steps: red, green, red, blue. The frames flag a step; the one Hydrogen call on the same run votes."""
    from wordless import config
    # Hydrogen agrees the step never happened: the flag stands
    s, v = perform(card, ["red", "dark", "red", "blue"])
    assert v["skipped"] == ["q02"] and "second" not in v
    v = s.second_vote(["q02"], lat=4.2)
    assert v["skipped"] == ["q02"] and v["unsure"] == [] and v["text"] == "step 2 never happened", v
    assert v["second"] == {"model": config.MODELS["hydrogen"], "lat": 4.2, "confirmed": ["q02"], "softened": []}
    # Hydrogen saw the step the frames missed: "not sure", never a flat "never happened"
    s, v = perform(card, ["red", "dark", "red", "blue"])
    v = s.second_vote([])
    assert v["skipped"] == [] and v["unsure"] == ["q02"] and v["text"] == "not sure about step 2" and not v["clean"], v
    assert s.second_vote(["q02"])["unsure"] == ["q02"]                     # a second answer changes nothing
    # Hydrogen cannot un-see a step the frames saw: a clean run stays clean
    s, v = perform(card, ["red", "green", "red", "blue"])
    assert v["clean"]
    v = s.second_vote(["q01", "q03"])
    assert v["clean"] and v["skipped"] == [] and v["unsure"] == [] and v["second"]["confirmed"] == [], v
