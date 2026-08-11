from report import plan_build


def test_plan_build_orders_a_simple_chain():
    assert plan_build({"a": ["b"], "b": []}) == ["b", "a"]
