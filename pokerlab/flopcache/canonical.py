from __future__ import annotations

from itertools import combinations, permutations

_SUIT_PERMS = tuple(permutations(range(4)))


def apply_perm(cards, suit_perm):
    out = []
    for c in cards:
        c = int(c)
        r, s = divmod(c, 4)
        out.append(r * 4 + suit_perm[s])
    return out


def invert_perm(suit_perm):
    inv = [0, 0, 0, 0]
    for s in range(4):
        inv[suit_perm[s]] = s
    return tuple(inv)


def canonical_flop(board3):
    cards = [int(c) for c in board3]
    if len(cards) != 3:
        raise ValueError(f"a flop must have 3 cards, got {len(cards)}")
    if len(set(cards)) != 3:
        raise ValueError(f"flop has duplicate cards: {cards}")

    ranks = [c >> 2 for c in cards]
    suits = [c & 3 for c in cards]

    best_image = None
    best_perm = None
    for perm in _SUIT_PERMS:
        image = sorted(ranks[i] * 4 + perm[suits[i]] for i in range(3))
        image = tuple(image)
        if best_image is None or image < best_image:
            best_image = image
            best_perm = perm
    return best_image, best_perm


def enumerate_canonical_flops():
    seen = set()
    for combo in combinations(range(52), 3):
        canon, _ = canonical_flop(combo)
        seen.add(canon)
    return sorted(seen)


def board_key(board3):
    return "_".join(str(int(c)) for c in sorted(board3))
