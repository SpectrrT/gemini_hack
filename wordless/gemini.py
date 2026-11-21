"""Thin REST client for the Gemini API plus a tape that records every answer.

Tape modes (env WORDLESS_TAPE):
  replay  only recorded answers are used; a missing key raises TapeMiss. No network, no key needed.
  auto    recorded answer if there is one, otherwise call the API and record it. (default)
  live    always call the API and record it.
Keys are chosen by the caller and describe the job, e.g. "follow/tomato/12_43/card/0007".
"""
import base64
import http.client
import json
import os
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from . import config


class ApiError(Exception):
    def __init__(self, status, body):
        super().__init__(f"Gemini API HTTP {status}: {body[:300]}")
        self.status, self.body = status, body


class NoCredit(ApiError):
    """HTTP 402: the key's prepaid credit is used up."""


class TapeMiss(Exception):
    """Replay mode asked for an answer that was never recorded."""


def base_url():
    return os.environ.get("GEMINI_BASE_URL", "https://generativelanguage.googleapis.com").rstrip("/")


def api_key():
    k = os.environ.get("GEMINI_API_KEY")
    if k:
        return k
    env = config.ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if line.startswith("GEMINI_API_KEY="):
                return line.split("=", 1)[1].strip()
    raise ApiError(0, "GEMINI_API_KEY is not set (put it in .env)")


def mode():
    return os.environ.get("WORDLESS_TAPE", "auto")


# ---------------------------------------------------------------- tape
class Tape:
    def __init__(self, root=None):
        self.root = Path(root or config.TAPE)

    def _path(self, key, ext):
        return self.root / (key + ext)

    def has(self, key):
        return self._path(key, ".json").exists() or self._path(key, ".bin").exists()

    def get_json(self, key):
        p = self._path(key, ".json")
        return json.loads(p.read_text()) if p.exists() else None

    def put_json(self, key, value):
        p = self._path(key, ".json")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(value))

    def get_bytes(self, key):
        p = self._path(key, ".bin")
        return p.read_bytes() if p.exists() else None

    def put_bytes(self, key, value):
        p = self._path(key, ".bin")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(value)

    def count(self, prefix):
        d = self.root / prefix
        return len(list(d.glob("*.json"))) if d.is_dir() else 0


tape = Tape()


def taped(key, fn, kind="json"):
    """Return the recorded answer for `key`, or run fn() and record it, depending on the tape mode."""
    get, put = (tape.get_json, tape.put_json) if kind == "json" else (tape.get_bytes, tape.put_bytes)
    m = mode()
    if key and m in ("replay", "auto"):
        v = get(key)
        if v is not None:
            return v
    if m == "replay":
        raise TapeMiss(key or "(call without a tape key)")
    v = fn()
    if key and v is not None:
        put(key, v)
    return v


# ---------------------------------------------------------------- HTTP
_lock = threading.Lock()
_last = [0.0]


def _throttle(gap):
    with _lock:
        wait = _last[0] + gap - time.time()
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.time()


def _post(path, body, timeout):
    req = urllib.request.Request(
        base_url() + path, data=json.dumps(body).encode(),
        headers={"x-goog-api-key": api_key(), "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        text = e.read().decode(errors="replace")
        raise (NoCredit if e.code == 402 else ApiError)(e.code, text) from None
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise ApiError(-1, f"network: {e}") from None
    except (ValueError, http.client.HTTPException) as e:      # truncated or non-JSON body
        raise ApiError(-1, f"bad response: {type(e).__name__}: {e}") from None


def _post_retry(path, body, timeout, tries, gap=0.0):
    """Back-off for 429/5xx follows the measured scripts (3 s, then 6 s, ...)."""
    for attempt in range(tries):
        if gap:
            _throttle(gap)          # every attempt goes through the rate limit, not only the first
        try:
            return _post(path, body, timeout)
        except NoCredit:
            raise
        except ApiError as e:
            retryable = e.status in (-1, 429, 500, 502, 503, 504)
            if not retryable or attempt == tries - 1:
                raise
            time.sleep(0.5 + attempt if e.status == -1 else 3 + 3 * attempt)


def b64(data):
    return base64.b64encode(data).decode()


def text_block(t):
    return {"type": "text", "text": t}


def image_block(data, mime="image/jpeg", resolution=None):
    blk = {"type": "image", "data": b64(data), "mime_type": mime}
    if resolution:
        blk["resolution"] = resolution
    return blk


def video_block(data, mime="video/mp4"):
    return {"type": "video", "data": b64(data), "mime_type": mime}


def decide(blocks, questions, timeout=20, tries=4, gap=None):
    """Decisions API. Returns {"answers": {...}, "latency": s, "tokens": n}.
    Request and response shapes are the ones measured in research/feasibility/FINDINGS.md."""
    t = time.time()
    d = _post_retry("/v1beta/decisions", {"model": config.MODELS["decision"], "input": blocks, "questions": questions},
                    timeout, tries, gap=config.DECISIONS_MIN_GAP_S if gap is None else gap)
    if not isinstance(d, dict) or "answers" not in d:
        raise ApiError(200, "no answers in response: " + json.dumps(d)[:300])
    return {"answers": d["answers"], "latency": round(time.time() - t, 3),
            "tokens": (d.get("usage") or {}).get("total_input_tokens")}


def generate(model, parts, cfg=None, timeout=180, tries=2):
    """generateContent. parts use {"text": ..} and {"inlineData": {"mimeType", "data"}}."""
    body = {"contents": [{"role": "user", "parts": parts}]}
    if cfg:
        body["generationConfig"] = cfg
    t = time.time()
    d = _post_retry(f"/v1beta/models/{model}:generateContent", body, timeout, tries)
    d["_latency"] = round(time.time() - t, 2)
    return d


def inline(data, mime):
    return {"inlineData": {"mimeType": mime, "data": b64(data)}}


def text_of(d):
    try:
        return "".join(p.get("text", "") for p in d["candidates"][0]["content"]["parts"] if not p.get("thought"))
    except (KeyError, IndexError, TypeError):
        raise ApiError(200, "no text in response: " + json.dumps(d)[:300]) from None


def image_of(d):
    try:
        for p in d["candidates"][0]["content"]["parts"]:
            if "inlineData" in p:
                return base64.b64decode(p["inlineData"]["data"])
    except (KeyError, IndexError, TypeError):
        pass
    raise ApiError(200, "no image in response: " + json.dumps(d)[:300])


def json_of(d):
    """Parse a JSON answer, tolerating a ```json fence around it."""
    s = text_of(d).strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[1] if "\n" in s else s
        s = s.rsplit("```", 1)[0]
    start = min([i for i in (s.find("{"), s.find("[")) if i >= 0], default=0)
    return json.loads(s[start:])
