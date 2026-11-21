"""Download every CaptainCook4D recording of one activity (default 12, the tomato salad the card was
taught on) as the 360p GoPro file, plus the human labels for them.

  python scripts/fetch_captaincook.py                 # activity 12 -> data/<id>.mp4, fixtures/eval_wide/labels.json
  python scripts/fetch_captaincook.py --skip 12_17    # leave out the teaching recording

Sources (public, the dataset's own repositories):
  links   https://github.com/CaptainCook4D/downloader   metadata/download_links.json
  labels  https://github.com/CaptainCook4D/annotations  annotation_json/error_annotations.json
          annotation_json/complete_step_annotations.json (person and kitchen ids)
The labels file written here has the same shape as fixtures/tomato/labels.json, with the per-step error
tags, person id and environment id kept.
"""
import argparse
import concurrent.futures as cf
import json
import shutil
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = "https://raw.githubusercontent.com/CaptainCook4D/"
LINKS = RAW + "downloader/main/metadata/download_links.json"
ERRORS = RAW + "annotations/main/annotation_json/error_annotations.json"
COMPLETE = RAW + "annotations/main/annotation_json/complete_step_annotations.json"


def get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "captaincook-fetch"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def download(url, dst):
    tmp = dst.with_suffix(".part")
    req = urllib.request.Request(url, headers={"User-Agent": "captaincook-fetch"})
    with urllib.request.urlopen(req, timeout=120) as r, open(tmp, "wb") as f:
        shutil.copyfileobj(r, f, 1 << 20)
    if tmp.stat().st_size < 100_000 or tmp.read_bytes()[4:8] != b"ftyp":
        tmp.unlink()
        raise RuntimeError(f"{dst.name}: the download is not an mp4")
    tmp.rename(dst)
    return dst.stat().st_size


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--activity", type=int, default=12)
    ap.add_argument("--skip", nargs="*", default=[])
    ap.add_argument("--data", default=str(ROOT / "data"))
    ap.add_argument("--labels-out", default=str(ROOT / "fixtures" / "eval_wide" / "labels.json"))
    ap.add_argument("--labels-only", action="store_true")
    a = ap.parse_args()

    links, errors, complete = get_json(LINKS), get_json(ERRORS), get_json(COMPLETE)
    num = lambda r: int(r.split("_")[1])
    labels = sorted((e for e in errors if e["activity_id"] == a.activity), key=lambda e: num(e["recording_id"]))
    for e in labels:
        c = complete.get(e["recording_id"], {})
        e["person_id"], e["environment"] = c.get("person_id"), c.get("environment")
    out = Path(a.labels_out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(labels, indent=1))
    recs = [e["recording_id"] for e in labels if e["recording_id"] not in a.skip]
    print(f"activity {a.activity}: {len(labels)} labelled recordings, labels -> {out}")
    if a.labels_only:
        return

    data = Path(a.data)
    data.mkdir(parents=True, exist_ok=True)

    def one(rec):
        dst = data / f"{rec}.mp4"
        if dst.exists():
            return rec, "already there"
        url = (links.get(rec) or {}).get("gopro_360p")
        if not url:
            return rec, "NO 360p LINK"
        try:
            return rec, f"{download(url, dst) >> 20} MB"
        except Exception as ex:                          # one bad link must not stop the rest
            return rec, f"FAILED {type(ex).__name__}: {ex}"

    bad = 0
    with cf.ThreadPoolExecutor(6) as ex:
        for rec, msg in ex.map(one, recs):
            print(f"  {rec:8} {msg}")
            bad += msg.startswith(("FAILED", "NO"))
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
