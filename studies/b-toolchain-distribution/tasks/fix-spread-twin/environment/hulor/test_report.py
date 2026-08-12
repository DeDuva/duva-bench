from report import summarize


def test_summarize_reports_an_exact_spread():
    assert summarize([1, 2]) == {"count": 2, "mean": 1.5, "spread": 0.5}
