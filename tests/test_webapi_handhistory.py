import json
import threading
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer

import pytest

import pokerlab.webapi as webapi

SAMPLE_HAND = """PokerStars Hand #222000001:  Hold'em No Limit ($0.02/$0.05 USD) - 2026/07/21 20:56:02 ET
Table 'TestTable' 6-max Seat #1 is the button
Seat 1: Alice ($6.37 in chips)
Seat 2: Bob ($3.17 in chips)
Seat 3: PatrikMontigny ($5 in chips)
Seat 4: Carol ($1.50 in chips)
Seat 5: Dave ($4.64 in chips)
Seat 6: Eve ($7.40 in chips)
Bob: posts small blind $0.02
PatrikMontigny: posts big blind $0.05
*** HOLE CARDS ***
Dealt to PatrikMontigny [Jh 9d]
Carol: folds
Dave: folds
Eve: raises $0.08 to $0.13
Alice: folds
Bob: folds
PatrikMontigny: folds
Uncalled bet ($0.08) returned to Eve
Eve collected $0.12 from pot
*** SUMMARY ***
Total pot $0.12 | Rake $0
Seat 1: Alice (button) folded before Flop (didn't bet)
Seat 2: Bob (small blind) folded before Flop
Seat 3: PatrikMontigny (big blind) folded before Flop
Seat 4: Carol folded before Flop (didn't bet)
Seat 5: Dave folded before Flop (didn't bet)
Seat 6: Eve collected ($0.12)
"""


@pytest.fixture()
def server(tmp_path, monkeypatch):
    (tmp_path / "HH sample.txt").write_text(SAMPLE_HAND, encoding="utf-8-sig")
    monkeypatch.setenv("POKER_STUDY_HAND_HISTORY_DIR", str(tmp_path))
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), webapi.Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield httpd.server_address
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=2)


def request(server, path):
    connection = HTTPConnection(*server, timeout=10)
    connection.request("GET", path)
    response = connection.getresponse()
    body = json.loads(response.read())
    connection.close()
    return response.status, body


def test_list_files(server):
    status, body = request(server, "/hand-history/files")
    assert status == 200
    assert [f["name"] for f in body["files"]] == ["HH sample.txt"]


def test_list_hands(server):
    status, body = request(server, "/hand-history/hands?file=HH%20sample.txt")
    assert status == 200
    assert len(body["hands"]) == 1
    hand = body["hands"][0]
    assert hand["handId"] == "222000001"
    assert hand["heroPosition"] == "BB"
    assert hand["heroCards"] == ["Jh", "9d"]
    assert hand["result"] == {"outcome": "folded", "amount": None}


def test_get_hand_includes_situation_for_the_gto_check(server):
    status, body = request(server, "/hand-history/hand?file=HH%20sample.txt&id=222000001")
    assert status == 200
    assert body["hero_name"] == "PatrikMontigny"
    assert body["situation"]["heroPosition"] == "BB"
    assert body["situation"]["history"][2] == {"position": "CO", "action": "raise", "toBB": 2.6}
    assert "*** SUMMARY ***" in body["raw_text"]


def test_unknown_hand_id_returns_404(server):
    status, body = request(server, "/hand-history/hand?file=HH%20sample.txt&id=999")
    assert status == 404
    assert "error" in body


def test_path_traversal_is_rejected(server):
    status, body = request(server, "/hand-history/hands?file=..%2F..%2Fsecret.txt")
    assert status in (400, 404)
    assert "error" in body
