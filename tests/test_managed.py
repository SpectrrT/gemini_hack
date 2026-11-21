"""The blind reader against a local fake of the Interactions and Decisions APIs. No network.

The fake agent "sees" by colour, like tests/fake_gemini.py: a mostly red panel reads as "Hold up the red
card." It answers in the measured shape of an interaction (code_execution_call / code_execution_result /
function_call view_file / model_output). The fake Decisions API says yes when sentences A and B name the
same colour. This proves the plumbing, the hash check and the scoring arithmetic, not the models.
"""
import base64
import hashlib
import io
import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from PIL import Image

from wordless import card as cards, config, gemini, managed

COLOURS = {"red": (200, 30, 30), "green": (30, 170, 60), "blue": (30, 60, 200)}
state = {}


def reset():
    state.update(interactions=0, decisions=0, inline=0, corrupt_copy=0, misread={}, bodies=[])


def panel_jpeg(colour, mark=0):
    """A white panel with a black shape (survives the 1-bit copy) and a colour patch (seen by the fake drawer)."""
    im = Image.new("RGB", (640, 360), "white")
    im.paste((0, 0, 0), (40 + 60 * mark, 40, 100 + 60 * mark, 320))
    im.paste(COLOURS[colour], (300, 100, 600, 300))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=92)
    return buf.getvalue()


def mark_of(png_or_jpeg):
    """Which panel is this? The fake agent recognises a panel by where its black bar is."""
    im = Image.open(io.BytesIO(png_or_jpeg)).convert("L")
    im = im.resize((640, 360))
    for m in range(3):
        if im.getpixel((70 + 60 * m, 180)) < 80:
            return m
    return None


def sentence(mark):
    colour = list(COLOURS)[mark] if mark is not None else "unknown"
    colour = state["misread"].get(colour, colour)
    return f"Hold up the {colour} card."


def interaction(body):
    state["interactions"] += 1
    state["bodies"].append(body)
    assert body["agent"] == managed.AGENT and body["environment"] == "remote"
    blocks = body["input"]
    assert all(b["type"] in ("text", "image") for b in blocks)          # the measured limit: text and images only
    text = " ".join(b.get("text", "") for b in blocks)
    images = [b for b in blocks if b["type"] == "image"]

    def done(steps):
        return 200, {"id": "v1_fake", "status": "completed", "usage": {"total_tokens": 20000}, "steps": steps,
                     "environment": "remote", "agent": body["agent"]}
    say = lambda obj: {"type": "model_output", "content": [{"type": "text", "text": "```json\n" + json.dumps(obj) + "\n```"}]}
    if "numbered panels" in text:                                        # whole sheet
        n = int(re.search(r"(\d+) numbered panels", text).group(1))
        return done([{"type": "thought", "signature": "x"},
                     say({"task": "Hold up cards", "steps": {str(i + 1): sentence(i) for i in range(n)}, "order_ok": True, "note": ""})])
    if images:                                                           # plain look, no sandbox
        state["inline"] += 1
        return done([say({"small": "", "full": sentence(mark_of(base64.b64decode(images[0]["data"]))), "objects": ["card"],
                          "writing": "", "crops": 0, "unsure": ""})])
    b64 = text.split("characters):\n", 1)[1].strip()                     # sandbox copy
    raw = base64.b64decode(b64, validate=True)
    sha = hashlib.sha256(raw).hexdigest()
    if state["corrupt_copy"] > 0:                                        # the agent mistyped the base64
        state["corrupt_copy"] -= 1
        sha = "0" * 64
    s = sentence(mark_of(raw))
    return done([
        {"id": "c1", "type": "code_execution_call", "signature": "x", "arguments": {"language": "bash", "code": "base64 -d ... && sha256sum /tmp/panel.png"}},
        {"call_id": "c1", "type": "code_execution_result", "is_error": False, "result": f"[STDOUT]\n{sha}  /tmp/panel.png\n\n[STDERR]\n"},
        {"id": "c2", "type": "function_call", "name": "view_file", "arguments": {"AbsolutePath": "/tmp/small.png"}},
        {"call_id": "c2", "type": "function_result", "name": "view_file", "is_error": False, "result": ""},
        {"id": "c3", "type": "function_call", "name": "view_file", "arguments": {"AbsolutePath": "/tmp/big.png"}},
        {"call_id": "c3", "type": "function_result", "name": "view_file", "is_error": False, "result": ""},
        say({"small": s, "full": s, "objects": ["card"], "writing": "", "crops": 1, "unsure": ""})])


