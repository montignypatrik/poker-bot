from __future__ import annotations

import json
import mimetypes
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from .preflop.mtt_icm import solve_mtt_preflop_subgame, solve_mtt_rfi
from .webapi_handhistory import GET_ROUTES as HANDHISTORY_GET_ROUTES
from .webapi_postflop import GET_ROUTES, POST_ROUTES

HOST = os.environ.get("POKERBOT_WEBAPI_HOST", "127.0.0.1")
PORT = int(os.environ.get("POKERBOT_WEBAPI_PORT", "5602"))

POSITIONS_9MAX = ["UTG", "UTG1", "UTG2", "LJ", "HJ", "CO", "BTN", "SB", "BB"]
MAX_RAISES = 8


def _padded_bet_sizes(committed: list[float], opener_stack: float, defender_stack: float) -> list[float]:
    sizes = list(committed)
    cap = min(opener_stack, defender_stack)
    target = min(MAX_RAISES, len(committed) + 2)
    while len(sizes) < target:
        nxt = round(min(cap, sizes[-1] * 2.5), 2)
        if nxt <= sizes[-1]:
            break
        sizes.append(nxt)
    return sizes


def _starting_stacks(positions: list[str], starting_stacks: dict, ante_bb: float) -> list[float]:
    stacks = []
    for pos in positions:
        s = float(starting_stacks[pos]) - ante_bb
        if pos == "SB":
            s -= 0.5
        if pos == "BB":
            s -= 1.0
        stacks.append(max(0.1, s))
    return stacks


def _classify_actions(positions: list[str], actions: list[dict], hero_position: str):
    valid_positions = set(positions)
    for a in actions:
        if a["position"] not in valid_positions:
            raise ValueError(f"unknown position {a['position']!r}")
    if hero_position not in valid_positions:
        raise ValueError(f"unknown heroPosition {hero_position!r}")

    raises = [a for a in actions if a["action"] == "raise"]
    extra_dead_money = sum(a["toBB"] for a in actions if a["action"] == "call")

    if not raises:
        return {"shape": "rfi", "hero_position": hero_position, "extra_dead_money": extra_dead_money}
    if len(raises) > MAX_RAISES:
        raise ValueError(f"{len(raises)}-bet+ pots aren't modeled (cap is {MAX_RAISES} raises)")

    opener_pos = raises[0]["position"]
    defender_pos = next((r["position"] for r in raises[1:] if r["position"] != opener_pos), None)
    if defender_pos is None:
        defender_pos = hero_position
        if defender_pos == opener_pos:
            raise ValueError("heroPosition must differ from the opener when only one raise has occurred")

    expected = [opener_pos, defender_pos]
    for i, r in enumerate(raises):
        want = expected[i % 2]
        if r["position"] != want:
            raise ValueError(
                f"raise #{i + 1} expected from {want!r}, got {r['position']!r} -- "
                "raises must alternate between the two live raisers"
            )

    n = len(raises)
    shape = "vs_raise" if n == 1 else f"vs_{n + 1}bet"
    return {
        "shape": shape,
        "opener": opener_pos,
        "defender": defender_pos,
        "bet_sizes": [r["toBB"] for r in raises],
        "hero_position": hero_position,
        "extra_dead_money": extra_dead_money,
    }


