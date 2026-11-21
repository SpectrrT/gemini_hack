# Blind reader (Managed Agents)

Question it answers: can a person understand this card without ever seeing the video?

```bash
.venv/bin/python scripts/blind_read.py tomato
```

```bash
.venv/bin/python scripts/blind_read.py tomato --redraw
```

`--apply` lets a redraw that now passes replace the card's panel (the old one is kept as
`pn_<id>.before.jpg`). `--fresh` ignores recorded answers. `--tag .b` keeps a repeat run apart on the tape.
The result is printed and written to `runs/blind_<card_id>.json`. Code: `wordless/managed.py`.

## What happens

1. One managed agent per panel, all in parallel, plus one agent for the whole numbered sheet
   (`POST /v1beta/interactions`, agent `antigravity-preview-09-2026`, `environment: "remote"`).
   An agent gets pictures only. It never gets the video, the keyframe photo or the step names
   (a test checks the requests for this).
2. Each panel agent writes one sentence: what the panel tells a person to do.
3. Our server asks the Decisions API, for each panel: do the true step name and the blind sentence describe
   the same action? The answer is a probability. 0.5 or more is a pass. Two extra questions (same motion,
   same thing) say why a panel missed.
4. Score: panels understood out of N. Failing panels are the ones to redraw.
5. With `--redraw`, each failing panel is drawn once more from its keyframe, with the misreading added to
   the drawing prompt, checked for writing, and read blind again.

The Decisions API is called from our server. The sandbox's own key is a placeholder.

## What the sandbox does, and what it does not

Measured on Nov 21 before building:

| Fact | Result |
|---|---|
| An image block sent to the agent | The model sees it. It is not a file in the sandbox. Code cannot open it. |
| Image by Files API URI | Same: not on disk. |
| `files` on `environment`, `name` on an image block | HTTP 400, unknown parameter. |
| Sandbox network | `pip install pillow` works, `curl` gets HTTP 200. No route to our local server. |
| Agent tools | bash, `view_file` (the model can look at an image file it made), file write, search, browse. |
| Base64 through the prompt, hash checked | 5,900 characters copied exactly (2 of 2). 10,120 characters: wrong hash. |

So the only way to give sandbox code a panel is a small copy passed as text. The panel agent gets a 1-bit
PNG, 512 pixels wide or less (at most 6,000 base64 characters), and no image block. In the sandbox it:

- writes the copy to disk and runs `sha256sum`; our server looks for the right hash in the tool log, not in
  the agent's own words;
- shrinks the panel to 160 pixels wide with Pillow and looks at that first;
- enlarges it, and crops and enlarges regions it is unsure about, looking at each crop.

Every file it looked at is in the step log, so the blindness can be audited. A 512-pixel copy is larger
than a panel on the printed sheet (400 pixels), and side by side it shows the same lines as the original.

Honest view: the sandbox is not needed for the reading itself. A plain model call on the panel image gives
a sentence too, and our server could do the shrinking. The sandbox is used because it is the only place
the agent's own code can touch the picture, and getting the picture there costs most of the time.
If the copy cannot be proven (wrong hash, or no answer), the agent takes one plain look at the full image
with no sandbox work; the table marks that panel `[inline, no sandbox]`.

## Measured on the tomato card (9 panels), real API, Nov 21

| Run | Understood | After one redraw | Failing panels | Through sandbox | First pass | Total |
|---|---|---|---|---|---|---|
| A | 7 of 9 | 7 of 9 | 1, 6 | 7 | 143 s | 250 s |
| B | 7 of 9 | 8 of 9 | 4, 8 | 9 | 350 s | 431 s |
| C | 5 of 9 | 6 of 9 | 1, 2, 6, 8 | 6 | 188 s | 283 s |

Run A's total is the first pass plus the 109 s redraw pass, which ran separately. Run B allowed a second
sandbox try per panel; the code now allows one try and 180 s per agent (run C).

One panel agent through the sandbox: 67 to 99 s when the copy works first time. A plain look: about 8 s.

What the runs agree on:

- The whole-sheet agent always read the card as seasoned tomato slices with cheese and a dressing, in a
  sensible order, and always said panels 5, 6 and 7 (pepper, salt, herbs) look alike.
