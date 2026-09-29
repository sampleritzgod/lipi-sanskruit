"""Local web tool for typing gold transcriptions, one line image at a time.

    uv run lipi-transcribe --name <transcriber>

Serves on http://127.0.0.1:8765 (local only). Every line is saved to
data/gold/ the moment it is confirmed, so closing the browser loses nothing.
"""

from __future__ import annotations

import argparse
import json
import re
import webbrowser
from functools import partial
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from lipi import gold

SAFE_ID = re.compile(r"^[A-Za-z0-9_-]+$")
PAGE_HTML = Path(__file__).with_name("transcribe.html")


def list_pages(lines_dir: Path, gold_dir: Path) -> list[dict]:
    pages = []
    for page_dir in sorted(lines_dir.glob("*/page-*")):
        file_id, page = page_dir.parent.name, page_dir.name
        boxes = json.loads((page_dir / "lines.json").read_text())
        saved = gold.load_page(gold_dir, file_id, page)["lines"]
        pages.append({"file_id": file_id, "page": page, "lines": len(boxes),
                      "done": sum(1 for b in boxes if str(b["index"]) in saved)})
    return pages


class Handler(BaseHTTPRequestHandler):
    def __init__(self, *args, data: Path, transcriber: str, **kwargs):
        self.lines_dir = data / "lines"
        self.gold_dir = data / "gold"
        self.transcriber = transcriber
        super().__init__(*args, **kwargs)

    def log_message(self, format, *args):  # noqa: A002 - stdlib signature
        pass

    def send(self, body: bytes, content_type: str, status: HTTPStatus = HTTPStatus.OK):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, obj, status: HTTPStatus = HTTPStatus.OK):
        self.send(json.dumps(obj, ensure_ascii=False).encode(), "application/json; charset=utf-8", status)

    def page_dir(self, file_id: str, page: str) -> Path | None:
        if not (SAFE_ID.match(file_id) and SAFE_ID.match(page)):
            return None
        path = self.lines_dir / file_id / page
        return path if path.is_dir() else None

    def do_GET(self):
        parts = self.path.split("?")[0].strip("/").split("/")
        if parts == [""]:
            self.send(PAGE_HTML.read_bytes(), "text/html; charset=utf-8")
        elif parts == ["api", "pages"]:
            self.send_json({"pages": list_pages(self.lines_dir, self.gold_dir),
                            "transcriber": self.transcriber})
        elif len(parts) == 4 and parts[:2] == ["api", "page"]:
            page_dir = self.page_dir(parts[2], parts[3])
            if page_dir is None:
                return self.send_json({"error": "no such page"}, HTTPStatus.NOT_FOUND)
            boxes = json.loads((page_dir / "lines.json").read_text())
            saved = gold.load_page(self.gold_dir, parts[2], parts[3])["lines"]
            self.send_json({"lines": [{"line": b["index"], **saved.get(str(b["index"]), {})}
                                      for b in boxes]})
        elif len(parts) == 4 and parts[0] == "img" and SAFE_ID.match(parts[3].removesuffix(".jpg")):
            page_dir = self.page_dir(parts[1], parts[2])
            image = page_dir / parts[3] if page_dir else None
            if image is None or not image.is_file():
                return self.send_json({"error": "no such image"}, HTTPStatus.NOT_FOUND)
            self.send(image.read_bytes(), "image/jpeg")
        else:
            self.send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)

    def do_POST(self):
        if self.path != "/api/save":
            return self.send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)
        try:
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            if self.page_dir(body["file_id"], body["page"]) is None:
                raise ValueError("no such page")
            record = gold.save_line(self.gold_dir, body["file_id"], body["page"],
                                    int(body["line"]), body["text"], body["status"],
                                    self.transcriber)
        except (KeyError, ValueError, TypeError, json.JSONDecodeError) as e:
            return self.send_json({"error": str(e)}, HTTPStatus.BAD_REQUEST)
        self.send_json(record)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data", type=Path, default=Path(__file__).resolve().parents[3] / "data")
    parser.add_argument("--name", required=True, help="who is transcribing (saved with every line)")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    handler = partial(Handler, data=args.data.resolve(), transcriber=args.name)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), handler)
    url = f"http://127.0.0.1:{args.port}/"
    print(f"Transcription tool running at {url} (Ctrl+C to stop)")
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
