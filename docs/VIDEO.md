# Video: shot list and script (60 s or less)

One raw screen-and-camera take can follow this: screen recording of the app, plus (optional) a face or hands
camera for the opening and closing lines. Read the script in one go at a steady pace; each block's seconds
are a guide, and the total is about 58 s at 140 words per minute. Numbers are from `README.md` "State of the
evidence" (tag `[R:..]`); re-check them at 15:30.

## Honest-labelling rules (apply to every shot)

1. Any replayed or recorded run carries an on-screen label for the whole shot: **"REPLAY: recorded API answers
   (CaptainCook4D footage)"**. The app is started with `WORDLESS_TAPE=replay`; the label can be a text overlay if
   the UI has none.
2. Say "recorded" or "replayed" out loud in that shot (it is in the script).
3. "LIVE" appears on screen only if the camera and the API are really live in that shot. If the table gate has
   not run, there is no live shot; do not fake one.
4. Footage credit once at the end: "Footage: CaptainCook4D dataset, Apache 2.0".
5. Show the failure number on screen at the same time it is spoken. Do not cut it.
6. Say "tested instruction sheet" or "card", never "coach" or "analyzer".

## Script (spoken text, 138 words)

> Every routine gets taught in words nobody reads. So film it once.
>
> This is Wordless. One demonstration, a tomato salad, becomes a card of line drawings. No words.
>
> Gemini 4 Hydrogen names the steps. The Decisions API finds each one in the footage. Argon plans which steps matter.
>
> Now a different person, a different kitchen. The card watches. Panels turn green as each step is seen.
>
> This run skips the last four steps. Those panels stay grey, and it says: panels six to nine never happened.
>
> That is recorded footage replayed through the real code, not live.
>
> Across four recordings, every skipped step was flagged, and the clean run raised no false alarms.
>
> It also breaks. On an off-script cook it wrongly said two steps never happened.
>
> Film it once. The demonstration is the manual, and the test.

Word count of the spoken text: 138 (`wc -w`, checked). Numbers spoken: four recordings `[R:card dev, 12_26, 12_41]`;
skipped steps all flagged `[R:card dev, 12_26]`; clean run no false alarms `[R:card dev]`; two false
"never happened" `[R:12_41]`; panels six to nine is the 12_43 verdict in the README's Follow notes `[R:run it]`.
If the words "four recordings" change at the freeze, change them here and on screen.

## Shot list

| # | Time | Picture | Voice | On-screen text / label |
|---|---|---|---|---|
| 1 | 0:00 to 0:06 | Camera on you (or hands) at a counter, then cut to the Teach tab with the 4-minute teaching clip playing | "Every routine gets taught in words nobody reads. So film it once." | none |
| 2 | 0:06 to 0:14 | Teach tab: "Rebuild the tomato card from recorded answers"; panels appear one by one; card with 9 panels fills the screen | "This is Wordless. One demonstration, a tomato salad, becomes a card of line drawings. No words." | **REPLAY: recorded API answers (CaptainCook4D footage)**; "card from recording 12_17" |
| 3 | 0:14 to 0:24 | The "How it works" table (README, or a slide): highlight Hydrogen, Decisions, Argon rows in turn | "Gemini 4 Hydrogen names the steps. The Decisions API finds each one in the footage. Argon plans which steps matter." | model names as written in the README table |
| 4 | 0:24 to 0:32 | Follow tab, recording 12_43 selected, press Start; video on the left, card on the right, panels 1 to 5 turning green | "Now a different person, a different kitchen. The card watches. Panels turn green as each step is seen." | REPLAY label stays on |
| 5 | 0:32 to 0:41 | Same run to the end: panels 6 to 9 stay grey, the verdict text appears: panels 6 to 9 never happened | "This run skips the last four steps. Those panels stay grey, and it says: panels six to nine never happened." | zoom on the verdict line |
| 6 | 0:41 to 0:44 | Hold the verdict | "That is recorded footage replayed through the real code, not live." | **REPLAY** label enlarged |
| 7 | 0:44 to 0:51 | Proof tab: "Run the eval", the three-column table fills in; keep 12_10, 12_43, 12_26 rows visible | "Across four recordings, every skipped step was flagged, and the clean run raised no false alarms." | the numbers as shown in the table, tagged "development recordings" where applicable |
| 8 | 0:51 to 0:55 | Same table, scroll to / highlight the 12_41 row: "2 false never happened" | "It also breaks. On an off-script cook it wrongly said two steps never happened." | "12_41, off-script: 2 false 'never happened'" |
| 9 | 0:55 to 0:59 | Back to the face/hands camera, or the final card with the verdict | "Film it once. The demonstration is the manual, and the test." | "Wordless. Footage: CaptainCook4D dataset, Apache 2.0" and the repo URL |

Total about 59 s. If it runs long, cut shot 3's highlighting, not the failure shot.

## Take plan (one pass)

- Pre-roll: start the server with `WORDLESS_TAPE=replay`, open http://localhost:5119, pre-select 12_43.
  Check that the "Rebuild the tomato card" button works before recording.
- Record screen and (optional) camera together in one take; read the script from the table above; leave a
  beat at each row boundary so the cuts are clean.
- If a live webcam shot is added after the table gate: record it as a separate row with a **LIVE** label, and
  do not change the REPLAY shots. It must show the real latency, and its result must be stated even if wrong.
- Export 1080p, under 60 s, add captions from the script (no words on the cards; captions are on the video,
  not the product).
