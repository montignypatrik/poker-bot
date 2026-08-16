from __future__ import annotations

from ..cards import RANKS
from ..pushfold import CLASS_INDEX, nash_push_fold, nash_push_fold_icm


def hand_class(hole):
    r0, r1 = hole[0] // 4, hole[1] // 4
    suited = (hole[0] % 4) == (hole[1] % 4)
    if r0 == r1:
        return RANKS[r0] * 2
    hi, lo = max(r0, r1), min(r0, r1)
    return RANKS[hi] + RANKS[lo] + ("s" if suited else "o")


def check_call_bot(obs):
    if obs["to_call"] <= 1e-9:
        return "check", 0.0
    return "call", 0.0


def tight_bot(obs):
    return ("check", 0.0) if obs["to_call"] <= 1e-9 else ("fold", 0.0)


def _players_behind(obs):
    seats = obs["seats"]
    i = seats.index(obs["seat"])
    behind = 0
    for s in seats[i + 1:]:
        if not obs["folded"][s] and not obs["allin"][s]:
            behind += 1
    return max(1, behind)


class PushFoldBot:
    def __init__(self, mode="chipev", payouts=None, max_jam_bb=16.0, boards=400):
        self.mode = mode
        self.payouts = payouts
        self.max_jam_bb = float(max_jam_bb)
        self.boards = boards
        self._cache = {}

    def _jam_set(self, bb_depth, players_behind):
        key = ("jam", bb_depth, players_behind)
        if key not in self._cache:
            r = nash_push_fold(bb_depth, players_behind=players_behind, boards=self.boards)
            self._cache[key] = r["jam_hands"]
        return self._cache[key]

    def _call_set(self, bb_depth, obs):
        if self.mode == "icm" and self.payouts is not None:
            live = [s for s in obs["seats"] if obs["stacks"][s] > 0 or not obs["folded"][s]]
            stacks = [max(obs["stacks"][s], 0.0) for s in live]
            hero = live.index(obs["seat"])
            others = [(obs["stacks"][s], i) for i, s in enumerate(live) if i != hero]
            villain = max(others)[1] if others else hero
            key = ("call_icm", bb_depth, tuple(round(x) for x in stacks), hero, villain)
            if key not in self._cache:
                r = nash_push_fold_icm(bb_depth, stacks, self.payouts, hero, villain,
                                       boards=self.boards)
                self._cache[key] = r["call_hands"]
            return self._cache[key]
        key = ("call", bb_depth)
        if key not in self._cache:
            self._cache[key] = nash_push_fold(bb_depth, boards=self.boards)["call_hands"]
        return self._cache[key]

    def __call__(self, obs):
        if obs["street"] != "preflop":
            return check_call_bot(obs)
        bb = obs["bb"]
        eff_bb = obs["stack"] / bb
        cls = hand_class(obs["hole"])
        if cls not in CLASS_INDEX:
            return check_call_bot(obs)
        bb_depth = max(1, min(25, round(eff_bb + obs["committed"] / bb)))

        facing_allin = obs["current_bet"] >= obs["stack"] + obs["committed"] - 1e-9 \
            and obs["to_call"] > 1e-9
        if facing_allin or (obs["to_call"] > obs["bb"] + 1e-9):
            return ("call", 0.0) if cls in self._call_set(bb_depth, obs) else ("fold", 0.0)

        if eff_bb <= self.max_jam_bb:
            behind = _players_behind(obs)
            if cls in self._jam_set(bb_depth, behind):
                return "raise", obs["committed"] + obs["stack"]
            return ("check", 0.0) if obs["to_call"] <= 1e-9 else ("fold", 0.0)
        return check_call_bot(obs)
