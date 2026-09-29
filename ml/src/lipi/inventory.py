"""Build data/inventory.csv from everything under data/raw.

Layout: data/raw/<source>/<file>, where <source> is book, manuscripts or refs.

Machine columns are recomputed on every run. Human columns (script, language,
era, condition, rotation, notes) are carried over from the previous inventory,
matched by sha256, so files can be renamed or moved without losing that work.

Pages of book and manuscript files are rendered to
data/processed/<file_id>/page-NNN.jpg for the later pipeline stages. Reference
PDFs are only counted here; their text is extracted in the RAG phase.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
from dataclasses import dataclass, field
from pathlib import Path

import pillow_heif
import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_c
from PIL import Image, ImageOps

pillow_heif.register_heif_opener()

IMAGE_EXTS = {".heic", ".heif", ".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp"}
PDF_EXTS = {".pdf"}
RENDER_SOURCES = {"book", "manuscripts"}
PDF_DPI = 300
JPEG_QUALITY = 95

MACHINE_COLS = ["file_id", "path", "source", "kind", "pages", "width", "height",
                "bytes", "status", "problem", "sha256"]
# condition: clear | average | damaged (the accuracy classes in PLAN.md)
# rotation: 0 | 90 | 180 | 270, clockwise degrees needed to make text upright
HUMAN_COLS = ["script", "language", "era", "condition", "rotation", "notes"]
COLUMNS = MACHINE_COLS + HUMAN_COLS


@dataclass
class Entry:
    path: Path
    source: str
    kind: str
    sha256: str
    bytes: int
    pages: int = 0
    width: int = 0
    height: int = 0
    status: str = "ok"
    problem: str = ""
    images: list[Image.Image] = field(default_factory=list, repr=False)

    @property
    def file_id(self) -> str:
        return self.sha256[:12]


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def is_apple_placeholder(path: Path) -> bool:
    # Failed Photos/iCloud exports leave a tiny NSKeyedArchiver plist named .heic.
    with path.open("rb") as f:
        return f.read(8) == b"bplist00"


def load_image(entry: Entry, render: bool) -> None:
    if is_apple_placeholder(entry.path):
        entry.status, entry.problem = "broken", "apple placeholder, no image data; re-export from Photos"
        return
    try:
        with Image.open(entry.path) as im:
            im = ImageOps.exif_transpose(im).convert("RGB")
            entry.pages, (entry.width, entry.height) = 1, im.size
            if render:
                entry.images = [im.copy()]
    except Exception as e:  # noqa: BLE001 - any decode failure means the file is unusable
        entry.status, entry.problem = "broken", f"cannot decode image: {e}"


def scan_image_of(page: pdfium.PdfPage) -> pdfium.PdfImage | None:
    """The page's only image, if the page is a plain scan.

    Archive PDFs (e.g. kobatirth.org) overlay header/footer text on the scan;
    taking the embedded image skips that text and avoids resampling.
    """
    images = [o for o in page.get_objects() if o.type == pdfium_c.FPDF_PAGEOBJ_IMAGE]
    return images[0] if len(images) == 1 else None


def page_to_pil(page: pdfium.PdfPage) -> Image.Image:
    image = scan_image_of(page)
    if image is not None:
        return image.get_bitmap().to_pil().convert("RGB")
    return page.render(scale=PDF_DPI / 72).to_pil().convert("RGB")


def load_pdf(entry: Entry, render: bool) -> None:
    try:
        pdf = pdfium.PdfDocument(entry.path)
    except Exception as e:  # noqa: BLE001
        entry.status, entry.problem = "broken", f"cannot open pdf: {e}"
        return
    with pdf:
        entry.pages = len(pdf)
        if entry.pages:
            first = pdf[0]
            image = scan_image_of(first)
            if image is not None:
                entry.width, entry.height = image.get_px_size()
            else:
                w, h = first.get_size()
                entry.width, entry.height = round(w * PDF_DPI / 72), round(h * PDF_DPI / 72)
        if render:
            entry.images = [page_to_pil(page) for page in pdf]


def scan(raw_dir: Path, processed_dir: Path) -> list[Entry]:
    entries = []
    for path in sorted(p for p in raw_dir.rglob("*") if p.is_file() and not p.name.startswith(".")):
        ext = path.suffix.lower()
        if ext in IMAGE_EXTS:
            kind = "image"
        elif ext in PDF_EXTS:
            kind = "pdf"
        else:
            continue
        rel = path.relative_to(raw_dir)
        source = rel.parts[0] if len(rel.parts) > 1 else "unsorted"
        entry = Entry(path=path, source=source, kind=kind, sha256=sha256_of(path),
                      bytes=path.stat().st_size)
        out_dir = processed_dir / entry.file_id
        render = source in RENDER_SOURCES and not out_dir.exists()
        (load_image if kind == "image" else load_pdf)(entry, render)
        if entry.images:
            out_dir.mkdir(parents=True)
            for i, im in enumerate(entry.images, 1):
                im.save(out_dir / f"page-{i:03d}.jpg", quality=JPEG_QUALITY, subsampling=0)
            entry.images = []
        entries.append(entry)
    return entries


def read_human_columns(csv_path: Path) -> dict[str, dict[str, str]]:
    if not csv_path.exists():
        return {}
    with csv_path.open(newline="", encoding="utf-8") as f:
        return {row["sha256"]: {c: row.get(c, "") for c in HUMAN_COLS} for row in csv.DictReader(f)}


def write_inventory(entries: list[Entry], csv_path: Path, root: Path) -> None:
    human = read_human_columns(csv_path)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        for e in entries:
            row = {
                "file_id": e.file_id, "path": e.path.relative_to(root).as_posix(),
                "source": e.source, "kind": e.kind, "pages": e.pages,
                "width": e.width, "height": e.height, "bytes": e.bytes,
                "status": e.status, "problem": e.problem, "sha256": e.sha256,
            }
            row.update(human.get(e.sha256, dict.fromkeys(HUMAN_COLS, "")))
            writer.writerow(row)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data", type=Path, default=Path(__file__).resolve().parents[3] / "data")
    args = parser.parse_args()

    data = args.data.resolve()
    entries = scan(data / "raw", data / "processed")
    write_inventory(entries, data / "inventory.csv", data)

    ok = [e for e in entries if e.status == "ok"]
    broken = [e for e in entries if e.status != "ok"]
    by_source: dict[str, int] = {}
    for e in ok:
        by_source[e.source] = by_source.get(e.source, 0) + e.pages
    print(f"{len(entries)} files: {len(ok)} ok, {len(broken)} broken")
    for source, pages in sorted(by_source.items()):
        print(f"  {source}: {pages} pages")
    by_problem: dict[str, list[Entry]] = {}
    for e in broken:
        by_problem.setdefault(e.problem, []).append(e)
    for problem, group in by_problem.items():
        print(f"broken ({len(group)}): {problem}")
        for e in group[:3]:
            print(f"  {e.path.relative_to(data)}")
        if len(group) > 3:
            print(f"  ... and {len(group) - 3} more (see inventory.csv)")
    print(f"wrote {data / 'inventory.csv'}")


if __name__ == "__main__":
    main()
