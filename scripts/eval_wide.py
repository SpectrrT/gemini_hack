"""Wide eval: every CaptainCook4D recording of the tomato salad except the teaching one, three methods.

  python scripts/eval_wide.py run       # needs the key and data/<id>.mp4 (scripts/fetch_captaincook.py);
                                        # one evalrun process per recording, in parallel, answers go on the tape
  python scripts/eval_wide.py collect   # tape + run output -> fixtures/eval_wide/<id>.json (small, no video)
  python scripts/eval_wide.py check     # no key, no video: recompute every verdict from the saved window
                                        # answers with the frozen rule and print the table in docs/EVAL.md

Answer key: a step counts as skipped when the dataset gives it no time span (start_time < 0) or tags it
"Missing Step". wordless/evalrun.py uses the first condition only; the two differ on one step (12_38 rinse).
Skip detection only; order reports are not scored.
"""
import argparse
import concurrent.futures as cf
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from wordless import card as cards, config  # noqa: E402
from wordless.tracker import Tracker  # noqa: E402

FX = ROOT / "fixtures" / "eval_wide"
OUT = config.RUNS / "eval_wide"
CARD = "tomato"
TEACH = "12_17"
DEV = ("12_10", "12_43")            # the verdict rule was tuned on these
SEEN_BEFORE = ("12_26", "12_41")    # scored once before this eval (README gate)
NAMES = {"s02": "rinse", "s03": "dry", "s05": "slice", "s07": "plate", "s08": "pepper", "s09": "salt",
         "s10": "herbs", "s11": "cheese", "s12": "oil"}
METHODS = (("card", "Card"), ("text", "Text-only"), ("hydrogen", "One call"))


def labels():
    return {e["recording_id"]: e for e in json.loads((FX / "labels.json").read_text())}


def recordings():
    done = sorted((p.stem for p in FX.glob("12_*.json")), key=lambda r: int(r.split("_")[1]))
    return done


def truth(card, entry):
    inv = {v: k for k, v in card["label_map"].items()}
    skipped, changed = [], []
    for s in entry["step_annotations"]:
        sid = inv.get(s["step_id"])
        if not sid:
            continue
        tags = [e.get("tag") for e in s.get("errors", [])]
        if s["start_time"] < 0 or "Missing Step" in tags:
            skipped.append(sid)
        elif tags:
            changed.append(sid)
    ids = cards.step_ids(card)
    return {"skipped": sorted(skipped), "changed": sorted(changed), "performed": [s for s in ids if s not in skipped]}


def verdict_from_windows(card, windows):
    tr = Tracker(cards.step_ids(card))
    for i, w in enumerate(windows):
        if w:
            tr.add(i, w[0], w[1])
    v = tr.verdict()
    return {"skipped": v["skipped"], "unsure": v["unsure"], "scores": v["scores"]}


def score(t, v):
    """v: {"skipped": [...], "unsure": [...]} -> the three reported numbers."""
    real, flagged, unsure = set(t["skipped"]), set(v["skipped"]), set(v.get("unsure", []))
    return {"flagged": sorted(flagged & real), "skips_total": len(real),
            "false_never": sorted(flagged - real), "not_sure": sorted(unsure - real),
            "not_sure_on_skip": sorted(unsure & real), "missed": sorted(real - flagged - unsure)}


# ---------------------------------------------------------------- run (API)
def run(recs, workers, force):
    OUT.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, WORDLESS_TAPE="auto")

    def one(rec):
        out = OUT / f"{rec}.json"
        if out.exists() and not force:
            return rec, "already run"
        p = subprocess.run([sys.executable, "-m", "wordless.evalrun", "--card", CARD, rec, "--labels", str(FX / "labels.json"),
                            "--text", "--hydrogen", "--json", str(out)], cwd=ROOT, env=env, capture_output=True, text=True)
        (OUT / f"{rec}.log").write_text(p.stdout + p.stderr)
        return rec, "ok" if p.returncode == 0 else "FAILED, see " + str(OUT / f"{rec}.log")

    with cf.ThreadPoolExecutor(workers) as ex:
        for rec, msg in ex.map(one, recs):
            print(f"  {rec:8} {msg}")


