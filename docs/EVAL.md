# Wide eval: 16 recordings of the tomato salad

Run on Nov 21 2026 against the live API. The card was taught from CaptainCook4D recording 12_17 and is
scored here on every other recording of the same recipe that the dataset publishes as GoPro video: 16
recordings, 5 people, 6 kitchens. 12 of them had never been scored by anything in this project before this
run. The verdict rule and its cut-offs were not changed for this run.

**Short version: on recordings it had not seen, the card checker is worse than one Hydrogen call on the
whole clip.** It reports a performed step as "never happened" in 10 of the 12 new recordings; the one-call
baseline does so in 2 of 12. The earlier 4-recording result did not hold up.

## What was run

- **Card**: the card image plus each 2 s window, one Decisions question per window, verdict by the frozen
  rule in `wordless/tracker.py`.
- **Text-only**: the same windows and rule, with the step names as text and no card image.
- **One call**: one Hydrogen call on the whole clip with the step list (`wordless/baseline.py`). It answers
  after the task is over; it has no "not sure" answer.
- **Answer key**: the dataset's human labels. A step counts as skipped when it has no time span or carries
  the tag "Missing Step". "Changed" lists steps the labels tag with any other error (wrong ingredient, wrong
  amount, spilled, wrong order); those steps were still performed, so flagging them is a false alarm.
- Skip detection only. Step-order reports are known to be unreliable and are not scored.

Groups: **dev** = the two recordings the cut-offs were tuned on; **seen once** = scored once before in the
README gate; **new** = first scored in this run.

## Per recording

| Recording | Group | Labels: skipped | Labels: changed | Card: skips flagged | Card: false "never happened" | Card: "not sure" | Text-only: skips flagged | Text-only: false "never happened" | Text-only: "not sure" | One call: skips flagged | One call: false "never happened" | One call: "not sure" |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 12_2 | new | none | none | n/a | 0 | 1 (salt) | n/a | 0 | 1 (pepper) | n/a | 0 | 0 |
| 12_5 | new | none | none | n/a | 2 (salt, herbs) | 0 | n/a | 0 | 1 (pepper) | n/a | 0 | 0 |
| 12_9 | new | none | none | n/a | 1 (herbs) | 0 | n/a | 0 | 0 | n/a | 0 | 0 |
| 12_10 | dev | none | none | n/a | 0 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |
| 12_12 | new | none | none | n/a | 1 (herbs) | 0 | n/a | 0 | 0 | n/a | 0 | 0 |
| 12_13 | new | none | none | n/a | 0 | 0 | n/a | 0 | 0 | n/a | 0 | 0 |
| 12_15 | new | none | none | n/a | 1 (herbs) | 1 (salt) | n/a | 0 | 1 (pepper) | n/a | 0 | 0 |
| 12_16 | new | none | none | n/a | 1 (herbs) | 0 | n/a | 0 | 1 (pepper) | n/a | 0 | 0 |
| 12_19 | new | none | none | n/a | 1 (salt) | 1 (herbs) | n/a | 0 | 1 (salt) | n/a | 0 | 0 |
| 12_26 | seen once | oil | dry, slice, plate, pepper, cheese | 1/1 | 0 | 1 (herbs) | 1/1 | 0 | 1 (herbs) | 1/1 | 0 | 0 |
| 12_38 | new | rinse | dry, slice, plate, pepper, salt, cheese, oil | 0/1 | 2 (salt, herbs) | 0 | 0/1 | 0 | 3 (pepper, herbs, rinse) | 1/1 | 4 (dry, salt, cheese, oil) | 0 |
| 12_41 | seen once | none | slice, plate, pepper, salt, herbs, cheese, oil | n/a | 2 (salt, herbs) | 2 (plate, cheese) | n/a | 1 (salt) | 4 (plate, herbs, cheese, oil) | n/a | 6 (dry, slice, plate, pepper, cheese, oil) | 0 |
| 12_43 | dev | salt, herbs, cheese, oil | rinse, slice, plate | 4/4 | 0 | 0 | 3/4 | 0 | 3 (plate, pepper, salt) | 4/4 | 0 | 0 |
| 12_48 | new | none | slice, plate, pepper, oil | n/a | 2 (dry, herbs) | 0 | n/a | 1 (dry) | 1 (herbs) | n/a | 2 (dry, slice) | 0 |
| 12_51 | new | none | pepper, herbs, cheese, oil | n/a | 1 (pepper) | 0 | n/a | 0 | 1 (pepper) | n/a | 0 | 0 |
| 12_119 | new | none | none | n/a | 3 (dry, salt, herbs) | 0 | n/a | 2 (dry, herbs) | 0 | n/a | 0 | 0 |

