from __future__ import annotations

import os
import re
from datetime import datetime
from pathlib import Path

from .handhistory import hand_to_situation, parse_file
from .webapi_postflop import APIError


def _hand_history_dir() -> Path | None:
    override = os.environ.get("POKER_STUDY_HAND_HISTORY_DIR")
    if override:
        path = Path(override)
        return path if path.is_dir() else None
    base = Path.home() / "AppData" / "Local" / "PokerStars" / "HandHistory"
    if not base.is_dir():
        return None
    subdirs = sorted((p for p in base.iterdir() if p.is_dir()), key=lambda p: p.name)
    return subdirs[0] if subdirs else None


def _resolve_file(name: str) -> Path:
    directory = _hand_history_dir()
    if directory is None:
        raise APIError(404, "no PokerStars hand history folder was found on this machine")
    candidate = (directory / name).resolve()
    if candidate != directory and directory not in candidate.parents:
        raise APIError(400, "invalid file")
    if not candidate.is_file():
        raise APIError(404, "hand history file not found")
    return candidate


_RESULT_AMOUNT = re.compile(r"\(\$?([\d.,]+)\)")


def _hero_result(hand: dict) -> dict | None:
    hero = hand.get("hero_name")
    if not hero:
        return None
    raw_text = hand["raw_text"]
    summary_start = raw_text.find("*** SUMMARY ***")
    summary = raw_text[summary_start:] if summary_start != -1 else raw_text
    for line in summary.splitlines():
        stripped = line.strip()
        if not stripped.startswith("Seat") or hero not in stripped:
            continue
        if "collected (" in stripped or "won (" in stripped:
            match = _RESULT_AMOUNT.search(stripped)
            return {"outcome": "won", "amount": float(match.group(1).replace(",", "")) if match else None}
        if "folded" in stripped:
            return {"outcome": "folded", "amount": None}
        return {"outcome": "other", "amount": None}
    return None


def list_files(_query: dict) -> dict:
    directory = _hand_history_dir()
    if directory is None:
        return {"directory": None, "files": [], "note": "no PokerStars hand history folder was found on this machine"}
    files = []
    for path in directory.glob("*.txt"):
        stat = path.stat()
        files.append({
            "name": path.name,
            "size": stat.st_size,
            "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
        })
    files.sort(key=lambda f: f["modified"], reverse=True)
    return {"directory": str(directory), "files": files}


def list_hands(query: dict) -> dict:
    name = query.get("file", [None])[0]
    if not name:
        raise APIError(400, "file query parameter is required")
    path = _resolve_file(name)
    hands = parse_file(path)
    summaries = []
    for hand in hands:
        situation = hand_to_situation(hand)
        summaries.append({
            "handId": hand["hand_id"],
            "datetime": hand["datetime"],
            "gameType": hand["game_type"],
            "maxSeats": hand["max_seats"],
            "heroCards": hand["hero_cards"],
            "heroPosition": situation.get("heroPosition"),
            "note": situation.get("note"),
            "result": _hero_result(hand),
        })
    return {"file": name, "hands": summaries}


def get_hand(query: dict) -> dict:
    name = query.get("file", [None])[0]
    hand_id = query.get("id", [None])[0]
    if not name or not hand_id:
        raise APIError(400, "file and id query parameters are required")
    path = _resolve_file(name)
    for hand in parse_file(path):
        if hand["hand_id"] == hand_id:
            return {**hand, "situation": hand_to_situation(hand)}
    raise APIError(404, "hand not found in file")


GET_ROUTES = {
    "/hand-history/files": list_files,
    "/hand-history/hands": list_hands,
    "/hand-history/hand": get_hand,
}
