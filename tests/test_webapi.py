import json
import threading
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer

import pytest

import pokerlab.webapi as webapi


@pytest.fixture()
def server(monkeypatch):
    classes = {"AA": 1.0, "72o": 0.0}
    monkeypatch.setattr(webapi, "solve_mtt_rfi", lambda **_kwargs: {"open_freq": classes, "open_pct": 0.45})

    def fake_subgame(**kwargs):
        bet_sizes = kwargs["bet_sizes_bb"]
        levels = []
        for m, size in enumerate(bet_sizes):
            role = "defender" if m % 2 == 0 else "opener"
            levels.append({"role": role, "betSizeBB": size, "strategies": {"AA": {"f": 0.0, "c": 0.2, "r": 0.8}}})
        return {"levels": levels}

    monkeypatch.setattr(webapi, "solve_mtt_preflop_subgame", fake_subgame)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), webapi.Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield httpd.server_address
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=2)


def request(server, method, path, payload=None, raw=None):
    connection = HTTPConnection(*server, timeout=10)
    body = raw if raw is not None else (json.dumps(payload) if payload is not None else None)
    headers = {"Content-Type": "application/json"} if body is not None else {}
    connection.request(method, path, body=body, headers=headers)
    response = connection.getresponse()
    content_type = response.getheader("Content-Type", "")
    body = response.read()
    connection.close()
    parsed = json.loads(body) if "application/json" in content_type else body
    return response.status, content_type, parsed


POSITIONS_9MAX = ["UTG", "UTG1", "UTG2", "LJ", "HJ", "CO", "BTN", "SB", "BB"]


def preflop_payload(raises, positions=POSITIONS_9MAX, opener="UTG", defender="BTN", hero=None, prefix_folds=()):
    actions = [{"position": pos, "action": "fold", "toBB": 0} for pos in prefix_folds]
    raisers = [opener, defender] * raises
    for index in range(raises):
        actions.append({"position": raisers[index], "action": "raise", "toBB": 2.3 + index * 4})
    return {
        "positions": positions,
        "startingStacks": {position: 40 for position in positions},
        "heroPosition": hero or (defender if raises else opener),
        "actions": actions,
        "payouts": [100, 60, 40],
        "anteBB": 0.125,
        "iterations": 10,
    }


def test_health_static_files_and_unknown_route(server):
    status, _, health = request(server, "GET", "/health")
    assert status == 200
    assert health == {"status": "ok", "service": "poker-study"}

    status, content_type, page = request(server, "GET", "/")
    assert status == 200
    assert content_type.startswith("text/html")
    assert b"Poker Study" in page

    status, content_type, script = request(server, "GET", "/js/app.js")
    assert status == 200
    assert "javascript" in content_type
    assert b"preflop_trainer" in script

    assert request(server, "GET", "/%2e%2e/README.md")[0] == 404
    assert request(server, "POST", "/unknown", {})[0] == 404


@pytest.mark.parametrize("raises,shape", [(0, "rfi"), (1, "vs_raise"), (2, "vs_3bet"), (3, "vs_4bet"), (5, "vs_6bet")])
def test_all_preflop_shapes_over_real_http(server, raises, shape):
    status, _, result = request(server, "POST", "/mtt-preflop", preflop_payload(raises))
    assert status == 200
    assert result["shape"] == shape
    assert "rfi" in result
    if raises:
        assert result["opener"] == "UTG"
        assert result["defender"] == "BTN"
        levels = result["levels"]
        assert len(levels) == raises
        assert [lvl["role"] for lvl in levels] == ["defender" if i % 2 == 0 else "opener" for i in range(raises)]


def test_nine_max_positions_and_folds_before_opener(server):
    payload = preflop_payload(1, opener="UTG2", defender="CO", hero="CO", prefix_folds=["UTG", "UTG1"])
    status, _, result = request(server, "POST", "/mtt-preflop", payload)
    assert status == 200
    assert result["shape"] == "vs_raise"
    assert result["opener"] == "UTG2"


def test_raise_ladder_must_alternate_between_the_two_raisers(server):
    payload = preflop_payload(2)
    payload["actions"].append({"position": "CO", "action": "raise", "toBB": 20})
    status, _, result = request(server, "POST", "/mtt-preflop", payload)
    assert status == 500
    assert "alternate" in result["error"]


def test_raise_ladder_deeper_than_cap_is_rejected(server):
    status, _, result = request(server, "POST", "/mtt-preflop", preflop_payload(9))
    assert status == 500
    assert "error" in result


def test_malformed_json_returns_500(server):
    status, _, result = request(server, "POST", "/mtt-preflop", raw="{")
    assert status == 500
    assert "error" in result
