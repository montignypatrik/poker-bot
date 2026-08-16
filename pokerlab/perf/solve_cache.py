from __future__ import annotations

from collections import Counter, OrderedDict

POT_STEP_BB = 2.0
STACK_STEP_BB = 5.0


def _street(n_board):
    return {0: "preflop", 3: "flop", 4: "turn", 5: "river"}.get(n_board, f"board{n_board}")


def _texture(board):
    ranks = tuple(sorted(c // 4 for c in board))
    suit_counts = Counter(c % 4 for c in board)
    pattern = tuple(sorted(suit_counts.values(), reverse=True))
    return ranks, pattern


def _effective_stack(obs):
    live = [s for s in obs["seats"] if not obs["folded"].get(s)]
    stacks = obs["stacks"]
    behind = sorted(stacks[s] for s in live if s in stacks)
    return behind[0] if behind else obs.get("stack", 0.0)


def _extra_sig(extra):
    if extra is None:
        return None
    if isinstance(extra, dict):
        return tuple(sorted((str(k), v) for k, v in extra.items()))
    return extra


def make_key(obs, extra=None):
    bb = obs.get("bb") or 1.0
    ranks, pattern = _texture(obs["board"])
    pot_b = round(obs["pot"] / bb / POT_STEP_BB)
    stack_b = round(_effective_stack(obs) / bb / STACK_STEP_BB)
    return (_street(len(obs["board"])), ranks, pattern, pot_b, stack_b, _extra_sig(extra))


class SolveCache:
    def __init__(self, maxsize=256):
        if maxsize < 1:
            raise ValueError("maxsize must be >= 1")
        self.maxsize = maxsize
        self._store = OrderedDict()
        self._hits = 0
        self._misses = 0

    def get(self, key, compute_fn):
        if key in self._store:
            self._hits += 1
            self._store.move_to_end(key)
            return self._store[key]
        self._misses += 1
        value = compute_fn()
        self._store[key] = value
        self._store.move_to_end(key)
        while len(self._store) > self.maxsize:
            self._store.popitem(last=False)
        return value

    def solve(self, obs, compute_fn, extra=None):
        return self.get(make_key(obs, extra), compute_fn)

    def stats(self):
        total = self._hits + self._misses
        return {"hits": self._hits, "misses": self._misses, "size": len(self._store),
                "maxsize": self.maxsize,
                "hit_rate": (self._hits / total) if total else 0.0}

    def clear(self):
        self._store.clear()
        self._hits = 0
        self._misses = 0

    def __len__(self):
        return len(self._store)

    def __contains__(self, key):
        return key in self._store
