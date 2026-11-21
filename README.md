# Wordless

**Do it once on camera. Your demonstration becomes the manual and the test.**

Film a hands-on routine once. Gemini turns it into a picture card with no words, drawn from the real
keyframes. The same card then watches the next person and names the step they skipped.

Gemini 4 NYC Hackathon, Nov 21 2026 (Element 119).

## State of the evidence

Card taught from CaptainCook4D recording 12_17; checked on other people in other kitchens. Small samples.

| Part | State |
|---|---|
| Card checker, development recordings (the verdict rule was tuned on these two) | Measured: 12_10 clean run 9/9 steps found, 0 false alarms; 12_43 4/4 skipped steps flagged, 0 false alarms. |
| Card checker, first recording never used for tuning (12_26, oil skipped) | the skipped step flagged, 0 false "never happened", 1 "not sure". |
| Card checker, off-script recording (12_41: nothing skipped, ingredients swapped, different order) | **2 false "never happened"**, 2 "not sure", 5/9 done steps found. This is where it breaks. |
| Live camera path (two stills, one question every 2 s), fed from recorded footage | 12_10 9/9 found; 12_43 4/4 skips flagged; 12_26 skip flagged, 1 "not sure". 0 false "never happened" on all three. About 0.5 s per question at real cadence. Not yet run from a webcam at a table. |
| One Hydrogen call on the whole clip (baseline) | ties the card on 12_10, 12_43 and 12_26 (cleaner on 12_26: no "not sure"); on 12_41 it gives 6 false "never happened" against the card's 2. The card's edge is answering during the task, not accuracy on on-script runs. |
| Text-only checker (no card image) | 12_43: 4/4 flagged plus 2 false alarms under the frozen rule. 12_26 same as the card; 12_41 1 false "never happened", 4 "not sure". |
| Teach pipeline as one program | all stages ran on the real API on the 4-minute clip 12_17: 10 panels in 126 s; the card recognised 8 of its own 10 steps. Not yet timed on a short table clip. |
| Answer stability | re-asking 12_43 gave the same label on 85 of 100 windows as an earlier run; one short step dropped from 2.07 to 0.89 and flipped to a false "never happened". Short steps are fragile. |
| Order errors | Unreliable: 6 false order reports on 12_26. Claim skip detection only. |
| Table gate (own routine, own camera) | Tooling built and tested against the fake API. Not yet run on real clips. |

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
