"""Load the answers recorded against the live API onto the tape, then build the
"tomato" card from them in replay mode. After this, the whole app runs with no key and no network.

What is real and what is not:
  real (recorded API answers)  Hydrogen's step names; Decisions labels for every 2 s window of the teaching
                               recording 12_17 and of the follow recordings 12_10 and 12_43 (card and text-only);
                               the nine line-art panels; the keyframes they were drawn from.
  stand-in (written by hand)   the plan (which steps are setup, the order links). Argon was never called.
  never recorded               letters gate, self-test, two-still live checks, Hydrogen one-call baseline.
"""
import json
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["WORDLESS_TAPE"] = "replay"

from wordless import card as cards, config, gemini, teach  # noqa: E402

FX = config.FIXTURES / "tomato"
tape = gemini.tape


def conv(a):
    step = None if a["step"] in ("zz_none", "error") else a["step"]
    probs = {("none" if k == "zz_none" else k): v for k, v in (a.get("probs") or {}).items()}
    return {"step": step, "conf": a["conf"], "probs": probs, "lat": a.get("lat"), "tok": a.get("tok")}


def main():
    steps = json.loads((FX / "steps.json").read_text())
    tape.put_json("teach/tomato/steps", {"steps": [{"action": s["action"], "done_when": s["done_when"]} for s in steps]})
    for i, a in enumerate(json.loads((FX / "locate_12_17.json").read_text())):
        tape.put_json(f"teach/tomato/locate/{i:04d}", conv(a))
    for s in steps:
        sid = f"s{s['n']:02d}"
        kf, pn = FX / "keyframes" / f"A_kf{s['n']}.jpg", FX / "panels" / f"A_pn{s['n']}.jpg"
        if kf.exists():
            tape.put_bytes(f"teach/tomato/keyframe/{sid}", kf.read_bytes())
        if pn.exists():
            tape.put_bytes(f"teach/tomato/panel/{sid}", pn.read_bytes())
    chain, tops = ["s02", "s03", "s05", "s07"], ["s08", "s09", "s10", "s11", "s12"]
    tape.put_json("teach/tomato/plan", {
        "source": "hand-written stand-in, not an Argon answer",
        "steps": [{"id": f"s{s['n']:02d}", "setup": s["n"] in (1, 4, 6), "trace_question": None} for s in steps],
        "links": [[chain[i], chain[j]] for i in range(4) for j in range(i + 1, 4)] + [[c, t] for c in chain for t in tops]})
    for rec in ("12_10", "12_43"):
        for mode, src in (("card", "card"), ("text", "text")):
            for i, a in enumerate(json.loads((FX / "follow" / f"{src}_{rec}.json").read_text())):
                tape.put_json(f"follow/tomato/{rec}/{mode}/{i:04d}", conv(a))

    shutil.rmtree(cards.card_dir("tomato"), ignore_errors=True)
    card = teach.build(None, card_id="tomato", title="Tomato mozzarella salad (CaptainCook4D 12_17)",
                       emit=lambda ev: print(f"  [{ev['t']:>5}s] {ev['stage']:9} {ev['state']:8} {ev['detail']}"))
    # the exact sheet image that was sent to the API when the follow answers were recorded
    shutil.copy(FX / "sheet_as_sent.jpg", cards.card_dir("tomato") / "sheet_as_sent.jpg")
    card["sheet_as_sent"] = "sheet_as_sent.jpg"
    card["source"] = "replayed from recorded answers (see scripts/import_tomato_fixture.py)"
    # card step -> CaptainCook4D step id, taken from the teaching recording's own labels
    card["label_map"] = {"s02": 125, "s03": 122, "s05": 119, "s07": 120, "s08": 126, "s09": 123, "s10": 127, "s11": 124, "s12": 121}
    cards.save(card)
    print("card steps:", [s["id"] for s in card["steps"]], "| dropped:", [(d["id"], d["reason"]) for d in card["dropped"]])


if __name__ == "__main__":
    main()
