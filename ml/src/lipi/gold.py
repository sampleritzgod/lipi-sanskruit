"""Gold transcriptions: storage and validation.

One JSON file per page at data/gold/<file_id>/<page>.json. The rules the text
must follow are in data/gold/CONVENTIONS.md; check_text enforces the
mechanical ones so that CER numbers are not polluted by typing accidents.
"""

from __future__ import annotations

import json
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

STATUSES = {"done", "skip"}

# Devanagari block plus the markup from CONVENTIONS.md: [x] unsure, [?] unreadable
# akshara, [...] damaged span. Word spaces are allowed only where the scribe left
# a gap. Everything else (Gujarati look-alikes, Latin, ASCII digits) is an error.
_DEVANAGARI = "ऀ-ॿ꣠-ꣿ"
_ALLOWED = re.compile(rf"[{_DEVANAGARI} \[\]?.]")
_MARKUP = re.compile(r"\[(\?|\.\.\.|[^\[\]?.]+)\]")


def check_text(text: str) -> list[str]:
    """Problems with a line transcription; empty if it is acceptable."""
    problems = []
    if text != unicodedata.normalize("NFC", text):
        problems.append("text is not NFC-normalized")
    bad = sorted({c for c in text if not _ALLOWED.match(c)})
    if bad:
        names = ", ".join(f"'{c}' {unicodedata.name(c, hex(ord(c)))}" for c in bad)
        problems.append(f"characters outside Devanagari: {names}")
    leftover = _MARKUP.sub("", text)
    if any(c in leftover for c in "[]"):
        problems.append("unbalanced or malformed [ ] markup")
    if "  " in text or text != text.strip():
        problems.append("double or leading/trailing spaces")
    return problems


def clean(text: str) -> str:
    return unicodedata.normalize("NFC", text).strip()


def page_path(gold_dir: Path, file_id: str, page: str) -> Path:
    return gold_dir / file_id / f"{page}.json"


def load_page(gold_dir: Path, file_id: str, page: str) -> dict:
    path = page_path(gold_dir, file_id, page)
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"file_id": file_id, "page": page, "lines": {}}


def save_line(gold_dir: Path, file_id: str, page: str, line: int, text: str,
              status: str, transcriber: str) -> dict:
    if status not in STATUSES:
        raise ValueError(f"status must be one of {sorted(STATUSES)}")
    text = clean(text)
    record = {
        "text": text,
        "status": status,
        "problems": check_text(text) if status == "done" else [],
        "transcriber": transcriber,
        "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    data = load_page(gold_dir, file_id, page)
    data["lines"][str(line)] = record
    path = page_path(gold_dir, file_id, page)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)  # atomic: a crash never leaves a half-written page
    return record
