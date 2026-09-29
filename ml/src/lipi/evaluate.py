"""Score a website reading against the corrector's gold transcription.

    uv run lipi-eval <job_id> <file_id>/<page>     e.g. 526526510540 b9c9c31dd01c/page-001

Compares line by line and reports character error rate (CER): edit distance
divided by the gold length. Two numbers are reported:
- strict: exactly as typed, spaces included;
- letters: spaces removed, because where a scribe "left a gap" is a judgment
  call that should not count as a reading error.
The model's [ ] markup is dropped before scoring (its best guess inside counts);
the gold's [?] and [...] mean "unreadable" and those lines are scored as-is.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from lipi import gold
from lipi.reader import DATA

_UNSURE = re.compile(r"\[([^\[\]?.]+)\]")


def strip_markup(text: str) -> str:
    return _UNSURE.sub(r"\1", text)


def edit_distance(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def score(pairs: list[tuple[str, str]]) -> dict:
    """pairs of (gold, prediction) -> strict and letters-only CER."""
    out = {}
    for name, norm in (("strict", lambda s: s), ("letters", lambda s: s.replace(" ", ""))):
        errors = sum(edit_distance(norm(g), norm(p)) for g, p in pairs)
        length = sum(len(norm(g)) for g, _ in pairs)
        out[name] = errors / length if length else 0.0
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("job_id")
    parser.add_argument("gold_page", help="<file_id>/<page>, as in data/gold/")
    args = parser.parse_args()

    job = json.loads((DATA / "jobs" / args.job_id / "job.json").read_text(encoding="utf-8"))
    file_id, page = args.gold_page.split("/")
    typed = gold.load_page(DATA / "gold", file_id, page)["lines"]
    predicted = job["pages"][0]["lines"]

    pairs, rows = [], []
    for line in predicted:
        g = typed.get(str(line["line"]))
        if not g or g["status"] != "done" or g["problems"]:
            continue
        pred = strip_markup(line.get("text", ""))
        pairs.append((g["text"], pred))
        rows.append((line["line"], line.get("confidence", ""), g["text"], pred))

    if not pairs:
        print("No checked gold lines to compare yet (lines must be saved without warnings).")
        return
    for n, conf, g, p in rows:
        s = score([(g, p)])
        mark = "OK " if g.replace(" ", "") == p.replace(" ", "") else "   "
        print(f"{mark}line {n:>2}  CER {s['letters']:6.1%}  (model said: {conf})")
        if mark != "OK ":
            print(f"      gold : {g}\n      model: {p}")
    total = score(pairs)
    print(f"\n{len(pairs)} lines compared")
    print(f"CER letters-only: {total['letters']:.2%}  ->  accuracy {1 - total['letters']:.2%}")
    print(f"CER strict      : {total['strict']:.2%}")


if __name__ == "__main__":
    main()
