"""Uploaded document -> pages -> lines -> readings, with progress saved to disk.

Two passes: every page is read, then every page is checked again against its
images using the handwriting notes gathered from all pages.

A job lives in data/jobs/<job_id>/: the upload, page-NNN/line-NN.jpg crops,
page-NNN/overlay.jpg, and job.json, which is rewritten after every line so the
website can show progress and a crash never loses finished lines.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

import pypdfium2 as pdfium
from PIL import Image, ImageOps

from lipi.inventory import IMAGE_EXTS, PDF_EXTS, page_to_pil
from lipi.reader import MODEL, PageResult, Reader
from lipi.segment import save_page

MAX_PAGES = 50
MAX_HAND_NOTES = 30


def document_pages(path: Path) -> list[Image.Image]:
    ext = path.suffix.lower()
    if ext in PDF_EXTS:
        with pdfium.PdfDocument(path) as pdf:
            if len(pdf) > MAX_PAGES:
                raise ValueError(f"PDF has {len(pdf)} pages; the limit is {MAX_PAGES}")
            return [page_to_pil(page) for page in pdf]
    if ext in IMAGE_EXTS:
        with Image.open(path) as im:
            return [ImageOps.exif_transpose(im).convert("RGB")]
    raise ValueError(f"unsupported file type {ext}; upload a PDF or an image")


class Job:
    def __init__(self, job_dir: Path):
        self.dir = job_dir
        self.path = job_dir / "job.json"
        self.state = json.loads(self.path.read_text(encoding="utf-8"))

    @classmethod
    def create(cls, jobs_dir: Path, job_id: str, filename: str, data: bytes) -> "Job":
        job_dir = jobs_dir / job_id
        job_dir.mkdir(parents=True)
        upload = job_dir / f"upload{Path(filename).suffix.lower()}"
        upload.write_bytes(data)
        state = {"id": job_id, "filename": filename, "upload": upload.name, "model": MODEL,
                 "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                 "status": "queued", "error": "", "cost_usd": 0.0, "pages": []}
        (job_dir / "job.json").write_text(json.dumps(state, ensure_ascii=False))
        return cls(job_dir)

    def save(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.state, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.path)

    def text(self) -> str:
        """Readable text: one passage per page."""
        return "\n\n".join(f"--- Page {i} ---\n{page.get('clean_text', '')}"
                             for i, page in enumerate(self.state["pages"], 1)) + "\n"

    def exact_text(self) -> str:
        """Line by line, exactly as written, with [ ] uncertainty markup."""
        parts = []
        for i, page in enumerate(self.state["pages"], 1):
            parts.append(f"--- Page {i} ---")
            parts += [line.get("text", "") for line in page["lines"]]
            parts.append("")
        return "\n".join(parts)


async def run(job: Job, reader: Reader | None = None) -> None:
    reader = reader or Reader()
    state = job.state
    try:
        state["status"] = "splitting"
        job.save()
        images = await asyncio.to_thread(document_pages, job.dir / state["upload"])
        for i, image in enumerate(images, 1):
            name = f"page-{i:03d}"
            src = job.dir / f"{name}.jpg"
            image.save(src, quality=95, subsampling=0)
            lines = await asyncio.to_thread(save_page, src, job.dir / name)
            state["pages"].append({"name": name, "lines": [
                {"line": l.index, "status": "pending", "box": asdict(l)} for l in lines]})
        job.save()

        state["status"] = "reading"
        job.save()

        def load(path: Path) -> Image.Image:
            with Image.open(path) as im:
                return im.copy()

        def images_of(page: dict) -> tuple[Image.Image, list[Image.Image]]:
            return (load(job.dir / f"{page['name']}.jpg"),
                    [load(job.dir / page["name"] / f"line-{l['line']:02d}.jpg") for l in page["lines"]])

        def store(page: dict, result: PageResult, stage: str) -> None:
            for line, r in zip(page["lines"], result.lines):
                line.update(status="error" if r.error else "done", text=r.text, confidence=r.confidence,
                            note=r.note, problems=r.problems, error=r.error)
            page.update(hand_notes=result.hand_notes, clean_text=result.clean_text, stage=stage)
            state["cost_usd"] = round(reader.usage.usd, 4)
            job.save()

        pages = [p for p in state["pages"] if p["lines"]]
        drafts: dict[str, PageResult] = {}

        async def first(page: dict) -> None:
            drafts[page["name"]] = result = await reader.read_page(*images_of(page))
            store(page, result, "read")

        await asyncio.gather(*(first(p) for p in pages))

        state["status"] = "checking"
        job.save()
        notes = list(dict.fromkeys(n for d in drafts.values() for n in d.hand_notes))[:MAX_HAND_NOTES]

        async def check(page: dict) -> None:
            draft = drafts[page["name"]]
            if draft.error:  # nothing to check; keep the error visible
                return
            store(page, await reader.read_page(*images_of(page), draft=draft, notes=notes), "checked")

        await asyncio.gather(*(check(p) for p in pages))
        state["status"] = "done"
    except Exception as e:  # noqa: BLE001 - surface any failure to the user
        state["status"], state["error"] = "failed", str(e)
    job.save()