## Totals

"Verdict fully right" = every skipped step flagged, no false "never happened", no "not sure".

| Set | Method | N recordings | Skipped steps flagged | False "never happened" / performed steps | Recordings with a false "never happened" | "Not sure" | Verdict fully right |
|---|---|---|---|---|---|---|---|
| All | Card | 16 | 5/6 | 17/138 | 11/16 | 6 | 3/16 |
| All | Text-only | 16 | 4/6 | 4/138 | 3/16 | 18 | 4/16 |
| All | One call | 16 | 6/6 | 12/138 | 3/16 | 0 | 13/16 |
| Never scored before | Card | 12 | 0/1 | 15/107 | 10/12 | 3 | 1/12 |
| Never scored before | Text-only | 12 | 0/1 | 3/107 | 2/12 | 10 | 3/12 |
| Never scored before | One call | 12 | 1/1 | 6/107 | 2/12 | 0 | 10/12 |
| Not used for tuning | Card | 14 | 1/2 | 17/124 | 11/14 | 6 | 1/14 |
| Not used for tuning | Text-only | 14 | 1/2 | 4/124 | 3/14 | 15 | 3/14 |
| Not used for tuning | One call | 14 | 2/2 | 12/124 | 3/14 | 0 | 11/14 |

Only 6 skipped steps exist in the 16 recordings (4 of them in dev recording 12_43), and only 1 in the 12 new
recordings. So this eval says little about catching skips and a lot about false alarms on people who did
every step. Per step over all 16 recordings, the card's false "never happened" count is: herbs 9, salt 5,
dry 2, pepper 1.

## Where it breaks

1. **The three sprinkle steps look alike to the card.** Inside the time spans the labels give for each step,
   the card names the right panel in 96% of slicing windows but only 31% of herbs windows (57 of 133 were
   called pepper), 52% of salt windows and 42% of oil windows (71 of 247 called pepper). Pepper, salt, herbs
   and oil are all "a hand tips a small container over the plate"; the line-art panels do not tell them
   apart, so the pepper panel absorbs the others and herbs or salt never reach the cut-off. This is the
   cause of 14 of the card's 17 false "never happened". The text-only checker, which reads "salt" and
   "italian seasoning" as words, gets 76% and 53% on the same windows and makes 4 false "never happened"
   instead of 17, at the price of 18 "not sure".
2. **Worst recordings for the card.**
   - **12_119** (new, clean run, a kitchen seen nowhere else): 3 false "never happened" (dry, salt, herbs).
     Drying got 1 of 9 windows right; herbs windows were called plate.
   - **12_38** (new; cherry tomatoes, sugar for salt, cheddar, rinse skipped): the one real skip in the new
     set was missed by card and text-only (the person holds the tomato at the sink without rinsing; the card
     saw "rinse"), plus 2 false "never happened". The one-call baseline caught the skip but gave 4 false
     "never happened" of its own.
   - **12_41** (seen once; lid for a plate, steps out of order): 2 false "never happened" and 2 "not sure",
     the same as the first time it was scored. The baseline is worse here: 6 false.
   - **12_5, 12_48** (new): 2 false "never happened" each. In 12_48 two steps last 2 to 4 s, which is one or
     two windows and cannot reach the 1.6 cut-off even when every window is right.
3. **Where the baseline breaks.** All 12 of its false "never happened" are in three recordings where the
   person changed ingredients or order (12_38, 12_41, 12_48). On the 13 others it made no error. It fails
   rarely and badly; the card fails often and mildly.
