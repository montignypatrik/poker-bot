from __future__ import annotations

from .cards import RANKS, SUITS, card_index


def _rank_index(ch: str) -> int:
    try:
        return RANKS.index(ch.upper())
    except ValueError:
        raise ValueError(f"invalid rank character: {ch!r}") from None


def _pair_combos(r: int) -> list[tuple[int, int]]:
    cards = [r * 4 + s for s in range(4)]
    combos = []
    for i in range(4):
        for j in range(i + 1, 4):
            combos.append((cards[i], cards[j]))
    return combos


def _suited_combos(r_hi: int, r_lo: int) -> list[tuple[int, int]]:
    combos = []
    for s in range(4):
        a, b = r_hi * 4 + s, r_lo * 4 + s
        combos.append((min(a, b), max(a, b)))
    return combos


def _offsuit_combos(r_hi: int, r_lo: int) -> list[tuple[int, int]]:
    combos = []
    for s1 in range(4):
        for s2 in range(4):
            if s1 == s2:
                continue
            a, b = r_hi * 4 + s1, r_lo * 4 + s2
            combos.append((min(a, b), max(a, b)))
    return combos


def _both_combos(r_hi: int, r_lo: int) -> list[tuple[int, int]]:
    return _suited_combos(r_hi, r_lo) + _offsuit_combos(r_hi, r_lo)


def _expand_token(token: str) -> list[tuple[int, int]]:
    tok = token.strip()
    if not tok:
        raise ValueError("empty range token")

    if len(tok) == 4 and tok[1].lower() in SUITS and tok[3].lower() in SUITS:
        a = card_index(tok[0], tok[1])
        b = card_index(tok[2], tok[3])
        if a == b:
            raise ValueError(f"duplicate card in combo: {tok!r}")
        return [(min(a, b), max(a, b))]

    plus = tok.endswith("+")
    if plus:
        tok = tok[:-1]

    if "-" in tok:
        if plus:
            raise ValueError(f"cannot combine '-' and '+': {token!r}")
        lo_tok, _, hi_tok = tok.partition("-")
        lo_tok, hi_tok = lo_tok.strip(), hi_tok.strip()
        if len(lo_tok) != 2 or len(hi_tok) != 2 or lo_tok[0] != lo_tok[1] or hi_tok[0] != hi_tok[1]:
            raise ValueError(f"dash range must be between pairs: {token!r}")
        r1 = _rank_index(lo_tok[0])
        r2 = _rank_index(hi_tok[0])
        lo, hi = min(r1, r2), max(r1, r2)
        combos: list[tuple[int, int]] = []
        for r in range(lo, hi + 1):
            combos.extend(_pair_combos(r))
        return combos

    if len(tok) == 2:
        r1 = _rank_index(tok[0])
        r2 = _rank_index(tok[1])
        if r1 == r2:
            combos = []
            top = 12 if plus else r1
            for r in range(r1, top + 1):
                combos.extend(_pair_combos(r))
            return combos
        if plus:
            raise ValueError(f"'+' requires a suited/offsuit qualifier: {token!r}")
        r_hi, r_lo = max(r1, r2), min(r1, r2)
        return _both_combos(r_hi, r_lo)

    if len(tok) == 3:
        r1 = _rank_index(tok[0])
        r2 = _rank_index(tok[1])
        suit_flag = tok[2].lower()
        if r1 == r2:
            raise ValueError(f"pair cannot be suited/offsuit: {token!r}")
        r_hi, r_lo = max(r1, r2), min(r1, r2)
        if suit_flag == "s":
            builder = _suited_combos
        elif suit_flag == "o":
            builder = _offsuit_combos
        else:
            raise ValueError(f"expected 's' or 'o' qualifier: {token!r}")
        if not plus:
            return builder(r_hi, r_lo)
        combos = []
        for kicker in range(r_lo, r_hi):
            combos.extend(builder(r_hi, kicker))
        return combos

    raise ValueError(f"malformed range token: {token!r}")


def parse_range(text: str) -> list[tuple[int, int]]:
    if text is None:
        raise ValueError("range text must be a string")
    seen: set[tuple[int, int]] = set()
    result: list[tuple[int, int]] = []
    for token in text.split(","):
        token = token.strip()
        if not token:
            continue
        for combo in _expand_token(token):
            if combo not in seen:
                seen.add(combo)
                result.append(combo)
    return result


def range_size(text: str) -> int:
    return len(parse_range(text))
