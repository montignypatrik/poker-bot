from __future__ import annotations

from ..cards import parse_card
from ..engine.bots import hand_class

_SUFFIX = ["HJ", "CO", "BTN", "SB", "BB"]
_PREFIX_POOL = ["UTG", "UTG1", "UTG2", "LJ"]


def seat_positions(n: int) -> list[str]:
    if n < 2:
        raise ValueError("need at least 2 seats")
    if n == 2:
        return ["BTN", "BB"]
    if n <= 5:
        return _SUFFIX[-n:]
    if n <= 9:
        return _PREFIX_POOL[: n - 5] + _SUFFIX
    raise ValueError("more than 9 seats isn't supported")


def _acting_order(seats: list[dict], button_seat: int) -> list[dict]:
    seated = sorted(seats, key=lambda s: s["seat"])
    n = len(seated)
    btn_idx = next((i for i, s in enumerate(seated) if s["seat"] == button_seat), None)
    if btn_idx is None:
        raise ValueError(f"button seat {button_seat} is not occupied")
    if n == 2:
        return seated[btn_idx:] + seated[:btn_idx]
    rotated = seated[btn_idx + 1:] + seated[:btn_idx + 1]
    return rotated[2:] + rotated[:2]


def _normalize(action: dict, position: str, bb: float) -> dict:
    if action["action"] == "fold":
        return {"position": position, "action": "fold", "toBB": 0}
    if action["action"] in ("call", "check"):
        return {"position": position, "action": "call", "toBB": round((action["amount"] or 0.0) / bb, 4)}
    return {"position": position, "action": "raise", "toBB": round((action["amount"] or 0.0) / bb, 4)}


def hand_to_situation(hand: dict) -> dict:
    seats = hand["seats"]
    n = len(seats)
    if n < 2:
        return {"note": "hand has fewer than 2 seated players; nothing to study"}

    bb = hand.get("bb")
    if not bb:
        return {"note": "could not determine the big blind size for this hand"}

    try:
        order = _acting_order(seats, hand["button_seat"])
        labels = seat_positions(n)
    except ValueError as exc:
        return {"note": str(exc)}
    name_to_position = {seat["name"]: labels[i] for i, seat in enumerate(order)}

    hero_name = hand.get("hero_name")
    hero_position = name_to_position.get(hero_name) if hero_name else None
    if hero_position is None:
        return {"note": "hero was not seated at this table"}

    starting_stacks = {
        name_to_position[seat["name"]]: round(seat["stack"] / bb, 4)
        for seat in seats
        if seat["name"] in name_to_position
    }

    history = []
    hero_action = None
    for action in hand["preflop_actions"]:
        position = name_to_position.get(action["name"])
        if position is None:
            continue
        if position == hero_position:
            hero_action = _normalize(action, position, bb)
            break
        history.append(_normalize(action, position, bb))

    if hero_action is None:
        return {"note": "hero didn't get a preflop decision in this hand (folded before acting, or won without one)"}

    hero_class = None
    if hand.get("hero_cards"):
        try:
            hero_class = hand_class([parse_card(c) for c in hand["hero_cards"]])
        except ValueError:
            hero_class = None

    return {
        "positions": labels,
        "startingStacks": starting_stacks,
        "heroPosition": hero_position,
        "history": history,
        "anteBB": round((hand.get("ante") or 0.0) / bb, 4),
        "heroClass": hero_class,
        "heroCards": hand.get("hero_cards"),
        "heroAction": hero_action,
    }