def _solve_mtt_preflop(payload: dict) -> dict:
    positions = payload.get("positions", POSITIONS_9MAX)
    starting_stacks = payload["startingStacks"]
    actions = payload.get("actions", [])
    hero_position = payload["heroPosition"]
    payouts = payload["payouts"]
    ante_bb = float(payload.get("anteBB", 0.0))
    iterations = int(payload.get("iterations", 20000))

    situation = _classify_actions(positions, actions, hero_position)
    stacks = _starting_stacks(positions, starting_stacks, ante_bb)
    base_dead_money = 1.5 + len(positions) * ante_bb + situation["extra_dead_money"]

    hero_position = situation["hero_position"]
    hero_idx = positions.index(hero_position)

    if situation["shape"] == "rfi":
        num_behind = len(positions) - 1 - hero_idx
        rfi = solve_mtt_rfi(
            full_stacks=stacks,
            payouts=payouts,
            opener_idx=hero_idx,
            num_players_behind=num_behind,
            dead_money_bb=base_dead_money,
        )
        return {"shape": "rfi", "rfi": rfi}

    opener_idx = positions.index(situation["opener"])
    defender_idx = positions.index(situation["defender"])

    num_behind_opener = len(positions) - 1 - opener_idx
    rfi = solve_mtt_rfi(
        full_stacks=stacks,
        payouts=payouts,
        opener_idx=opener_idx,
        num_players_behind=num_behind_opener,
        dead_money_bb=1.5 + len(positions) * ante_bb,
    )

    bet_sizes = _padded_bet_sizes(situation["bet_sizes"], stacks[opener_idx], stacks[defender_idx])
    subgame = solve_mtt_preflop_subgame(
        opener_range=rfi["open_freq"],
        full_stacks=stacks,
        payouts=payouts,
        opener_idx=opener_idx,
        defender_idx=defender_idx,
        bet_sizes_bb=bet_sizes,
        dead_money_bb=base_dead_money,
        iterations=iterations,
    )
    subgame["levels"] = subgame["levels"][: len(situation["bet_sizes"])]
    return {"shape": situation["shape"], "rfi": rfi, "opener": situation["opener"],
            "defender": situation["defender"], **subgame}


_ROUTES = {
    ("POST", "/mtt-preflop"): _solve_mtt_preflop,
    **{("POST", path): handler for path, handler in POST_ROUTES.items()},
    **{("GET", path): handler for path, handler in GET_ROUTES.items()},
    **{("GET", path): handler for path, handler in HANDHISTORY_GET_ROUTES.items()},
}


def _study_root():
    override = os.environ.get("POKER_STUDY_STATIC_ROOT")
    if override:
        return Path(override).resolve()
    root = Path(sys._MEIPASS) if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent
    return (root / "study_app").resolve()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(f"[webapi] {self.address_string()} - {fmt % args}")

    def _send_json(self, status: int, payload: dict):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", f"http://{HOST}:{PORT}")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path):
        root = _study_root()
        relative = unquote(path).lstrip("/") or "index.html"
        candidate = (root / relative).resolve()
        if candidate != root and root not in candidate.parents:
            self._send_json(404, {"error": "not found"})
            return
        if not candidate.is_file():
            self._send_json(404, {"error": "not found"})
            return
        body = candidate.read_bytes()
        content_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8" if content_type.startswith("text/") else content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", f"http://{HOST}:{PORT}")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        parsed = urlsplit(self.path)
        if parsed.path == "/health":
            self._send_json(200, {"status": "ok", "service": "poker-study"})
            return
        handler = _ROUTES.get(("GET", parsed.path))
        if handler is not None:
            try:
                self._send_json(200, handler(parse_qs(parsed.query)))
            except Exception as exc:  # noqa: BLE001
                self._send_json(getattr(exc, "status", 500), {"error": str(exc)})
            return
        self._send_file(parsed.path)

    def do_POST(self):
        parsed = urlsplit(self.path)
        handler = _ROUTES.get(("POST", parsed.path))
        if handler is None:
            self._send_json(404, {"error": f"no route for {parsed.path}"})
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            if length > 1_000_000:
                raise ValueError("request body is too large")
            raw = self.rfile.read(length) if length else b"{}"
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                raise ValueError("request body must be a JSON object")
            result = handler(payload)
            self._send_json(200, result)
        except Exception as exc:  # noqa: BLE001
            self._send_json(getattr(exc, "status", 500), {"error": str(exc)})


def main():
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"pokerlab webapi listening on http://{HOST}:{PORT}")
    print("Routes: GET /health, POST /mtt-preflop, POST /postflop-node, "
          "GET /hand-history/{files,hands,hand}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