# ---------------------------------------------------------------- collect (tape -> fixtures)
def tape_windows(rec, mode, n_used):
    d = config.TAPE / "follow" / CARD / rec / mode
    files = sorted(d.glob("*.json"))
    if not files:
        return None
    n = int(files[-1].stem) + 1
    out = [None] * n
    for f in files:
        a = json.loads(f.read_text())
        out[int(f.stem)] = [a["step"], a["conf"]]
    return out[:n_used]                 # the tape may hold a trailing fragment the run did not use


def tape_probs(rec, mode, n_used):
    """Per-window probabilities (the API returns those above 0.02); None where the window got no answer."""
    out = [None] * n_used
    for f in sorted((config.TAPE / "follow" / CARD / rec / mode).glob("*.json")):
        if int(f.stem) < n_used:
            a = json.loads(f.read_text())
            out[int(f.stem)] = a.get("probs") or {str(a["step"] or "none"): a["conf"]}
    return out


def collect(recs):
    card = cards.load(CARD)
    lab = labels()
    (FX / "card_steps.json").write_text(json.dumps({"id": CARD, "steps": [{"id": i} for i in cards.step_ids(card)],
                                                    "label_map": card["label_map"]}, indent=1))
    for rec in recs:
        src = OUT / f"{rec}.json"
        if not src.exists():
            print(f"  {rec:8} not run")
            continue
        row = json.loads(src.read_text())["rows"][0]
        hyd = config.TAPE / "baseline" / "hydrogen" / CARD / f"{rec}.json"
        e = lab[rec]
        doc = {"recording": rec, "card": CARD, "person_id": e.get("person_id"), "environment": e.get("environment"),
               "window_seconds": config.WINDOW_S,
               "label_notes": {str(s["step_id"]): [f"{x.get('tag')}: {x.get('description')}" for x in s["errors"]]
                               for s in e["step_annotations"] if s.get("errors")},
               "truth": truth(card, e),
               "card_windows": tape_windows(rec, "card", row["windows"]), "text_windows": tape_windows(rec, "text", row["windows"]),
               "card_probs": tape_probs(rec, "card", row["windows"]), "text_probs": tape_probs(rec, "text", row["windows"]),
               "hydrogen": json.loads(hyd.read_text()) if hyd.exists() else None,
               "hydrogen_error": (row.get("hydrogen_one_call") or {}).get("error"),
               "text_error": (row.get("text_only") or {}).get("error"),
               "evalrun_row": row}
        (FX / f"{rec}.json").write_text(json.dumps(doc, separators=(",", ":")))
        print(f"  {rec:8} {len(doc['card_windows'] or [])} card windows, {len(doc['text_windows'] or [])} text windows, "
              f"baseline {'ok' if doc['hydrogen'] else 'MISSING'}")


# ---------------------------------------------------------------- check (no API)
def results():
    card = json.loads((FX / "card_steps.json").read_text())      # step ids and label map only; no built card needed
    rows = []
    for rec in recordings():
        d = json.loads((FX / f"{rec}.json").read_text())
        t = d["truth"]
        r = {"recording": rec, "truth": t, "person": d["person_id"], "kitchen": d["environment"], "notes": d["label_notes"],
             "group": "dev" if rec in DEV else "seen once" if rec in SEEN_BEFORE else "new"}
        for key, wins in (("card", d["card_windows"]), ("text", d["text_windows"])):
            if wins is None:
                r[key] = None
                continue
            v = verdict_from_windows(card, wins)
            if key == "card":
                v_card = v
            r[key] = dict(score(t, v), scores=v["scores"], unanswered=sum(w is None for w in wins))
        r["hydrogen"] = score(t, {"skipped": d["hydrogen"]["skipped"]}) if d["hydrogen"] else None
        # the card column must agree with what evalrun reported when it ran against the API
        er, et = d["evalrun_row"]["card"], set(d["evalrun_row"]["truth_skipped"])
        fl, un = set(v_card["skipped"]), set(v_card["unsure"])
        r["matches_evalrun"] = (un == set(er["unsure"]) and fl - et == set(er["false_alarms"])
                                and len(fl & et) == er["skips_caught"])
        rows.append(r)
    return rows


