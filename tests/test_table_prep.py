"""Table prep: clips recorded with no key, printable card and sealed cards, and the one-command table gate
(run here against the fake API)."""
import io
import json

import pytest

from wordless import config, table


@pytest.fixture
def client(sandbox, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    import server
    return server.app.test_client()


def upload(client, path, role, truth=None, skip=None, marks=None):
    data = {"video": (io.BytesIO(path.read_bytes()), "clip.mp4"), "role": role, "marks": json.dumps(marks or [])}
    if truth:
        data["truth"] = truth
    if skip:
        data["skip"] = str(skip)
    return client.post("/api/table/clips", data=data, content_type="multipart/form-data")


def clips(fake, sandbox, client):
    all4 = ["red", "green", "blue", "yellow"]
    mk = lambda name, cols: fake.colour_clip(sandbox / f"{name}.mp4", cols, seconds=8)
    assert upload(client, mk("a", all4), "teach", marks=[2, 12, 22, 32]).status_code == 200
    assert upload(client, mk("b", all4), "follow", "right").status_code == 200
    assert upload(client, mk("c", ["red", "blue", "yellow"]), "follow", "skip", 2).status_code == 200
    assert upload(client, mk("d", ["red", "green", "blue"]), "follow", "skip", 4).status_code == 200


def test_clips_are_saved_with_their_answer_key_and_pace_without_any_api_call(fake_api, sandbox, client, monkeypatch):
    monkeypatch.setenv("WORDLESS_TAPE", "replay")
    assert client.get("/api/table").get_json()["need"][0] == "a teaching run"
    clips(fake_api, sandbox, client)
    t = client.get("/api/table").get_json()
    assert [c["name"] for c in t["clips"]] == ["t_teach", "t_right_1", "t_skip2_1", "t_skip4_1"]
    assert t["need"] == [] and t["can_run"] is False                      # replay mode: recorded but not runnable
    teach = t["clips"][0]
    assert [p["seconds"] for p in teach["pace"]][:3] == [10.0, 10.0, 10.0] and not any(p["short"] for p in teach["pace"])
    assert fake_api.calls == {"decisions": 0, "generate": 0, "bad": []}
    assert client.get("/video/t_skip2_1.mp4").status_code == 200
    assert client.post("/api/table/gate", json={}).status_code == 400    # needs the live API


def test_short_steps_are_marked_and_bad_input_is_refused(fake_api, sandbox, client):
    clip = fake_api.colour_clip(sandbox / "x.mp4", ["red", "green"], seconds=4)
    r = upload(client, clip, "follow", "right", marks=[2, 6, 8.5])
    assert [p["short"] for p in r.get_json()["clip"]["pace"]] == [True, True, True]
    assert upload(client, clip, "follow", "skip", 7).status_code == 400   # the kit has 4 steps
    assert upload(client, clip, "follow").status_code == 400              # no answer key
    bad = sandbox / "bad.mp4"
    bad.write_bytes(b"not a video")
    assert upload(client, bad, "teach").status_code == 400
    assert client.post("/api/table/clips/t_right_1/delete", json={}).get_json()["clips"] == []
    assert client.post("/api/table/clips/..%2Fx/delete", json={}).status_code in (400, 404)


def test_table_gate_scores_every_clip_against_its_answer_key(fake_api, sandbox, client):
    clips(fake_api, sandbox, client)
    res = table.run_gate()
    assert res["panels"] == 4 and res["problems"] == []
    assert [(r["clip"], r["outcome"]) for r in res["rows"]] == [("t_right_1", "correct"), ("t_skip2_1", "correct"), ("t_skip4_1", "correct")]
    assert res["rows"][1]["flagged"] == [2] and res["false_never_happened"] == 0 and res["passed"]
    assert json.loads((config.RUNS / "gate_g2.json").read_text())["correct"] == 3
    assert client.get("/api/table").get_json()["last_gate"]["passed"] is True


def test_gate_fails_loudly_when_the_answer_key_and_the_verdict_disagree(fake_api, sandbox, client):
    clips(fake_api, sandbox, client)
    lied = fake_api.colour_clip(sandbox / "e.mp4", ["red", "green", "blue", "yellow"], seconds=8)
    upload(client, lied, "follow", "skip", 3)                             # the key says step 3 was skipped; it was not
    res = table.run_gate()
    assert res["passed"] is False and {r["clip"]: r["outcome"] for r in res["rows"]}["t_skip3_1"] == "missed"


def test_gate_refuses_to_score_skips_when_the_card_has_a_different_number_of_panels(fake_api, sandbox, client):
    clips(fake_api, sandbox, client)
    client.post("/api/table/kit", json={"steps": 5})
    res = table.run_gate()
    assert not res["passed"] and "4 panels but the kit has 5 steps" in res["problems"][0]
    assert [r["outcome"] for r in res["rows"]] == ["correct", "unscored", "unscored"]


def test_print_pages(fake_api, sandbox, client):
    clips(fake_api, sandbox, client)
    table.run_gate()
    html = client.get("/print/card/table").get_data(as_text=True)
    assert html.count('class="p"') == 4 and "self-test: 4/4" in html
    assert client.get("/print/card/nope").status_code == 404
    deck = client.get("/print/sealed?steps=4").get_data(as_text=True)
    assert deck.count("Do it right") == 4 and all(f"Skip step {k}" in deck for k in (1, 2, 3, 4))
    assert client.get("/print/sealed?steps=40").status_code == 400


def test_rerecording_a_clip_drops_its_recorded_answers(fake_api, sandbox, client, monkeypatch):
    monkeypatch.setenv("WORDLESS_TAPE", "auto")                # the default: recorded answers are reused
    clips(fake_api, sandbox, client)
    table.run_gate()
    n = fake_api.calls["decisions"]
    assert table.run_gate()["passed"] and fake_api.calls["decisions"] == n          # unchanged clips: answers reused
    client.post("/api/table/clips/t_skip2_1/delete", json={})
    wrong = fake_api.colour_clip(sandbox / "w.mp4", ["red", "green", "blue", "yellow"], seconds=8)
    assert upload(client, wrong, "follow", "skip", 2).get_json()["clip"]["name"] == "t_skip2_1"   # same name, new video
    res = table.run_gate()
    assert {r["clip"]: r["outcome"] for r in res["rows"]}["t_skip2_1"] == "missed" and fake_api.calls["decisions"] > n


def test_kit_cannot_shrink_below_a_recorded_skip_and_gate_runs_do_not_overlap(fake_api, sandbox, client):
    clips(fake_api, sandbox, client)
    assert client.post("/api/table/kit", json={"steps": 3}).status_code == 400
    assert table.gate_lock.acquire(blocking=False)
    try:
        with pytest.raises(ValueError):
            table.run_gate()
        assert client.post("/api/table/clips/t_right_1/delete", json={}).status_code == 400
    finally:
        table.gate_lock.release()


def test_running_out_of_credit_mid_gate_is_not_scored(fake_api, sandbox, client, monkeypatch):
    clips(fake_api, sandbox, client)
    table.run_gate()
    client.post("/api/table/clips/t_right_1/delete", json={})
    upload(client, fake_api.colour_clip(sandbox / "r.mp4", ["red", "green", "blue", "yellow"], seconds=8), "follow", "right")
    monkeypatch.setenv("GEMINI_API_KEY", "broke")
    from wordless import gemini
    with pytest.raises(gemini.NoCredit):
        table.run_gate()
    assert json.loads((config.RUNS / "gate_g2.json").read_text())["passed"] is True  # the earlier result is kept
