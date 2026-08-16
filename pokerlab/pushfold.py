from __future__ import annotations

import random

from . import poker_core as pc
from .cards import RANKS
from .icm import bubble_factor
from .range import parse_range


def _build_classes() -> list[str]:
    labels: list[str] = []
    for r in range(12, -1, -1):
        labels.append(RANKS[r] * 2)
    for hi in range(12, -1, -1):
        for lo in range(hi):
            labels.append(RANKS[hi] + RANKS[lo] + "s")
            labels.append(RANKS[hi] + RANKS[lo] + "o")
    return labels


HAND_CLASSES: list[str] = _build_classes()
CLASS_INDEX: dict[str, int] = {lab: i for i, lab in enumerate(HAND_CLASSES)}
NUM_CLASSES = len(HAND_CLASSES)


def _combo_count(label: str) -> int:
    if len(label) == 2:
        return 6
    return 4 if label.endswith("s") else 12


COMBO_COUNTS: list[int] = [_combo_count(lab) for lab in HAND_CLASSES]
TOTAL_COMBOS = sum(COMBO_COUNTS)

_MATRIX_CACHE: dict[tuple[int, int, int], list[list[float]]] = {}


def _disjoint_pairs(ci_list, cj_list):
    out = []
    for a0, a1 in ci_list:
        for b0, b1 in cj_list:
            if a0 != b0 and a0 != b1 and a1 != b0 and a1 != b1:
                out.append(((a0, a1), (b0, b1)))
    return out


def _build_matrix(seed: int, boards: int, reps: int) -> list[list[float]]:
    rng = random.Random(seed)
    n = NUM_CLASSES
    combos = [parse_range(lab) for lab in HAND_CLASSES]
    E = [[0.0] * n for _ in range(n)]
    ev7 = pc.evaluate7_batch

    pass_frac = 0.6588
    pool_size = max(1, round(boards / (reps * pass_frac)))
    full = list(range(52))
    pool = []
    for _ in range(pool_size):
        b = rng.sample(full, 5)
        pool.append((b, frozenset(b)))

    for i in range(n):
        ci = combos[i]
        row_i = E[i]
        for j in range(i, n):
            pairs = _disjoint_pairs(ci, combos[j])
            if len(pairs) > reps:
                step = len(pairs) / reps
                sel = [pairs[int(k * step)] for k in range(reps)]
            else:
                sel = pairs

            records = []
            append = records.append
            for (h0, h1), (g0, g1) in sel:
                for b, bs in pool:
                    if h0 in bs or h1 in bs or g0 in bs or g1 in bs:
                        continue
                    append(bytes((h0, h1, b[0], b[1], b[2], b[3], b[4],
                                  g0, g1, b[0], b[1], b[2], b[3], b[4])))

            scores = ev7(b"".join(records))
            total = len(records)
            wins = 0
            ties = 0
            for k in range(0, len(scores), 2):
                a = scores[k]
                c = scores[k + 1]
                if a > c:
                    wins += 1
                elif a == c:
                    ties += 1
            eq = (wins + 0.5 * ties) / total if total else 0.5

            row_i[j] = eq
            if j > i:
                E[j][i] = 1.0 - eq
    return E


def equity_matrix(seed: int = 0, boards: int = 1000, reps: int = 4) -> list[list[float]]:
    if boards < 1 or reps < 1:
        raise ValueError("boards and reps must be positive")
    key = (int(seed), int(boards), int(reps))
    m = _MATRIX_CACHE.get(key)
    if m is None:
        m = _build_matrix(*key)
        _MATRIX_CACHE[key] = m
    return m


def hand_equity_vs_range(
    hand_class: str,
    opponent_classes_with_weights,
    seed: int = 0,
    boards: int = 1000,
    reps: int = 4,
) -> float:
    if hand_class not in CLASS_INDEX:
        raise ValueError(f"unknown hand class: {hand_class!r}")
    E = equity_matrix(seed, boards, reps)
    h = CLASS_INDEX[hand_class]
    row = E[h]
    num = 0.0
    den = 0.0
    for lab, freq in dict(opponent_classes_with_weights).items():
        if lab not in CLASS_INDEX:
            raise ValueError(f"unknown hand class: {lab!r}")
        f = float(freq)
        if f < 0.0:
            raise ValueError(f"negative weight for {lab!r}: {f}")
        w = COMBO_COUNTS[CLASS_INDEX[lab]] * f
        if w:
            num += w * row[CLASS_INDEX[lab]]
            den += w
    return num / den if den > 0 else 0.0


def _scenario(stack_bb: float, players_behind: int, ante: float):
    s = float(stack_bb)
    a = float(ante)
    if players_behind == 1:
        return 1.0 + a, (s - 1.0) / (2.0 * s + a), -0.5
    return 1.5 + a, s / (2.0 * s + a), 0.0


