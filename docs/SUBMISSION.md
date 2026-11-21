# Submission text

Gemini 4 NYC Hackathon, Nov 21 2026. Everything here is taken from `README.md`; if the two ever differ, the
README is right.

## Short description (about 300 characters)

> Do a hands-on routine once on camera. Gemini turns it into a picture card with no words, then the card
> watches the next person frame by frame and names the step they skipped, while they are still going. A tested
> instruction sheet for people who do not share a language. Look-alike steps still break it.

## Long description

**Do it once on camera. Your demonstration becomes the manual and the test.**

A trainer shows any hands-on routine to the camera, at any speed, with any number of steps. Nobody names the
steps or says how many there are. Gemini finds them and draws each one as a panel with no words. The card then
watches the next person frame by frame and says which step never happened. It is a tested instruction sheet,
not a coach: it says which step did not happen, not how well a step was done.

**Element 119.** Video goes in and a drawn card comes out; the card is then used to read live camera frames.
Nothing is typed at any point. It does not use audio.

**Which model does which job**

- `gemini-4-carbon` (Gemini 4) watches the teaching clip once and lists the distinct steps in order.
- `gemini-decision-1` (Decisions API) labels every teaching frame to find each step's clearest moment, runs the
  card's self-test, and during a check answers "which step is this frame?" about eight times a second.
- `gemini-3-pro-image` (not a Gemini 4 model) redraws each clearest frame as a line-art panel.
- `gemini-4-hydrogen` (Gemini 4) reviews the whole run afterwards as a second vote. "Never happened" stands
  only when the frames and Hydrogen both say so; otherwise the step becomes "not sure".
- Lining the frame answers up against the card and writing the verdict is plain code (`wordless/decode.py`).

**Does it work?** On 16 public recordings of other people (CaptainCook4D, 5 people, 6 kitchens, scored against
the dataset's human labels), out of 138 steps people really did:

| Method | Wrongly reported "never happened" |
|---|---|
| Our first version (card alone) | 17 |
| One Hydrogen call on the whole clip (baseline) | 12 |
| Card plus whole-clip review | 4 |

Whole verdicts are right as often as the baseline (13 of 16), not more often. These numbers are for the
earlier 2-second-window method. The frame-by-frame flow in the demo has been measured on generated hand-sign
clips (six of six signs taught and checked down to 0.45 s a sign, skipped signs named) and on our own trials at
the table, which are logged on the Proof tab, wrong verdicts included.

**Where it breaks.** Look-alike steps: salt, pepper, herbs and oil are all "a hand tips a small container over
the plate", and the first version confused them in 11 of 16 recordings. A step held under about half a second
can be missed. It cannot see someone undo a step. Order errors are not claimed. The full list is under "Known
gaps" in the README.

**Built at the event.** Everything in the repository was written on Nov 21 2026 after 10:30 AM; nothing existed
before. The CaptainCook4D footage and labels, the Gemini models and the libraries in `requirements.txt` are not
ours. See "What was built at the event" in the README.

## One-breath answers for judges

1. **How do you know it works?** The 17 / 12 / 4 table above, on other people's recordings, with a baseline.
2. **Show me a failure.** Look-alike steps; the first version got 11 of 16 recordings wrong for that reason.
3. **What breaks without the Decisions API?** The live check. A whole-clip model call took 16 to 50 s and missed
   a 1.2 s step that the frame answers caught.
4. **What was built today?** All of it. Only the dataset, the models and the libraries are not ours.
5. **Who would use it?** A trainer whose new hire does not share their language, at a prep station, a packing
   bench or a workshop.
