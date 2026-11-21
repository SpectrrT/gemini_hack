"""Frame-by-frame checking (wordless/signs.py) on the 16 wide-eval recordings.

  python scripts/eval_frames.py run [--fps 2]   # needs the key and data/<id>.mp4; one process per recording
  python scripts/eval_frames.py check           # no key: score fixtures/eval_wide/frames/<id>.json, print tables

The kit is the tomato card turned into a sign kit (signs.from_card): reference sheet = the card's keyframe
photos. Each still is one Decisions question. Two readings of each result:
  in order     the product's own answer: steps the alignment against the card order reports missing or wrong
  order-free   a step counts as seen when any decoded segment carries its label, wherever it falls
Neither reading has a "not sure" answer.
"""
import argparse
import concurrent.futures as cf
import json
import os
import statistics
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import eval_wide as ew  # noqa: E402

OUT = ew.FX / "frames"
KIT = "tomato-fast"


def run_one(rec, fps):
    from wordless import card as cards, signs
    try:
        kit = signs.load(KIT)
    except Exception:
        kit = None
    if not kit:
        kit = signs.from_card(cards.load(ew.CARD), kid=KIT)
    s = signs.run_video(kit, ROOT / "data" / f"{rec}.mp4", fps=fps, mode="follow", target="routine", name=f"frames-{rec}")
    r = s.result
    if s.fatal or not r:
        raise SystemExit(f"{rec}: {s.fatal or 'no result'}")
    idx = sorted(s.times)
    doc = {"recording": rec, "fps": fps, "frames": r["frames"], "missing_frames": r["missing_frames"],
           "median_latency_s": r["latency"], "wall_seconds": round(s.state()["seconds"], 1),
           "errors": sorted(set(s.errors.values()))[:5], "distance": r["distance"], "ops": r["best"]["ops"],
           "seen": [{k: (round(v, 2) if isinstance(v, float) else v) for k, v in g.items() if k != "name"} for g in r["seen"]],
           "text": r["text"],
           "frame_answers": [[s.answers[i]["top"], s.answers[i]["conf"], s.answers[i]["lat"]] if i in s.answers else None for i in idx]}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{rec}.json").write_text(json.dumps(doc, separators=(",", ":")))
    print(rec, r["frames"], "frames,", r["missing_frames"], "unanswered |", r["text"][:200])


def run(recs, fps, force):
    from wordless import card as cards, signs
    signs.from_card(cards.load(ew.CARD), kid=KIT)          # build the kit once, before the parallel processes
    env = dict(os.environ, WORDLESS_TAPE="auto")
    logs = ROOT / "runs" / "eval_frames"
    logs.mkdir(parents=True, exist_ok=True)

    def one(rec):
        if (OUT / f"{rec}.json").exists() and not force:
            return rec, "already run"
        p = subprocess.run([sys.executable, __file__, "run-one", rec, "--fps", str(fps)], cwd=ROOT, env=env, capture_output=True, text=True)
        (logs / f"{rec}.log").write_text(p.stdout + p.stderr)
        return rec, (p.stdout.strip().splitlines() or ["?"])[-1] if p.returncode == 0 else "FAILED: " + (p.stderr.strip().splitlines() or ["?"])[-1]

    with cf.ThreadPoolExecutor(len(recs)) as ex:
        for rec, msg in ex.map(one, recs):
            print(f"  {rec:8} {msg}")


def results():
    """Rows carrying frames_order / frames_any next to the card, one_call and review columns."""
    import eval_rules as er
    rows = er.run()
    ids = [s["id"] for s in json.loads((ew.FX / "card_steps.json").read_text())["steps"]]
    for r in rows:
        f = OUT / f"{r['recording']}.json"
        if not f.exists():
            r["frames_order"] = r["frames_any"] = r["frames_doc"] = None
            continue
        d = json.loads(f.read_text())
        not_seen = sorted({o["want"] for o in d["ops"] if o["op"] in ("missing", "wrong")})
        labels = {g["label"] for g in d["seen"]}
        r["frames_order"] = ew.score(r["truth"], {"skipped": not_seen})
        r["frames_any"] = ew.score(r["truth"], {"skipped": [s for s in ids if s not in labels]})
        r["frames_doc"] = d
    return rows


COLS = (("card", "Card, 2 s windows"), ("one_call", "One call"), ("review", "Card + review (ships)"),
        ("frames_order", "Frame by frame, in order"), ("frames_any", "Frame by frame, order-free"))


def table(rows):
    sets = (("All 16", rows), ("12 never scored before", [r for r in rows if r["group"] == "new"]),
            ("14 not used for tuning", [r for r in rows if r["group"] != "dev"]))
    out = ["| Set | Method | N | Skipped steps flagged | False \"never happened\" / performed steps | "
           "Recordings with a false \"never happened\" | \"Not sure\" | Verdict fully right |", "|---|---|---|---|---|---|---|---|"]
    for title, rs in sets:
        for k, n in COLS:
            t = ew.totals(rs, k)
            out.append(f"| {title} | {n} | {t['n']} | {t['flagged']}/{t['skips']} | {t['false_never']}/{t['performed']} | "
                       f"{t['recordings_with_false_never']}/{t['n']} | {t['not_sure']} | {t['verdict_fully_right']}/{t['n']} |")
    return "\n".join(out)


def per_recording(rows):
    out = ["| Recording | Labels: skipped | In order: skips flagged | In order: false \"never happened\" | "
           "Order-free: skips flagged | Order-free: false \"never happened\" | Stills | Unanswered |", "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        d = r["frames_doc"]
        if not d:
            out.append(f"| {r['recording']} | {ew.names(r['truth']['skipped'])} | failed | | | | | |")
            continue
        a, b = ew.cell(r["frames_order"]), ew.cell(r["frames_any"])
        out.append(f"| {r['recording']} | {ew.names(r['truth']['skipped'])} | {a[0]} | {a[1]} | {b[0]} | {b[1]} | {d['frames']} | {d['missing_frames']} |")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=("run", "run-one", "check"))
    ap.add_argument("recordings", nargs="*")
    ap.add_argument("--fps", type=float, default=2.0)
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    if a.cmd == "run-one":
        return run_one(a.recordings[0], a.fps)
    if a.cmd == "run":
        return run(a.recordings or ew.recordings(), a.fps, a.force)
    rows = results()
    print(per_recording(rows), "\n")
    print(table(rows), "\n")
    docs = [r["frames_doc"] for r in rows if r["frames_doc"]]
    lat = [x[2] for d in docs for x in d["frame_answers"] if x]
    if lat:
        print(f"stills: {sum(d['frames'] for d in docs)}, unanswered: {sum(d['missing_frames'] for d in docs)}, "
              f"fps: {sorted({d['fps'] for d in docs})}, median seconds per answer: {statistics.median(lat):.2f}, "
              f"90th percentile: {sorted(lat)[int(len(lat) * 0.9)]:.2f}")


if __name__ == "__main__":
    main()
