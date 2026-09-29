"""Read manuscript pages into Devanagari with Claude, one request per page.

The model sees the whole page for context plus every line crop at full
resolution, so it can learn the scribe's hand across lines and follow the
narrative. Every request shares one cached prefix: the instructions plus the
lipi-book glyph tables (medieval letter forms -> modern Devanagari). Only the
page changes per request, so the reference pages are billed at cache-read
rates after the first call.
"""

from __future__ import annotations

import asyncio
import base64
import csv
import io
import os
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Literal

import anthropic
from dotenv import load_dotenv
from PIL import Image
from pydantic import BaseModel

from lipi.gold import check_text, clean

ROOT = Path(__file__).resolve().parents[3]
DATA = ROOT / "data"
MODEL = "claude-opus-5"
EFFORT = "high"
REFERENCE_MAX_EDGE = 2000  # book photos are 4032 px; this keeps the glyphs legible
MAX_CONCURRENT = 3  # pages in flight at once
MAX_EDGE = 2576  # the model's largest image edge; bigger images get downscaled

# USD per million tokens for MODEL, for the cost shown in the UI.
PRICE_IN, PRICE_OUT, PRICE_CACHE_READ, PRICE_CACHE_WRITE = 5.00, 25.00, 0.50, 6.25

INSTRUCTIONS = """\
You transcribe pages of handwritten Indian manuscripts line by line (old \
Nagari, especially Jain Nagari of the 15th-19th centuries; Sanskrit, Prakrit, Old \
Gujarati, Hindi) into modern Unicode Devanagari.

The attached reference pages come from a manuscript-reading course. Each row \
shows the historical forms of a letter (left, "મધ્યકાલીન વર્ણો"), the modern \
Devanagari letter, and the Gujarati letter. They cover vowels, consonants, the \
क and ध barakhadi, numerals and conjuncts. Use them to identify letter shapes.

Transcription rules (diplomatic: write what the scribe wrote):
- Output only modern Devanagari (U+0900-U+097F). Never Gujarati letters, Latin \
letters or ASCII digits. Numerals as Devanagari digits.
- Keep the scribe's spelling, even if it looks wrong. Do not correct or \
normalise it, and do not replace it with a better-known version of the text.
- Words usually run together. Do not add spaces. Put a single space only where \
the scribe left a clear gap.
- पृष्ठमात्रा: a vertical stroke written before a letter is the e/ai/o/au vowel \
sign of that letter. Write the modern form (के, कै, को, कौ), not a separate letter.
- Keep anusvara vs. nasal consonant, avagraha ऽ, and dandas । ॥ exactly as written.
- You get the whole page for context, then each line cut out and numbered. \
A line crop may show pieces of the lines above and below: transcribe only the \
main line through its middle, from its first letter to its last. Give exactly \
one reading per numbered line, in order.
- Ignore red ruling lines, marginal notes and stamps.
- Uncertainty markup: [x] around an akshara you are not sure of (your best \
reading inside); [?] for one akshara you cannot read at all; [...] for a \
damaged or missing stretch.

Use your knowledge of the language to decide between similar letter shapes, \
but when the shapes and the language disagree, follow the shapes and mark the \
akshara with [ ].

Before transcribing, study the scribe's hand across the whole page. The same \
letters, conjuncts and names recur: a shape that is unclear in one line is \
often clear in another, and a recurring odd shape usually has one consistent \
reading. Old forms differ from modern ones (for example ख, भ, ज्ञ and \
the e/o strokes), so check the reference tables before settling on an \
unusual consonant cluster. Readings must still come from the shapes on the \
page, not from a remembered version of the text.

For each line give a confidence: high = every akshara is certain; medium = \
one or two aksharas marked [ ]; low = more than that. Add a short note only \
if useful. Also list the scribe's letter-form habits you relied on \
(which shape stands for which letter), as short hand notes.

Finally, give the page as clean, readable text (clean_text): the same letters \
and spelling as your line readings, but with a space between words, words \
that break across a line end joined, and dandas as written. No [ ] around \
unsure letters in clean_text (use your best reading); keep [?] and [...] for \
what cannot be read. Do not modernise or correct the spelling.\
"""

REVIEW = """Below is a first reading of this page, and notes on this scribe's hand \
gathered from every page of the manuscript. Check each line again, akshara by \
akshara, against its line image. Correct misread letters, especially where \
the notes show a letter form the first reading missed. Keep what the image \
supports; do not smooth the text into more fluent Sanskrit or Hindi than the \
shapes show. Return the full corrected page in the same format.\
"""


class LineReading(BaseModel):
    line: int
    text: str
    confidence: Literal["high", "medium", "low"]
    note: str


class PageReading(BaseModel):
    hand_notes: list[str]
    lines: list[LineReading]
    clean_text: str


PAGE_SCHEMA = {
    "type": "object",
    "properties": {
        "hand_notes": {"type": "array", "items": {"type": "string"}},
        "lines": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "line": {"type": "integer"},
                "text": {"type": "string", "description": "Unicode Devanagari with [ ] markup"},
                "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                "note": {"type": "string", "description": "Short note on difficulties, or empty"},
            },
            "required": ["line", "text", "confidence", "note"],
            "additionalProperties": False,
        }},
        "clean_text": {"type": "string", "description": "The page as readable text with word spaces"},
    },
    "required": ["hand_notes", "lines", "clean_text"],
    "additionalProperties": False,
}


