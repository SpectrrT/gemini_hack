# Submission pack

Draft for the Gemini 4 NYC Hackathon, Nov 21 2026. Every number is tagged `[R:<row>]` = taken from the
"State of the evidence" table in `README.md` (commit 5395083), or `[R:how]` = README "How it works".
**At 15:30 when numbers freeze, search this file for `[R:` and re-check each against the README.**
Planned `docs/EVAL.md` numbers (wide eval) should replace the four-recording figures if they land.

> Source note: the planning notes `DEMO-KIT.md` and `JUDGES.md` were not readable from this session
> (`/Users/tensae/Desktop/gemini_demo/research/` does not exist on this machine). Sections (b), (c) and (f)
> were therefore reconstructed from the brief given to this task: outcome sentence first, 300+ characters,
> model sentence, eval summary with N and source, one named failure, problem statement. The five Q&A
> questions and the hygiene boxes are my picks, not the owner's wording. Diff against the real notes
> before submitting.

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

## 3. One-breath answers to the five likely judge questions

(Reconstructed; replace with the questions in the "2-minute Q&A card" if they differ.)

1. **"Isn't this just an image analyzer or a coach?"** No. It is a tested instruction sheet: a card
   drawn from one demonstration that names a skipped step against that demonstration. It gives no advice and
   explains nothing; its only output is "panel N never happened", "seen" or "not sure".
2. **"How do you know it works?"** Four held and development recordings from CaptainCook4D: 9/9 steps found
   and 0 false alarms on the clean run, 4/4 skips flagged on the skipped run `[R:card dev]`, the oil skip
   flagged on a recording never used for tuning `[R:12_26]`. Small samples, and the first two are
   development data. The README table shows where it fails.
3. **"Where does it break?"** Off-script cooking: on 12_41 it gave 2 false "never happened" `[R:12_41]`.
   Short steps are fragile (one step flipped from 2.07 to 0.89 on re-asking) `[R:stability]`, and order
   errors are unreliable `[R:order]`, so we claim skip detection only.
4. **"Why Gemini 4, why these models?"** Hydrogen understands the whole demonstration video and names the
   steps; the Decisions API gives fast, low-cost per-window answers (about 0.5 s per question `[R:live]`) so
   the card can answer while the person works; Argon plans which steps and orderings matter; the image
   model turns real keyframes into wordless panels. Each has one job `[R:how]`.
5. **"Is the demo live? What did you build today versus bring?"** Replay is recorded real answers run
   through the real code, and is labelled "replay" on screen. The live camera path is built and tested
   against a fake API and fed from recorded footage; the table gate (own routine, own camera) was `[R:table gate]`
   not yet run on real clips when this was written. The dataset recordings are CaptainCook4D (licence in
   `docs/LICENCES.md`); the code is ours.

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
7. Remove or reword the comment references to `research/feasibility/...` in code (see checklist).

## 5. Hygiene checklist

Written against the checks I could define without `DEMO-KIT.md` section (f); map each line to the real
box. Status: **Done** / **Not done** / **Owner**. Audit date 2026-11-21, tree at commit 5395083.

| # | Box | Status | Notes |
|---|---|---|---|
| 1 | Repository public at submission | **Owner** | Currently private (`SpectrrT/gemini_hack`). The owner flips it; this session did not and must not. |
| 2 | No secrets in the working tree | **Done** | `.env` and `.env.*` are git-ignored; only `.env.example` (empty `GEMINI_API_KEY=`) is tracked. |
| 3 | No secrets in the full git history | **Done** | See "History scan" below. |
| 4 | Key not required to run / judge can run it | **Done** | `import_tomato_fixture.py` then `WORDLESS_TAPE=replay server.py` works in a clean copy of the tree (verified in a scratch copy). |
| 5 | Tests pass from a clean clone | **Not done** | In a scratch copy of 5395083: 31 passed, **6 failed**, all in `tests/test_table_prep.py` (`ApiError: GEMINI_API_KEY is not set`, even with the variable set in the shell). Owner of tests must fix; this session may not edit tests. |
| 6 | README has the outcome sentence, run steps, honest evidence | **Done** | Opens with the outcome; evidence table lists a failure. |
| 7 | README has the dataset attribution | **Not done** | Proposed text in `docs/LICENCES.md`; README edit is outside this task. |
| 8 | Licence for our own code | **Not done** | No `LICENSE` file. Needs the owner's choice (MIT proposed) and a commit to the repo root. |
| 9 | Third-party licences listed | **Done** | `docs/LICENCES.md`. |
| 10 | Dataset redistribution cleared | **Owner** | Labels yes; keyframes likely but not clearly stated (Apache 2.0 vs MIT file conflict, no mention of video). Owner decides keep or remove; removal list and consequences in `docs/LICENCES.md`. |
| 11 | No large or private media in the repo | **Done** | Tracked files total about 2.7 MB; the largest is a 312 KB panel image. No `.mp4`; `data/`, `cards/`, `tape/`, `runs/` are git-ignored. |
| 12 | No dangling references to private paths | **Not done** | Code comments point to `research/feasibility/...` (`wordless/tracker.py:3`, `wordless/gemini.py:175`, `tests/fake_gemini.py:3`, `tests/test_replay_tomato.py:2`) and `wordless/config.py:11` has a `research/data/captaincook` video dir. Harmless but a dead link for a judge. Code owners should reword. |
| 13 | `scripts/gate.sh` runs without a private folder | **Done** | Now reads `data/12_26.mp4` and `data/12_41.mp4` and names a missing file; checked by running it with both absent. Needs the owner to put the recordings in `data/` before running it for real. |
| 14 | No banned-category wording (coach, analyzer, chatbot, dashboard, tutor) | **Done** | No matches in `README.md` or `web/index.html`. Keep it that way in the video and form. |
| 15 | Commit messages: no AI attribution trailers | **Done** (history) / **Owner** (going forward) | The single existing commit has none. The owner's rule is no `Co-Authored-By` trailer; this pack's own commit follows it. Other sessions' commits should be checked before submission. |
| 16 | Eval numbers match the README | **Owner at 15:30** | Update the `[R:` tags in this file. |
| 17 | Demo video recorded, uploaded, link in the form | **Owner** | Script and shot list in `docs/VIDEO.md`. |
| 18 | Submission form text pasted, 300+ characters | **Owner** | Sections 1 and 2 above. |
| 19 | Honest labelling of replay and recorded runs | **Done** in drafts | Rule applied in `docs/VIDEO.md`; the UI itself must show a "replay" badge when `WORDLESS_TAPE=replay` (not checked here). |
| 20 | No dependence on `research/` at run time | **Not done** | `wordless/config.py:11` lists `research/data/captaincook` in `VIDEO_DIRS`; harmless when absent. |

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
