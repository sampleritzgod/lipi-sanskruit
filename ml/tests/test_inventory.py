import csv

import pypdfium2 as pdfium
from PIL import Image

from lipi.inventory import scan, write_inventory


def make_data(tmp_path):
    raw = tmp_path / "raw"
    (raw / "manuscripts").mkdir(parents=True)
    (raw / "refs").mkdir()
    Image.new("RGB", (40, 20), "white").save(raw / "manuscripts" / "page.png")
    (raw / "manuscripts" / "ghost.heic").write_bytes(b"bplist00" + b"\0" * 127)
    pdf = pdfium.PdfDocument.new()
    pdf.new_page(72, 144)
    pdf.new_page(72, 144)
    pdf.save(raw / "refs" / "dict.pdf")
    return raw


def run(tmp_path):
    raw = make_data(tmp_path)
    entries = scan(raw, tmp_path / "processed")
    write_inventory(entries, tmp_path / "inventory.csv", tmp_path)
    with (tmp_path / "inventory.csv").open(encoding="utf-8") as f:
        return {r["path"]: r for r in csv.DictReader(f)}


def test_detects_placeholder_and_counts_pages(tmp_path):
    rows = run(tmp_path)
    assert rows["raw/manuscripts/ghost.heic"]["status"] == "broken"
    assert rows["raw/manuscripts/page.png"]["status"] == "ok"
    assert rows["raw/refs/dict.pdf"]["pages"] == "2"


def test_renders_manuscripts_but_not_refs(tmp_path):
    rows = run(tmp_path)
    page_id = rows["raw/manuscripts/page.png"]["file_id"]
    ref_id = rows["raw/refs/dict.pdf"]["file_id"]
    assert (tmp_path / "processed" / page_id / "page-001.jpg").exists()
    assert not (tmp_path / "processed" / ref_id).exists()


def test_scan_pdf_uses_embedded_image_at_native_size(tmp_path):
    raw = tmp_path / "raw" / "manuscripts"
    raw.mkdir(parents=True)
    Image.new("RGB", (640, 320), "white").save(tmp_path / "scan.jpg")
    pdf = pdfium.PdfDocument.new()
    page = pdf.new_page(100, 50)  # 640 px over 100 pt, i.e. not 300 dpi
    image = pdfium.PdfImage.new(pdf)
    image.load_jpeg(tmp_path / "scan.jpg")
    image.set_matrix(pdfium.PdfMatrix().scale(100, 50))
    page.insert_obj(image)
    page.gen_content()
    pdf.save(raw / "scan.pdf")

    [entry] = scan(tmp_path / "raw", tmp_path / "processed")
    assert (entry.width, entry.height) == (640, 320)
    with Image.open(tmp_path / "processed" / entry.file_id / "page-001.jpg") as im:
        assert im.size == (640, 320)


def test_keeps_human_columns_across_runs(tmp_path):
    rows = run(tmp_path)
    csv_path = tmp_path / "inventory.csv"
    rows["raw/manuscripts/page.png"]["condition"] = "damaged"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(next(iter(rows.values())).keys()))
        writer.writeheader()
        writer.writerows(rows.values())

    (tmp_path / "raw" / "manuscripts" / "page.png").rename(tmp_path / "raw" / "manuscripts" / "renamed.png")
    entries = scan(tmp_path / "raw", tmp_path / "processed")
    write_inventory(entries, csv_path, tmp_path)
    with csv_path.open(encoding="utf-8") as f:
        again = {r["path"]: r for r in csv.DictReader(f)}
    assert again["raw/manuscripts/renamed.png"]["condition"] == "damaged"
