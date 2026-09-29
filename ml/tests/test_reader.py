import asyncio
from types import SimpleNamespace

from PIL import Image

from lipi import reader


class HangingStream:
    def __init__(self, calls):
        self.calls = calls

    async def __aenter__(self):
        self.calls.append(1)
        await asyncio.sleep(3600)

    async def __aexit__(self, *exc):
        return False


def test_stuck_page_is_retried_once_then_reported(monkeypatch):
    monkeypatch.setattr(reader, "PAGE_TIMEOUT", 0.05)
    monkeypatch.setattr(reader.Reader, "prefix", lambda self: [])
    calls = []
    client = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(
        stream=lambda **kwargs: HangingStream(calls))))
    r = reader.Reader(client)

    page = Image.new("RGB", (100, 40), "white")
    result = asyncio.run(r.read_page(page, [page, page]))

    assert len(calls) == 2
    assert result.error.startswith("took longer than")
    assert [line.error for line in result.lines] == [result.error] * 2
