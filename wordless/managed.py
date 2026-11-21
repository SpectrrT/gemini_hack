"""Blind reader: managed agents test whether a card can be understood without the video.

For a built card, one managed agent per panel (in parallel) plus one for the whole sheet. An agent gets
pictures only: never the video, never the step names. It writes, in one sentence, what the picture tells a
person to do. Our server then asks the Decisions API whether that sentence and the true step name describe
the same action. Output: pass or fail per panel with the probability, and "panels understood out of N".

What the sandbox is used for (measured Nov 21, see docs/MANAGED.md):
  An image block sent to the agent is seen by the model but is NOT a file in the sandbox. So each panel
  agent receives a compact 1-bit copy of the panel as base64 text, writes it to disk, and proves the copy
  with sha256sum (we check the hash in the tool log, not in the agent's prose). Its code then shrinks the
  panel to the size it has when the card is seen from across a table, the agent looks at that first, then
  at the full copy, and crops and enlarges regions it is unsure about. Every look is in the step log.

The Decisions API is called from here, never from the sandbox (the sandbox's own key is a placeholder).
"""
import base64
import concurrent.futures as cf
import hashlib
import io
import json
import re
import time

from PIL import Image

from . import card as cards
from . import checker, config, gemini

AGENT = "antigravity-preview-09-2026"
PASS_P = 0.5              # a panel is "understood" at or above this probability of "same action"
COPY_WIDTHS = (512, 448, 384, 320)
COPY_MAX_B64 = 6000       # measured: 5,900 characters copied exactly twice; 10,120 characters did not
SANDBOX_TRIES = 1         # tries through the sandbox copy before a plain look (a second try cost up to 180 s more, measured)
AGENT_TIMEOUT_S = 180     # a sandbox read took 67 to 99 s when it worked first time
SMALL_W = 160             # "seen from across a table": a 400 px sheet cell at well under half size

PANEL_PROMPT = """You are testing a picture-only instruction card. Below is ONE panel of the card as a PNG file in base64.
You have never seen the task and there is nothing else to go on. Work in your sandbox:

1. Write the base64 to /tmp/panel.b64 exactly as given (no line breaks added or removed inside it), decode it to
   /tmp/panel.png and run `sha256sum /tmp/panel.png`. The hash must be %(sha)s.
   If it differs, write the file once more. If it still differs, reply with only {"error": "hash mismatch"}.
2. `pip install pillow`. With Python, save /tmp/small.png: the panel scaled to %(small)d pixels wide. Look at
   /tmp/small.png FIRST (view the file) and decide what it tells a person to do before you look at anything larger.
3. Save /tmp/big.png: the panel enlarged 2x. Look at it. Wherever you are unsure (what is in the hand, what
   comes out of a container, where the arrow points), crop that region, enlarge it 4x, save it and look at it.
4. Reply with JSON only, no other text:
{"small": "<imperative sentence, at most 12 words: what the small version tells a person to do>",
 "full": "<imperative sentence, at most 12 words: what the panel tells a person to do>",
 "objects": ["<things you can identify>"],
 "writing": "<any letters or words you can see in the drawing, else empty>",
 "crops": <how many regions you cropped and looked at>,
 "unsure": "<what is still ambiguous, else empty>"}

BASE64 (%(n)d characters):
%(b64)s"""

INLINE_PROMPT = """You are testing a picture-only instruction card. The image is ONE panel of the card. You have never
seen the task and there is nothing else to go on. Reply with JSON only, no other text:
{"small": "", "full": "<imperative sentence, at most 12 words: what the panel tells a person to do>",
 "objects": ["<things you can identify>"], "writing": "<any letters or words you can see, else empty>",
 "crops": 0, "unsure": "<what is ambiguous, else empty>"}"""

SHEET_PROMPT = """The image is a picture-only instruction card: %(n)d numbered panels, read in order. You have never seen the
task and there is nothing else to go on. You may use your sandbox if it helps.
Reply with JSON only, no other text:
{"task": "<what the whole card makes or does, at most 10 words>",
 "steps": {"1": "<imperative sentence, at most 12 words, for panel 1>", "2": "..."},
 "order_ok": <true if the panels make sense in this order>,
 "note": "<panels that look the same or are unclear, else empty>"}"""

