import numpy as np
import pytest

from pokerlab.cards import parse_cards
from pokerlab.engine.bots import hand_class
from pokerlab.webapi_postflop import get_flop_table_node, solve_postflop_node


def _solver_available():
    try:
        solve_postflop_node({
            "board": "Ah 7c 2d",
            "oopRange": "KsKc",
            "ipRange": "QhQs",
            "betSizes": [1.0],
            "maxRaises": 1,
            "iterations": 1,
            "depthLimit": 0,
        })
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _solver_available(), reason="compiled Rust solver unavailable")


def test_postflop_node_returns_explicit_combos_and_weighted_classes():
    result = solve_postflop_node({
        "board": ["Ah", "7c", "2d"],
        "oopRange": "KsKc,5h5d",
        "ipRange": "QhQs,9c8c",
        "pot": 20,
        "stack": 80,
        "betSizes": [1.0],
        "maxRaises": 1,
        "iterations": 3,
        "depthLimit": 0,
        "path": [],
    })

    assert result["source"] == "solve"
    assert result["nodeType"] == "decision"
    assert result["actions"] == ["x", "b0"]
    assert result["rangeSizes"] == {"oop": 2, "ip": 2}
    assert {tuple(row["cards"]) for row in result["combos"]} == {("Kc", "Ks"), ("5d", "5h")}

    for label, frequencies in result["classes"].items():
        rows = [row for row in result["combos"] if row["class"] == label]
        for action in result["actions"]:
            expected = np.mean([row["strategy"][action] for row in rows])
            assert frequencies[action] == pytest.approx(expected)


def test_postflop_chance_children_are_human_readable_cards():
    base = {
        "board": "Ah 7c 2d",
        "oopRange": "KsKc",
        "ipRange": "QhQs",
        "pot": 10,
        "stack": 20,
        "betSizes": [1.0],
        "maxRaises": 1,
        "iterations": 1,
        "depthLimit": 1,
    }
    root = solve_postflop_node({**base, "path": []})
    checked = solve_postflop_node({**base, "path": ["x"]})
    chance = solve_postflop_node({**base, "path": ["x", "x"]})

    assert root["nodeType"] == checked["nodeType"] == "decision"
    assert chance["nodeType"] == "chance"
    assert chance["children"]
    assert all(len(child["token"]) == 2 for child in chance["children"])


def test_flop_table_response_maps_rows_to_actual_cards():
    result = get_flop_table_node({"board": ["Ah 7c 2d"], "path": [""]})

    assert result["source"] == "flopcache"
    assert result["nodeType"] == "decision"
    assert len(result["combos"]) == result["rangeSizes"]["acting"]
    assert all(row["class"] == hand_class(parse_cards(" ".join(row["cards"]))) for row in result["combos"])
