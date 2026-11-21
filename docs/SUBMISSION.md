# Submission pack

Draft for the Gemini 4 NYC Hackathon, Nov 21 2026. Every number is tagged `[R:<row>]` = taken from the
"State of the evidence" table in `README.md` (commit 5395083), or `[R:how]` = README "How it works".
**At 15:30 when numbers freeze, search this file for `[R:` and re-check each against the README.**
Planned `docs/EVAL.md` numbers (wide eval) should replace the four-recording figures if they land.

> Source note: `DEMO-KIT.md` and `JUDGES.md` are gone from this machine; the spec was relayed by the main
> session in a message (description order, video rules, the five Q&A questions, the hygiene list, judging
> weights 35/25/20/20). Sections 3 and 5 below follow that relayed spec.

## 1. Description, short (about 300 characters)

> Film a hands-on routine once and Wordless turns it into a wordless picture card; the same card then
> watches the next person and names the step they skipped. Gemini 4 Hydrogen names the steps, the Decisions
> API finds them. On four recordings every skipped step was flagged; off-script cooking breaks it.

(about 300 characters; recount after any edit)

## 2. Description, long

**Film a routine once, and Wordless turns that single demonstration into a wordless picture card, then uses the
same card to name the step the next person skipped.** It is a tested instruction sheet: the card is the manual
and the test, drawn from your own footage, with no words to translate or skim past.

**Element 119.** The product only works because Gemini 4 can look at video and then generate media: it
watches a demonstration, and the image model draws each step as line art from the real keyframes. Nothing
here is a text description of a text description. (It does not use audio; we do not claim hearing.)

**Which model does which job** `[R:how]`

- `gemini-4-hydrogen` watches the teaching clip and names the steps (never asked for timestamps; they drift).
- `gemini-decision-1` (Decisions API) labels every 2 s window of the teaching clip to find each step's keyframe,
  rejects drawn panels that contain writing, runs the self-test, and, while someone works, answers once a
  second which panel the camera is looking at.
- `gemini-4-argon` plans: which steps are setup, which must come before which, and the end-state questions.
- `gemini-3.1-flash-lite-image` draws each keyframe as a line-art panel (this one is not a Gemini 4 model).
- The verdict (seen, never happened, not sure) is plain code, the heaviest-run rule in `wordless/tracker.py`.

**Does it work? Small samples, reported as such.** The card was taught from CaptainCook4D recording 12_17 and
checked on other people in other kitchens `[R:intro]`. On a clean run (12_10) it found 9 of 9 steps with 0
false alarms; on a run with four skipped steps (12_43) it flagged 4 of 4 with 0 false alarms `[R:card dev]`.
Those two are development data (the rule was tuned on them). On a recording never used for tuning (12_26, oil
skipped) it flagged the skipped step with 0 false "never happened" and one "not sure" `[R:12_26]`. N = 4
checking recordings, 1 teaching recording; source: `README.md` "State of the evidence", re-runnable with
`scripts/gate.sh` and the replay tests.

**Named failure.** On an off-script recording (12_41: nothing skipped, ingredients swapped, different order)
the card said 2 steps "never happened" when they had, with 2 more "not sure" and only 5 of 9 done steps
found `[R:12_41]`. It also cannot be trusted on order errors (6 false order reports on 12_26 `[R:order]`), so
we claim skip detection only. And one Hydrogen call on the whole clip matches the card's accuracy on
on-script runs `[R:baseline]`: the card's edge is that it answers during the task, not that it is more accurate.

**Live camera path.** Two stills every 2 s fed from recorded footage gave the same skip results with 0 false
"never happened" on all three recordings, about 0.5 s per question `[R:live]`. It has not yet been run from a
webcam at a table `[R:table gate]` (update if the table gate has run by 16:00).

**Honesty about the demo.** Videos shown in the replay are recorded API answers replayed through the real
code; they are labelled that way on screen. The fixtures come from the CaptainCook4D dataset (see
`docs/LICENCES.md`).

## 3. One-breath answers to the five judge questions

1. **How do you know it works?** Four CaptainCook4D recordings, one teaching recording. Clean run 12_10: 9/9
   steps found, 0 false alarms; skipped run 12_43: 4/4 flagged, 0 false alarms `[R:card dev]` (both were used to
   tune the rule); never-tuned run 12_26: the oil skip flagged, 0 false "never happened", 1 "not sure"
   `[R:12_26]`. Small samples; source `README.md`, replayable offline with the tests.
