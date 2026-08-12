from report import summarize


def test_summarize_counts_and_means():
    assert summarize([2, 4, 6]) == {"count": 3, "mean": 4.0}