4. **Short steps.** A step shorter than about 6 s gives at most three windows. 12_51 pepper (5 s) and 12_48
   dry (4 s) and herbs (2 s) were lost this way.

## What this does and does not show

- The card checker's edge is that it answers during the task. On accuracy after the task, one Hydrogen call
  is better on this recipe: 10 of 12 new recordings fully right against the card's 1 of 12.
- Dropping the card image for text criteria removes most false alarms (3 against 15 on the new recordings),
  so the weak part is telling look-alike panels apart, not the windowing or the rule.
- One recipe, one card, one run per recording. Answers shift a little between runs (85 of 100 windows gave
  the same label when 12_43 was asked twice), so single counts can move by one or two.
- 5 of 3,160 windows got no answer from the card checker and 5 from the text-only checker, in 12_5, 12_9,
  12_13 (2) and 12_48, on two attempts each. None changed a verdict.
- 12_6 (oil skipped) is not scored: the dataset publishes no GoPro video for it.

## What we changed after seeing the failures

No new API calls. Every rule below is scored on the answers recorded for the tables above
(`scripts/eval_rules.py`, reading `fixtures/eval_wide`). No rule has a number of its own; all reuse the
cut-offs frozen on 12_10 and 12_43. The last two rules were designed after looking at all 16 recordings, so
their numbers on the 12 new recordings are not a clean test; they need fresh recordings to be confirmed.

Sources per step: **C** card checker, **T** text-only checker (each: seen / not sure / never happened),
**H** the one Hydrogen call (performed / not performed).

| Rule | Verdict "never happened" when | Otherwise |
|---|---|---|
| confirmed | C says never and H says not performed | exactly one of them says so: not sure; neither: seen |
| card_and_text | C and T both say never | exactly one: not sure; neither: seen |
| all_three | C, T and H all say so | one or two of them: not sure; none: seen |
| averaged_confirmed | as "confirmed", with C replaced by the frozen rule applied to the per-window mean of the card and text-only probabilities | same |
| sprinkle_group | as "confirmed" | plus: pepper, salt, herbs and oil are one look-alike group. A member H says was performed counts as seen when the card windows labelled with any group member weigh at least 1.6 per member H says was performed |
| one_call_veto | H says not performed and neither C nor T saw the step | H says not performed but C or T saw it: not sure; H says performed: seen |

**All 16**

| Rule | Skipped steps flagged | Skips answered "not sure" | Skips missed | False "never happened" / performed steps | Recordings with a false "never happened" | "Not sure" on performed steps | Verdict fully right |
|---|---|---|---|---|---|---|---|
| card | 5/6 | 0 | 1 | 17/138 | 11/16 | 6 | 3/16 |
| text | 4/6 | 2 | 0 | 4/138 | 3/16 | 16 | 4/16 |
| one_call | 6/6 | 0 | 0 | 12/138 | 3/16 | 0 | 13/16 |
| confirmed | 5/6 | 1 | 0 | 2/138 | 2/16 | 25 | 5/16 |
| card_and_text | 4/6 | 1 | 1 | 4/138 | 3/16 | 13 | 4/16 |
| all_three | 4/6 | 2 | 0 | 1/138 | 1/16 | 26 | 4/16 |
| averaged_confirmed | 5/6 | 1 | 0 | 2/138 | 2/16 | 20 | 8/16 |
| sprinkle_group | 5/6 | 1 | 0 | 2/138 | 2/16 | 11 | 12/16 |
| one_call_veto | 5/6 | 1 | 0 | 3/138 | 2/16 | 9 | 13/16 |

**12 never scored before**

