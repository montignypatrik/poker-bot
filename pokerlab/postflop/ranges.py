from __future__ import annotations

from functools import lru_cache

from ..range import parse_range


@lru_cache(maxsize=None)
def _range_to_combos_cached(range_spec, dead_cards):
    if isinstance(range_spec, str):
        combos = parse_range(range_spec)
    else:
        combos = parse_range(",".join(range_spec))
    dead = set(dead_cards)
    return tuple((a, b) for (a, b) in combos if a not in dead and b not in dead)


def range_to_combos(range_spec, dead_cards=()):
    spec_key = range_spec if isinstance(range_spec, str) else tuple(range_spec)
    dead_key = tuple(sorted(int(c) for c in dead_cards))
    return list(_range_to_combos_cached(spec_key, dead_key))
