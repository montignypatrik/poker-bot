import numpy as np
import pytest

from pokerlab.cards import parse_cards
from pokerlab.postflop.grid import combos_to_class_grid


def test_combo_weighted_class_average_uses_only_live_combos():
    combos = [tuple(parse_cards(cards)) for cards in ("As Ks", "Ah Kh", "Qc Qd")]
    actions = ["x", "b0"]
    strategy = np.array([[0.2, 0.8], [0.6, 0.4], [1.0, 0.0]])

    result = combos_to_class_grid(combos, actions, strategy)

    assert result["AKs"] == pytest.approx({"x": 0.4, "b0": 0.6})
    assert result["QQ"] == pytest.approx({"x": 1.0, "b0": 0.0})
    assert "AA" not in result


def test_grid_rejects_strategy_shape_mismatch():
    with pytest.raises(ValueError, match="strategy shape"):
        combos_to_class_grid([(0, 1)], ["x", "b0"], [[1.0]])