REDRAW_HINT = (" The action must be unmistakable: %(action)s A person who saw only the previous drawing read it as: "
               "\"%(blind)s\" Make the object in the hand and what comes out of it clear by shape alone.")


# ---------------------------------------------------------------- the agent call
def interact(blocks, timeout=None, tries=1):
    """One managed-agent task on the Interactions API. Returns the raw interaction plus wall time."""
    t = time.time()
    d = gemini._post_retry("/v1beta/interactions", {"agent": AGENT, "environment": "remote", "input": blocks},
                            timeout or AGENT_TIMEOUT_S, tries)
    if not isinstance(d, dict) or d.get("status") != "completed" or not isinstance(d.get("steps"), list):
        raise gemini.ApiError(200, "interaction not completed: " + json.dumps(d)[:300])
    return {"steps": [{k: v for k, v in s.items() if k != "signature"} for s in d["steps"]],
            "tokens": (d.get("usage") or {}).get("total_tokens"), "seconds": round(time.time() - t, 1)}


def final_text(steps):
    out = [c.get("text", "") for s in steps if s.get("type") == "model_output" for c in s.get("content", [])]
    return out[-1] if out else ""


def final_json(steps):
    """The JSON object in the agent's last message, tolerating a fence or prose around it."""
    s = final_text(steps)
    m = re.search(r"\{.*\}", s, re.S)
    if not m:
        raise gemini.ApiError(200, "agent gave no JSON: " + s[:200])
    try:
        return json.loads(m.group(0))
    except ValueError:
        raise gemini.ApiError(200, "agent JSON did not parse: " + s[:200]) from None


def tool_log(steps):
    """What the agent actually did, from the step log: code runs, files looked at, text of every tool result."""
    runs = [s for s in steps if s.get("type") == "code_execution_call"]
    looks = [s for s in steps if s.get("type") == "function_call" and s.get("name") == "view_file"]
    results = " ".join(str(s.get("result", "")) for s in steps if s.get("type") in ("code_execution_result", "function_result"))
    return {"code_runs": len(runs), "files_viewed": [(s.get("arguments") or {}).get("AbsolutePath") for s in looks], "results": results}


# ---------------------------------------------------------------- one panel
def compact_copy(jpeg, widths=COPY_WIDTHS):
    """A 1-bit PNG of the panel small enough to be copied into the sandbox through the prompt."""
    im = Image.open(io.BytesIO(jpeg)).convert("L")
    for w in widths:
        g = im.resize((w, max(1, round(w * im.height / im.width))), Image.LANCZOS).point(lambda v: 255 if v > 150 else 0).convert("1")
        buf = io.BytesIO()
        g.save(buf, "PNG", optimize=True)
        b64 = base64.b64encode(buf.getvalue()).decode()
        if len(b64) <= COPY_MAX_B64:
            break
    return {"b64": b64, "sha": hashlib.sha256(buf.getvalue()).hexdigest(), "width": w}


def read_panel(jpeg, key=None):
    """Blind read of one panel through the sandbox copy. If the copy cannot be proven (the hash is checked in
    the tool log) there can be more tries with a smaller copy (SANDBOX_TRIES); after that one plain look at the image with no sandbox
    work, marked via="inline" so the report says so."""
    def call():
        secs, toks, why = 0.0, 0, ""
        for attempt, widths in enumerate((COPY_WIDTHS, COPY_WIDTHS[2:], COPY_WIDTHS[3:])[:SANDBOX_TRIES]):
            cp = compact_copy(jpeg, widths)
            try:
                r = interact([gemini.text_block(PANEL_PROMPT % {"sha": cp["sha"], "small": SMALL_W, "n": len(cp["b64"]), "b64": cp["b64"]})])
                secs, toks = secs + r["seconds"], toks + (r["tokens"] or 0)
                log, ans = tool_log(r["steps"]), final_json(r["steps"])
                if cp["sha"] in log["results"] and ans.get("full"):
                    return {"via": "sandbox", "copy_width": cp["width"], "hash_ok": True, "attempts": attempt + 1,
                            "code_runs": log["code_runs"], "files_viewed": log["files_viewed"],
                            "seconds": round(secs, 1), "tokens": toks, **_fields(ans)}
                why = "hash not confirmed in the tool log" if ans.get("full") else str(ans.get("error") or "no sentence")
            except gemini.NoCredit:
                raise
            except gemini.ApiError as e:
                why = str(e)[:160]
        for attempt in range(2):                         # an empty last message was seen once; ask again
            r2 = interact([gemini.text_block(INLINE_PROMPT), gemini.image_block(jpeg)])
            secs, toks = secs + r2["seconds"], toks + (r2["tokens"] or 0)
            try:
                ans = final_json(r2["steps"])
                break
            except gemini.ApiError:
                if attempt:
                    raise
        return {"via": "inline", "fallback_reason": why, "hash_ok": False, "attempts": SANDBOX_TRIES + 1, "code_runs": 0, "files_viewed": [],
                "seconds": round(secs, 1), "tokens": toks, **_fields(ans)}
    return gemini.taped(key, call)


