"""Presence and order logic. Pure code, no API: the model labels windows, this decides what happened.

The rule ("heaviest run") is the one frozen in research/feasibility/s2_1/score.py:
for each step, take the windows labelled with it at confidence >= MIN_CONF, join windows that are at most
RUN_GAP apart into runs, and score each run by its summed confidence. A step is SEEN when its best run
reaches its threshold, NOT SURE when it reaches the unsure band, otherwise NEVER HAPPENED.
"""
from . import config

SEEN, UNSURE, SKIPPED = "seen", "unsure", "skipped"


class Tracker:
    def __init__(self, step_ids, links=(), optional=(), thresholds=None,
                 min_conf=config.MIN_CONF, gap=config.RUN_GAP, min_mass=config.MIN_MASS, unsure_mass=config.UNSURE_MASS):
        self.step_ids = list(step_ids)
        self.links = [tuple(l) for l in links]          # (a, b): a must come before b
        self.optional = set(optional)
        self.thresholds = dict(thresholds or {})        # per-step override of min_mass
        self.min_conf, self.gap, self.min_mass, self.unsure_mass = min_conf, gap, min_mass, unsure_mass
        self.obs = {}                                   # window index -> (step or None, confidence)

    def add(self, i, step, conf):
        """Record the label for window i. Late answers may arrive in any order (back-fill)."""
        self.obs[int(i)] = (step, float(conf))

    def threshold(self, sid):
        return self.thresholds.get(sid, self.min_mass)

    def runs(self, sid):
        idx = sorted(i for i, (s, c) in self.obs.items() if s == sid and c >= self.min_conf)
        runs = []
        for j in idx:
            if runs and j - runs[-1][-1] <= self.gap + 1:
                runs[-1].append(j)
            else:
                runs.append([j])
        return runs

    def score(self, sid):
        """(mass, centre window index) of the heaviest run, or (0, None)."""
        best = (0.0, None)
        for r in self.runs(sid):
            mass = sum(self.obs[j][1] for j in r)
            if mass > best[0]:
                best = (mass, sum(r) / len(r))
        return best

    def state(self, sid):
        mass, _ = self.score(sid)
        thr = self.threshold(sid)
        if mass >= thr:
            return SEEN
        # the unsure band scales with a lowered per-step threshold
        if mass >= self.unsure_mass * thr / self.min_mass:
            return UNSURE
        return SKIPPED

    def current(self):
        """Label of the most recent window (for the 'now' highlight)."""
        if not self.obs:
            return None, 0.0
        return self.obs[max(self.obs)]

    def panel_states(self):
        """Display state per step while the task is running: pending / unsure (amber) / seen (green)."""
        out = {}
        for sid in self.step_ids:
            st = self.state(sid)
            out[sid] = {"state": "pending" if st == SKIPPED else st, "mass": round(self.score(sid)[0], 2)}
        return out

    def verdict(self):
        seen, unsure, skipped, where = [], [], [], {}
        for sid in self.step_ids:
            mass, centre = self.score(sid)
            st = self.state(sid)
            if st == SEEN:
                seen.append(sid)
                where[sid] = centre
            elif sid in self.optional:
                continue                                # optional steps are never reported as missing
            elif st == UNSURE:
                unsure.append(sid)
            else:
                skipped.append(sid)
        seen.sort(key=lambda s: where[s])
        violations = [[a, b] for a, b in self.links if a in where and b in where and where[a] > where[b]]
        return {
            "seen": seen, "unsure": unsure, "skipped": skipped, "order_violations": violations,
            "scores": {sid: round(self.score(sid)[0], 2) for sid in self.step_ids},
            "thresholds": {sid: round(self.threshold(sid), 2) for sid in self.step_ids},
            "windows": len(self.obs),
            "clean": not skipped and not unsure and not violations,
        }


def own_thresholds(own_scores, fraction=config.OWN_SCORE_FRACTION, clamp=config.OWN_SCORE_CLAMP):
    """Per-panel threshold from the score each panel earns in its own teaching clip (untested idea, see README)."""
    lo, hi = clamp
    return {sid: round(min(hi, max(lo, s * fraction)), 2) for sid, s in own_scores.items() if s}
