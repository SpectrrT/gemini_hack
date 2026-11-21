"""A local stand-in for the Gemini API, used to exercise the LIVE code path without a funded key.

It speaks the request and response shapes measured against the real API (research/feasibility/FINDINGS.md)
and rejects malformed requests the way the real one did (questions must be a map; types noul/choice/score;
instructions required). Its "vision" is a colour rule: a clip or still that is mostly red is step 1, green is
step 2, blue is step 3, yellow is step 4, anything dark is "none". That is enough to drive the whole
pipeline end to end on synthetic colour-card videos. It says nothing about how well the real models see.
"""
import base64
import io
import json
import re
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from PIL import Image, ImageFilter, ImageOps

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from wordless import video  # noqa: E402

COLOURS = {"red": (200, 30, 30), "green": (30, 170, 60), "blue": (30, 60, 200), "yellow": (220, 200, 40)}
ORDER = ["red", "green", "blue", "yellow"]
calls = {"decisions": 0, "generate": 0, "bad": []}
faults = {"decisions_503": 0, "image_no_image": 0}     # tests set these to make the next N calls misbehave


def colour_of(img):
    r, g, b = img.convert("RGB").resize((8, 8)).resize((1, 1)).getpixel((0, 0))
    if max(r, g, b) < 70:
        return None
    return min(COLOURS, key=lambda c: sum((x - y) ** 2 for x, y in zip(COLOURS[c], (r, g, b))))


def frames_of(mp4_bytes, fps=1):
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "v.mp4"
        src.write_bytes(mp4_bytes)
        subprocess.run([video.ffmpeg(), "-hide_banner", "-loglevel", "error", "-i", str(src), "-vf", f"fps={fps}",
                        "-pix_fmt", "yuvj420p", str(Path(tmp) / "f%04d.jpg")], check=True)
        return [Image.open(p).copy() for p in sorted(Path(tmp).glob("f*.jpg"))]


