# Wordless

**Do it once on camera. Your demonstration becomes the manual and the test.**

Two ways in, one idea: show it once, and the pictures both teach the next person and check them.

- **Routines** (`/`): film a hands-on routine once. Gemini turns it into a picture card with no words, drawn
  from the real keyframes. The same card then watches the next person and names the step they skipped.
- **Sequences** (`/signs`): show the camera a few poses, one photo each, and name sequences of them. The camera
  then names which fast sequence someone performed, or says which sign was wrong, missing or extra. Nothing in
  it is specific to one domain: hand signals, finger counts, hand-washing positions, positions of a tool.

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

**Sequences** (`/signs`). Plumbing tested against the fake API; on the real API one question per frame runs at
about 13 answers a second, about 1 s each. Not yet measured on people performing poses: no accuracy number is
claimed.

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

### Sequences (needs a key and a camera)

```bash
.venv/bin/python server.py
```

Open http://localhost:5119/signs.

1. Pick a preset (finger counts is the easiest first try) or name a blank kit, and press New kit.
2. "Teach all remaining": each pose gets a 3 s countdown and one photo. A line drawing of each pose is made
   in the background.
3. Name a sequence, click poses in order, save. Presets add their sequences once their poses are taught.
4. Start, perform a sequence, pause. The strip fills in as poses are recognised and the verdict names the
   sequence. "Check someone doing it" watches one chosen sequence and marks each sign; "Show the steps" opens
   the printable wordless strip.

A routine card can also be opened as a kit ("from routine: ..." in the preset list), which checks it frame by
frame instead of in 2 s windows. Camera previews are mirrored on screen only; frames sent to the models are not
flipped.

## Tests

```bash
.venv/bin/python -m pytest -q
```

- `test_tracker.py`: the verdict rule.
- `test_whole_clip_review.py`: the review rule that combines the card with the one whole-clip call.
- `test_signs.py`: the sequence decoder, and kits, sessions and the HTTP path against the fake.
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
| sequences | `gemini-decision-1` | `/signs`: reference sheet plus one frame, several a second: which pose? Code decodes the sequence and names it. |

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
wordless/decode.py         sequences: frame answers -> signs -> which known sequence
wordless/signs.py          sequences: kits, the per-frame question, sessions, clip scoring
wordless/signs_routes.py   routes for /signs
wordless/managed.py        blind reader on Managed Agents (see docs/MANAGED.md)
wordless/evalrun.py        eval on labelled recordings
wordless/table.py          table prep: test clips with an answer key, the table gate
server.py                  Flask server, demo shell (clock, deadline, baseline, QR, recorded runs)
web/                       index.html (Routines), signs.html (Sequences), wordless.css, fonts, logo
scripts/eval_wide.py       the 16-recording eval; eval_rules.py re-scores verdict rules without the API
scripts/fetch_captaincook.py   downloads the public recordings and labels
fixtures/tomato/           answers recorded against the real API
fixtures/eval_wide/        per-recording answers behind docs/EVAL.md
fixtures/sequence_presets.json   example kits for /signs
docs/                      EVAL.md, MANAGED.md, SUBMISSION.md, VIDEO.md, LICENCES.md, ui/ screenshots
tests/                     tests and the fake API
```

## Managed Agents (experimental, not on the demo path)

`python scripts/blind_read.py <card_id>` starts one managed agent per panel. Each sees only the panel image,
never the video or the step names, and writes what the panel tells a person to do; the Decisions API then
scores that sentence against the true step. On the tomato card it scored 7, 7 and 5 of 9 panels over three
runs, at 2.5 to 6 minutes a run: too noisy and too slow to rely on. Details in [docs/MANAGED.md](docs/MANAGED.md).

## Known gaps

- Neither mode has been run with a person at a camera at a table yet. All routine numbers come from recorded
  footage; sequences have no accuracy number.
- The whole-clip review needs the whole clip, so the final routine verdict arrives some seconds after the
  person stops (capped at 45 s; if the review does not answer, the card's own verdict is shown and says so).
- The review rule was chosen after seeing all 16 eval recordings; it has not been confirmed on fresh ones.
- Look-alike steps (several "tip a small container" steps) are what the card confuses. The review hides this
  in the verdict; the live panel-by-panel view can still light the wrong look-alike panel.
- Routine steps of 4 to 5 s give two or three windows; hold each step about 8 s, or open the card as a
  sequence kit for the frame-by-frame path (not yet measured on recordings).
- Sequences: poses must be holdable for about half a second and look different from each other. Sub-second
  flicks and poses that differ only in small finger detail are expected to fail; a repeated pose needs a pause.
- Order errors in routines are unreliable and not claimed.
- The end-state second vote exists as a question (`checker.end_state`) but is not wired into the verdict.
- Preset sequences are examples written from memory; check them before relying on them.

## Third-party material

Fixtures under `fixtures/tomato/` and `fixtures/eval_wide/` are derived from the CaptainCook4D dataset (Peddi et
al., NeurIPS 2024 Datasets and Benchmarks, https://aria-research-lab.github.io/projects/CaptainCook4D), licensed
under the Apache License 2.0 per the dataset's project page. We use step labels, a small number of video frames
and recorded model answers, modified from the originals. Other licences: [docs/LICENCES.md](docs/LICENCES.md).