2. **Show me a failure.** Open the 12_41 row: an off-script cook (ingredients swapped, different order) gives 2
   false "never happened", 2 "not sure", 5/9 done steps found `[R:12_41]`. Also: 6 false order reports on 12_26
   `[R:order]`, and a short step that flipped on re-asking `[R:stability]`. So we claim skip detection only.
3. **What breaks without the Decisions API?** The card could not answer during the task. Decisions is the fast
   per-window labeller behind locate, letters, self-test and follow: about 0.5 s per question at real cadence
   `[R:live]`. Without it the fallback is one Hydrogen call on the whole clip: it ties the card on 12_10,
   12_43 and 12_26 but only gives a verdict afterwards, and on 12_41 it gave 6 false "never happened" against
   the card's 2 `[R:baseline]`. Say plainly that on on-script runs it is not more accurate.
4. **Anything besides Gemini, and what was built today?** Besides Gemini 4 (`hydrogen`, `argon`,
   `decision-1`): the image model `gemini-3.1-flash-lite-image` (not Gemini 4), Flask, Pillow, FFmpeg through
   imageio-ffmpeg, and the CaptainCook4D footage and labels (Apache 2.0, `docs/LICENCES.md`). Everything under
   `wordless/`, `server.py`, `web/`, `tests/` and `scripts/` is ours; the owner confirms the built-today list
   (the git history has one scaffold commit, so it cannot prove timing).
5. **Would a real user adopt it?** For routines with no manual (a prep station, a repair, a sequence of
   hand signs), a filmed demonstration is cheaper than writing instructions, and the card is printable with
   no words. Honest limit: the own-routine, own-camera table gate has not been run on real clips
   `[R:table gate]` and off-script behaviour is weak, so today it is a tested instruction sheet for fixed
   routines, not a general tool.

## 4. Proposed `README.md` changes (not applied; the README is not ours to edit)

1. First screen: add one line under the title: "A tested instruction sheet, not a coach: it names the step
   that did not happen." (keeps clear of the banned categories).
2. Add a **Data and licences** section: the attribution paragraph from `docs/LICENCES.md` plus "The
   CaptainCook4D recordings are not in this repo; put `12_26.mp4`, `12_41.mp4` in `data/` for `scripts/gate.sh`".
3. Add a **Licence** line and a `LICENSE` file for our own code (MIT proposed).
4. In "Going live", note that `scripts/gate.sh` now reads recordings from `data/` and names a missing file.
5. Add a link to `docs/SUBMISSION.md`, `docs/VIDEO.md`, `docs/LICENCES.md` and, when they exist,
   `docs/EVAL.md`, `docs/MANAGED.md`.
6. If the fast-sequence mode lands, add it to the evidence table and to "How it works" only with its own
   measured numbers; nothing in this pack claims it.
7. Add a one-sentence model line near the top, an N and source for each evidence row, a "Built today / not ours"
   list (not ours: CaptainCook4D footage and labels, Flask, Pillow, imageio-ffmpeg, the Gemini models), and a
   rubric-to-evidence map: live demo (35%) → replay and table gate; proof against a baseline with honest
   failures (25%) → the evidence table with the Hydrogen baseline column and the 12_41 failure; creativity (20%)
   → film once, becomes the manual and the test; Gemini 4 and Decisions API use (20%) → "How it works".
8. Remove or reword the comment references to `research/feasibility/...` in code (see checklist).

## 5. Hygiene checklist

Against the relayed `DEMO-KIT.md` section (f). Status: **Done** / **Not done** / **Owner**. Audit
2026-11-21, tree at commit 5395083.

