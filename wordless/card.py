"""The card: an ordered list of steps, each with a real keyframe and a line-art panel, plus the sheet image
that is sent to the checker as the reference."""
import io
import json
import math
import re
import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from . import config

CELL = (400, 225)   # the tested sheet was a 3 x 3 grid of 400 x 225 cells


def card_dir(card_id):
    return config.CARDS / card_id


def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "card"


def new_id(title="card"):
    return f"{slug(title)}-{time.strftime('%H%M%S')}"


def load(card_id):
    p = card_dir(card_id) / "card.json"
    if not p.exists():
        raise FileNotFoundError(f"no card '{card_id}'")
    return json.loads(p.read_text())


def save(card):
    d = card_dir(card["id"])
    d.mkdir(parents=True, exist_ok=True)
    (d / "card.json").write_text(json.dumps(card, indent=1))
    return card


def list_cards():
    out = []
    if config.CARDS.is_dir():
        for p in sorted(config.CARDS.glob("*/card.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            c = json.loads(p.read_text())
            out.append({"id": c["id"], "title": c.get("title", c["id"]), "steps": len(c["steps"]), "source": c.get("source")})
    return out


def steps(card):
    """Steps that have a panel, in card order."""
    return card["steps"]


def step_ids(card):
    return [s["id"] for s in card["steps"]]


def panel_number(card, sid):
    return step_ids(card).index(sid) + 1


def _font(size):
    for name in ("/System/Library/Fonts/Helvetica.ttc", "/System/Library/Fonts/Supplemental/Arial Bold.ttf", "DejaVuSans-Bold.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def fit(img, size):
    """Letterbox `img` onto a white canvas of `size`."""
    img = img.convert("RGB")
    img.thumbnail(size, Image.LANCZOS)
    canvas = Image.new("RGB", size, "white")
    canvas.paste(img, ((size[0] - img.width) // 2, (size[1] - img.height) // 2))
    return canvas


def compose_sheet(card, cell=CELL):
    """Numbered grid of the panels. Digits are the only text on the card."""
    d = card_dir(card["id"])
    n = len(card["steps"])
    cols = n if n <= 3 else 2 if n == 4 else 3
    rows = math.ceil(n / cols)
    line = 3
    sheet = Image.new("RGB", (cols * cell[0], rows * cell[1]), "black")
    draw = ImageDraw.Draw(sheet)
    font = _font(26)
    for k, s in enumerate(card["steps"]):
        x, y = (k % cols) * cell[0], (k // cols) * cell[1]
        inner = (cell[0] - 2 * line, cell[1] - 2 * line)
        panel = fit(Image.open(d / s["panel"]), inner)
        sheet.paste(panel, (x + line, y + line))
        draw.rectangle([x + line + 4, y + line + 4, x + line + 42, y + line + 42], fill="black")
        draw.text((x + line + 23, y + line + 23), str(k + 1), fill="white", font=font, anchor="mm")
    for k in range(n, cols * rows):       # blank cells stay white
        x, y = (k % cols) * cell[0], (k // cols) * cell[1]
        draw.rectangle([x + line, y + line, x + cell[0] - line - 1, y + cell[1] - line - 1], fill="white")
    out = d / "sheet.jpg"
    sheet.save(out, quality=90)
    return out


def sheet_bytes(card):
    """The reference image sent to the checker. A card may pin the exact bytes that were sent when its
    recorded answers were made (`sheet_as_sent`), so replays stay faithful."""
    d = card_dir(card["id"])
    p = d / (card.get("sheet_as_sent") or "sheet.jpg")
    return p.read_bytes()


def to_jpeg(data, max_side=1024, quality=88):
    img = Image.open(io.BytesIO(data)).convert("RGB")
    img.thumbnail((max_side, max_side), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=quality)
    return buf.getvalue()
