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
    for i, col in enumerate(["blue"] * 3 + ["yellow"] * 3):
        assert c.post(f"/api/follow/{st['id']}/frame", json={"i": i, "t": i / 5, "image": data(col)}).get_json()["ok"]
    done = c.post(f"/api/follow/{st['id']}/finish", json={}).get_json()
    assert done["done"] and done["verdict"]["clean"] and done["shell"]["questions"] == 6, done
    assert c.get("/signs").status_code == 404
