"""Blind read of a card by managed agents.

  python scripts/blind_read.py <card_id>             read every panel blind, score, print the table
  python scripts/blind_read.py <card_id> --redraw    also redraw failing panels once and read them again
  python scripts/blind_read.py <card_id> --redraw --apply   a redraw that passes replaces the card's panel
  --fresh        ignore recorded answers and ask the API again
  --tag .b       keep this run apart from earlier ones on the tape

Writes runs/blind_<card_id>.json.
"""
import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("card_id")
    ap.add_argument("--redraw", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--fresh", action="store_true")
    ap.add_argument("--tag", default="")
    a = ap.parse_args()
    if a.fresh:
        os.environ["WORDLESS_TAPE"] = "live"
    from wordless import config, gemini, managed

    def emit(ev):
        if "panel" in ev:
            print(f"  [{ev['t']:6.1f} s] panel {ev['panel']}" + (" (redrawn)" if ev["round"] else "")
                  + f": {'PASS' if ev['passed'] else 'FAIL'}  {ev['blind'] or ''}", file=sys.stderr, flush=True)
    try:
        out = managed.blind_read(a.card_id, redraw=a.redraw, apply=a.apply, emit=emit, tag=a.tag)
    except FileNotFoundError as e:
        sys.exit(str(e))
    except gemini.TapeMiss as e:
        sys.exit(f"replay mode and no recorded answer for {e}")
    except gemini.ApiError as e:
        sys.exit(str(e))
    print(managed.table(out))
    print("saved", config.RUNS / f"blind_{a.card_id}.json")


if __name__ == "__main__":
    main()
