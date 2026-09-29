import json

from lipi.gold import check_text, load_page, save_line


def test_accepts_plain_devanagari_and_markup():
    assert check_text("मालवमंडले सुदर्शनपुरं अस्ति ॥") == []
    assert check_text("तस्य[भ्रा]ता [?]गबाहु [...] राजा") == []
    assert check_text("रेहाऽ १२") == []


def test_rejects_gujarati_lookalikes():
    # पत + Gujarati virama + Gujarati ra: looks like पत्र, is not.
    problems = check_text("पत્ર")
    assert problems and "GUJARATI" in problems[0]


def test_rejects_latin_ascii_digits_and_bad_markup():
    assert check_text("राजा a")
    assert check_text("राजा 12")
    assert check_text("राजा [क")
    assert check_text("राजा  तस्य")


def test_rejects_non_nfc():
    # U+0958 (precomposed क़) is a composition exclusion: NFC is क + nukta.
    assert check_text("क़") == []
    assert check_text("क़") == ["text is not NFC-normalized"]


def test_save_line_is_merged_per_page(tmp_path):
    save_line(tmp_path, "abc", "page-001", 1, " राजा ", "done", "corrector")
    save_line(tmp_path, "abc", "page-001", 2, "", "skip", "corrector")
    page = load_page(tmp_path, "abc", "page-001")
    assert page["lines"]["1"]["text"] == "राजा"
    assert page["lines"]["2"]["status"] == "skip"
    raw = (tmp_path / "abc" / "page-001.json").read_text(encoding="utf-8")
    assert "राजा" in raw  # stored readable, not \u escapes
    assert json.loads(raw)["page"] == "page-001"
