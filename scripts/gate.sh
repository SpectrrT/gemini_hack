#!/bin/sh
# Go / no-go G1 once the key has credit: two tomato recordings the card has never been scored on.
# 12_26: oil skipped, nothing else missing (pass = oil flagged, at most one false alarm).
# 12_41: plating after the toppings plus ingredient substitutions (informative only).
# About 800 Decisions calls (400 windows, card and text-only; ~0.8M tokens, about 5 minutes) and two Hydrogen calls.
#
# The two CaptainCook4D recordings must already be in data/ as 12_26.mp4 and 12_41.mp4
# (data/ is git-ignored; download them from the dataset, see docs/LICENCES.md for the source).
cd "$(dirname "$0")/.." || exit 1
mkdir -p data
missing=0
for r in 12_26 12_41; do
  if [ ! -f "data/$r.mp4" ]; then
    echo "gate: missing recording data/$r.mp4 (expected at $(pwd)/data/$r.mp4)" >&2
    missing=1
  fi
done
if [ "$missing" -ne 0 ]; then
  echo "gate: put the missing file(s) in data/ and run scripts/gate.sh again. Nothing was sent to the API." >&2
  exit 1
fi
WORDLESS_TAPE=auto .venv/bin/python -m wordless.evalrun --card tomato 12_26 12_41 --text --hydrogen --json runs/gate_g1.json
