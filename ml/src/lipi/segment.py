"""Cut manuscript pages into single-line images.

For each data/processed/<file_id>/page-NNN.jpg of a manuscript this writes
data/lines/<file_id>/page-NNN/line-NN.jpg, a lines.json with the boxes, and an
overlay.jpg to eyeball the result.

Method (classical, no model): the text block is the widest gap between the red
vertical rulings of a pothi leaf (or the whole page when there are none). Inside
it, dark non-red pixels are ink; the row profile of ink has one hump per text
line, spaced at a regular pitch. Cuts go at the profile minimum between humps.
This is good enough for straight pothi lines; a trained baseline segmenter
replaces it when pages with curved or crowded lines turn up.
"""

from __future__ import annotations

import argparse
import csv
import json
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from scipy.ndimage import gaussian_filter1d
from scipy.signal import find_peaks

RED_MIN_DIFF = 60  # red channel above green and blue by this much = red ink
RULING_MIN_COVER = 0.5  # a column is a ruling if this share of it is red
BLOCK_PAD = 12  # px of slack around the text block, for strokes touching a ruling
LINE_OVERLAP = 0.15  # share of pitch each line crop extends past its cuts (matras)


@dataclass
class Line:
    index: int
    x0: int
    y0: int
    x1: int
    y1: int


def red_mask(rgb: np.ndarray) -> np.ndarray:
    r, g, b = (rgb[..., i].astype(int) for i in range(3))
    return (r - g > RED_MIN_DIFF) & (r - b > RED_MIN_DIFF)


def text_block_x(red: np.ndarray) -> tuple[int, int]:
    """Left/right x of the widest red-free span of columns."""
    is_ruling = red.mean(0) > RULING_MIN_COVER
    width = len(is_ruling)
    best, start = (0, width), None
    best_len = -1
    for x in range(width + 1):
        free = x < width and not is_ruling[x]
        if free and start is None:
            start = x
        elif not free and start is not None:
            if x - start > best_len:
                best, best_len = (start, x), x - start
            start = None
    if best_len == width:  # no rulings at all
        return 0, width
    return max(best[0] - BLOCK_PAD, 0), min(best[1] + BLOCK_PAD, width)


def otsu(values: np.ndarray) -> float:
    hist, edges = np.histogram(values, bins=256, range=(0, 256))
    p = hist / hist.sum()
    omega = np.cumsum(p)
    mu = np.cumsum(p * np.arange(256))
    with np.errstate(divide="ignore", invalid="ignore"):
        between = (mu[-1] * omega - mu) ** 2 / (omega * (1 - omega))
    # The dark class includes the chosen bin, so the cut is that bin's upper edge.
    return float(edges[np.nanargmax(between) + 1])


def line_pitch(profile: np.ndarray) -> float:
    """Typical distance between text lines, from the profile's autocorrelation."""
    p = profile - profile.mean()
    ac = np.correlate(p, p, mode="full")[len(p) - 1:]
    lo, hi = 15, max(len(p) // 3, 16)
    peaks, _ = find_peaks(ac[lo:hi])
    if len(peaks) == 0:
        return float(len(p))
    return float(lo + peaks[np.argmax(ac[lo:hi][peaks])])


def segment_page(rgb: np.ndarray) -> list[Line]:
    red = red_mask(rgb)
    x0, x1 = text_block_x(red)
    gray = rgb[:, x0:x1].mean(2)
    block_red = red[:, x0:x1]
    ink = (gray < otsu(gray[~block_red])) & ~block_red

    profile = ink.mean(1)
    pitch = line_pitch(profile)
    smooth = gaussian_filter1d(profile, sigma=pitch / 6)
    peaks, _ = find_peaks(smooth, distance=pitch * 0.6, prominence=smooth.max() * 0.15)
    if len(peaks) == 0:
        return []

    cuts = [int(a + np.argmin(smooth[a:b])) for a, b in zip(peaks[:-1], peaks[1:])]
    half = pitch / 2
    bounds = [int(peaks[0] - half)] + cuts + [int(peaks[-1] + half)]
    pad = int(pitch * LINE_OVERLAP)
    height = rgb.shape[0]
    return [
        Line(i + 1, x0, max(top - pad, 0), x1, min(bottom + pad, height))
        for i, (top, bottom) in enumerate(zip(bounds[:-1], bounds[1:]))
    ]


def save_page(page_path: Path, out_dir: Path) -> list[Line]:
    with Image.open(page_path) as im:
        rgb = np.asarray(im.convert("RGB"))
    lines = segment_page(rgb)
    out_dir.mkdir(parents=True, exist_ok=True)
    page = Image.fromarray(rgb)
    for line in lines:
        page.crop((line.x0, line.y0, line.x1, line.y1)).save(
            out_dir / f"line-{line.index:02d}.jpg", quality=95, subsampling=0)
    (out_dir / "lines.json").write_text(json.dumps([asdict(l) for l in lines], indent=1))

    overlay = page.copy()
    draw = ImageDraw.Draw(overlay)
    for line in lines:
        color = (0, 90, 255) if line.index % 2 else (0, 170, 60)
        draw.rectangle((line.x0, line.y0, line.x1, line.y1), outline=color, width=3)
        draw.text((line.x0 - 40, line.y0 + 5), str(line.index), fill=color)
    overlay.save(out_dir / "overlay.jpg", quality=80)
    return lines


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data", type=Path, default=Path(__file__).resolve().parents[3] / "data")
    args = parser.parse_args()
    data = args.data.resolve()

    with (data / "inventory.csv").open(newline="", encoding="utf-8") as f:
        ids = [r["file_id"] for r in csv.DictReader(f)
               if r["source"] == "manuscripts" and r["status"] == "ok"]
    total = 0
    for file_id in dict.fromkeys(ids):
        for page_path in sorted((data / "processed" / file_id).glob("page-*.jpg")):
            lines = save_page(page_path, data / "lines" / file_id / page_path.stem)
            total += len(lines)
            print(f"{file_id}/{page_path.stem}: {len(lines)} lines")
    print(f"{total} lines written to {data / 'lines'}")


if __name__ == "__main__":
    main()