- Panel 6 (salt) failed in 2 of 3 runs: the reader sees powder going onto a spoon, not onto the tomatoes.
- Panel 1 (rinse) failed in 2 of 3 runs: the drawing shows a tap and no water.
- The reader found writing that the letters gate let through: "grind" on the grinder in panel 5 and
  "meese" on the cheese bag in panel 8.
- Panels are mostly understood better on the sheet than alone (column `ctx`).

## Limits

- The score is not stable. Three runs gave 7, 7 and 5 of 9, and which panels fail changes from run to run.
  Do not quote one run as the card's score.
- The judge is part of the noise. "Pour shredded cheese from the bag onto the plate of tomatoes" scored
  0.87 against the mozzarella step; "…onto the salad plate" scored 0.18. Several passes sit at 0.52 to 0.59.
- The judge's wording was changed once after the first run (a cloth for a paper towel now counts as the
  same thing). That was tuned on this card.
- Redraw helped 1 panel in run B, 1 in run C and 0 in run A, out of 8 redraws in total. Not a reliable gain.
- The 160-pixel reading (column `small`) fails on almost every panel. A 1-bit copy shrunk that far is
  harsher than a real small print, so this column says little.
- Slow: 2.5 to 6 minutes for the first pass, because the slowest agent sets the time. Not usable live in
  a demo; use the recorded run (`WORDLESS_TAPE=replay`).
- One card, three runs. No human has checked the blind sentences against real readers.

## Redrawing one panel: what `wordless/teach.py` would need

`teach.py` has no function that redraws one panel of a finished card. Its `draw()` and `keyframe()` are
closures inside `build()`. `managed.redraw_panel()` therefore repeats the same call (same model, same
`DRAW_PROMPT`, the saved `kf_<id>.jpg`) through public pieces. To make it one code path, move the draw call
out of `build()`:

```python
def redraw_panel(card, sid, extra="", key=None):
    """Draw one panel of a finished card again from its saved keyframe. Returns JPEG bytes."""
    kf = (cards.card_dir(card["id"]) / f"kf_{sid}.jpg").read_bytes()
    def call():
        d = gemini.generate(config.MODELS["image"], [gemini.inline(kf, "image/jpeg"), {"text": DRAW_PROMPT + extra}],
                            {"responseModalities": ["IMAGE"]})
        return cards.to_jpeg(gemini.image_of(d))
    return gemini.taped(key, call, kind="bytes")
```

`build()`'s inner `draw()` would call it, and `managed.py` would drop its own copy.

## Lines for `server.py`

Checked with Flask's test client against the recorded run. Add `managed` to the `from wordless import …`
line, then:

```python
@app.post("/api/cards/<cid>/blind")
def blind_start(cid):
    """Managed agents read the card blind. JSON body (optional): {"redraw": true, "apply": false}."""
    try:
        cards.load(cid)
    except FileNotFoundError:
        abort(404)
    body = request.get_json(silent=True) or {}
    jid = uuid.uuid4().hex[:8]
    job = jobs[jid] = {"id": jid, "events": [], "done": False, "card": cid, "error": None, "result": None}

    def run():
        try:
            job["result"] = managed.blind_read(cid, redraw=bool(body.get("redraw")), apply=bool(body.get("apply")),
                                               emit=job["events"].append)
        except Exception as e:
            job["error"] = f"{type(e).__name__}: {e}"[:300]
        job["done"] = True
    threading.Thread(target=run, daemon=True).start()
    return jsonify({"job": jid})
```

In `job_state`, add `"result"` to the returned keys (`j.get("result")`), so `GET /api/jobs/<job>` carries
the table. Each event is `{"stage": "blind", "panel": n, "passed": bool, "p": float, "blind": "<sentence>"}`;
the result has `understood`, `panels`, `understood_after_redraw`, `failing` and `rows`.

For an offline demo, copy `tape/blind/tomato/` next to the other recorded answers; the route then answers
from the tape in under a second.

## Tests

```bash
.venv/bin/python -m pytest -q tests/test_managed.py
```

Nine tests against a local fake of the Interactions and Decisions APIs. They cover the plumbing, the hash
check, the fall-back, the redraw and the replay. They say nothing about how well the real agent reads.