def _fields(ans):
    return {"small": str(ans.get("small") or "").strip(), "full": str(ans.get("full") or "").strip(),
            "objects": list(ans.get("objects") or [])[:12], "writing": str(ans.get("writing") or "").strip(),
            "crops": ans.get("crops") or 0, "unsure": str(ans.get("unsure") or "").strip()}


def read_sheet(sheet_jpeg, n, key=None):
    """Blind read of the whole numbered sheet: one sentence per panel, read in sequence."""
    def call():
        r = interact([gemini.text_block(SHEET_PROMPT % {"n": n}), gemini.image_block(sheet_jpeg)])
        ans, log = final_json(r["steps"]), tool_log(r["steps"])
        return {"task": str(ans.get("task") or ""), "steps": {str(k): str(v) for k, v in (ans.get("steps") or {}).items()},
                "order_ok": ans.get("order_ok"), "note": str(ans.get("note") or ""), "code_runs": log["code_runs"],
                "seconds": r["seconds"], "tokens": r["tokens"]}
    return gemini.taped(key, call)


# ---------------------------------------------------------------- scoring (our server, Decisions API)
def same_action(truth, blind, key=None):
    """P(the blind sentence describes the same action as the true step name). Also asks the two halves apart,
    so a miss can be told as 'wrong motion' or 'wrong thing'."""
    if not blind:
        return {"p": 0.0, "motion": 0.0, "thing": 0.0}

    def call():
        q = {"same": {"type": "noul", "instructions": "Sentence A is a step of a hands-on task. Sentence B was written by someone else about the same moment. Do A and B describe the same physical action done with or to the same thing? Different wording is fine, and so is a vaguer or an everyday-equivalent name for the same thing (a cloth for a paper towel, seasoning for herbs). Answer no if the action differs, or if the thing used or added is a different thing or is not identified at all."},
             "motion": {"type": "noul", "instructions": "Ignoring which objects are involved, do sentences A and B describe the same kind of hand motion (for example both sprinkling, both cutting, both wiping)?"},
             "thing": {"type": "noul", "instructions": "Is the main thing being used or added in sentence A the same thing as in sentence B (for example both salt, both a knife, both a paper towel)?"}}
        res = gemini.decide([gemini.text_block(f"A: {truth}\nB: {blind}")], q)
        a = res["answers"]
        return {"p": round(a["same"]["noul"], 3), "motion": round(a["motion"]["noul"], 3), "thing": round(a["thing"]["noul"], 3)}
    return gemini.taped(key, call)


# ---------------------------------------------------------------- redraw (see docs/MANAGED.md)
def redraw_panel(card, step, blind, tag):
    """Draw one panel again from its keyframe, telling the image model how the first drawing was misread.
    wordless/teach.py keeps its draw step inside build(), so this repeats that call with the same model and
    prompt through public pieces. The result is returned, not written over the card's panel."""
    from . import teach
    kf = (cards.card_dir(card["id"]) / step["keyframe"]).read_bytes()
    extra = REDRAW_HINT % {"action": step["action"], "blind": blind}

    def call():
        d = gemini.generate(config.MODELS["image"], [gemini.inline(kf, "image/jpeg"), {"text": teach.DRAW_PROMPT + extra}],
                            {"responseModalities": ["IMAGE"]})
        return cards.to_jpeg(gemini.image_of(d))
    return gemini.taped(f"blind/{card['id']}/redraw/{step['id']}{tag}", call, kind="bytes")


