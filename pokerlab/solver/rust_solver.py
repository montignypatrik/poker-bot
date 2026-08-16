from __future__ import annotations

import numpy as np

from .. import poker_core as pc


def analytic_leaf(board, oop, ip):
    return pc.equity_matrix_py(
        [int(c) for c in board],
        [tuple(int(x) for x in h) for h in oop],
        [tuple(int(x) for x in h) for h in ip])


def subgame_cfv(board, oop, ip, pot, stack, bet_sizes=(0.66, 1.0), max_raises=2,
                iters=300, reach0=None, reach1=None):
    cfv0, cfv1 = pc.subgame_cfv(
        [int(c) for c in board],
        [tuple(int(x) for x in h) for h in oop],
        [tuple(int(x) for x in h) for h in ip],
        float(pot), float(stack), [float(s) for s in bet_sizes], int(max_raises),
        int(iters),
        None if reach0 is None else [float(x) for x in reach0],
        None if reach1 is None else [float(x) for x in reach1])
    return np.asarray(cfv0), np.asarray(cfv1)


class RustSolver:
    def __init__(self, board, oop, ip, pot, stack, bet_sizes=(0.66, 1.0),
                 max_raises=2, iters=300, depth_limit=None, leaf_values=None):
        self.oop = [tuple(int(x) for x in h) for h in oop]
        self.ip = [tuple(int(x) for x in h) for h in ip]
        leaf = None
        if leaf_values is not None:
            items = (leaf_values.items() if isinstance(leaf_values, dict)
                     else leaf_values)
            leaf = [([int(c) for c in b], [float(v) for v in m]) for b, m in items]
        res = pc.solve_postflop(
            [int(c) for c in board], self.oop, self.ip, float(pot), float(stack),
            [float(s) for s in bet_sizes], int(max_raises), int(iters),
            None if depth_limit is None else int(depth_limit), leaf,
        )
        (self._expl, self._types, self._players, self._children, self._actions,
         self._chance, self._avg, self.h0, self.h1, self.root) = res

    def exploitability(self):
        return self._expl

    def node_at(self, path):
        idx = self.root
        for tok in path:
            if self._types[idx] == 0:
                idx = self._children[idx][self._actions[idx].index(tok)]
            elif self._types[idx] == 1:
                idx = self._children[idx][self._chance[idx].index(tok)]
            else:
                raise ValueError("path runs past a terminal node")
        return idx

    def children(self, node_idx):
        if not 0 <= node_idx < len(self._types):
            raise IndexError("node index out of range")
        if self._types[node_idx] == 0:
            tokens = self._actions[node_idx]
        elif self._types[node_idx] == 1:
            tokens = self._chance[node_idx]
        else:
            return []
        return list(zip(tokens, self._children[node_idx]))

    def strategy(self, node_idx):
        if self._types[node_idx] != 0:
            raise ValueError("not a decision node")
        player = self._players[node_idx]
        actions = self._actions[node_idx]
        hp = self.h0 if player == 0 else self.h1
        arr = np.array(self._avg[node_idx]).reshape(hp, len(actions))
        return player, actions, arr
