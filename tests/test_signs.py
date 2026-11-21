"""Fast sequences: the decoder (pure code) and the kit / session / HTTP path against the fake API.
The fake "sees" by colour, so signs here are colour cards named red, green, blue, yellow."""
import base64
import io
import json

import pytest
from PIL import Image

from wordless import decode

L = ["a", "b", "c"]


def f(label, p=0.85):
    rest = (1 - p) / 3
    d = {x: rest for x in L + ["none"]}
    d[label] = p
    return d


def seen(frames, fps=5.0):
    return [s["label"] for s in decode.segments(frames, [i / fps for i in range(len(frames))], L)]


def test_signs_in_order_with_pauses():
    frames = [f("none")] * 2 + [f("a")] * 3 + [f("none")] + [f("b")] * 3 + [f("c")] * 4 + [f("none")] * 2
    assert seen(frames) == ["a", "b", "c"]


def test_one_wrong_frame_does_not_make_a_sign():
    frames = [f("a")] * 3 + [f("c", 0.6)] + [f("a")] * 3 + [f("b")] * 3
    assert seen(frames) == ["a", "b"]


def test_a_sign_held_for_two_frames_counts():
    frames = [f("none")] * 2 + [f("a")] * 2 + [f("none")] * 2 + [f("b")] * 2 + [f("none")] * 2
    assert seen(frames) == ["a", "b"]


def test_the_same_sign_twice_needs_a_real_pause():
    frames = [f("a")] * 3 + [f("none")] * 4 + [f("a")] * 3
    assert seen(frames) == ["a", "a"]


def test_unanswered_frames_carry_no_evidence():
    frames = [f("a")] * 2 + [None] * 2 + [f("a")] * 2 + [f("b")] * 3
    assert seen(frames) == ["a", "b"]


def test_low_confidence_run_is_dropped():
    frames = [f("a")] * 3 + [f("b", 0.35)] * 3 + [f("c")] * 3
    assert "b" not in seen(frames)


def test_align_names_the_error():
    d, ops = decode.align(["a", "c"], ["a", "b", "c"])
    assert d == 1 and [o["op"] for o in ops] == ["match", "missing", "match"] and ops[1]["want"] == "b" and ops[1]["pos"] == 2
    d, ops = decode.align(["a", "c", "c"], ["a", "b", "c"])
    assert d == 1 and ops[1] == {"op": "wrong", "want": "b", "got": "c", "pos": 2}
    d, ops = decode.align(["a", "b", "b", "c"], ["a", "b", "c"])
    assert d == 1 and sum(o["op"] == "extra" for o in ops) == 1


SEQS = [{"id": "abc", "name": "ABC", "signs": ["a", "b", "c"]}, {"id": "cba", "name": "CBA", "signs": ["c", "b", "a"]},
        {"id": "ab", "name": "AB", "signs": ["a", "b"]}]


def test_verdict_exact_near_unknown():
    assert decode.verdict(["c", "b", "a"], SEQS)["best"]["id"] == "cba"
    assert decode.verdict(["a", "b"], SEQS)["best"]["id"] == "ab"              # the exact one, not a prefix of ABC
    v = decode.verdict(["c", "a"], SEQS)
    assert v["kind"] == "near" and v["best"]["id"] == "cba"
    assert decode.verdict(["b", "b", "b", "b"], SEQS)["kind"] == "unknown"
    assert decode.verdict([], SEQS)["kind"] == "nothing"


def test_live_ranking_follows_progress():
    r = decode.rank(["c", "b"], SEQS, done=False)
    assert r[0]["id"] == "cba" and r[0]["covered"] == 2 and r[0]["errors"] == 0


# ---------------------------------------------------------------- kit + session against the fake API
COL = {"red": (200, 30, 30), "green": (30, 170, 60), "blue": (30, 60, 200), "yellow": (220, 200, 40), "dark": (10, 10, 10)}


def jpeg(colour):
    buf = io.BytesIO()
    Image.new("RGB", (320, 240), COL[colour]).save(buf, "JPEG")
    return buf.getvalue()


