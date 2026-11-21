# Wordless: the 60-second video

Two presenters. Whoever is not on camera narrates, so hands are always free.
Marvin teaches; Tensae follows and skips a step. Two different people is the point: the card was made from
one person and checks another.

Target: 59 seconds, about 140 spoken words. Five clips, recorded separately, joined in Recordly.

## The routine

Six hand signs, each held about one second, hands down for a beat between them, hands down at the start and end:

1. closed fist  2. one finger up  3. peace sign  4. open palm  5. thumbs up  6. palms together

These six are the ones measured (6 of 6 taught and checked down to 0.45 s a sign on generated clips).
Chest-up framing, plain background, even light, both hands inside the frame the whole time.

## Clips

| Clip | Shown as | What happens on screen | Who talks |
|---|---|---|---|
| Intro | 0:00 to 0:04, real time | Page on "Show it once" with the camera on, so the product is on screen from the first second. Both in frame. | Both |
| A. Teach | 0:04 to 0:13, real time | Marvin alone in frame does the six signs in about 7 s. | Tensae |
| B. Card builds | 0:13 to 0:19, sped up, with the caption "card build: about 35 s, shown 6x" | Stages tick through, the six panels appear. | Tensae |
| C. Check with a skip | 0:19 to 0:39, REAL TIME, no cuts inside | "Check someone". Tensae does signs 1, 2, skips 3, holds 4 for two full seconds, then 5, 6. Panel 3 turns red and the guide says "You skipped this" while he is still going. Verdict and evidence frames land. | Marvin |
| D. Proof | 0:39 to 0:52 | Proof tab, top table: 17, 12, 4. Then cut back to the six-panel card. | Tensae |
| E. Close | 0:52 to 0:59 | Verdict screen from clip C, or the card. | Marvin, then Tensae |

## Script

**Intro (0:00)** Tensae: "Hey, I'm Tensae." Marvin: "I'm Marvin." Tensae: "And we built Wordless."

**A (Tensae, 0:04)** "Show it once, and it catches the next person's mistake as they make it. Marvin shows six
hand signs. Nothing typed."

**B (Tensae, 0:13)** "Carbon finds the steps, the Decisions API picks each clearest frame, the image model draws
the card. No words."

**C (Marvin, 0:19)** "Now Tensae follows it. Every camera frame is one Decisions question, eight a second.
He skips a step..." *(wait for the red panel)* "...and it's caught while he's still going. The verdict names
the step and shows the camera frame behind every other one."

**D (Tensae, 0:39)** "We pushed it until it broke. On sixteen public recordings, our first version raised
seventeen false alarms; a whole-clip review cut that to four. At half a second a sign, the model saw two of
six. Now it sees six."

**E (Marvin, 0:52)** "Look-alike steps are still its weak point."
**(Tensae)** "One clip, no labels. Wordless: teach anyone anything."

About 140 words, so keep the pace up. If it runs long, cut in this order: Marvin's line in E, then the
"two of six" sentences in D, then "Nothing typed" in A.

## Honest-labelling rules

- Clip C is real time with no cut between Start and the verdict. It is the claim; it cannot be edited.
- Clip B is sped up and says so on screen.
- If a recorded run (`R`) is ever shown, its yellow "Recorded run" banner stays visible.
- Every number spoken is in the README or on the Proof tab. Do not round them up.
- If the alert does not fire or the verdict is wrong in a take, retake. Do not narrate over a wrong result.

## Before recording

1. Stop everything else that uses the API key (other sessions, evals). Answers took about 0.55 s on a quiet key
   and several seconds on a busy one; a slow key delays the red alert.
2. Restart the server, reload the page, browser full screen at 110 to 125% zoom, bookmarks bar hidden.
3. Do the whole thing once without recording. The clean version must show six ticks and no alert; the skip
   version must turn panel 3 red before Tensae finishes.
4. For the skip: hold sign 4 for two full seconds. The alert needs the next step held solidly before it speaks.
5. Hydrogen's second vote can change "never happened" to "not sure" a few seconds after the verdict if it thinks
   it saw the step. Keep recording five seconds past the verdict; if it flips, retake.
6. Recordly: record screen plus webcam bubble off (the page already shows the camera). Let auto-zoom follow the
   verdict, or add one manual zoom on the red panel and one on the verdict.
7. Add captions for the spoken lines: the hall is loud and many people watch muted.
8. Title the video "Wordless: show it once, it catches the next person's mistake". Open the link in a private
   window to check it plays logged out.
