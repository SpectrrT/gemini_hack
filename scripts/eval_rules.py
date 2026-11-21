"""Combined verdict rules, scored on the answers already recorded in fixtures/eval_wide (no API, no video).

  python scripts/eval_rules.py            # totals table for every rule
  python scripts/eval_rules.py --detail   # plus what each rule still gets wrong, per recording

Three sources per step:
  C  card checker        seen / unsure / skipped   (frozen rule on the card-image window answers)
  T  text-only checker   seen / unsure / skipped   (frozen rule on the text-criteria window answers)
  H  one Hydrogen call   performed / not performed (after the task; no "not sure")

Rules (a verdict per step: never happened / not sure / seen):
  card, text, one_call   the single sources, for reference
  confirmed              never only when C says never AND H says not performed; exactly one -> not sure
  card_and_text          never only when C and T both say never; exactly one -> not sure
  all_three              never only when C, T and H all say so; one or two -> not sure
  averaged_confirmed     per window, average the card and text-only probabilities, apply the frozen rule to
                         that, then confirm with H as in "confirmed"
  sprinkle_group         "confirmed", plus: pepper, salt, herbs and oil are treated as one look-alike group.
                         A member the card did not see, but H says was performed, counts as seen when the
                         card's windows for the whole group weigh at least MIN_MASS per member H says was
                         performed
  one_call_veto          H decides "never happened"; a window checker that saw the step (C or T) turns H's
                         "not performed" into "not sure"; a step H says was performed is seen

No rule has a number of its own: all reuse the cut-offs frozen in wordless/config.py on 12_10 and 12_43.
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import eval_wide as ew  # noqa: E402
from wordless import config  # noqa: E402
from wordless.tracker import Tracker  # noqa: E402

SPRINKLE = ("s08", "s09", "s10", "s12")     # pepper, salt, herbs, oil
SEEN, UNSURE, NEVER = "seen", "unsure", "skipped"


def states(ids, windows):
    """Frozen rule on [step, conf] windows -> ({step: state}, {step: mass})."""
    tr = Tracker(ids)
    for i, w in enumerate(windows):
        if w:
            tr.add(i, w[0], w[1])
    return {s: tr.state(s) for s in ids}, {s: tr.score(s)[0] for s in ids}


def averaged_windows(ids, card_probs, text_probs):
    """Mean of the two checkers' probabilities per window; label = the heaviest choice."""
    out = []
    for c, t in zip(card_probs, text_probs):
        if c is None and t is None:
            out.append(None)
            continue
        srcs = [p for p in (c, t) if p is not None]
        avg = {s: sum(p.get(s, 0.0) for p in srcs) / len(srcs) for s in ids}
        best = max(ids, key=lambda s: avg[s])
        none = 1.0 - sum(avg.values())        # everything else: "none" and the text checker's setup steps
        out.append([best, avg[best]] if avg[best] >= none else [None, none])
    return out


def agree(votes):
    """never when every source says never, seen when none does, otherwise not sure."""
    n = sum(votes)
    return NEVER if n == len(votes) else SEEN if n == 0 else UNSURE


def load(rec):
    d = json.loads((ew.FX / f"{rec}.json").read_text())
    ids = [s["id"] for s in json.loads((ew.FX / "card_steps.json").read_text())["steps"]]
    C, c_mass = states(ids, d["card_windows"])
    T, _ = states(ids, d["text_windows"])
    A, _ = states(ids, averaged_windows(ids, d["card_probs"], d["text_probs"]))
    H = {s: (NEVER if s in d["hydrogen"]["skipped"] else SEEN) for s in ids}
    return d, ids, C, T, A, H, c_mass


def rules(ids, C, T, A, H, c_mass):
    v = {"card": dict(C), "text": dict(T), "one_call": dict(H)}
    v["confirmed"] = {s: agree([C[s] == NEVER, H[s] == NEVER]) for s in ids}
    v["card_and_text"] = {s: agree([C[s] == NEVER, T[s] == NEVER]) for s in ids}
    v["all_three"] = {s: agree([C[s] == NEVER, T[s] == NEVER, H[s] == NEVER]) for s in ids}
    v["averaged_confirmed"] = {s: agree([A[s] == NEVER, H[s] == NEVER]) for s in ids}

    g = dict(v["confirmed"])
    members = [s for s in SPRINKLE if H[s] == SEEN]
    # every card window labelled with a group member, as one pool (heaviest-run logic does not apply to a pool)
    pool = sum(c_mass[s] for s in SPRINKLE)
    if members and pool >= config.MIN_MASS * len(members):
        for s in members:
            g[s] = SEEN
    v["sprinkle_group"] = g

    v["one_call_veto"] = {s: SEEN if H[s] == SEEN else (UNSURE if SEEN in (C[s], T[s]) else NEVER) for s in ids}
    return v


ORDER = ("card", "text", "one_call", "confirmed", "card_and_text", "all_three", "averaged_confirmed",
         "sprinkle_group", "one_call_veto")


def run():
    rows = []
    for rec in ew.recordings():
        d, ids, C, T, A, H, c_mass = load(rec)
        r = {"recording": rec, "truth": d["truth"],
             "group": "dev" if rec in ew.DEV else "seen once" if rec in ew.SEEN_BEFORE else "new"}
        for name, st in rules(ids, C, T, A, H, c_mass).items():
            r[name] = ew.score(d["truth"], {"skipped": [s for s in ids if st[s] == NEVER],
                                            "unsure": [s for s in ids if st[s] == UNSURE]})
        rows.append(r)
    return rows


def table(rows):
    sets = (("All 16", rows), ("12 never scored before", [r for r in rows if r["group"] == "new"]),
            ("14 not used for tuning", [r for r in rows if r["group"] != "dev"]))
    out = []
    for title, rs in sets:
        out += [f"**{title}**", "",
                "| Rule | Skipped steps flagged | Skips answered \"not sure\" | Skips missed | False \"never happened\" / performed steps | "
                "Recordings with a false \"never happened\" | \"Not sure\" on performed steps | Verdict fully right |",
                "|---|---|---|---|---|---|---|---|"]
        for name in ORDER:
            t = ew.totals(rs, name)
            ns_skip = sum(len(r[name]["not_sure_on_skip"]) for r in rs)
            missed = sum(len(r[name]["missed"]) for r in rs)
            out.append(f"| {name} | {t['flagged']}/{t['skips']} | {ns_skip} | {missed} | {t['false_never']}/{t['performed']} | "
                       f"{t['recordings_with_false_never']}/{t['n']} | {t['not_sure'] - ns_skip} | {t['verdict_fully_right']}/{t['n']} |")
        out.append("")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--detail", action="store_true")
    a = ap.parse_args()
    rows = run()
    print(table(rows))
    if a.detail:
        for name in ORDER[3:]:
            print(name)
            for r in rows:
                c = r[name]
                if c["false_never"] or c["not_sure"] or c["not_sure_on_skip"] or c["missed"]:
                    print(f"  {r['recording']:7} false never: {ew.names(c['false_never'])}; not sure: {ew.names(c['not_sure'])}; "
                          f"skip answered not sure: {ew.names(c['not_sure_on_skip'])}; skip missed: {ew.names(c['missed'])}")


if __name__ == "__main__":
    main()
