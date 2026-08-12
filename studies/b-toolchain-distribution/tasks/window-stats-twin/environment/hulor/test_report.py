from report import rolling_mean


def test_rolling_mean_over_adjacent_windows():
    assert rolling_mean([1, 2, 3, 4], 2, 2) == [1.5, 3.5]