def decisions(body):
    state["decisions"] += 1
    text = " ".join(b.get("text", "") for b in body["input"] if b["type"] == "text")
    answers = {}
    for qid, q in body["questions"].items():
        assert q["type"] == "noul" and q["instructions"]
        if "A: " in text:
            a, b = text.split("A: ", 1)[1].split("\nB: ", 1)
            same = bool({c for c in COLOURS if c in a} & {c for c in COLOURS if c in b})
            answers[qid] = {"noul": 0.92 if same else 0.04, "confidence": 0.9}
        else:
            answers[qid] = {"noul": 0.05, "confidence": 0.9}             # letters gate: no writing
    return 200, {"answers": answers, "usage": {"total_input_tokens": 80}}


def generate(body):
    """Fake image model: draws the panel that the prompt asks for ("... the <colour> card")."""
    text = " ".join(p.get("text", "") for p in body["contents"][0]["parts"])
    colour = re.search(r"unmistakable: Hold up the (\w+) card", text).group(1)
    data = panel_jpeg(colour, list(COLOURS).index(colour))
    return 200, {"candidates": [{"content": {"parts": [{"inlineData": {"mimeType": "image/jpeg", "data": base64.b64encode(data).decode()}}]}}]}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        try:
            if self.path == "/v1beta/interactions":
                code, out = interaction(body)
            elif self.path == "/v1beta/decisions":
                code, out = decisions(body)
            elif ":generateContent" in self.path:
                code, out = generate(body)
            else:
                code, out = 404, {"error": {"message": "unknown path"}}
        except Exception as e:
            code, out = 400, {"error": {"message": f"{type(e).__name__}: {e}"}}
        data = json.dumps(out).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


@pytest.fixture
def api(sandbox, monkeypatch):
    reset()
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setenv("GEMINI_BASE_URL", f"http://127.0.0.1:{srv.server_address[1]}")
    monkeypatch.setenv("GEMINI_API_KEY", "test")
    monkeypatch.setenv("WORDLESS_TAPE", "live")
    yield state
    srv.shutdown()


@pytest.fixture
def card(api):
    """A three-panel card on disk: red, green, blue."""
    d = cards.card_dir("rgb")
    d.mkdir(parents=True)
    steps = []
    for i, c in enumerate(COLOURS):
        (d / f"pn_s{i + 1:02d}.jpg").write_bytes(panel_jpeg(c, i))
        (d / f"kf_s{i + 1:02d}.jpg").write_bytes(panel_jpeg(c, i))
        steps.append({"id": f"s{i + 1:02d}", "action": f"Hold up the {c} card.", "done_when": "", "panel": f"pn_s{i + 1:02d}.jpg",
                      "keyframe": f"kf_s{i + 1:02d}.jpg"})
    c = cards.save({"id": "rgb", "title": "RGB", "steps": steps})
    cards.compose_sheet(c)
    return c


def test_all_panels_understood(card, api):
    out = managed.blind_read("rgb")
    assert (out["understood"], out["panels"], out["failing"]) == (3, 3, [])
    assert out["sandbox_reads"] == 3 and out["inline_reads"] == 0
    assert [r["blind"] for r in out["rows"]] == [s["action"] for s in card["steps"]]
    assert all(r["passed"] and r["p"] == 0.92 and r["files_viewed"] == 2 for r in out["rows"])
    assert out["understood_in_context"] == 3 and out["sheet"]["task"] == "Hold up cards"
    assert api["interactions"] == 4                                       # three panels and the sheet
    assert json.loads((config.RUNS / "blind_rgb.json").read_text())["understood"] == 3
    assert "3 of 3 panels understood" in managed.table(out)