# ---------------------------------------------------------------- the job
def blind_read(card_id, redraw=False, apply=False, emit=None, workers=10, tag=""):
    """Run the blind reader on a card. tag keeps repeated runs apart on the tape (e.g. ".b" for a second run).
    redraw: failing panels are drawn again once and read again; apply: a redraw that now passes replaces the
    card's panel (the old one is kept as pn_<id>.before.jpg)."""
    card = cards.load(card_id)
    d = cards.card_dir(card_id)
    steps = card["steps"]
    say = emit or (lambda ev: None)
    t0 = time.time()
    k = lambda *parts: "/".join(("blind", card_id) + tuple(str(p) for p in parts)) + tag

    def panel_job(i, s, jpeg, rnd):
        try:
            r = read_panel(jpeg, key=k("panel", s["id"], f"r{rnd}"))
            sc = same_action(s["action"], r["full"], key=k("score", s["id"], f"r{rnd}"))
            sm = same_action(s["action"], r["small"], key=k("score_small", s["id"], f"r{rnd}")) if r["small"] else None
            out = {"read": r, "p": sc["p"], "motion": sc["motion"], "thing": sc["thing"], "p_small": sm["p"] if sm else None,
                   "passed": sc["p"] >= PASS_P}
        except (gemini.NoCredit, gemini.TapeMiss):
            raise
        except gemini.ApiError as e:
            out = {"read": None, "error": str(e)[:200], "p": None, "passed": False}
        say({"stage": "blind", "panel": i + 1, "step": s["id"], "round": rnd, "passed": out["passed"], "p": out["p"],
             "blind": (out["read"] or {}).get("full"), "t": round(time.time() - t0, 1)})
        return out

    with cf.ThreadPoolExecutor(workers) as ex:
        sheet_f = ex.submit(lambda: _sheet_job(card, d, k))
        first = list(ex.map(lambda a: panel_job(a[0], a[1], (d / a[1]["panel"]).read_bytes(), 0), enumerate(steps)))
        sheet = sheet_f.result()
    t_first = round(time.time() - t0, 1)

    rows = []
    for i, (s, f) in enumerate(zip(steps, first)):
        ctx = (sheet.get("scores") or {}).get(s["id"])
        rows.append({"panel": i + 1, "step": s["id"], "truth": s["action"], "blind": (f["read"] or {}).get("full"),
                     "blind_small": (f["read"] or {}).get("small"), "p": f["p"], "p_small": f.get("p_small"),
                     "motion": f.get("motion"), "thing": f.get("thing"), "passed": f["passed"], "error": f.get("error"),
                     "in_context": (sheet.get("steps") or {}).get(str(i + 1)), "p_in_context": ctx,
                     "via": (f["read"] or {}).get("via"), "writing": (f["read"] or {}).get("writing"),
                     "unsure": (f["read"] or {}).get("unsure"), "code_runs": (f["read"] or {}).get("code_runs"),
                     "files_viewed": len((f["read"] or {}).get("files_viewed") or []),
                     "agent_seconds": (f["read"] or {}).get("seconds"), "redraw": None})
    before = sum(r["passed"] for r in rows)

    if redraw:
        todo = [(i, steps[i]) for i, r in enumerate(rows) if not r["passed"] and r["blind"]]

        def fix(i, s):
            try:
                jpeg = redraw_panel(card, s, rows[i]["blind"], tag)
                letters = checker.has_letters(jpeg, key=k("letters", s["id"]))["p"]
                (d / f"pn_{s['id']}.blind.jpg").write_bytes(jpeg)
                again = panel_job(i, s, jpeg, 1)
                return {"blind": (again["read"] or {}).get("full"), "p": again["p"], "passed": again["passed"],
                        "letters_p": letters, "file": f"pn_{s['id']}.blind.jpg", "applied": False, "error": again.get("error")}
            except (gemini.NoCredit, gemini.TapeMiss):
                raise
            except gemini.ApiError as e:
                return {"blind": None, "p": None, "passed": False, "error": str(e)[:200], "applied": False}
        with cf.ThreadPoolExecutor(max(1, len(todo))) as ex:
            for (i, s), res in zip(todo, ex.map(lambda a: fix(*a), todo)):
                rows[i]["redraw"] = res
                if apply and res["passed"] and (res.get("letters_p") or 0) < 0.5:
                    (d / f"pn_{s['id']}.before.jpg").write_bytes((d / s["panel"]).read_bytes())
                    (d / s["panel"]).write_bytes((d / res["file"]).read_bytes())
                    res["applied"] = True
        if any((r["redraw"] or {}).get("applied") for r in rows):
            cards.compose_sheet(card)

    after = sum(1 for r in rows if (r["redraw"] or {}).get("passed") or r["passed"])
    out = {"card": card_id, "title": card.get("title"), "panels": len(rows), "understood": before,
           "understood_after_redraw": after if redraw else None,
           "understood_in_context": sum(1 for r in rows if (r["p_in_context"] or 0) >= PASS_P) if sheet.get("steps") else None,
           "understood_small": sum(1 for r in rows if (r["p_small"] or 0) >= PASS_P),
           "failing": [r["panel"] for r in rows if not r["passed"]],
           "sandbox_reads": sum(1 for r in rows if r["via"] == "sandbox"), "inline_reads": sum(1 for r in rows if r["via"] == "inline"),
           "seconds_first_pass": t_first, "seconds_total": round(time.time() - t0, 1),
           "sheet": {x: sheet.get(x) for x in ("task", "order_ok", "note", "seconds", "error")},
           "rows": rows, "agent": AGENT, "pass_p": PASS_P, "created": time.strftime("%Y-%m-%d %H:%M:%S")}
    config.RUNS.mkdir(parents=True, exist_ok=True)
    (config.RUNS / f"blind_{card_id}.json").write_text(json.dumps(out, indent=1))
    say({"stage": "blind", "state": "done", "understood": before, "of": len(rows), "after": out["understood_after_redraw"],
         "t": out["seconds_total"]})
    return out