def names(ids):
    return ", ".join(NAMES.get(s, s) for s in ids) or "none"


def cell(c):
    if c is None:
        return "failed", "", ""
    fl = f"{len(c['flagged'])}/{c['skips_total']}" if c["skips_total"] else "n/a"
    ns = c["not_sure"] + c["not_sure_on_skip"]
    return fl, f"{len(c['false_never'])}" + (f" ({names(c['false_never'])})" if c["false_never"] else ""), \
        f"{len(ns)}" + (f" ({names(ns)})" if ns else "")


def totals(rows, key):
    rs = [r for r in rows if r[key] is not None]
    performed = sum(len(r["truth"]["performed"]) for r in rs)
    skips = sum(r[key]["skips_total"] for r in rs)
    return {"n": len(rs), "flagged": sum(len(r[key]["flagged"]) for r in rs), "skips": skips,
            "false_never": sum(len(r[key]["false_never"]) for r in rs), "performed": performed,
            "not_sure": sum(len(r[key]["not_sure"]) + len(r[key]["not_sure_on_skip"]) for r in rs),
            "recordings_with_false_never": sum(bool(r[key]["false_never"]) for r in rs),
            "verdict_fully_right": sum(len(r[key]["flagged"]) == r[key]["skips_total"] and not r[key]["false_never"]
                                       and not r[key]["not_sure"] and not r[key]["not_sure_on_skip"] for r in rs)}


def markdown(rows):
    out = ["| Recording | Group | Labels: skipped | Labels: changed | "
           + " | ".join(f"{n}: skips flagged | {n}: false \"never happened\" | {n}: \"not sure\"" for _, n in METHODS) + " |",
           "|" + "---|" * (4 + 3 * len(METHODS))]
    for r in rows:
        cells = [x for k, _ in METHODS for x in cell(r[k])]
        out.append(f"| {r['recording']} | {r['group']} | {names(r['truth']['skipped'])} | {names(r['truth']['changed'])} | "
                   + " | ".join(cells) + " |")
    out.append("")
    out.append("| Set | Method | N recordings | Skipped steps flagged | False \"never happened\" / performed steps | "
               "Recordings with a false \"never happened\" | \"Not sure\" | Verdict fully right |")
    out.append("|---|---|---|---|---|---|---|---|")
    sets = (("All", rows), ("Never scored before", [r for r in rows if r["group"] == "new"]),
            ("Not used for tuning", [r for r in rows if r["group"] != "dev"]))
    for title, rs in sets:
        for k, n in METHODS:
            t = totals(rs, k)
            out.append(f"| {title} | {n} | {t['n']} | {t['flagged']}/{t['skips']} | {t['false_never']}/{t['performed']} | "
                       f"{t['recordings_with_false_never']}/{t['n']} | {t['not_sure']} | {t['verdict_fully_right']}/{t['n']} |")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=("run", "collect", "check"))
    ap.add_argument("recordings", nargs="*")
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--json", action="store_true", help="check: print the per-recording results as JSON")
    a = ap.parse_args()
    if a.cmd in ("run", "collect"):
        recs = a.recordings or [r for r in labels() if r != TEACH and (ROOT / "data" / f"{r}.mp4").exists()]
        (run(recs, a.workers, a.force) if a.cmd == "run" else collect(recs))
        return
    rows = results()
    if a.json:
        print(json.dumps(rows, indent=1))
        return
    print(markdown(rows))
    bad = [r["recording"] for r in rows if not r["matches_evalrun"]]
    print("\ncard column agrees with the live evalrun output:", "yes" if not bad else f"NO for {bad}")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