def test_agents_never_get_the_step_names_or_the_video(card, api):
    managed.blind_read("rgb")
    sent = json.dumps(api["bodies"])
    assert "Hold up" not in sent and "video" not in [b["type"] for body in api["bodies"] for b in body["input"]]
    panel_bodies = [b for b in api["bodies"] if len(b["input"]) == 1]
    assert len(panel_bodies) == 3                                         # panel agents get text only: the copy


def test_a_misread_panel_fails_and_is_listed(card, api):
    api["misread"] = {"green": "blue"}
    out = managed.blind_read("rgb")
    assert out["understood"] == 2 and out["failing"] == [2]
    assert out["rows"][1]["p"] == 0.04 and not out["rows"][1]["passed"]
    assert "Panels to redraw: 2" in managed.table(out)


def test_copy_that_cannot_be_proven_falls_back_to_a_plain_look(card, api):
    api["corrupt_copy"] = 1                                               # the one sandbox try of one panel
    out = managed.blind_read("rgb", workers=1)
    assert out["understood"] == 3 and out["inline_reads"] == 1 and out["sandbox_reads"] == 2
    row = [r for r in out["rows"] if r["via"] == "inline"][0]
    assert row["files_viewed"] == 0 and row["p_small"] is None
    assert "[inline, no sandbox]" in managed.table(out)


def test_one_corrupt_copy_is_retried_in_the_sandbox_when_two_tries_are_allowed(card, api, monkeypatch):
    monkeypatch.setattr(managed, "SANDBOX_TRIES", 2)
    api["corrupt_copy"] = 1
    out = managed.blind_read("rgb", workers=1)
    assert out["sandbox_reads"] == 3 and api["inline"] == 0 and api["interactions"] == 5


def test_redraw_raises_the_score_and_can_be_applied(card, api):
    d = cards.card_dir("rgb")
    (d / "pn_s02.jpg").write_bytes(panel_jpeg("green", 0))                # panel 2 is drawn so that it reads as panel 1
    out = managed.blind_read("rgb", redraw=True)
    assert out["understood"] == 2 and out["understood_after_redraw"] == 3
    fix = out["rows"][1]["redraw"]
    assert fix["passed"] and fix["blind"] == "Hold up the green card." and not fix["applied"]
    assert mark_of((d / "pn_s02.jpg").read_bytes()) == 0                  # the card itself is untouched
    out = managed.blind_read("rgb", redraw=True, apply=True, tag=".b")
    assert out["rows"][1]["redraw"]["applied"] and mark_of((d / "pn_s02.jpg").read_bytes()) == 1
    assert (d / "pn_s02.before.jpg").exists()


def test_replay_needs_no_network(card, api, monkeypatch):
    first = managed.blind_read("rgb")
    n = api["interactions"]
    monkeypatch.setenv("WORDLESS_TAPE", "replay")
    monkeypatch.setenv("GEMINI_BASE_URL", "http://127.0.0.1:9")
    again = managed.blind_read("rgb")
    assert again["understood"] == first["understood"] and api["interactions"] == n


def test_compact_copy_stays_under_the_measured_limit():
    noisy = Image.effect_noise((1365, 768), 80).convert("RGB")
    buf = io.BytesIO()
    noisy.save(buf, "JPEG")
    cp = managed.compact_copy(buf.getvalue())
    assert cp["width"] == managed.COPY_WIDTHS[-1]                         # noise does not compress: smallest width
    cp = managed.compact_copy(panel_jpeg("red"))
    assert cp["width"] == 512 and len(cp["b64"]) <= managed.COPY_MAX_B64
    assert hashlib.sha256(base64.b64decode(cp["b64"])).hexdigest() == cp["sha"]


def test_final_json_tolerates_prose_and_rejects_none():
    steps = [{"type": "model_output", "content": [{"type": "text", "text": 'Here it is:\n{"full": "Cut it."}\nDone.'}]}]
    assert managed.final_json(steps) == {"full": "Cut it."}
    with pytest.raises(gemini.ApiError):
        managed.final_json([{"type": "model_output", "content": [{"type": "text", "text": ""}]}])