def _solve(
    stack_bb: float,
    E: list[list[float]],
    players_behind: int,
    dead_won: float,
    caller_threshold: float,
    hero_fold_ev: float,
    ante: float,
    iters: int = 300,
    alpha: float = 0.15,
    tol: float = 1e-7,
):
    s = float(stack_bb)
    n = NUM_CLASSES
    cc = COMBO_COUNTS
    T = TOTAL_COMBOS
    k = int(players_behind)
    pot_called = 2.0 * s + ante
    jam = [1.0] * n
    call = [0.0] * n

    for _ in range(iters):
        jam_weight = sum(cc[h] * jam[h] for h in range(n))
        call_new = [0.0] * n
        if jam_weight > 0:
            for c in range(n):
                row = E[c]
                num = 0.0
                for h in range(n):
                    w = cc[h] * jam[h]
                    if w:
                        num += w * row[h]
                call_new[c] = 1.0 if num / jam_weight > caller_threshold else 0.0

        call_weight = sum(cc[c] * call[c] for c in range(n))
        c_freq = call_weight / T
        all_fold = (1.0 - c_freq) ** k
        jam_new = [0.0] * n
        if call_weight > 0:
            for h in range(n):
                row = E[h]
                num = 0.0
                for c in range(n):
                    w = cc[c] * call[c]
                    if w:
                        num += w * row[c]
                eq = num / call_weight
                jam_ev = all_fold * dead_won + (1.0 - all_fold) * (eq * pot_called - s)
                jam_new[h] = 1.0 if jam_ev > hero_fold_ev else 0.0
        else:
            jam_new = [1.0] * n

        max_delta = 0.0
        for i in range(n):
            nj = (1.0 - alpha) * jam[i] + alpha * jam_new[i]
            nc = (1.0 - alpha) * call[i] + alpha * call_new[i]
            max_delta = max(max_delta, abs(nj - jam[i]), abs(nc - call[i]))
            jam[i] = nj
            call[i] = nc
        if max_delta < tol:
            break

    return jam, call


def _package(stack_bb, jam, call, players_behind, ante) -> dict:
    jam_freq = {HAND_CLASSES[i]: jam[i] for i in range(NUM_CLASSES)}
    call_freq = {HAND_CLASSES[i]: call[i] for i in range(NUM_CLASSES)}
    jam_hands = {HAND_CLASSES[i] for i in range(NUM_CLASSES) if jam[i] > 0.5}
    call_hands = {HAND_CLASSES[i] for i in range(NUM_CLASSES) if call[i] > 0.5}
    jam_pct = 100.0 * sum(COMBO_COUNTS[i] * jam[i] for i in range(NUM_CLASSES)) / TOTAL_COMBOS
    call_pct = 100.0 * sum(COMBO_COUNTS[i] * call[i] for i in range(NUM_CLASSES)) / TOTAL_COMBOS
    return {
        "stack_bb": stack_bb,
        "players_behind": players_behind,
        "ante": ante,
        "jam_freq": jam_freq,
        "call_freq": call_freq,
        "jam_hands": jam_hands,
        "call_hands": call_hands,
        "jam_pct": jam_pct,
        "call_pct": call_pct,
        "sb_jam_freq": jam_freq,
        "bb_call_freq": call_freq,
        "sb_jam_hands": jam_hands,
        "bb_call_hands": call_hands,
        "sb_jam_pct": jam_pct,
        "bb_call_pct": call_pct,
    }


def nash_push_fold(
    stack_bb: float,
    players_behind: int = 1,
    ante: float = 0.0,
    seed: int = 0,
    boards: int = 1000,
    reps: int = 4,
    iters: int = 300,
    alpha: float = 0.15,
) -> dict:
    if stack_bb <= 0:
        raise ValueError("stack_bb must be positive")
    if players_behind < 1:
        raise ValueError("players_behind must be >= 1")
    if ante < 0:
        raise ValueError("ante must be non-negative")
    E = equity_matrix(seed, boards, reps)
    dead_won, threshold, hero_fold_ev = _scenario(stack_bb, players_behind, ante)
    jam, call = _solve(stack_bb, E, players_behind, dead_won, threshold, hero_fold_ev,
                       ante, iters=iters, alpha=alpha)
    return _package(stack_bb, jam, call, players_behind, ante)


def _icm_threshold(chip_threshold: float, bubble: float) -> float:
    if bubble == float("inf"):
        return 1.0
    t = chip_threshold
    return bubble * t / (bubble * t + (1.0 - t))


def nash_push_fold_icm(
    stack_bb: float,
    stacks,
    payouts,
    hero_index: int,
    villain_index: int,
    players_behind: int = 1,
    ante: float = 0.0,
    seed: int = 0,
    boards: int = 1000,
    reps: int = 4,
    iters: int = 300,
    alpha: float = 0.15,
) -> dict:
    if stack_bb <= 0:
        raise ValueError("stack_bb must be positive")
    if players_behind < 1:
        raise ValueError("players_behind must be >= 1")
    if ante < 0:
        raise ValueError("ante must be non-negative")
    stacks = list(stacks)
    if not 0 <= hero_index < len(stacks) or not 0 <= villain_index < len(stacks):
        raise ValueError("hero_index/villain_index out of range")
    if hero_index == villain_index:
        raise ValueError("hero and villain must differ")
    E = equity_matrix(seed, boards, reps)
    dead_won, chip_thr, hero_fold_ev = _scenario(stack_bb, players_behind, ante)
    bubble = bubble_factor(stacks, payouts, hero_index, villain_index)
    threshold = _icm_threshold(chip_thr, bubble)
    jam, call = _solve(stack_bb, E, players_behind, dead_won, threshold, hero_fold_ev,
                       ante, iters=iters, alpha=alpha)
    return _package(stack_bb, jam, call, players_behind, ante)
