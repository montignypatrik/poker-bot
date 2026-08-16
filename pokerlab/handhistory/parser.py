from __future__ import annotations

import re
from pathlib import Path

_HAND_START = re.compile(r"^PokerStars", re.MULTILINE)
_HEADER = re.compile(
    r"^PokerStars(?: Zoom)? Hand #(?P<id>\d+):.*?"
    r"\(\$?(?P<sb>[\d.,]+)\s*/\s*\$?(?P<bb>[\d.,]+)(?:\s*USD)?\)\s*-\s*"
    r"(?P<datetime>\d{4}/\d{2}/\d{2} [\d:]+) ET",
    re.MULTILINE,
)
_TABLE = re.compile(
    r"^Table '(?P<name>[^']*)' (?P<max>\d+)-max(?: Seat #(?P<button>\d+) is the button)?",
    re.MULTILINE,
)
_SEAT = re.compile(r"^Seat (?P<seat>\d+): (?P<name>.+?) \(\$?(?P<stack>[\d,]+(?:\.\d+)?) in chips", re.MULTILINE)
_ANTE = re.compile(r"^.+?: posts the ante \$?(?P<amt>[\d,]+(?:\.\d+)?)", re.MULTILINE)
_DEALT = re.compile(r"^Dealt to (?P<hero>.+?) \[(?P<c1>\w+) (?P<c2>\w+)\]", re.MULTILINE)
_ACTION = re.compile(
    r"^(?P<name>.+?): (?P<verb>folds|checks|bets|calls|raises)"
    r"(?: \$?(?P<amt1>[\d,]+(?:\.\d+)?))?(?: to \$?(?P<amt2>[\d,]+(?:\.\d+)?))?",
    re.MULTILINE,
)

_VERB_MAP = {"folds": "fold", "checks": "check", "bets": "bet", "calls": "call", "raises": "raise"}
_END_MARKERS = ("*** FLOP ***", "*** SUMMARY ***", "*** SHOW DOWN ***")


def _num(text: str | None) -> float | None:
    if text is None:
        return None
    return float(text.replace(",", ""))


def _parse_preflop_actions(block: str) -> list[dict]:
    start = block.find("*** HOLE CARDS ***")
    if start == -1:
        return []
    end = len(block)
    for marker in _END_MARKERS:
        idx = block.find(marker, start)
        if idx != -1:
            end = min(end, idx)
    section = block[start:end]
    actions = []
    for match in _ACTION.finditer(section):
        verb = match.group("verb")
        amount = _num(match.group("amt2")) if match.group("amt2") is not None else _num(match.group("amt1"))
        actions.append({"name": match.group("name").strip(), "action": _VERB_MAP[verb], "amount": amount})
    return actions


def parse_hand(block: str) -> dict | None:
    header = _HEADER.search(block)
    if header is None:
        return None
    table = _TABLE.search(block)
    seats = [
        {"seat": int(m.group("seat")), "name": m.group("name").strip(), "stack": _num(m.group("stack"))}
        for m in _SEAT.finditer(block)
    ]
    ante_match = _ANTE.search(block)
    dealt = _DEALT.search(block)
    first_line = block.split("\n", 1)[0]

    return {
        "hand_id": header.group("id"),
        "datetime": header.group("datetime"),
        "game_type": "tournament" if "Tournament #" in first_line else "cash",
        "sb": _num(header.group("sb")),
        "bb": _num(header.group("bb")),
        "ante": _num(ante_match.group("amt")) if ante_match else 0.0,
        "table_name": table.group("name") if table else "",
        "max_seats": int(table.group("max")) if table else len(seats),
        "button_seat": int(table.group("button")) if table and table.group("button") else (seats[0]["seat"] if seats else 0),
        "seats": seats,
        "hero_name": dealt.group("hero").strip() if dealt else None,
        "hero_cards": [dealt.group("c1"), dealt.group("c2")] if dealt else None,
        "preflop_actions": _parse_preflop_actions(block),
        "raw_text": block.strip(),
    }


def iter_hands(text: str):
    starts = [m.start() for m in _HAND_START.finditer(text)]
    for i, start in enumerate(starts):
        end = starts[i + 1] if i + 1 < len(starts) else len(text)
        hand = parse_hand(text[start:end])
        if hand is not None:
            yield hand


def parse_file(path) -> list[dict]:
    text = Path(path).read_text(encoding="utf-8-sig")
    return list(iter_hands(text))