@pytest.fixture
def kit(fake_api):
    from wordless import signs
    k = signs.new("Colours")
    for c in ("red", "green", "blue", "yellow"):
        signs.add_sign(k["id"], c, jpeg(c), draw=False)
    signs.set_sequence(k["id"], "Traffic", ["red", "yellow", "green"])
    signs.set_sequence(k["id"], "Sea", ["blue", "green", "blue"])
    return signs.load(k["id"])


def perform(kit, colours, per=3, **kw):
    from wordless import signs
    s = signs.Session(kit, **kw)
    i = 0
    for c in colours:
        for _ in range(per if c != "dark" else 2):
            s.add_frame(i, i / 5.0, jpeg(c), wait=True, timeout=10, tries=2)
            i += 1
    return s, s.finish(wait_s=20)


def test_identify_names_the_sequence(kit):
    s, res = perform(kit, ["dark", "red", "yellow", "green", "dark"])
    assert res["kind"] == "exact" and res["best"]["name"] == "Traffic", res
    assert res["missing_frames"] == 0
    assert (s.dir / "signs.json").exists()


def test_identify_repeated_sign_and_unknown(kit):
    _, res = perform(kit, ["blue", "green", "blue"])
    assert res["best"]["name"] == "Sea"
    _, res = perform(kit, ["yellow", "yellow", "dark", "red", "dark", "blue", "dark", "yellow"])
    assert res["kind"] == "unknown" and res["text"].startswith("no known sequence")


def test_follow_names_the_missing_sign(kit):
    _, res = perform(kit, ["red", "green"], mode="follow", target="traffic")
    assert res["kind"] == "errors" and "never happened" in res["text"] and "yellow" in res["text"], res
    _, res = perform(kit, ["red", "yellow", "green"], mode="follow", target="traffic")
    assert res["kind"] == "exact"


def test_failed_frames_are_asked_again(kit, fake_api):
    fake_api.faults["decisions_503"] = 3
    _, res = perform(kit, ["red", "yellow", "green"])
    assert res["best"]["name"] == "Traffic" and res["missing_frames"] == 0


def test_session_replays_from_tape_without_network(kit, monkeypatch):
    from wordless import signs
    s, res = perform(kit, ["red", "yellow", "green"])
    monkeypatch.setenv("WORDLESS_TAPE", "replay")
    monkeypatch.setenv("GEMINI_BASE_URL", "http://127.0.0.1:9")
    again = signs.replay_session(kit, s.id)
    assert again.result["best"]["name"] == "Traffic"


def test_http_path(kit):
    import server
    c = server.app.test_client()
    assert c.get("/signs").status_code == 200
    st = c.get("/api/signs/status").get_json()
    assert st["kits"][0]["signs"] == 4 and any(p["id"] == "seals" for p in st["presets"])
    data = lambda col: "data:image/jpeg;base64," + base64.b64encode(jpeg(col)).decode()
    sid = c.post("/api/signs/sessions", json={"kit": kit["id"]}).get_json()["id"]
    i = 0
    for col in ["red", "yellow", "green"]:
        for _ in range(3):
            assert c.post(f"/api/signs/sessions/{sid}/frame", json={"i": i, "t": i / 5, "image": data(col)}).get_json()["ok"]
            i += 1
    st = c.post(f"/api/signs/sessions/{sid}/finish", json={}).get_json()
    assert st["done"] and st["result"]["best"]["name"] == "Traffic"
    assert c.get(f"/print/signs/{kit['id']}/traffic").status_code == 200
    # a preset kit: sequences appear once their signs are taught
    k = c.post("/api/signs/kits", json={"preset": "countdown"}).get_json()
    for n in ["One", "Two", "Three", "Four", "Five"]:
        k = c.post(f"/api/signs/kits/{k['id']}/signs", json={"name": n, "image": data("red")}).get_json()
    assert {q["name"] for q in k["sequences"]} == {"Count up", "Count down", "Odds", "Evens"}
