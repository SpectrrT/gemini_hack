"""HTTP routes for fast sequences (the /signs page). Registered on the app in server.py."""
import base64
import json
import tempfile
from pathlib import Path

from flask import Blueprint, abort, jsonify, render_template_string, request, send_file, send_from_directory

from . import card as cards
from . import config, gemini, signs, video

bp = Blueprint("signs", __name__)
PRESETS = config.FIXTURES / "sequence_presets.json"


def _kit(kid):
    try:
        return signs.load(kid)
    except FileNotFoundError:
        abort(404)


def _session(sid):
    try:
        return signs.get(sid)
    except KeyError:
        abort(404)


def _image(data):
    return base64.b64decode(data.split(",", 1)[-1])


def _public(kit):
    out = dict(kit)
    out["signs"] = [dict(s, picture=f"/signs/kit/{kit['id']}/{s.get('panel') or s['ref']}?v={s.get('v', 0)}",
                         photo=f"/signs/kit/{kit['id']}/{s['ref']}?v={s.get('v', 0)}", drawn=bool(s.get("panel")))
                    for s in kit["signs"]]
    return out


@bp.get("/signs")
def page():
    return send_from_directory(config.ROOT / "web", "signs.html")


@bp.get("/signs/kit/<kid>/<name>")
def kit_file(kid, name):
    return send_from_directory(signs.kit_dir(kid), name)


@bp.get("/api/signs/status")
def status():
    presets = json.loads(PRESETS.read_text()) if PRESETS.exists() else []
    return jsonify({"kits": signs.list_kits(), "tape": gemini.mode(), "cards": cards.list_cards(),
                    "presets": [{"id": p["id"], "title": p["title"], "signs": p["signs"], "sequences": len(p["sequences"]),
                                 "note": p.get("note", "")} for p in presets]})


@bp.post("/api/signs/kits")
def kit_new():
    d = request.get_json(silent=True) or {}
    if d.get("from_card"):
        return jsonify(_public(signs.from_card(cards.load(d["from_card"]))))
    kit = signs.new(d.get("title") or "Signs")
    if d.get("preset"):
        preset = next((p for p in json.loads(PRESETS.read_text()) if p["id"] == d["preset"]), None)
        if not preset:
            abort(400, "unknown preset")
        kit["title"], kit["preset"] = preset["title"], preset     # sign names to teach; sequences are added as signs arrive
        signs.save(kit)
    return jsonify(_public(kit))


@bp.get("/api/signs/kits/<kid>")
def kit_get(kid):
    return jsonify(_public(_kit(kid)))


@bp.post("/api/signs/kits/<kid>/signs")
def sign_add(kid):
    _kit(kid)
    d = request.get_json()
    kit = signs.add_sign(kid, d["name"], _image(d["image"]))
    preset = kit.get("preset")
    if preset:                                # a preset sequence becomes available once all its signs are taught
        have = {s["name"].lower() for s in kit["signs"]}
        known = {q["id"] for q in kit["sequences"]}
        for q in preset["sequences"]:
            if cards.slug(q["name"]) not in known and all(x.lower() in have for x in q["signs"]):
                kit = signs.set_sequence(kid, q["name"], q["signs"])
    return jsonify(_public(kit))


@bp.post("/api/signs/kits/<kid>/signs/<sid>/delete")
def sign_delete(kid, sid):
    _kit(kid)
    return jsonify(_public(signs.remove_sign(kid, sid)))


@bp.post("/api/signs/kits/<kid>/sequences")
def seq_set(kid):
    _kit(kid)
    d = request.get_json()
    try:
        return jsonify(_public(signs.set_sequence(kid, d["name"], d["signs"], d.get("id"))))
    except ValueError as e:
        abort(400, str(e))


@bp.post("/api/signs/kits/<kid>/sequences/<qid>/delete")
def seq_delete(kid, qid):
    _kit(kid)
    return jsonify(_public(signs.remove_sequence(kid, qid)))


@bp.post("/api/signs/sessions")
def session_new():
    d = request.get_json()
    if gemini.mode() == "replay":
        abort(400, "The server is in replay mode (no API calls). Restart without WORDLESS_TAPE=replay for the camera.")
    kit = _kit(d["kit"])
    if not kit["signs"]:
        abort(400, "This kit has no signs yet: teach some first.")
    try:
        s = signs.Session(kit, mode=d.get("mode", "identify"), target=d.get("target"))
    except ValueError as e:
        abort(400, str(e))
    return jsonify(s.state())


@bp.post("/api/signs/sessions/<sid>/frame")
def session_frame(sid):
    s = _session(sid)
    d = request.get_json()
    ok = s.add_frame(int(d["i"]), float(d["t"]), _image(d["image"]))
    return jsonify({"ok": ok})


@bp.get("/api/signs/sessions/<sid>")
def session_state(sid):
    return jsonify(_session(sid).state())


@bp.post("/api/signs/sessions/<sid>/finish")
def session_finish(sid):
    s = _session(sid)
    s.finish()
    return jsonify(s.state())


@bp.post("/api/signs/kits/<kid>/clip")
def clip(kid):
    """Score an uploaded clip through the same path as the camera."""
    kit = _kit(kid)
    f = request.files.get("clip")
    if not f:
        abort(400, "no clip")
    with tempfile.TemporaryDirectory() as tmp:
        raw = Path(tmp) / "in"
        f.save(raw)
        mp4 = video.normalize(raw, Path(tmp) / "clip.mp4")
        try:
            s = signs.run_video(kit, mp4, fps=float(request.form.get("fps", 4)), mode=request.form.get("mode", "identify"),
                                target=request.form.get("target") or None)
        except ValueError as e:
            abort(400, str(e))
    return jsonify(s.state())


SHEET = """<!doctype html><meta charset=utf-8><title>{{title}}</title>
<style>
  body { font-family: Helvetica, Arial, sans-serif; margin: 24px; color:#111; }
  .bar { margin-bottom: 14px; } @media print { .bar { display:none; } }
  .strip { display:flex; flex-wrap:wrap; gap:10px; align-items:center; }
  .cell { position:relative; border:3px solid #111; width:220px; height:165px; }
  .cell img { width:100%; height:100%; object-fit:contain; background:#fff; }
  .n { position:absolute; left:0; top:0; background:#111; color:#fff; font-weight:700; font-size:20px; padding:2px 9px; }
  .arrow { font-size:34px; }
</style>
<div class=bar><button onclick="print()">Print</button></div>
<div class=strip>{% for p in pics %}<div class=cell><span class=n>{{loop.index}}</span><img src="{{p}}"></div>{% if not loop.last %}<span class=arrow>&#8594;</span>{% endif %}{% endfor %}</div>
"""


@bp.get("/print/signs/<kid>/<qid>")
def print_sequence(kid, qid):
    """The sequence as a strip of pictures with no words: the sheet handed to the next person."""
    kit = _public(_kit(kid))
    q = next((q for q in kit["sequences"] if q["id"] == qid), None)
    if not q:
        abort(404)
    pic = {s["id"]: s["picture"] for s in kit["signs"]}
    return render_template_string(SHEET, title=q["name"], pics=[pic[x] for x in q["signs"]])
