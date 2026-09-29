"""Lipi website: upload a manuscript PDF or photo, get its lines read.

    uv run lipi-web            # http://127.0.0.1:8000
"""

from __future__ import annotations

import argparse
import asyncio
import re
import uuid
import webbrowser
from pathlib import Path
from urllib.parse import quote

import uvicorn
from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse

from lipi import pipeline
from lipi.inventory import IMAGE_EXTS, PDF_EXTS
from lipi.reader import DATA

JOBS = DATA / "jobs"
MAX_UPLOAD_BYTES = 100 * 1024 * 1024
SAFE = re.compile(r"^[A-Za-z0-9_-]+$")
PAGE = Path(__file__).with_name("web.html")

app = FastAPI(title="Lipi")
_running: set[asyncio.Task] = set()


@app.on_event("startup")
def mark_interrupted_jobs() -> None:
    JOBS.mkdir(parents=True, exist_ok=True)
    for path in JOBS.glob("*/job.json"):
        job = pipeline.Job(path.parent)
        if job.state["status"] in {"queued", "splitting", "reading", "checking"}:
            job.state.update(status="failed", error="interrupted: the server stopped while reading")
            job.save()


def load_job(job_id: str) -> pipeline.Job:
    if not SAFE.match(job_id) or not (JOBS / job_id / "job.json").exists():
        raise HTTPException(404, "no such job")
    return pipeline.Job(JOBS / job_id)


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return PAGE.read_text(encoding="utf-8")


@app.post("/api/jobs")
async def create_job(file: UploadFile) -> dict:
    name = Path(file.filename or "upload").name
    if Path(name).suffix.lower() not in PDF_EXTS | IMAGE_EXTS:
        raise HTTPException(400, "Upload a PDF or an image (JPG, PNG, HEIC, TIFF).")
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "File is larger than 100 MB.")
    job = pipeline.Job.create(JOBS, uuid.uuid4().hex[:12], name, data)
    task = asyncio.create_task(pipeline.run(job))
    _running.add(task)
    task.add_done_callback(_running.discard)
    return {"id": job.state["id"]}


@app.get("/api/jobs")
def list_jobs() -> list[dict]:
    jobs = [pipeline.Job(p.parent).state for p in JOBS.glob("*/job.json")]
    jobs.sort(key=lambda s: s["created"], reverse=True)
    return [{k: s[k] for k in ("id", "filename", "created", "status", "cost_usd")} for s in jobs[:50]]


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> dict:
    return load_job(job_id).state


@app.get("/api/jobs/{job_id}/text", response_class=PlainTextResponse)
def job_text(job_id: str, exact: bool = False) -> PlainTextResponse:
    job = load_job(job_id)
    stem = Path(job.state["filename"]).stem + ("-exact" if exact else "")
    return PlainTextResponse(job.exact_text() if exact else job.text(), headers={
        "Content-Disposition": f"attachment; filename*=UTF-8''{quote(stem)}.txt"})


@app.get("/api/jobs/{job_id}/img/{page}/{image}")
def job_image(job_id: str, page: str, image: str) -> FileResponse:
    job = load_job(job_id)
    stem = image.removesuffix(".jpg")
    if not (SAFE.match(page) and SAFE.match(stem)):
        raise HTTPException(404, "no such image")
    path = job.dir / page / f"{stem}.jpg"
    if not path.is_file():
        raise HTTPException(404, "no such image")
    return FileResponse(path, media_type="image/jpeg")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    url = f"http://127.0.0.1:{args.port}/"
    print(f"Lipi running at {url} (Ctrl+C to stop)")
    if not args.no_browser:
        webbrowser.open(url)
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
