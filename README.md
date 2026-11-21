# Wordless

**Do it once on camera. Your demonstration becomes the manual and the test.**

Film a hands-on routine once. Gemini turns it into a picture card with no words, drawn from the real
keyframes. The same card then watches the next person and names the step they skipped.

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

## Tests

```bash
.venv/bin/python -m pytest -q
```

- `test_tracker.py`: the verdict rule.
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
wordless/gemini.py    REST client + tape (record / replay of every answer)
wordless/teach.py     teaching clip -> card
wordless/checker.py   the questions put to the Decisions API
wordless/tracker.py   presence and order rule, verdict
wordless/follow.py    live and replay sessions
wordless/baseline.py  one Hydrogen call on the whole clip
wordless/evalrun.py   eval on labelled recordings
server.py, web/       Flask server and the single-page UI
fixtures/tomato/      answers recorded against the real API
tests/                tests and the fake API
wordless/table.py     table prep: test clips with an answer key, the table gate
```

## Known gaps

- Kit steps of 4 to 5 s give two or three windows; a correct step then scores close to the 1.6 cut-off.
  Hold each step about 8 s (the pace bar under the video fills in 8 s) and test per-panel cut-offs in G2.
- The teaching locate step was weak on look-alike steps: herbs scored 0.56 in the tomato teaching clip.
- Live sends one question per 2 s (the measured protocol). Overlapping windows at 2 to 3 calls a second would
  give more evidence per step but need re-tuned cut-offs; not built.
- The end-state second vote exists as a question (`checker.end_state`) but is not wired into the verdict.
- The text-only column is not computed for live table trials, only for file recordings.
