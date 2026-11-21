"""The simple baseline: ONE Hydrogen call on the whole follow video with the step list.
Never run against the live API yet (the key ran out of credit); the request shape is the same generateContent
call that named the steps."""
import re
import subprocess
import tempfile
from pathlib import Path

from . import card as cards
from . import config, gemini, video

PROMPT = """A person is supposed to perform these steps of a routine (any order unless one needs another):
%s
Watch the whole video. For each step say whether it was performed.
Answer with JSON only: {"performed": ["<step id>", ...], "not_performed": ["<step id>", ...]}"""


def stills_to_video(run_dir, dst):
    """Turn a saved live session (0000_0.jpg, 0000_1.jpg, 0001_0.jpg, ... one still a second) into a 1 fps mp4."""
    subprocess.run([video.ffmpeg(), "-hide_banner", "-loglevel", "error", "-y", "-framerate", "1", "-pattern_type", "glob",
                    "-i", str(Path(run_dir) / "*_[01].jpg"), "-c:v", "libx264", "-pix_fmt", "yuv420p", "-vf", "scale=-2:360", str(dst)],
                   check=True)
    return dst


def hydrogen_one_call(card, rec):
    """Returns {"skipped": [step ids], "lat": seconds}."""
    def call():
        live = config.RUNS / rec
        with tempfile.TemporaryDirectory() as tmp:
            if live.is_dir():
                clip = stills_to_video(live, Path(tmp) / "v.mp4")
            else:
                src = video.find_video(rec)
                if not src:
                    raise FileNotFoundError(f"no video for recording {rec}")
                # the measured recipe: 4 fps, crf 33 (a 5 min recording stays near 6-8 MB inline)
                clip = Path(tmp) / "v.mp4"
                video._run(["-i", str(src), "-an", "-vf", "scale=-2:360,fps=4", "-c:v", "libx264", "-preset", "veryfast",
                            "-crf", "33", "-pix_fmt", "yuv420p", str(clip)])
            if Path(clip).stat().st_size > 15 * 1024 * 1024:
                raise ValueError(f"baseline clip is {Path(clip).stat().st_size >> 20} MB, too large to send inline")
            listing = "\n".join(f"- {s['id']}: {s['action']}" for s in card["steps"])
            d = gemini.generate(config.MODELS["hydrogen"], [gemini.inline(Path(clip).read_bytes(), "video/mp4"), {"text": PROMPT % listing}],
                                {"responseMimeType": "application/json"})
        out = gemini.json_of(d)
        ids = set(cards.step_ids(card))
        def norm(v):
            if isinstance(v, dict):                      # {"s01": true, ...}
                v = [k for k, on in v.items() if on]
            got = set()
            for x in v or []:
                m = re.match(r"s\d+", str(x).strip().lower())
                if m:
                    got.add(m.group(0))
            return got & ids
        if not isinstance(out, dict):
            raise ValueError("unparseable baseline answer: " + str(out)[:200])
        performed, not_performed = norm(out.get("performed")), norm(out.get("not_performed"))
        if (performed | not_performed) != ids or (performed & not_performed):
            raise ValueError("baseline answer does not cover every step exactly once: " + str(out)[:200])
        return {"skipped": sorted(not_performed), "lat": d["_latency"]}
    return gemini.taped(f"baseline/hydrogen/{card['id']}/{rec}", call)
