"""Paths, model ids and the few tuned numbers. Everything tuned lives here so it can be frozen in one commit."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOME = Path(os.environ.get("WORDLESS_HOME", ROOT))   # where generated data lives; override to keep runs apart
CARDS = HOME / "cards"          # built cards (card.json, panels, sheet.jpg)
TAPE = HOME / "tape"            # recorded API answers, keyed by meaning (see gemini.Tape)
RUNS = HOME / "runs"            # follow sessions: stills, answers, verdicts, tally
FIXTURES = ROOT / "fixtures"
VIDEO_DIRS = [ROOT / "research" / "data" / "captaincook", HOME / "data"]

MODELS = {
    "hydrogen": os.environ.get("WORDLESS_HYDROGEN", "gemini-4-hydrogen"),      # names the steps; one-call baseline
    "argon": os.environ.get("WORDLESS_ARGON", "gemini-4-argon"),               # plans the card: optional steps, order links
    "carbon": os.environ.get("WORDLESS_CARBON", "gemini-4-carbon"),            # fast path: names the steps; reviews the verdict
    "image": os.environ.get("WORDLESS_IMAGE", "gemini-3-pro-image"),           # keyframe -> line-art panel (the lite model added hands)
    "decision": os.environ.get("WORDLESS_DECISION", "gemini-decision-1"),      # locate, letters gate, self-test, live check
}

WINDOW_S = 2.0            # clip length for file-based checking (the measured setting)
DECISIONS_MIN_GAP_S = 0.34  # ~3 requests/s was measured as sustainable

# Presence rule ("heaviest run"), frozen on recordings 12_10 and 12_43.
MIN_CONF = 0.45           # a window counts toward a step only at or above this confidence
RUN_GAP = 2               # windows of a different label tolerated inside one run
MIN_MASS = 1.6            # summed confidence of the best run needed to call a step "seen"
UNSURE_MASS = 0.9         # between this and MIN_MASS the verdict is "not sure" (strongest skipped step measured: 0.6)
# Per-panel thresholds from the card's own teaching clip (tournament change no. 2; NOT yet measured).
OWN_SCORE_FRACTION = 0.5
OWN_SCORE_CLAMP = (0.9, 1.6)

# Fast sequences (wordless/signs.py): one still per question, several a second, answered in parallel.
SIGNS_MIN_GAP_S = float(os.environ.get("WORDLESS_SIGNS_GAP", 0.0))   # no spacing between questions

# Whole-clip review of every verdict: one Hydrogen call decides "never happened"; the card can only turn that
# into "not sure" (rule "review" in docs/EVAL.md, added after the 16-recording eval). WORDLESS_REVIEW=0 turns it off.
REVIEW = os.environ.get("WORDLESS_REVIEW", "1") != "0"
REVIEW_TIMEOUT_S = float(os.environ.get("WORDLESS_REVIEW_TIMEOUT", 45))

# Fast path, optional: a larger model watches the whole run once it is over and its reading decides the verdict;
# the frame answers can then only turn its "never happened" into "not sure". OFF by default: measured on two runs,
# Carbon, Neon and Hydrogen each took 16 to 50 s and every one of them missed a 1.2 s step that the frame-by-frame
# answers caught. WORDLESS_FAST_REVIEW=1 turns it on.
FAST_REVIEW = os.environ.get("WORDLESS_FAST_REVIEW", "0") == "1"
FAST_REVIEW_TIMEOUT_S = float(os.environ.get("WORDLESS_FAST_REVIEW_TIMEOUT", 40))
