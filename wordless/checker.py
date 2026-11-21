"""The questions put to the Decisions API. One place, so the live checker, the replay and the eval ask the
same thing. Prompts for the card + clip and card + two stills questions are the measured ones."""
from . import card as cards
from . import gemini

NONE = "zz_none"


def _panel_criteria(card):
    crit = {f"p{k + 1}": f"panel {k + 1}: {s['action']}" for k, s in enumerate(card["steps"])}
    crit[NONE] = "none of the panels: walking, searching, fetching things, idle, tidying or between steps"
    return crit


def _clip(clip_bytes, key):
    if clip_bytes is None:                       # no video file: only a recorded answer can serve this window
        raise gemini.TapeMiss(key or "(clip without a file)")
    return clip_bytes() if callable(clip_bytes) else clip_bytes


def _answer(card, res, by_panel=True):
    a = res["answers"].get("step") or {}
    if "choice" not in a or "confidence" not in a:
        raise gemini.ApiError(200, "answer without a choice: " + str(res["answers"])[:200])
    ids = cards.step_ids(card)
    conv = (lambda lab: None if lab == NONE else ids[int(lab[1:]) - 1]) if by_panel else (lambda lab: None if lab == NONE else lab)
    probs = {(conv(k) or "none"): round(v, 3) for k, v in (a.get("probabilities") or {}).items() if v > 0.02}
    return {"step": conv(a["choice"]), "conf": round(a["confidence"], 3), "probs": probs,
            "lat": res["latency"], "tok": res["tokens"]}


def classify_clip(card, clip_bytes, key=None):
    """Which panel is being performed in this 2 s clip? Reference: the card image."""
    def call():
        q = {"step": {"type": "choice", "criteria": _panel_criteria(card),
                      "instructions": "The first image is a numbered instruction sheet. The video is a 2-second clip of a different person following it. Which panel's action is being performed in the clip?"}}
        blocks = [gemini.text_block("INSTRUCTION SHEET:"), gemini.image_block(cards.sheet_bytes(card)),
                  gemini.text_block("CLIP:"), gemini.video_block(_clip(clip_bytes, key))]
        return _answer(card, gemini.decide(blocks, q))
    return gemini.taped(key, call)


def classify_stills(card, stills, key=None, timeout=6, tries=1):
    """Which panel is being performed in these webcam frames (taken a second apart)? The live path.
    As measured: sheet at default resolution, the two frames at resolution "low". Short timeout and a single
    try, because a late answer is useless on screen; Session.finish() asks again for windows that failed."""
    def call():
        q = {"step": {"type": "choice", "criteria": _panel_criteria(card),
                      "instructions": "The first image is a numbered instruction sheet. The next two images are consecutive webcam frames, one second apart, of a different person following it. Which panel's action is being performed in the frames?"}}
        blocks = [gemini.text_block("INSTRUCTION SHEET:"), gemini.image_block(cards.sheet_bytes(card)), gemini.text_block("FRAMES:")]
        blocks += [gemini.image_block(s, resolution="low") for s in (stills() if callable(stills) else stills)]
        return _answer(card, gemini.decide(blocks, q, timeout=timeout, tries=tries))
    return gemini.taped(key, call)


def classify_clip_text(step_list, clip_bytes, key=None):
    """Text-only variant (no card image): used to locate steps in the teaching clip, and as a baseline."""
    def call():
        crit = {s["id"]: f"{s['action']} (done when: {s['done_when']})" for s in step_list}
        crit[NONE] = "none of these: walking, searching, idle, tidying or between steps"
        q = {"step": {"type": "choice", "criteria": crit,
                      "instructions": "A person is doing a hands-on task. Which step are they performing in this 2-second clip?"}}
        res = gemini.decide([gemini.video_block(_clip(clip_bytes, key))], q)
        a = res["answers"].get("step") or {}
        if "choice" not in a or "confidence" not in a:
            raise gemini.ApiError(200, "answer without a choice: " + str(res["answers"])[:200])
        return {"step": None if a["choice"] == NONE else a["choice"], "conf": round(a["confidence"], 3),
                "probs": {("none" if k == NONE else k): round(v, 3) for k, v in (a.get("probabilities") or {}).items() if v > 0.02},
                "lat": res["latency"], "tok": res["tokens"]}
    return gemini.taped(key, call)


def has_letters(panel_jpeg, key=None):
    """Letters gate: P(the drawing contains letters or words). Digits in the corner are added later by code."""
    def call():
        q = {"letters": {"type": "noul", "instructions": "Does this drawing contain any written letters, words or brand names (ignore plain shapes and arrows)?"}}
        res = gemini.decide([gemini.image_block(panel_jpeg)], q)
        return {"p": round(res["answers"]["letters"]["noul"], 3), "lat": res["latency"]}
    return gemini.taped(key, call)


def end_state(questions, frame_jpeg, key=None):
    """End-state second vote: one yes/no per trace-leaving step on a frame taken at the end."""
    def call():
        q = {sid: {"type": "noul", "instructions": text} for sid, text in questions.items()}
        res = gemini.decide([gemini.image_block(frame_jpeg)], q)
        return {sid: round(a["noul"], 3) for sid, a in res["answers"].items()}
    return gemini.taped(key, call)
