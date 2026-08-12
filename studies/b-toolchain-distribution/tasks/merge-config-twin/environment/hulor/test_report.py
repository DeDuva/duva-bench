from report import effective


def test_effective_prefers_the_later_layer():
    assert effective([{"a": 1}, {"a": 2}]) == {"a": 2}
