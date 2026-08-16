from __future__ import annotations

import random

from ..icm import icm_equity
from ..pushfold import COMBO_COUNTS, HAND_CLASSES, NUM_CLASSES, TOTAL_COMBOS, equity_matrix

MAX_RAISE_LEVELS = 8


class PreflopSubgame:
    def __init__(
        self,
        opener_range: dict,
        full_stacks,
        payouts,
        opener_idx: int,
        defender_idx: int,
        bet_sizes_bb,
        dead_money_bb: float = 1.5,
        seed: int = 0,
        boards: int = 1000,
        reps: int = 4,
    ):
        if not 0 <= opener_idx < len(full_stacks) or not 0 <= defender_idx < len(full_stacks):
            raise ValueError("opener_idx/defender_idx out of range")
        if opener_idx == defender_idx:
            raise ValueError("opener and defender must differ")
        bet_sizes_bb = [float(size) for size in bet_sizes_bb]
        if not bet_sizes_bb:
            raise ValueError("bet_sizes_bb must contain at least one size (the open)")
        if len(bet_sizes_bb) > MAX_RAISE_LEVELS:
            raise ValueError(f"raise ladder deeper than {MAX_RAISE_LEVELS} levels isn't modeled")
        if any(size <= 0 for size in bet_sizes_bb):
            raise ValueError("bet sizes must be positive")

        self.E = equity_matrix(seed=seed, boards=boards, reps=reps)

        self.opener_weights = [
            COMBO_COUNTS[i] * float(opener_range.get(HAND_CLASSES[i], 0.0)) for i in range(NUM_CLASSES)
        ]
        total_ow = sum(self.opener_weights)
        if total_ow <= 0:
            raise ValueError("opener_range has zero total weight")
        self.opener_weights = [w / total_ow for w in self.opener_weights]
        self.defender_weights = [c / TOTAL_COMBOS for c in COMBO_COUNTS]

        self.full_stacks = list(full_stacks)
        self.payouts = list(payouts)
        self.opener_idx = opener_idx
        self.defender_idx = defender_idx
        bet_sizes_bb[0] = min(bet_sizes_bb[0], full_stacks[opener_idx])
        self.bet_sizes = bet_sizes_bb
        self.dead_money = dead_money_bb

        self._rng = random.Random(seed + 1)
        self._icm_cache: dict[tuple, list] = {}

    def initial_history(self):
        return ()

    def is_chance(self, h):
        return len(h) == 0

    def chance_outcomes(self, h):
        o = self._weighted_pick(self.opener_weights)
        d = self._weighted_pick(self.defender_weights)
        return [(("deal", o, d), 1.0)]

    def _weighted_pick(self, weights):
        r = self._rng.random()
        acc = 0.0
        for i, w in enumerate(weights):
            acc += w
            if r <= acc:
                return i
        return len(weights) - 1

    def is_terminal(self, h):
        return len(h) >= 2 and h[-1] in ("f", "c")

    def _level(self, h):
        return len(h) - 1

    def current_player(self, h):
        m = self._level(h)
        return 1 if m % 2 == 0 else 0

    def legal_actions(self, h):
        m = self._level(h)
        if m >= len(self.bet_sizes) - 1:
            return ["f", "c"]
        return ["f", "c", "r"]

    def infoset_key(self, h):
        deal = h[0]
        opener_cls, defender_cls = HAND_CLASSES[deal[1]], HAND_CLASSES[deal[2]]
        m = self._level(h)
        role = "D" if m % 2 == 0 else "O"
        cls = defender_cls if role == "D" else opener_cls
        return f"{role}|{cls}|L{m}"

    def next_history(self, h, action):
        return h + (action,)

    def _icm(self, stacks):
        key = tuple(round(s, 6) for s in stacks)
        v = self._icm_cache.get(key)
        if v is None:
            v = icm_equity(stacks, self.payouts)
            self._icm_cache[key] = v
        return v

    def _risked(self, desired_bb, *seat_idxs):
        amount = desired_bb
        for i in seat_idxs:
            amount = min(amount, self.full_stacks[i])
        return max(0.0, amount)

    def utility(self, h):
        deal = h[0]
        opener_cls_idx, defender_cls_idx = deal[1], deal[2]
        stacks = list(self.full_stacks)
        oi, di = self.opener_idx, self.defender_idx
        m = len(h) - 2

        if h[-1] == "c":
            risked = self._risked(self.bet_sizes[m], oi, di)
            return self._showdown_ev(stacks, oi, di, risked, opener_cls_idx, defender_cls_idx)

        if m == 0:
            stacks[oi] += self.dead_money
            return self._icm(stacks)[oi]

        folder_idx = di if m % 2 == 0 else oi
        winner_idx = oi if folder_idx == di else di
        lost = self._risked(self.bet_sizes[m - 1], folder_idx)
        stacks[folder_idx] -= lost
        stacks[winner_idx] += lost + self.dead_money
        return self._icm(stacks)[oi]

    def _showdown_ev(self, stacks, oi, di, matched_risk, opener_cls_idx, defender_cls_idx):
        eq = self.E[opener_cls_idx][defender_cls_idx]
        win = list(stacks)
        win[oi] += matched_risk + self.dead_money
        win[di] -= matched_risk
        lose = list(stacks)
        lose[oi] -= matched_risk
        lose[di] += matched_risk + self.dead_money
        return eq * self._icm(win)[oi] + (1.0 - eq) * self._icm(lose)[oi]
