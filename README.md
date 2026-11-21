# Wordless

**Do it once on camera. Your demonstration becomes the manual and the test.**

Show it once on camera: any hands-on routine, at any speed, with any number of steps, from a slow kitchen
task to a quick series of hand signs. Nobody names the steps or says how many there are. Gemini finds them,
draws each one as a panel with no words, and the card then watches the next person frame by frame and says
which step never happened, which was something else, and what was extra.

Gemini 4 NYC Hackathon, Nov 21 2026 (Element 119).

## State of the evidence

Full tables, per recording, in [docs/EVAL.md](docs/EVAL.md). Numbers below can be re-computed without the API:
`python scripts/eval_rules.py` (reads `fixtures/eval_wide`).

**Routines.** Card taught from CaptainCook4D recording 12_17, scored on the 16 other recordings of the same
recipe (5 people, 6 kitchens; 12 of them never scored before the eval). Answer key: the dataset's human labels.

| Method | False "never happened" (of 138 performed steps) | Skipped steps flagged (of 6) | "Not sure" on performed steps | Verdict fully right (of 16) |
|---|---|---|---|---|
| Card checker alone (what we started with) | 17 | 5 | 6 | 3 |
| One Hydrogen call on the whole clip (baseline) | 12 | 6 | 0 | 13 |
| **Card + whole-clip review (what ships now)** | **4** | 5 | 8 | 13 |

- **Where the first version broke.** The card checker alone reported a performed step as "never happened" in 11
  of 16 recordings. Pepper, salt, herbs and oil are all "a hand tips a small container over the plate"; the
  pepper panel absorbed the others (herbs windows were labelled correctly 31% of the time).
- **What we changed.** Every verdict now gets one whole-clip review by Hydrogen. It decides "never happened";
  the card can only turn that into "not sure" (`wordless/follow.py`, `apply_review`). The card still gives the
  live panel-by-panel view while the person works.
- **What that does and does not show.** False alarms drop from 17 (card) and 12 (baseline) to 4. Whole
  verdicts are right as often as the baseline (13 of 16), not more often. The rule was chosen after seeing all
  16 recordings, so it needs fresh recordings to be confirmed. One real skip (a tomato held at the sink but not
  rinsed) is reported as "not sure", not flagged.
- **Order errors** are unreliable (6 false reports on one recording). Only skipped steps are claimed.
- **Short steps** (under about 4 s) give one or two windows and cannot reach the cut-off on the card alone.

**Fast path (what the page uses now).** Teaching and checking run on single frames, five a second, instead
of 2 s windows. On a 25 s slice of real footage it built a 4-step card in 75 s, found a step 1.6 s long, and the
card recognised 4 of 4 steps in its own clip; fed back through the live route with one step cut out, it reported
that step as never happened. That is one clip, the same person and kitchen: a smoke test, not an accuracy
number. Answer time was 1.6 s per frame on a quiet key and up to 8 s when other jobs shared it. The 16-recording
numbers above are for the 2 s window card with review, which older cards still use.

**Not yet run:** a routine taught and followed from a webcam at a table; the table gate on real clips.

