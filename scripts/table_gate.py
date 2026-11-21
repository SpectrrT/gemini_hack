"""Gate G2 on the clips recorded in the Prep tab (needs a funded key).

  .venv/bin/python scripts/table_gate.py

Builds the card from the teaching run, replays every follow clip through the checker and scores each verdict
against the answer key entered when the clip was recorded. Pass: every verdict right, no false "never
happened", clip to card in 40 s or less. Writes runs/gate_g2.json.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from wordless import gemini, table  # noqa: E402


def main():
    need = table.readiness()
    if need:
        sys.exit("Not ready. Record in the Prep tab: " + "; ".join(need) + ".")
    try:
        res = table.run_gate(emit=lambda e: print(f"  {e.get('stage', ''):9} {e.get('state', ''):8} {e.get('detail', '')}"))
    except gemini.NoCredit:
        sys.exit("The API key has no credit (HTTP 402). The clips are saved; run this again after topping up.")
    except gemini.TapeMiss:
        sys.exit("Replay mode has no recorded answers for these clips. Run without WORDLESS_TAPE=replay and with a funded key.")
    print(f"\ncard: {res['panels']} panels for a {res['kit_steps']}-step kit, clip to card {res['clip_to_card_s']} s")
    for r in res["rows"]:
        want = "do it right" if r["truth"] == "right" else f"skip step {r['skip']}"
        print(f"  {r['clip']:12} sealed: {want:14} verdict: {r.get('verdict', r.get('fatal'))}  ->  {r['outcome']}")
    for p in res["problems"]:
        print("  problem:", p)
    print(f"\n{'PASS' if res['passed'] else 'FAIL'}: {res['correct']}/{res['of']} verdicts right, {res['false_never_happened']} false 'never happened'")
    sys.exit(0 if res["passed"] else 1)


if __name__ == "__main__":
    main()
