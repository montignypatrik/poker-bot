import pytest

from pokerlab.cards import parse_cards
from pokerlab.solver.rust_solver import RustSolver


def _solver():
    return RustSolver(
        parse_cards("Ah 7c 2d"), [(0, 1)], [(2, 3)], 5.0, 20.0,
        bet_sizes=(1.0,), max_raises=1, iters=1, depth_limit=0,
    )


def test_children_lists_legal_action_tokens_and_nodes():
    solver = _solver()
    children = solver.children(solver.root)

    assert [token for token, _ in children] == ["x", "b0"]
    assert all(isinstance(node, int) for _, node in children)
    assert solver.node_at(["x"]) == dict(children)["x"]


def test_children_validates_index_and_terminals_have_no_children():
    solver = _solver()
    with pytest.raises(IndexError):
        solver.children(-1)
    fold_node = solver.node_at(["b0", "f"])
    assert solver.children(fold_node) == []