## Run it (no key needed)

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
```

```bash
.venv/bin/python scripts/import_tomato_fixture.py
```

```bash
WORDLESS_TAPE=replay .venv/bin/python server.py
```

Open http://localhost:5119.

- **Follow**: pick recording 12_43 and press Start. Panels turn green as steps are seen; the verdict names
  panels 6 to 9 as never happened. 12_10 is the clean run.
- **Teach**: "Rebuild the tomato card from recorded answers" replays the build stages.
- **Proof**: "Run the eval" fills the three-column table from the recorded answers.

Videos play next to the card when the recordings are in `data/` as `<id>.mp4`; the replay works without them.

On the Follow tab the status line shows LIVE or REPLAY, the input, the number of questions and the last call's
seconds. A run has a clock and a hard deadline (default 90 s): a stalled call cannot hang the page. For a file
recording the one-call baseline runs beside ours and both verdicts are shown. `R` plays a labelled recorded
run with the network off. After a verdict, "Keep the card" shows a QR code to the printable card; a phone
needs `WORDLESS_PUBLIC_URL` (default: this machine's LAN address).

### Live (needs a key and a camera)

```bash
.venv/bin/python server.py
```

Open http://localhost:5119.

1. **Show it once**: record the routine from the camera, or drop a clip. Any length, any number of steps.
   The card builds itself (about a minute for a 25 s clip).
2. **Check someone**: press Start and do the routine. Panels light up in order; when the person stops, the
   verdict names what was missed, wrong or extra. A step needs to be held for about half a second.

Camera previews are mirrored on screen only; frames sent to the models are not flipped. Cards built before the
fast path (the tomato card) are still checked in 2 s windows with the whole-clip review.

## Tests

```bash
.venv/bin/python -m pytest -q
```

- `test_tracker.py`: the verdict rule.
- `test_whole_clip_review.py`: the review rule that combines the card with the one whole-clip call.
- `test_fast.py`: one clip in (a repeated step included), a card out, then clean, skipped, wrong and extra runs.
- `test_signs.py`: the frame decoder and frame-by-frame sessions against the fake.
- `test_shell.py`: clock, deadline, status line, baseline beside ours, QR card, recorded-run playback.
- `test_managed.py`: the blind reader against a fake.
- `test_replay_tomato.py`: the recorded real answers still give the reported numbers.
- `test_table_prep.py`: clip recording, print pages and the table gate, against the fake.
- `test_live_path_against_fake.py`: teach, follow from files, follow from stills over HTTP, back-fill,
  tally and baseline, all against `tests/fake_gemini.py`. The fake speaks the measured request and response
  shapes and "sees" by colour. It proves the plumbing, not the models.

## Going live

1. Put the key in `.env` (`GEMINI_API_KEY=...`).
2. Held-out recordings (about 800 Decisions calls and two Hydrogen calls):

```bash
scripts/gate.sh
```

3. Start the server without `WORDLESS_TAPE` (default `auto`: recorded answers where they exist, the API
   otherwise). Teach from the camera or a file, then follow with "Live camera".
4. Table gate: record a teaching run and three follow runs (one clean, two skipping a different step) in
   the Prep tab, then:

```bash
.venv/bin/python scripts/table_gate.py
```

   Pass: every verdict right, no false "never happened", clip to card in 40 s or less.

Every live session saves its stills and answers under `runs/<id>/` and appears in the source list as a
recording, so a session filmed at the table can be replayed if the network fails.

## How it works

| Stage | Model | Job |
|---|---|---|
| name | `gemini-4-hydrogen` | Watches the teaching clip, names the steps. Never asked for timestamps (they drift). |
| locate | `gemini-decision-1` | Labels every 2 s window; code picks each step's keyframe. |
| plan | `gemini-4-argon` | Marks setup steps, must-come-before links, end-state questions. |
| draw | `gemini-3.1-flash-lite-image` | Keyframe to line-art panel, all panels in parallel. |
| letters | `gemini-decision-1` | Rejects panels with writing; redraws up to twice, then reports the panel. |
| selftest | `gemini-decision-1` | The card must recognise each step in its own teaching clip; sets per-panel cut-offs. |
| follow | `gemini-decision-1` | Card image plus a clip or two stills: which panel is this? Once a second. |
| verdict | code | Heaviest-run rule in `wordless/tracker.py`. Seen, never happened, or not sure. |
| review | `gemini-4-hydrogen` | One call on the whole clip (or the session's saved stills) checks the verdict: it decides "never happened"; the card can only make that "not sure". |
| fast teach | `gemini-4-hydrogen`, `gemini-decision-1`, image model | Hydrogen lists the distinct steps it sees; the Decisions API labels every frame; code finds the steps in order and their clearest frames; the image model draws them. |
| fast follow | `gemini-decision-1` | Reference sheet plus one camera frame, five a second: which step? Code lines the answers up against the card. |

The verdict is computed from every buffered window when the follower is done. Windows whose call failed or
is still in flight are asked again first (up to 10 s). A window that stays unanswered is listed in the
verdict, and a step it could be hiding is reported as "not sure", never as "never happened". Panels turning
green during the task are display only.

Tuned numbers live in `wordless/config.py`. They were frozen on recordings 12_10 and 12_43, so those two
count as development data, not as a test.

## Layout

```
wordless/gemini.py         REST client + tape (record / replay of every answer)
wordless/teach.py          teaching clip -> card
wordless/checker.py        the questions put to the Decisions API
wordless/tracker.py        presence and order rule, verdict
wordless/follow.py         live and replay sessions; whole-clip review of the verdict
wordless/baseline.py       one Hydrogen call on the whole clip
wordless/fast.py           the fast path: one clip -> card with any number of steps; frame-by-frame follow
wordless/decode.py         frame answers -> steps performed -> lined up against the card
wordless/signs.py          reference sheet, the per-frame question, frame sessions
wordless/managed.py        blind reader on Managed Agents (see docs/MANAGED.md)
wordless/evalrun.py        eval on labelled recordings
wordless/table.py          table prep: test clips with an answer key, the table gate
server.py                  Flask server, demo shell (clock, deadline, baseline, QR, recorded runs)
web/                       index.html, wordless.css, fonts, logo
scripts/eval_wide.py       the 16-recording eval; eval_rules.py re-scores verdict rules without the API
scripts/fetch_captaincook.py   downloads the public recordings and labels
fixtures/tomato/           answers recorded against the real API
fixtures/eval_wide/        per-recording answers behind docs/EVAL.md
docs/                      EVAL.md, MANAGED.md, SUBMISSION.md, VIDEO.md, LICENCES.md, ui/ screenshots
tests/                     tests and the fake API
```

## Managed Agents (experimental, not on the demo path)

`python scripts/blind_read.py <card_id>` starts one managed agent per panel. Each sees only the panel image,
never the video or the step names, and writes what the panel tells a person to do; the Decisions API then
scores that sentence against the true step. On the tomato card it scored 7, 7 and 5 of 9 panels over three
runs, at 2.5 to 6 minutes a run: too noisy and too slow to rely on. Details in [docs/MANAGED.md](docs/MANAGED.md).

## Known gaps

- Not yet run with a person at a camera at a table. The fast path has only a one-clip smoke test; its accuracy
  on other people is unmeasured.
- Fast path: a step must be held about half a second and look different from the others. Two identical steps
  in a row need a visible pause between them, and when one of two identical steps is missed the verdict may
  name the wrong one of the pair. Steps the model named but could not find in the frames are left off the card.
- Fast path: answer time depends on API load (1.6 s to 8 s per frame measured); slow answers delay the lights,
  not the verdict.
- Teaching takes about a minute for a 25 s clip; most of it is Hydrogen naming the steps and the self-test.
- Older 2 s window cards: the whole-clip review was chosen after seeing all 16 eval recordings and is not
  confirmed on fresh ones; look-alike steps still light the wrong panel live; order errors are not claimed.
- The end-state second vote exists as a question (`checker.end_state`) but is not wired into the verdict.

## Licence

The code is under the MIT License: see [LICENSE](LICENSE). Material derived from third parties keeps its own terms:


Fixtures under `fixtures/tomato/` and `fixtures/eval_wide/` are derived from the CaptainCook4D dataset (Peddi et
al., NeurIPS 2024 Datasets and Benchmarks, https://aria-research-lab.github.io/projects/CaptainCook4D), licensed
under the Apache License 2.0 per the dataset's project page. We use step labels, a small number of video frames
and recorded model answers, modified from the originals. Other licences: [docs/LICENCES.md](docs/LICENCES.md).
