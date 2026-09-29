import asyncio
import json

from PIL import Image

from lipi import pipeline
from lipi.reader import PageResult, Result, Usage
from test_segment import fake_pothi


class FakeReader:
    def __init__(self):
        self.usage = Usage()
        self.reviews = []

    async def read_page(self, page, lines, draft=None, notes=None):
        if draft is not None:
            self.reviews.append(notes)
            fixed = [Result(r.text.replace("?", "३"), "high", "", []) if not r.error else r for r in draft.lines]
            return PageResult(fixed, draft.hand_notes, "पंक्ति१ पंक्ति३")
        results = [Result(f"पंक्ति{'?' if i == 3 else i}", "medium", "", []) for i in range(1, len(lines) + 1)]
        results[1] = Result("", "low", "", [], error="the model skipped this line")
        return PageResult(results, ["ख written like ष"], "draft")


def test_job_reads_then_checks_every_page(tmp_path):
    Image.fromarray(fake_pothi(n_lines=4)).save(tmp_path / "leaf.png")
    job = pipeline.Job.create(tmp_path / "jobs", "job1", "leaf.png", (tmp_path / "leaf.png").read_bytes())
    reader = FakeReader()
    asyncio.run(pipeline.run(job, reader))

    state = json.loads((tmp_path / "jobs" / "job1" / "job.json").read_text(encoding="utf-8"))
    assert state["status"] == "done"
    page = state["pages"][0]
    assert len(page["lines"]) == 4
    assert reader.reviews == [["ख written like ष"]]  # checked once, with notes from all pages
    assert page["stage"] == "checked"
    assert page["lines"][2]["text"] == "पंक्ति३"  # fixed by the checking pass
    assert [l["status"] for l in page["lines"]].count("error") == 1
    assert job.text() == "--- Page 1 ---\nपंक्ति१ पंक्ति३\n"
    assert job.exact_text().startswith("--- Page 1 ---\nपंक्ति1\n\nपंक्ति३")


def test_unsupported_upload_fails_cleanly(tmp_path):
    job = pipeline.Job.create(tmp_path / "jobs", "job2", "notes.docx", b"not a manuscript")
    asyncio.run(pipeline.run(job, FakeReader()))
    assert job.state["status"] == "failed"
    assert "unsupported file type" in job.state["error"]
