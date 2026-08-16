from __future__ import annotations

RANKS = "23456789TJQKA"
SUITS = "cdhs"

HAND_CATEGORIES = [
    "high card",
    "pair",
    "two pair",
    "three of a kind",
    "straight",
    "flush",
    "full house",
    "four of a kind",
    "straight flush",
]


def card_index(rank_ch: str, suit_ch: str) -> int:
    r = RANKS.index(rank_ch.upper())
    s = SUITS.index(suit_ch.lower())
    return r * 4 + s


def parse_card(token: str) -> int:
    token = token.strip()
    if len(token) != 2:
        raise ValueError(f"invalid card token: {token!r}")
    return card_index(token[0], token[1])


def parse_cards(text: str) -> list[int]:
    text = text.strip()
    tokens = text.split() if " " in text else [text[i : i + 2] for i in range(0, len(text), 2)]
    return [parse_card(t) for t in tokens]


def card_str(index: int) -> str:
    if not 0 <= index < 52:
        raise ValueError(f"card index out of range: {index}")
    r, s = divmod(index, 4)
    return RANKS[r] + SUITS[s]


def cards_str(indices) -> str:
    return " ".join(card_str(i) for i in indices)
