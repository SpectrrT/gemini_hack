"""Stress the verdict rule on the answers recorded against the real API (no key, no network).

  .venv/bin/python scripts/stress.py

Simulations on the two development recordings (12_10 clean, 12_43 four steps skipped): they show where the
rule breaks, not how well the model sees. The app also re-asks lost windows; this is the bare rule.
"""
import json, random, sys
import os; os.chdir(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')); sys.path.insert(0, '.')
from wordless.tracker import Tracker
IDS = ["s02","s03","s05","s07","s08","s09","s10","s11","s12"]
TRUTH = {"12_10": set(), "12_43": {"s09","s10","s11","s12"}}
REC = {r: json.load(open(f'fixtures/tomato/follow/card_{r}.json')) for r in TRUTH}
def verdict(ans, **kw):
    t = Tracker(IDS, **kw)
    for i, a in ans:
        t.add(i, None if a["step"] == "zz_none" else a["step"], a["conf"])
    v = t.verdict(); return set(v["skipped"]), set(v["unsure"])
def grade(r, ans, **kw):
    sk, un = verdict(ans, **kw); tr = TRUTH[r]
    return len(sk - tr), len(tr - sk - un), len(un)   # false "never happened", missed skips, unsure
base = {r: list(enumerate(REC[r])) for r in REC}
print("scores per step:")
for r in REC:
    t = Tracker(IDS)
    for i, a in base[r]: t.add(i, None if a["step"]=="zz_none" else a["step"], a["conf"])
    print(" ", r, {s: round(t.score(s)[0], 2) for s in IDS})
print("\nA. cut-off sweep (false alarms, missed skips, unsure)")
for m in [0.6,0.9,1.2,1.6,2.0,2.4,3.0]:
    print(f"  min_mass {m}:", {r: grade(r, base[r], min_mass=m, unsure_mass=m*0.9/1.6) for r in REC})
def trials(name, fn, n=500):
    random.seed(1)
    for r in REC:
        fa = ms = un = bad = 0
        for _ in range(n):
            g = grade(r, fn(base[r])); fa += g[0] > 0; ms += g[1] > 0; un += g[2] > 0; bad += (g[0] > 0 or g[1] > 0)
        print(f"  {name:34} {r}: wrong verdict {bad/n:4.0%} (false 'never happened' {fa/n:4.0%}, missed skip {ms/n:4.0%}), any 'not sure' {un/n:4.0%}")
print("\nB. windows lost at random (answer never arrives; no back-fill)")
for p in [0.05,0.1,0.2,0.3]:
    trials(f"{p:.0%} lost", lambda a, p=p: [x for x in a if random.random() > p])
print("\nC. confidence noise")
for sd in [0.05,0.1,0.15]:
    trials(f"sd {sd}", lambda a, sd=sd: [(i, {**x, "conf": min(1, max(0, x["conf"] + random.gauss(0, sd)))}) for i, x in a])
print("\nD. wrong labels (window given a random other panel, conf kept)")
for p in [0.05,0.1,0.2]:
    trials(f"{p:.0%} flipped", lambda a, p=p: [(i, {**x, "step": random.choice(IDS)}) if random.random() < p else (i, x) for i, x in a])
print("\nE. faster performer (keep every k-th window, re-indexed)")
for k in [2,3]:
    for off in range(k):
        print(f"  {k}x speed, offset {off}:", {r: grade(r, [(j, x) for j, (i, x) in enumerate(base[r][off::k])]) for r in REC})
print("\nF. slower sampling (live: one question per 2 s is the same cadence as recorded; drop every other window, keep indices)")
for off in (0,1):
    print(f"  half the windows, offset {off}:", {r: grade(r, base[r][off::2]) for r in REC})