| # | Box | Status | Notes |
|---|---|---|---|
| 1 | Playable video link, works logged out, product name in the title | **Owner** | Title suggestion: "Wordless: film it once, it becomes the manual and the test". Check the link in a private window. |
| 2 | README: outcome sentence | **Done** | Opens with it. |
| 3 | README: model sentence | **Not done** | The "How it works" table exists but no one-sentence summary; proposed in section 4. |
| 4 | README: how to run | **Done** | "Run it (no key needed)" verified in a scratch copy: import then replay server works. |
| 5 | README: eval table with N and source | **Not done** | Table exists, but N and a source line are not stated per row; proposed. |
| 6 | README: failures | **Done** | 12_41 row, order errors, answer stability. |
| 7 | README: built-today / not-ours list | **Not done** | Absent; proposed text in section 4 (owner confirms the built-today part). |
| 8 | README: rubric-to-evidence map | **Not done** | Absent; proposed in section 4. |
| 9 | Same numbers everywhere (README, form, video, this file) | **Owner at 15:30** | All pack numbers tagged `[R:`; re-check, plus `docs/EVAL.md` when it lands. |
| 10 | No secrets in repo or history | **Done** | See "History scan". Re-run before public. |
| 11 | UI is not Streamlit; results screen is not a dashboard as the main feature | **Done** | Flask server and a single `web/index.html`; the main feature is the card and verdict. Keep the Proof tab secondary in the video. |
| 12 | No banned-category wording | **Done** | No coach/analyzer/chatbot/dashboard/tutor in `README.md` or `web/index.html`; keep it out of the form and video. |
| 13 | No hot reload | **Done** | `server.py` calls `app.run` without `debug` or reloader. |
| 14 | Light theme | **Done** | `color-scheme: light` and white backgrounds in `server.py` and `web/index.html`. |
| 15 | Health indicator | **Partly** | A mode pill shows "replay" or live/no key (`web/index.html`), and `/api/status` exists. No API-health indicator beyond that. |
| 16 | Run clock | **Not done** | No elapsed-time display found in `server.py` or `web/index.html`; owner of the UI decides. |
| 17 | Hard deadline | **Not done** | No per-run deadline found. (The verdict waits up to 10 s for open windows, per README.) |
| 18 | One retry | **Done** | `wordless/gemini.py` retries 429, 5xx and network errors (`_post_retry`); check the number of tries matches "one retry" if that is the rule. |
| 19 | Replay tested once by a forced switch | **Owner** | Run the demo with network off or `WORDLESS_TAPE=replay` once before submission; the tests cover replay numbers, not the switch. |
| 20 | Says which problem statement it answers | **Done** | README header names Element 119; the form text states it. |
| 21 | Tests pass from a clean clone | **Not done** | Scratch copy of 5395083: 31 passed, 6 failed, all in `tests/test_table_prep.py` (`ApiError: GEMINI_API_KEY is not set`, even with the variable set). Tests are not editable here. |
| 22 | Repo public at submission | **Owner** | Currently private; owner flips it. |
| 23 | Licences: own code, third-party, dataset | **Owner** | Third-party and dataset in `docs/LICENCES.md`; no `LICENSE` file for our code (MIT proposed); keyframes keep-or-remove is the owner's call. |
| 24 | Dangling private paths | **Not done** | Comments reference `research/feasibility/...` (`wordless/tracker.py:3`, `wordless/gemini.py:175`, `tests/fake_gemini.py:3`, `tests/test_replay_tomato.py:2`); `wordless/config.py:11` lists `research/data/captaincook`. |
| 25 | `scripts/gate.sh` runs without a private folder | **Done** | Reads `data/` and names a missing file; owner supplies the recordings. |
| 26 | Commit messages without AI trailers | **Owner** | The existing commit and this pack's commit have none; check other sessions' commits. |

### History scan

- Scope: every commit reachable from every ref (`git log --all -p`), one commit, branches
  `main`, `claude/*`. Pattern families: Google API key prefix, OpenAI-style `sk-`, GitHub tokens
  (`ghp_`, `github_pat_`), Slack tokens, AWS key ids, PEM private-key headers, and generic
  `key/secret/token/password = <16+ characters>` assignments. File names across history were also listed
  (only `.env.example` is env-like).
- Result: **no secret values found.** The one hit family was `GEMINI_API_KEY=` appearing in the README, the
  fake-API help text, `wordless/gemini.py` and `.env.example`, all as variable names or empty examples.
- Caveats: the scan covers the local repository, including the other session worktrees' branches as of now;
  it does not see work other sessions add afterwards, nor anything pushed elsewhere. **Re-run before the
  repo goes public** (`git log --all -p | grep -E 'AIza|sk-|ghp_|PRIVATE KEY'`). If the key was ever pasted
  anywhere else (chat logs, shell history, screenshots), rotate it after the event.
