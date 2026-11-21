# Wordless

**Do it once on camera. Your demonstration becomes the manual and the test.**

Show it once on camera: any hands-on routine, at any speed, with any number of steps, from a slow kitchen
task to a quick series of hand signs. Nobody names the steps or says how many there are. Gemini finds them,
draws each one as a panel with no words, and the card then watches the next person frame by frame and says
which step never happened, which was something else, and what was extra.

Gemini 4 NYC Hackathon, Nov 21 2026 (Element 119).

## Who it is for

Anyone who has to pass on a hands-on routine without relying on written instructions:

- a trainer and a new hire who do not share a language, at a prep station, a packing bench or a workshop
- a lab or a makerspace, where a setup or shutdown sequence has to be done the same way by everyone
- a carer or family member showing someone how to use a device or follow a daily routine
- a teacher of signs, knots, folds or any other sequence of hand movements

One person films the routine once. The next person gets a card with no words on it and can check themselves
against it. Wordless is a tested instruction sheet, not a coach: it says which step did not happen, not how
well a step was done.

## What was built at the event

Everything in this repository was written and done during the Gemini 4 NYC Hackathon on Nov 21 2026. The first
commit is at 11:11 AM that day and the git history covers the whole build.

- **Built today, by the two of us:** all of `wordless/` (teaching, following, the frame decoder, the verdict
  rules), `server.py`, the page in `web/`, `tests/`, `scripts/`, the docs, the cards in `cards/`, and the
  recorded API answers in `tape/` and `fixtures/`. The 16-recording eval was run today.
- **Not ours:** the CaptainCook4D footage and human labels the eval is scored against (a public dataset, see
  [docs/LICENCES.md](docs/LICENCES.md)), the Gemini models, and the libraries in `requirements.txt`.
- Some comments mention `research/feasibility/...`. That was a scratch folder of API experiments run today at
  the venue to learn the request and response shapes; it is not part of this repository.

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

**The flow the page runs now** (frame by frame, eight frames a second).

- **Run live at a camera by the team throughout the build,** on table routines and hand signs. Each counted
  trial (what the person really did, our verdict, and the one-call baseline on the same run) is logged with the
  buttons under the verdict and shown on the Proof tab; that tally lives on the machine that ran the trials.
- **Six named, six on the card.** On generated six-sign clips at 1.6, 0.8 and 0.45 s per sign, every step the
  model named was placed on the card, and the card recognised 6 of 6 in its own clip.
- **Checking speed.** The same clips followed live through the server: all six signs seen at each speed, about
  0.55 s per answer.
- **Skips.** With the third or the fifth sign cut out, the verdict named that step, and the live alert announced
  it during the run, about 2 s after the next sign began. Clean runs at all three speeds raised no alert.
- **The live alert under stress** (`tests/test_live_alert.py`, no API): 100 randomized clean runs with answers
  arriving out of order, 60 of them with one frame in eight misread, gave no false alert; 40 randomized real
  skips were always announced, and only the skipped step.
- **Models.** Carbon names the steps (11 to 23 s) and separated more steps than Hydrogen did. `gemini-3-pro-image`
  draws the panels; the lite image model had added a hand that was not in the photo. Teaching a 6 to 15 s clip
  takes 30 to 40 s. Asked to judge a whole run alone, Carbon, Neon and Hydrogen each took 16 to 50 s and missed a
  1.2 s step the frame answers caught, so Hydrogen is used as a second vote on flagged steps, not as the judge.

The generated clips are clean, distinct poses held still. They show the mechanism works, not how it does on
look-alike signs. The 16-recording numbers above are for the older 2 s window method.

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
| name | `gemini-4-carbon` (Gemini 4) | Watches the teaching clip once and lists the distinct steps and the order performed. A short clip is slowed first so quick poses are visible. Hydrogen is the fallback if Carbon does not answer. |
| locate | `gemini-decision-1` (Decisions API) | Labels every teaching frame, ten a second; code places each named step and picks its clearest frame. A named step is never dropped. |
| draw | `gemini-3-pro-image` | Redraws each clearest frame as a line-art panel: only the hands and objects that carry the step, no portrait. |
| selftest | `gemini-decision-1` | The finished card follows its own teaching clip. |
| follow | `gemini-decision-1` | Reference sheet plus one camera frame, several a second: which step? Code lines the answers up against the card (`wordless/decode.py`). A low-movement step that reads as a pause is kept when one step stays the best guess for a second. |
| second vote | `gemini-4-hydrogen` (Gemini 4) | One call on the whole run once it is over. "Never happened" stands only when the frames and Hydrogen both say so; a flagged step Hydrogen saw performed becomes "not sure". It cannot un-see a step the frames saw, so a clean run never waits for it. The same call is shown beside our verdict as the baseline. |

The two Gemini 4 models are Carbon (teaches) and Hydrogen (confirms). The second vote, the low-movement rule
and the hands-only drawing were added on Nov 21 and are tested against the fake API only
(`tests/test_fast.py`, `tests/test_signs.py`); none has been measured on real footage yet.

Cards built before this flow (the tomato card behind the 16-recording eval) are checked in 2 s windows with a
whole-clip review; that method and its numbers are in [docs/EVAL.md](docs/EVAL.md). Its tuned numbers live in
`wordless/config.py` and were frozen on recordings 12_10 and 12_43, so those two count as development data,
not as a test.

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

- A step must be held about half a second and look different from the others. Two identical steps in a row
  need a visible pause between them, and when one of two identical steps is missed the verdict may name the
  wrong one of the pair.
- A step the model named is always placed on the card, even when the frames show it weakly, so a weak step can
  get a poor reference picture.
- Look-alike steps are the known weak point: if one is confidently read as another for several frames, the
  verdict, and the live alert with it, can be wrong.
- The live alert stays silent when it is not sure (answers still in flight, weak evidence, the same picture on
  both sides of a gap); the end-of-run verdict still reports the step.
- Answer time depends on API load: about 0.55 s per frame on a quiet key, several seconds on a busy one. Slow
  answers delay the lights and the alert, not the verdict.
- It checks that each step happened and in what order, not how well it was done.
- Older 2 s window cards: the whole-clip review was chosen after seeing all 16 eval recordings and is not
  confirmed on fresh ones; order errors are not claimed there.

## Licence

The code is under the MIT License: see [LICENSE](LICENSE). Material derived from third parties keeps its own terms:


Fixtures under `fixtures/tomato/` and `fixtures/eval_wide/` are derived from the CaptainCook4D dataset (Peddi et
al., NeurIPS 2024 Datasets and Benchmarks, https://aria-research-lab.github.io/projects/CaptainCook4D), licensed
under the Apache License 2.0 per the dataset's project page. We use step labels, a small number of video frames
and recorded model answers, modified from the originals. Other licences: [docs/LICENCES.md](docs/LICENCES.md).
