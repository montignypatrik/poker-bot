from __future__ import annotations


def icm_equity(stacks, payouts):
    stacks = [float(s) for s in stacks]
    payouts = [float(p) for p in payouts]
    n = len(stacks)
    memo = {}

    def rec(remaining):
        if remaining in memo:
            return memo[remaining]
        removed = n - len(remaining)
        pays = payouts[removed:]
        eq = {i: 0.0 for i in remaining}
        if not pays or not remaining:
            return eq
        total = sum(stacks[i] for i in remaining)
        p0 = pays[0]
        for j in remaining:
            pj = (stacks[j] / total) if total > 0 else 1.0 / len(remaining)
            eq[j] += pj * p0
            if len(pays) > 1 and len(remaining) > 1:
                for k, v in rec(remaining - {j}).items():
                    eq[k] += pj * v
        memo[remaining] = eq
        return eq

    full = rec(frozenset(range(n)))
    return [full[i] for i in range(n)]


def bubble_factor(stacks, payouts, hero, villain):
    stacks = [float(s) for s in stacks]
    eff = min(stacks[hero], stacks[villain])
    base = icm_equity(stacks, payouts)[hero]

    win = list(stacks)
    win[hero] += eff
    win[villain] -= eff
    lose = list(stacks)
    lose[hero] -= eff
    lose[villain] += eff

    eq_win = icm_equity(win, payouts)[hero]
    eq_lose = icm_equity(lose, payouts)[hero]
    risk = base - eq_lose
    reward = eq_win - base
    return risk / reward if reward > 1e-12 else float("inf")


def required_equity(stacks, payouts, hero, villain):
    bf = bubble_factor(stacks, payouts, hero, villain)
    if bf == float("inf"):
        return 1.0
    return bf / (1.0 + bf)
