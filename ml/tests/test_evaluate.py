from lipi.evaluate import edit_distance, score, strip_markup


def test_edit_distance():
    assert edit_distance("", "") == 0
    assert edit_distance("राजा", "राजा") == 0
    assert edit_distance("राजा", "रजा") == 1  # missing ा
    assert edit_distance("कगबाज", "युगबाहु") == 4


def test_markup_keeps_best_guess_and_leaves_unreadable_marks():
    assert strip_markup("तस्य[भ्रा]ता [?] [...]") == "तस्यभ्राता [?] [...]"


def test_letters_score_ignores_spaces_but_strict_does_not():
    s = score([("अस्ति तत्र", "अस्तितत्र")])
    assert s["letters"] == 0.0
    assert s["strict"] > 0.0
