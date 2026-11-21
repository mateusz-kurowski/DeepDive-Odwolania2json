from src.citations import citation_ok, citation_score

TEXT = (
    "Odwołanie\nwykonawcy STRABAG Sp. z o.o. wobec czynności\n"
    "Zamawiającego: publikacji specyfikacji warunków zamó-\nwienia (SWZ)."
)


def test_exact_substring_scores_100():
    assert citation_score("STRABAG Sp. z o.o.", TEXT) == 100


def test_whitespace_and_case_insensitive():
    assert citation_score("strabag   SP. z o.o.", TEXT) >= 95


def test_line_break_inside_quote_ok():
    assert citation_score("wobec czynności Zamawiającego", TEXT) >= 95


def test_hallucinated_quote_below_threshold():
    assert citation_score("Kancelaria Radców Prawnych w Gdyni", TEXT) < 85


def test_none_quote_zero():
    assert citation_score(None, TEXT) == 0.0
    assert citation_score("", TEXT) == 0.0


def test_pdf_hyphenation_tolerated():
    assert citation_score("specyfikacji warunków zamówienia", TEXT) >= 95


def test_citation_ok_uses_threshold():
    assert citation_ok("STRABAG Sp. z o.o.", TEXT, 85)
    assert not citation_ok("zupełnie inny tekst nieobecny w dokumencie", TEXT, 85)
