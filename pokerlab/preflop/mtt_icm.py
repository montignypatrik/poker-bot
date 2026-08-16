from __future__ import annotations

from ..icm import icm_equity
from .subgame_cfr import PreflopSubgame
from ..pushfold import HAND_CLASSES, COMBO_COUNTS, NUM_CLASSES, TOTAL_COMBOS, equity_matrix
from ..solver.cfr import CFRSolver

_FIELD_WEIGHT_CACHE: dict[tuple, list[float]] = {}


def _field_continue_weight(field_continue_frac: float, seed: int, boards: int, reps: int) -> list[float]:
    key = (round(field_continue_frac, 6), seed, boards, reps)
    cached = _FIELD_WEIGHT_CACHE.get(key)
    if cached is not None:
        return cached

    E = equity_matrix(seed=seed, boards=boards, reps=reps)
    strengths = []
    for i in range(NUM_CLASSES):
        num = 0.0
        den = 0.0
        for j in range(NUM_CLASSES):
            if j == i:
                continue
            num += E[i][j] * COMBO_COUNTS[j]
            den += COMBO_COUNTS[j]
        strengths.append((num / den if den else 0.5, i))
    strengths.sort(reverse=True)

    target_combos = field_continue_frac * TOTAL_COMBOS
    field_weight = [0.0] * NUM_CLASSES
    acc = 0.0
    for _, i in strengths:
        c = COMBO_COUNTS[i]
        if acc >= target_combos:
            break
        take = min(c, target_combos - acc)
        field_weight[i] = take / c
        acc += take

    _FIELD_WEIGHT_CACHE[key] = field_weight
    return field_weight


def solve_mtt_rfi(
    full_stacks,
    payouts,
    opener_idx,
    num_players_behind,
    open_size_bb: float = 2.3,
    dead_money_bb: float = 1.5,
    field_continue_frac: float = 0.40,
    three_bet_share: float = 0.15,
    seed: int = 0,
    boards: int = 1000,
    reps: int = 4,
) -> dict:
    E = equity_matrix(seed=seed, boards=boards, reps=reps)
    stacks = list(full_stacks)
    open_size_bb = min(open_size_bb, stacks[opener_idx])

    p_continue_each = field_continue_frac
    p_flat_each = p_continue_each * (1.0 - three_bet_share)
    p_3bet_each = p_continue_each * three_bet_share
    k = int(num_players_behind)

    p_all_fold = (1.0 - p_continue_each) ** k
    p_faces_3bet = 1.0 - (1.0 - p_3bet_each) ** k
    p_flat_call_only = max(0.0, 1.0 - p_all_fold - p_faces_3bet)

    field_weight = _field_continue_weight(p_continue_each, seed, boards, reps)

    icm_baseline = icm_equity(stacks, payouts)[opener_idx]

    stacks_fold_out = list(stacks)
    stacks_fold_out[opener_idx] += dead_money_bb
    fold_out_ev = icm_equity(stacks_fold_out, payouts)[opener_idx] - icm_baseline

    stacks_3bet_faced = list(stacks)
    stacks_3bet_faced[opener_idx] -= open_size_bb
    three_bet_faced_ev = icm_equity(stacks_3bet_faced, payouts)[opener_idx] - icm_baseline

    open_freq = {}
    pot_if_called = open_size_bb * 2.0 + dead_money_bb

    for i in range(NUM_CLASSES):
        num = 0.0
        den = 0.0
        for j in range(NUM_CLASSES):
            w = field_weight[j] * COMBO_COUNTS[j]
            if w <= 0:
                continue
            num += w * E[i][j]
            den += w
        raw_equity = num / den if den > 0 else 0.5

        win = list(stacks)
        win[opener_idx] += open_size_bb + dead_money_bb
        lose = list(stacks)
        lose[opener_idx] -= open_size_bb
        icm_win = icm_equity(win, payouts)[opener_idx]
        icm_lose = icm_equity(lose, payouts)[opener_idx]
        flat_call_ev = (raw_equity * icm_win + (1.0 - raw_equity) * icm_lose) - icm_baseline

        ev_open = p_all_fold * fold_out_ev + p_flat_call_only * flat_call_ev + p_faces_3bet * three_bet_faced_ev

        mix_width = icm_baseline * 0.01 if icm_baseline > 0 else 1e-4
        if ev_open >= mix_width:
            freq = 1.0
        elif ev_open <= -mix_width:
            freq = 0.0
        else:
            freq = (ev_open + mix_width) / (2.0 * mix_width)
        open_freq[HAND_CLASSES[i]] = round(freq, 4)

    open_pct = 100.0 * sum(COMBO_COUNTS[i] * open_freq[HAND_CLASSES[i]] for i in range(NUM_CLASSES)) / TOTAL_COMBOS
    return {"open_freq": open_freq, "open_pct": open_pct}


def solve_mtt_preflop_subgame(
    opener_range: dict,
    full_stacks,
    payouts,
    opener_idx: int,
    defender_idx: int,
    bet_sizes_bb,
    dead_money_bb: float = 1.5,
    iterations: int = 20000,
    seed: int = 0,
    boards: int = 1000,
    reps: int = 4,
) -> dict:
    game = PreflopSubgame(
        opener_range=opener_range,
        full_stacks=full_stacks,
        payouts=payouts,
        opener_idx=opener_idx,
        defender_idx=defender_idx,
        bet_sizes_bb=bet_sizes_bb,
        dead_money_bb=dead_money_bb,
        seed=seed,
        boards=boards,
        reps=reps,
    )
    solver = CFRSolver(game)
    solver.train(iterations)
    avg = solver.average_strategy()

    levels = []
    for m, size in enumerate(game.bet_sizes):
        role = "defender" if m % 2 == 0 else "opener"
        role_code = "D" if role == "defender" else "O"
        default_actions = ["f", "c"] if m == len(game.bet_sizes) - 1 else ["f", "c", "r"]
        default_strategy = {a: (1.0 if a == "f" else 0.0) for a in default_actions}
        strategies = {}
        for cls in HAND_CLASSES:
            s = avg.get(f"{role_code}|{cls}|L{m}")
            strategies[cls] = {a: round(s[a], 4) for a in s} if s else dict(default_strategy)
        levels.append({"role": role, "betSizeBB": size, "strategies": strategies})

    return {"levels": levels}