def _sheet_job(card, d, k):
    """Whole-card agent. Its failure never stops the per-panel result."""
    try:
        sh = read_sheet((d / "sheet.jpg").read_bytes(), len(card["steps"]), key=k("sheet"))
        sh["scores"] = {s["id"]: same_action(s["action"], sh["steps"].get(str(i + 1), ""), key=k("score_ctx", s["id"]))["p"]
                        for i, s in enumerate(card["steps"])}
        return sh
    except (gemini.NoCredit, gemini.TapeMiss):
        raise
    except (gemini.ApiError, OSError) as e:
        return {"error": str(e)[:200]}


def table(out):
    """The result as plain text for the terminal."""
    cut = lambda s, n: (s or "-")[:n].ljust(n)
    pr = lambda p: "  -  " if p is None else f"{p:5.2f}"
    lines = [f"Blind read of card '{out['card']}': {out['understood']} of {out['panels']} panels understood without the video"
             + (f"; {out['understood_after_redraw']} of {out['panels']} after one redraw" if out["understood_after_redraw"] is not None else ""),
             f"{'#':>2}  {'':4} {'p':>5} {'small':>5} {'ctx':>5}  {cut('true step', 44)}  what the blind reader wrote"]
    for r in out["rows"]:
        lines.append(f"{r['panel']:>2}  {'PASS' if r['passed'] else 'FAIL'} {pr(r['p'])} {pr(r['p_small'])} {pr(r['p_in_context'])}  "
                     f"{cut(r['truth'], 44)}  {r['blind'] or r.get('error') or '-'}" + ("  [inline, no sandbox]" if r["via"] == "inline" else ""))
        if r["redraw"]:
            x = r["redraw"]
            lines.append(f"      redrawn: {'PASS' if x['passed'] else 'FAIL'} {pr(x['p'])}  {x.get('blind') or x.get('error') or '-'}"
                         + ("  (applied to the card)" if x.get("applied") else ""))
    lines.append(f"p = P(same action), panel alone; small = the {SMALL_W} px version; ctx = read on the whole sheet, in order.")
    if out["sheet"].get("task"):
        lines.append(f"Whole card read as: {out['sheet']['task']} (order makes sense: {out['sheet']['order_ok']})"
                     + (f". Note: {out['sheet']['note']}" if out["sheet"].get("note") else ""))
    lines.append(f"{out['sandbox_reads']} panels read through the sandbox copy, {out['inline_reads']} by a plain look. "
                 f"First pass {out['seconds_first_pass']} s, total {out['seconds_total']} s.")
    if out["failing"]:
        lines.append("Panels to redraw: " + ", ".join(str(p) for p in out["failing"]))
    return "\n".join(lines)