@dataclass
class Usage:
    input: int = 0
    output: int = 0
    cache_read: int = 0
    cache_write: int = 0

    def add(self, u) -> None:
        self.input += u.input_tokens or 0
        self.output += u.output_tokens or 0
        self.cache_read += u.cache_read_input_tokens or 0
        self.cache_write += u.cache_creation_input_tokens or 0

    @property
    def usd(self) -> float:
        return (self.input * PRICE_IN + self.output * PRICE_OUT + self.cache_read * PRICE_CACHE_READ
                + self.cache_write * PRICE_CACHE_WRITE) / 1e6


@dataclass
class Result:
    text: str
    confidence: str
    note: str
    problems: list[str]
    error: str = ""


@dataclass
class PageResult:
    lines: list[Result]
    hand_notes: list[str]
    clean_text: str
    error: str = ""


def jpeg_block(image: Image.Image, max_edge: int | None = None) -> dict:
    image = image.convert("RGB")
    if max_edge and max(image.size) > max_edge:
        image = image.copy()
        image.thumbnail((max_edge, max_edge), Image.LANCZOS)
    buf = io.BytesIO()
    image.save(buf, "JPEG", quality=92)
    data = base64.standard_b64encode(buf.getvalue()).decode()
    return {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": data}}


@cache
def reference_blocks() -> tuple[dict, ...]:
    """The lipi-book glyph tables, upright, from data/inventory.csv."""
    with (DATA / "inventory.csv").open(newline="", encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if r["source"] == "book" and r["status"] == "ok"]
    blocks = []
    for row in sorted(rows, key=lambda r: r["path"]):
        with Image.open(DATA / "processed" / row["file_id"] / "page-001.jpg") as im:
            rotation = int(row["rotation"] or 0)
            upright = im.rotate(-rotation, expand=True) if rotation else im.copy()
        blocks.append(jpeg_block(upright, REFERENCE_MAX_EDGE))
    return tuple(blocks)


def make_client() -> anthropic.AsyncAnthropic:
    load_dotenv(ROOT / ".env")
    headers = {}
    if workspace := os.environ.get("ANTHROPIC_WORKSPACE_ID", "").strip():
        headers["anthropic-workspace-id"] = workspace
    return anthropic.AsyncAnthropic(default_headers=headers, max_retries=4)


class Reader:
    def __init__(self, client: anthropic.AsyncAnthropic | None = None):
        self.client = client or make_client()
        self.usage = Usage()
        self.limit = asyncio.Semaphore(MAX_CONCURRENT)

    def prefix(self) -> list[dict]:
        refs = [dict(b) for b in reference_blocks()]
        refs[-1] = {**refs[-1], "cache_control": {"type": "ephemeral"}}
        return [{"type": "text", "text": "Reference pages (glyph tables):"}, *refs]

    async def read_page(self, page: Image.Image, lines: list[Image.Image],
                        draft: PageResult | None = None, notes: list[str] | None = None) -> PageResult:
        """Read a page; with a draft and notes, re-check that draft instead."""
        content = [*self.prefix(), {"type": "text", "text": "The page, for context:"},
                   jpeg_block(page, MAX_EDGE),
                   {"type": "text", "text": f"The page has {len(lines)} lines, cut out below at full resolution."}]
        for i, line in enumerate(lines, 1):
            content += [{"type": "text", "text": f"Line {i}:"}, jpeg_block(line, MAX_EDGE)]
        if draft is not None:
            first = "\n".join(f"Line {i}: {r.text}" for i, r in enumerate(draft.lines, 1))
            hand = "\n".join(f"- {n}" for n in notes or draft.hand_notes)
            content.append({"type": "text", "text": f"{REVIEW}\n\nHand notes:\n{hand}\n\nFirst reading:\n{first}"})

        def failed(error: str) -> PageResult:
            return draft or PageResult([Result("", "low", "", [], error=error) for _ in lines], [], "", error)

        async with self.limit:
            try:
                async with self.client.beta.messages.stream(
                    model=MODEL,
                    max_tokens=64000,
                    thinking={"type": "adaptive"},
                    output_config={"effort": EFFORT, "format": {"type": "json_schema", "schema": PAGE_SCHEMA}},
                    betas=["server-side-fallback-2026-07-01"],
                    fallbacks="default",
                    system=INSTRUCTIONS,
                    messages=[{"role": "user", "content": content}],
                ) as stream:
                    response = await stream.get_final_message()
            except anthropic.APIStatusError as e:
                return failed(f"API error {e.status_code}: {e.message}")
            except anthropic.APIConnectionError:
                return failed("network error")
        self.usage.add(response.usage)
        if response.stop_reason != "end_turn":
            return failed(f"no reading (stop reason: {response.stop_reason})")
        text = next((b.text for b in response.content if b.type == "text"), "")
        try:
            reading = PageReading.model_validate_json(text)
        except ValueError:
            return failed("unreadable response from the model")

        by_line = {r.line: r for r in reading.lines}
        results = []
        for i in range(1, len(lines) + 1):
            r = by_line.get(i)
            if r is None:
                results.append(Result("", "low", "", [], error="the model skipped this line"))
                continue
            line_text = clean(r.text)
            results.append(Result(line_text, r.confidence, r.note.strip(), check_text(line_text)))
        return PageResult(results, reading.hand_notes, clean(reading.clean_text))
