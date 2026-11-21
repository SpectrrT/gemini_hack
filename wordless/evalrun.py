"""Evaluation on recordings with human labels (CaptainCook4D format). Calls the same replay path as the UI.

  python -m wordless.evalrun --card tomato 12_10 12_43            # card checker
  python -m wordless.evalrun --card tomato 12_10 12_43 --text     # adds the text-only checker column
  python -m wordless.evalrun --card tomato 12_26 --hydrogen       # adds the one-call Hydrogen baseline

The card must carry "label_map" (step id -> dataset step id) and the labels file must list the recordings.
"""
import argparse
import concurrent.futures as cf
import json

from . import baseline, card as cards
from . import checker, config, follow, gemini
from .tracker import Tracker


def load_labels(path):
    return {e["recording_id"]: e for e in json.loads(open(path).read())}


def truth_for(card, labels, rec):
    inv = {v: k for k, v in card["label_map"].items()}
    ann = labels[rec]["step_annotations"]
    present = sorted((s for s in ann if s["start_time"] >= 0 and s["step_id"] in inv), key=lambda s: s["start_time"])
    return {"order": [inv[s["step_id"]] for s in present],
            "skipped": sorted(inv[s["step_id"]] for s in ann if s["start_time"] < 0 and s["step_id"] in inv),
            "spans": {inv[s["step_id"]]: (s["start_time"], s["end_time"]) for s in present},
            "has_errors": labels[rec].get("is_error")}


def score(card, truth, verdict, answers=None):
    flagged = set(verdict["skipped"])
    real = set(truth["skipped"])
    # frozen rule (no "not sure" band, as in the first scoring): a step below the cut-off counts as flagged
    frozen = flagged | set(verdict.get("unsure", []))
    out = {"frozen_rule": {"skips_caught": len(frozen & real), "false_alarms": sorted(frozen - real)},
           "skips_caught": len(flagged & real), "skips_total": len(real), "false_alarms": sorted(flagged - real),
           "unsure": verdict.get("unsure", []), "missed": sorted(real - flagged - set(verdict.get("unsure", []))),
           "found": len(set(verdict.get("seen", [])) & set(truth["order"])), "performed": len(truth["order"])}
    if answers:
        ok = tot = 0
        for i, a in answers.items():
            t0, t1 = int(i) * config.WINDOW_S, int(i) * config.WINDOW_S + config.WINDOW_S
            inside = [s for s, (a0, a1) in truth["spans"].items() if a0 <= t0 and t1 <= a1]
            if inside:
                tot += 1
                ok += a["step"] == inside[0]
        out["window_acc"] = [ok, tot]
    return out


def text_checker(card, rec, n):
    """Text-only checker: no card image, the named steps as text criteria (the weaker variant)."""
    named = card.get("named_steps") or card["steps"]
    kind, n, clips = follow.recording_windows(card, rec)     # n: the window indices
    def one(i):
        try:
            return checker.classify_clip_text(named, (lambda: clips[i].read_bytes()) if clips else None,
                                              key=f"follow/{card['id']}/{rec}/text/{i:04d}")
        except gemini.NoCredit:
            raise
        except gemini.ApiError:
            return None                                  # one lost window must not end the run
    with cf.ThreadPoolExecutor(3) as ex:
        labels = list(ex.map(one, n))
    if sum(a is None for a in labels) > len(labels) // 10:
        raise gemini.ApiError(-1, "more than 10% of the text-only windows failed")
    tr = Tracker(cards.step_ids(card))
    for i, a in zip(n, labels):
        if a:
            tr.add(i, a["step"], a["conf"])
    return tr.verdict()


def run(card_id, recs, labels_path, text=False, hydrogen=False, own=False, out_path=None):
    card = cards.load(card_id)
    labels = load_labels(labels_path)
    rows = []
    for rec in recs:
        truth = truth_for(card, labels, rec)
        s = follow.replay(card, rec, speed=0, use_own_thresholds=own, block=True)
        if s.fatal:
            raise SystemExit(s.fatal)
        row = {"recording": rec, "truth_skipped": truth["skipped"], "errors_in_recording": bool(truth["has_errors"]),
               "windows": len(s.answers), "failed_windows": len(s.errors),
               "card": score(card, truth, s.verdict, s.answers), "verdict": s.verdict["text"]}
        if text:
            try:
                row["text_only"] = score(card, truth, text_checker(card, rec, len(s.answers)))
            except gemini.TapeMiss:
                row["text_only"] = None
            except (gemini.ApiError, OSError, ValueError, RuntimeError) as e:
                if isinstance(e, gemini.NoCredit):
                    raise SystemExit(str(e))
                row["text_only"] = {"error": f"{type(e).__name__}: {e}"[:200]}
        if hydrogen:
            try:
                h = baseline.hydrogen_one_call(card, rec)
                row["hydrogen_one_call"] = score(card, truth, {"skipped": h["skipped"], "seen": [x for x in cards.step_ids(card) if x not in h["skipped"]]})
            except gemini.TapeMiss:
                row["hydrogen_one_call"] = None
            except (gemini.ApiError, OSError, ValueError, RuntimeError, AttributeError) as e:
                row["hydrogen_one_call"] = {"error": f"{type(e).__name__}: {e}"[:200]}
        rows.append(row)
        if out_path:                                     # keep what is done if a later recording fails
            open(out_path, "w").write(json.dumps({"card": card_id, "tape_mode": gemini.mode(), "rows": rows}, indent=1))
    return {"card": card_id, "tape_mode": gemini.mode(), "rows": rows}


def fmt(col):
    if col is None:
        return "not recorded"
    if "error" in col:
        return "failed: " + col["error"]
    s = f"{col['skips_caught']}/{col['skips_total']} skips caught, {len(col['false_alarms'])} false alarms, {col['found']}/{col['performed']} steps found"
    if col.get("unsure"):
        s += f", {len(col['unsure'])} not sure (frozen rule without that band: {col['frozen_rule']['skips_caught']}/{col['skips_total']} caught, {len(col['frozen_rule']['false_alarms'])} false alarms)"
    if col.get("window_acc"):
        s += f", windows {col['window_acc'][0]}/{col['window_acc'][1]}"
    return s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("recordings", nargs="+")
    ap.add_argument("--card", required=True)
    ap.add_argument("--labels", default=str(config.FIXTURES / "tomato" / "labels.json"))
    ap.add_argument("--text", action="store_true")
    ap.add_argument("--hydrogen", action="store_true")
    ap.add_argument("--own-thresholds", action="store_true")
    ap.add_argument("--json")
    a = ap.parse_args()
    res = run(a.card, a.recordings, a.labels, a.text, a.hydrogen, a.own_thresholds, out_path=a.json)
    for r in res["rows"]:
        print(f"\n{r['recording']}  truly skipped: {r['truth_skipped'] or 'none'}  ({r['windows']} windows, {r['failed_windows']} failed)")
        print("  card checker      :", fmt(r["card"]), "|", r["verdict"])
        for name in ("text_only", "hydrogen_one_call"):
            if name in r:
                print(f"  {name:18}:", fmt(r[name]))


if __name__ == "__main__":
    main()