| Rule | Skipped steps flagged | Skips answered "not sure" | Skips missed | False "never happened" / performed steps | Recordings with a false "never happened" | "Not sure" on performed steps | Verdict fully right |
|---|---|---|---|---|---|---|---|
| card | 0/1 | 0 | 1 | 15/107 | 10/12 | 3 | 1/12 |
| text | 0/1 | 1 | 0 | 3/107 | 2/12 | 9 | 3/12 |
| one_call | 1/1 | 0 | 0 | 6/107 | 2/12 | 0 | 10/12 |
| confirmed | 0/1 | 1 | 0 | 2/107 | 2/12 | 17 | 2/12 |
| card_and_text | 0/1 | 0 | 1 | 3/107 | 2/12 | 12 | 2/12 |
| all_three | 0/1 | 1 | 0 | 1/107 | 1/12 | 18 | 2/12 |
| averaged_confirmed | 0/1 | 1 | 0 | 2/107 | 2/12 | 12 | 5/12 |
| sprinkle_group | 0/1 | 1 | 0 | 2/107 | 2/12 | 5 | 9/12 |
| one_call_veto | 0/1 | 1 | 0 | 1/107 | 1/12 | 5 | 10/12 |

**14 not used for tuning**

| Rule | Skipped steps flagged | Skips answered "not sure" | Skips missed | False "never happened" / performed steps | Recordings with a false "never happened" | "Not sure" on performed steps | Verdict fully right |
|---|---|---|---|---|---|---|---|
| card | 1/2 | 0 | 1 | 17/124 | 11/14 | 6 | 1/14 |
| text | 1/2 | 1 | 0 | 4/124 | 3/14 | 14 | 3/14 |
| one_call | 2/2 | 0 | 0 | 12/124 | 3/14 | 0 | 11/14 |
| confirmed | 1/2 | 1 | 0 | 2/124 | 2/14 | 25 | 3/14 |
| card_and_text | 1/2 | 0 | 1 | 4/124 | 3/14 | 13 | 3/14 |
| all_three | 1/2 | 1 | 0 | 1/124 | 1/14 | 26 | 3/14 |
| averaged_confirmed | 1/2 | 1 | 0 | 2/124 | 2/14 | 20 | 6/14 |
| sprinkle_group | 1/2 | 1 | 0 | 2/124 | 2/14 | 11 | 10/14 |
| one_call_veto | 1/2 | 1 | 0 | 3/124 | 2/14 | 9 | 11/14 |

### Recommendation: one_call_veto

The one call decides, and the window checkers can only turn its "not performed" into "not sure".

- **What it fixes.** False "never happened" over all 16 recordings: 3 of 138 performed steps, against the
  card's 17 and the one call's 12. On the 12 new recordings: 1 of 107, against 15 and 6.
- **What it costs.** 9 "not sure" on performed steps (5 on the new recordings); the one call alone has none.
  5 of 6 skipped steps are still flagged; the sixth (12_38, tomato held at the sink but not rinsed) becomes
  "not sure" because both window checkers saw "rinse". No skip is reported as seen.
- **Why this one.** It needs no knowledge of the recipe and no new number. By construction it can never
  report a false "never happened" that the one call does not also report. It gives as many fully right
  verdicts as the one call alone (13 of 16).
- **What it does not fix.** The verdict now waits for the Hydrogen call, which took 8 to 109 s on these
  recordings (median 18 s). The card's own panels still cannot tell the sprinkle steps apart; under this rule
  the card image contributes almost nothing to the verdict that the text-only checker does not. The three
  remaining false "never happened" are in off-script recordings (12_41 plate and cheese, 12_48 dry).
- **No rule beats the one call on fully right verdicts.** The gain is fewer wrong accusations, paid for
  in "not sure".

sprinkle_group is close (2 false "never happened", 11 "not sure", 12 of 16 fully right) but names four
steps of this recipe by hand, so it does not carry to another card. all_three has the fewest false
"never happened" (1) and the most "not sure" (26). card_and_text does not help: the two window checkers
share the short-step problem, and it loses a skip.

## Re-check without the API

```bash
.venv/bin/python scripts/eval_wide.py check
```

This recomputes every verdict from the window answers saved in `fixtures/eval_wide/<id>.json` with the
frozen rule and prints the two tables above. The combined rules:

```bash
.venv/bin/python scripts/eval_rules.py --detail
```

To run it again from scratch (needs the key, about 7,000
Decisions calls and 16 Hydrogen calls, about 8 minutes in parallel):

```bash
.venv/bin/python scripts/fetch_captaincook.py --skip 12_17
```

```bash
.venv/bin/python scripts/eval_wide.py run
```

```bash
.venv/bin/python scripts/eval_wide.py collect
```
