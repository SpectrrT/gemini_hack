"""ffmpeg helpers. Uses the binary shipped with imageio-ffmpeg, so no system install is needed."""
import re
import shutil
import subprocess
from pathlib import Path

from . import config


def ffmpeg():
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def _run(args):
    p = subprocess.run([ffmpeg(), "-hide_banner", "-loglevel", "error", "-y", *args], capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError("ffmpeg failed: " + p.stderr[-500:])


def duration(path):
    p = subprocess.run([ffmpeg(), "-hide_banner", "-i", str(path)], capture_output=True, text=True)
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", p.stderr)
    if not m:
        raise RuntimeError(f"cannot read duration of {path}: {p.stderr[-300:]}")
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))


def normalize(src, dst, height=360, fps=15):
    """Any input (webm from the browser, phone mp4) -> small silent H.264 mp4 with a keyframe every second."""
    Path(dst).parent.mkdir(parents=True, exist_ok=True)
    _run(["-i", str(src), "-an", "-vf", f"scale=-2:{height},fps={fps}", "-c:v", "libx264", "-preset", "veryfast",
          "-crf", "28", "-g", str(fps), "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(dst)])
    return dst


def cut_windows(src, outdir, win=config.WINDOW_S, height=360, fps=15):
    """Cut `src` into consecutive `win`-second clips named 0000.mp4, 0001.mp4, ... Returns the list of paths."""
    outdir = Path(outdir)
    if outdir.exists():
        shutil.rmtree(outdir)
    outdir.mkdir(parents=True)
    _run(["-i", str(src), "-an", "-vf", f"scale=-2:{height},fps={fps}", "-c:v", "libx264", "-preset", "veryfast",
          "-crf", "28", "-pix_fmt", "yuv420p", "-force_key_frames", f"expr:gte(t,n_forced*{win})",
          "-f", "segment", "-segment_time", str(win), "-reset_timestamps", "1", str(outdir / "%04d.mp4")])
    files = sorted(outdir.glob("*.mp4"))
    # a trailing fragment much shorter than a window carries too little to classify
    if len(files) > 1 and duration(files[-1]) < win * 0.5:
        files[-1].unlink()
        files = files[:-1]
    return files


def frame_at(src, t, dst, height=360):
    Path(dst).parent.mkdir(parents=True, exist_ok=True)
    _run(["-ss", f"{max(t, 0):.2f}", "-i", str(src), "-frames:v", "1", "-vf", f"scale=-2:{height}",
          "-pix_fmt", "yuvj420p", "-q:v", "3", str(dst)])
    return dst


def find_video(name):
    """Look up a recording such as '12_43' in the known video folders."""
    for d in config.VIDEO_DIRS:
        p = d / f"{name}.mp4"
        if p.exists():
            return p
    return None
