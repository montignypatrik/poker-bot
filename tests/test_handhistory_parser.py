from pokerlab.handhistory import hand_to_situation, iter_hands, seat_positions

CASH_HAND = """PokerStars Hand #111000001:  Hold'em No Limit ($0.02/$0.05 USD) - 2026/07/21 20:56:02 ET
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

TOURNEY_HAND = """PokerStars Hand #111000002: Tournament #999, $5+$0.50 USD Hold'em No Limit - Level I (25/50) - 2026/07/21 20:34:59 ET
Table '999 1' 6-max Seat #1 is the button
Seat 1: PatrikMontigny (5000 in chips)
Seat 2: Wanda (5000 in chips)
Seat 3: Greta (5000 in chips)
Seat 4: Gordon (5000 in chips)
Seat 5: Evan (5000 in chips)
Seat 6: Zara (5000 in chips)
PatrikMontigny: posts the ante 12
Wanda: posts the ante 12
Greta: posts the ante 12
Gordon: posts the ante 12
Evan: posts the ante 12
Zara: posts the ante 12
Wanda: posts small blind 25
Greta: posts big blind 50
*** HOLE CARDS ***
Dealt to PatrikMontigny [Ac Kd]
Gordon: folds
Evan: folds
Zara: folds
PatrikMontigny: raises 75 to 125
Wanda: folds
Greta: folds
Uncalled bet (75) returned to PatrikMontigny
PatrikMontigny collected 235 from pot
*** SUMMARY ***
Total pot 235 | Rake 0
Seat 1: PatrikMontigny (button) collected (235)
Seat 2: Wanda (small blind) folded before Flop
Seat 3: Greta (big blind) folded before Flop
Seat 4: Gordon folded before Flop (didn't bet)
Seat 5: Evan folded before Flop (didn't bet)
Seat 6: Zara folded before Flop (didn't bet)
"""

MISSED_BLIND_HAND = """PokerStars Hand #111000003:  Hold'em No Limit (100/200) - 2026/07/21 20:57:02 ET
Table 'PlayMoney' 3-max Seat #1 is the button
Seat 1: Shaunel (10000 in chips)
Seat 2: PatrikMontigny (10000 in chips)
Seat 3: Quredz (10000 in chips)
PatrikMontigny: posts small blind 100
Quredz: posts small & big blinds 300
*** HOLE CARDS ***
Dealt to PatrikMontigny [2c 6h]
Shaunel: folds
PatrikMontigny: checks
Quredz: checks
*** SUMMARY ***
Total pot 600 | Rake 0
Seat 1: Shaunel (button) folded before Flop
Seat 2: PatrikMontigny (small blind) checked
Seat 3: Quredz checked
"""

HU_HAND = """PokerStars Hand #111000004:  Hold'em No Limit ($0.01/$0.02 USD) - 2026/07/21 20:58:02 ET
Table 'HUTable' 2-max Seat #1 is the button
Seat 1: Villain ($3.00 in chips)
Seat 2: PatrikMontigny ($3.00 in chips)
Villain: posts small blind $0.01
PatrikMontigny: posts big blind $0.02
*** HOLE CARDS ***
Dealt to PatrikMontigny [Ks Kh]
Villain: raises $0.02 to $0.04
PatrikMontigny: raises $0.06 to $0.10
Villain: folds
Uncalled bet ($0.06) returned to PatrikMontigny
PatrikMontigny collected $0.08 from pot
*** SUMMARY ***
Total pot $0.08 | Rake $0
Seat 1: Villain (button) (small blind) folded before Flop
Seat 2: PatrikMontigny (big blind) collected ($0.08)
"""


def test_seat_positions_matches_standard_convention():
    assert seat_positions(2) == ["BTN", "BB"]
    assert seat_positions(3) == ["BTN", "SB", "BB"]
    assert seat_positions(6) == ["UTG", "HJ", "CO", "BTN", "SB", "BB"]
    assert seat_positions(9) == ["UTG", "UTG1", "UTG2", "LJ", "HJ", "CO", "BTN", "SB", "BB"]


def test_iter_hands_splits_multiple_hands_in_one_blob():
    blob = CASH_HAND + "\n\n\n" + TOURNEY_HAND
    hands = list(iter_hands(blob))
    assert [h["hand_id"] for h in hands] == ["111000001", "111000002"]


def test_cash_hand_parses_and_hero_bb_gets_the_walked_around_pot():
    hand = next(iter_hands(CASH_HAND))
    assert hand["game_type"] == "cash"
    assert hand["bb"] == 0.05
    assert hand["hero_name"] == "PatrikMontigny"
    assert hand["hero_cards"] == ["Jh", "9d"]
    assert hand["max_seats"] == 6
    assert len(hand["seats"]) == 6

    situation = hand_to_situation(hand)
    assert situation["heroPosition"] == "BB"
    assert situation["positions"] == ["UTG", "HJ", "CO", "BTN", "SB", "BB"]
    assert situation["history"] == [
        {"position": "UTG", "action": "fold", "toBB": 0},
        {"position": "HJ", "action": "fold", "toBB": 0},
        {"position": "CO", "action": "raise", "toBB": 2.6},
        {"position": "BTN", "action": "fold", "toBB": 0},
        {"position": "SB", "action": "fold", "toBB": 0},
    ]
    assert situation["startingStacks"]["BB"] == 100.0
    assert situation["heroClass"] == "J9o"
    assert situation["heroAction"] == {"position": "BB", "action": "fold", "toBB": 0}


def test_tournament_hand_hero_is_button_and_ante_converts_to_bb():
    hand = next(iter_hands(TOURNEY_HAND))
    assert hand["game_type"] == "tournament"
    assert hand["bb"] == 50
    assert hand["ante"] == 12

    situation = hand_to_situation(hand)
    assert situation["heroPosition"] == "BTN"
    assert situation["history"] == [
        {"position": "UTG", "action": "fold", "toBB": 0},
        {"position": "HJ", "action": "fold", "toBB": 0},
        {"position": "CO", "action": "fold", "toBB": 0},
    ]
    assert situation["anteBB"] == 0.24
    assert situation["heroClass"] == "AKo"
    assert situation["heroAction"] == {"position": "BTN", "action": "raise", "toBB": 2.5}


def test_missed_blind_line_does_not_break_parsing():
    hand = next(iter_hands(MISSED_BLIND_HAND))
    assert len(hand["seats"]) == 3
    situation = hand_to_situation(hand)
    assert situation["heroPosition"] == "SB"
    # hero (SB) acts before BB, so BB's "posts small & big blinds" catch-up
    # line must not have derailed the seat/ante parsing.
    assert situation["history"] == [{"position": "BTN", "action": "fold", "toBB": 0}]


def test_heads_up_button_acts_first_and_is_not_labeled_sb():
    hand = next(iter_hands(HU_HAND))
    situation = hand_to_situation(hand)
    assert situation["positions"] == ["BTN", "BB"]
    assert situation["heroPosition"] == "BB"
    assert situation["history"] == [{"position": "BTN", "action": "raise", "toBB": 2.0}]
    assert situation["heroClass"] == "KK"
    assert situation["heroAction"] == {"position": "BB", "action": "raise", "toBB": 5.0}