def seen_colour(blocks):
    """Colour of the LAST video or image block (the first image is the card)."""
    media = [b for b in blocks if b.get("type") in ("video", "image")]
    if not media:
        return None
    last = media[-1]
    raw = base64.b64decode(last["data"])
    if last["type"] == "video":
        fr = frames_of(raw, fps=2)
        return colour_of(fr[len(fr) // 2]) if fr else None
    return colour_of(Image.open(io.BytesIO(raw)))


def decide(body):
    qs = body.get("questions")
    if not isinstance(qs, dict):
        return 400, {"error": {"message": "questions must be an object keyed by id"}}
    if not isinstance(body.get("input"), (list, str)):
        return 400, {"error": {"message": "input is required"}}
    blocks = body["input"] if isinstance(body["input"], list) else [{"type": "text", "text": body["input"]}]
    for blk in blocks:
        if blk.get("type") not in ("text", "image", "video", "audio", "document"):
            return 400, {"error": {"message": f"unknown block type {blk.get('type')}"}}
        if blk["type"] != "text":
            base64.b64decode(blk["data"], validate=True)
            if not blk.get("mime_type"):
                return 400, {"error": {"message": "mime_type required"}}
    col = seen_colour(blocks)
    answers = {}
    for qid, q in qs.items():
        if q.get("type") not in ("noul", "choice", "score") or not q.get("instructions"):
            return 400, {"error": {"message": f"question {qid}: type must be noul|choice|score and instructions are required"}}
        if q["type"] == "noul":
            answers[qid] = {"noul": 0.08, "confidence": 0.9}
        elif q["type"] == "choice":
            opts = list(q["criteria"])
            none = [o for o in opts if "none" in o or o == "other"][0]
            pick = none
            if col:
                for o in opts:      # an option matches if its text mentions the colour, or by position
                    if col in q["criteria"][o].lower():
                        pick = o
            p = 0.86 if pick != none else 0.8
            probs = {o: (p if o == pick else (1 - p) / (len(opts) - 1)) for o in opts}
            answers[qid] = {"choice": pick, "probabilities": probs, "confidence": p}
        else:
            answers[qid] = {"score": 1.0, "probabilities": {}, "legend": {}, "confidence": 0.8}
    return 200, {"answers": answers, "usage": {"total_input_tokens": 1946}}


def generate(model, body):
    parts = body["contents"][0]["parts"]
    text = " ".join(p.get("text", "") for p in parts)
    media = [p["inlineData"] for p in parts if "inlineData" in p]
    for m in media:
        base64.b64decode(m["data"], validate=True)
    def reply(part):
        return 200, {"candidates": [{"content": {"parts": [part]}}]}
    if "image" in model and faults["image_no_image"] > 0:   # a refusal: text only, no image part
        faults["image_no_image"] -= 1
        return reply({"text": "I can't help with that image."})
    if "image" in model:                                    # photo -> "line art"
        img = Image.open(io.BytesIO(base64.b64decode(media[0]["data"]))).convert("L")
        art = ImageOps.invert(img.filter(ImageFilter.FIND_EDGES)).convert("RGB")
        col = colour_of(Image.open(io.BytesIO(base64.b64decode(media[0]["data"]))))
        if col:                                             # keep a colour patch so the fake checker can match it
            art.paste(COLOURS[col], (art.width // 3, art.height // 3, 2 * art.width // 3, 2 * art.height // 3))
        buf = io.BytesIO()
        art.save(buf, "PNG")
        return reply({"inlineData": {"mimeType": "image/png", "data": base64.b64encode(buf.getvalue()).decode()}})
    if "not_performed" in text:                             # Hydrogen one-call baseline
        ids = re.findall(r"^- (\S+): .*?(red|green|blue|yellow)", text, re.M | re.I)
        present = {colour_of(f) for f in frames_of(base64.b64decode(media[0]["data"]))}
        done = [i for i, c in ids if c.lower() in present]
        return reply({"text": json.dumps({"performed": done, "not_performed": [i for i, c in ids if i not in done]})})
    if "trace_question" in text:                            # Argon plan
        ids = re.findall(r"^- (s\d+):", text, re.M)
        return reply({"text": "```json\n" + json.dumps({"steps": [{"id": i, "setup": False, "trace_question": None} for i in ids],
                                                        "links": [[ids[0], ids[-1]]] if len(ids) > 1 else []}) + "\n```"})
    # Hydrogen naming the steps of the teaching clip
    present = []
    for f in frames_of(base64.b64decode(media[0]["data"])):
        c = colour_of(f)
        if c and c not in present:
            present.append(c)
    return reply({"text": json.dumps([{"action": f"Hold up the {c} card.", "done_when": f"The {c} card fills the view."} for c in present])})


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        key = self.headers.get("x-goog-api-key")
        try:
            if key == "broke":
                code, out = 402, {"error": {"code": 402, "message": "Your prepayment credits are depleted.", "status": "RESOURCE_EXHAUSTED"}}
            elif not key:
                code, out = 403, {"error": {"message": "missing key"}}
            elif self.path == "/v1beta/decisions" and faults["decisions_503"] > 0:
                faults["decisions_503"] -= 1
                code, out = 503, {"error": {"message": "overloaded"}}
            elif self.path == "/v1beta/decisions":
                calls["decisions"] += 1
                code, out = decide(body)
            elif m := re.match(r"/v1beta/models/([^:]+):generateContent", self.path):
                calls["generate"] += 1
                code, out = generate(m.group(1), body)
            else:
                code, out = 404, {"error": {"message": "unknown path " + self.path}}
        except Exception as e:  # a malformed request is the client's bug: report it
            code, out = 400, {"error": {"message": f"fake could not read the request: {type(e).__name__}: {e}"}}
        if code == 400:
            calls["bad"].append(out["error"]["message"])
        data = json.dumps(out).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def start(port=0):
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


def colour_clip(dst, colours, seconds=4, gap=2, size="640x360"):
    """Synthetic video: each colour for `seconds`, with `gap` seconds of black before, between and after."""
    seq = [("black", gap)]
    for c in colours:
        seq += [("0x%02x%02x%02x" % COLOURS[c], seconds), ("black", gap)]
    args = []
    for col, d in seq:
        args += ["-f", "lavfi", "-t", str(d), "-i", f"color=c={col}:s={size}:r=15"]
    filt = "".join(f"[{i}:v]" for i in range(len(seq))) + f"concat=n={len(seq)}:v=1:a=0[v]"
    subprocess.run([video.ffmpeg(), "-hide_banner", "-loglevel", "error", "-y", *args, "-filter_complex", filt, "-map", "[v]",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(dst)], check=True)
    return dst


if __name__ == "__main__":
    srv, url = start(int(sys.argv[1]) if len(sys.argv) > 1 else 8765)
    print("fake Gemini API on", url, "- run the app with GEMINI_BASE_URL=" + url + " GEMINI_API_KEY=test WORDLESS_TAPE=live")
    threading.Event().wait()
