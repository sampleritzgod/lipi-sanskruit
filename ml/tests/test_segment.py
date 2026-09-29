import numpy as np

from lipi.segment import segment_page

PAPER = (215, 190, 150)
RED = (200, 60, 50)
INK = (40, 35, 30)


def fake_pothi(n_lines=7, pitch=60):
    """A leaf with double red rulings, margin ink outside them, and n text lines."""
    h, w = 80 + n_lines * pitch, 1200
    page = np.full((h, w, 3), PAPER, dtype=np.uint8)
    for x in (150, 170, 1030, 1050):
        page[:, x:x + 8] = RED
    page[100:400, 1100:1110] = INK  # marginal note, must be ignored
    rng = np.random.default_rng(0)
    for i in range(n_lines):
        top = 40 + i * pitch
        page[top + 10:top + 14, 200:1000] = INK  # shirorekha
        for x in range(200, 1000, 25):  # letter bodies hanging from it
            page[top + 14:top + 14 + rng.integers(15, 30), x:x + 6] = INK
    return page


def test_finds_every_line_inside_the_rulings():
    lines = segment_page(fake_pothi(n_lines=7))
    assert len(lines) == 7
    for line in lines:
        # text spans 200..1000; rulings end at 178 and start at 1030;
        # the marginal note at 1100 must stay out
        assert 150 < line.x0 <= 200 and 1000 <= line.x1 < 1100


def test_each_line_crop_contains_its_shirorekha():
    pitch = 60
    lines = segment_page(fake_pothi(n_lines=5, pitch=pitch))
    assert len(lines) == 5
    for i, line in enumerate(lines):
        shirorekha = 40 + i * pitch + 10
        assert line.y0 <= shirorekha and line.y1 >= shirorekha + 30
