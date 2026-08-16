from __future__ import annotations

import threading

import numpy as np

from .cards import card_str, parse_card, parse_cards
from .engine.bots import hand_class
from .flopcache.canonical import apply_perm, board_key, canonical_flop, invert_perm
from .flopcache.store import load_table, node_key
from .perf.solve_cache import SolveCache
from .postflop.grid import combos_to_class_grid
from .postflop.ranges import range_to_combos
from .solver.rust_solver import RustSolver

_SOLVERS = SolveCache(maxsize=4)
_SOLVER_LOCK = threading.RLock()
_TABLE = None
_TABLE_LOCK = threading.Lock()
_NODE_TYPES = {0: "decision", 1: "chance", 2: "showdown", 3: "fold", 4: "equity"}


class APIError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


def _cards(value, *, lengths):
    if isinstance(value, str):
        cards = parse_cards(value)
    elif isinstance(value, list):
        cards = [parse_card(card) if isinstance(card, str) else int(card) for card in value]
    else:
        raise ValueError("board must be a card string or list")
    if len(cards) not in lengths:
        expected = "/".join(str(n) for n in sorted(lengths))
        raise ValueError(f"board must contain {expected} cards")
    if any(card < 0 or card >= 52 for card in cards) or len(set(cards)) != len(cards):
        raise ValueError("board contains an invalid or duplicate card")
    return cards


def _normalized_path(solver, raw_path):
    path = []
    node = solver.root
    for raw in raw_path:
        if solver._types[node] == 1:
            token = parse_card(raw) if isinstance(raw, str) else int(raw)
        else:
            token = str(raw)
        path.append(token)
        choices = dict(solver.children(node))
        if token not in choices:
            raise ValueError(f"illegal path token {raw!r}")
        node = choices[token]
    return path


def _children(solver, node):
    return [
        {"token": card_str(token) if isinstance(token, int) else token, "node": child}
        for token, child in solver.children(node)
    ]


def _decision_payload(source, node, player, actions, arr, combos, children, **extra):
    rows = []
    for combo, strategy in zip(combos, np.asarray(arr)):
        rows.append({
            "cards": [card_str(combo[0]), card_str(combo[1])],
            "class": hand_class(combo),
            "strategy": {action: float(value) for action, value in zip(actions, strategy)},
        })
    return {
        "source": source,
        "node": node,
        "nodeType": "decision",
        "player": player,
        "actions": list(actions),
        "children": children,
        "combos": rows,
        "classes": combos_to_class_grid(combos, actions, arr),
        **extra,
    }


def solve_postflop_node(payload):
    board = _cards(payload.get("board"), lengths={3, 4, 5})
    oop = range_to_combos(payload.get("oopRange", ""), dead_cards=board)
    ip = range_to_combos(payload.get("ipRange", ""), dead_cards=board)
    if not oop or not ip:
        raise ValueError("both ranges must contain at least one live combo")

    pot = float(payload.get("pot", 5.5))
    stack = float(payload.get("stack", 97.5))
    bet_sizes = tuple(float(size) for size in payload.get("betSizes", [0.66, 1.0]))
    max_raises = int(payload.get("maxRaises", 2))
    iterations = int(payload.get("iterations", 300))
    depth = payload.get("depthLimit", 0)
    depth_limit = None if depth is None else int(depth)
    if pot <= 0 or stack <= 0 or not bet_sizes or any(size <= 0 for size in bet_sizes):
        raise ValueError("pot, stack, and bet sizes must be positive")
    if max_raises < 0 or iterations < 1:
        raise ValueError("maxRaises must be non-negative and iterations must be positive")

    key = (tuple(board), tuple(oop), tuple(ip), pot, stack, bet_sizes, max_raises, iterations, depth_limit)
    with _SOLVER_LOCK:
        solver = _SOLVERS.get(
            key,
            lambda: RustSolver(board, oop, ip, pot, stack, bet_sizes, max_raises, iterations, depth_limit),
        )

    path = _normalized_path(solver, payload.get("path", []))
    node = solver.node_at(path)
    node_type = _NODE_TYPES.get(solver._types[node], "unknown")
    common = {
        "source": "solve",
        "node": node,
        "nodeType": node_type,
        "children": _children(solver, node),
        "path": [card_str(token) if isinstance(token, int) else token for token in path],
        "board": [card_str(card) for card in board],
        "exploitability": float(solver.exploitability()),
        "rangeSizes": {"oop": len(oop), "ip": len(ip)},
    }
    if node_type != "decision":
        return common
    player, actions, arr = solver.strategy(node)
    combos = solver.oop if player == 0 else solver.ip
    children = common.pop("children")
    common.pop("source")
    common.pop("node")
    common.pop("nodeType")
    return _decision_payload(
        "solve", node, player, actions, arr, combos, children, **common
    )


def _table():
    global _TABLE
    if _TABLE is None:
        with _TABLE_LOCK:
            if _TABLE is None:
                _TABLE = load_table()
    return _TABLE


def get_flop_table_boards(_query):
    table = _table()
    boards = []
    for key in table["flops"]:
        cards = [int(card) for card in key.split("_")]
        boards.append({"key": key, "cards": [card_str(card) for card in cards]})
    return {"version": table["version"], "params": table["params"], "boards": boards}


def get_flop_table_node(query):
    raw_board = query.get("board", [None])[0]
    if raw_board is None:
        raise ValueError("board query parameter is required")
    board = _cards(raw_board, lengths={3})
    canonical, suit_perm = canonical_flop(board)
    table = _table()
    flop = table["flops"].get(board_key(canonical))
    if flop is None:
        raise APIError(404, "flop is not in the precomputed table")
    path = tuple(token for token in query.get("path", [""])[0].split("|") if token)
    key = node_key(path)
    stored = flop["nodes"].get(key)
    if stored is None:
        raise APIError(404, "node is not in the shallow flop table")

    params = table["params"]
    player = int(stored["player"])
    range_spec = params["oop_range" if player == 0 else "ip_range"]
    canonical_combos = range_to_combos(range_spec, dead_cards=canonical)
    inverse = invert_perm(suit_perm)
    actual_combos = [tuple(sorted(apply_perm(combo, inverse))) for combo in canonical_combos]
    actions = stored["actions"]
    arr = np.asarray(stored["strategy"], dtype=float)
    children = []
    for action in actions:
        child_key = node_key(path + (action,))
        if child_key in flop["nodes"]:
            children.append({"token": action, "node": child_key})
    return _decision_payload(
        "flopcache",
        key,
        player,
        actions,
        arr,
        actual_combos,
        children,
        path=list(path),
        board=[card_str(card) for card in board],
        params=params,
        rangeSizes={"acting": len(actual_combos)},
    )


POST_ROUTES = {"/postflop-node": solve_postflop_node}
GET_ROUTES = {
    "/flop-table-node": get_flop_table_node,
    "/flop-table-boards": get_flop_table_boards,
}
