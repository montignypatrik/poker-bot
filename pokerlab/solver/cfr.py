from __future__ import annotations

from collections import defaultdict


class CFRSolver:
    def __init__(self, game):
        self.game = game
        self.regret = defaultdict(lambda: defaultdict(float))
        self.strategy_sum = defaultdict(lambda: defaultdict(float))

    def _strategy(self, infoset, actions):
        regrets = self.regret[infoset]
        pos = {a: regrets[a] if regrets[a] > 0.0 else 0.0 for a in actions}
        total = sum(pos.values())
        if total > 0.0:
            return {a: pos[a] / total for a in actions}
        return {a: 1.0 / len(actions) for a in actions}

    def _cfr(self, h, p0, p1, pc):
        g = self.game
        if g.is_terminal(h):
            return g.utility(h)
        if g.is_chance(h):
            value = 0.0
            for action, prob in g.chance_outcomes(h):
                value += prob * self._cfr(g.next_history(h, action), p0, p1, pc * prob)
            return value

        player = g.current_player(h)
        infoset = g.infoset_key(h)
        actions = g.legal_actions(h)
        strategy = self._strategy(infoset, actions)

        util = {}
        node_util = 0.0
        for a in actions:
            child = g.next_history(h, a)
            if player == 0:
                util[a] = self._cfr(child, p0 * strategy[a], p1, pc)
            else:
                util[a] = self._cfr(child, p0, p1 * strategy[a], pc)
            node_util += strategy[a] * util[a]

        cf_reach = (p1 if player == 0 else p0) * pc
        sign = 1.0 if player == 0 else -1.0
        own_reach = p0 if player == 0 else p1
        for a in actions:
            self.regret[infoset][a] += cf_reach * sign * (util[a] - node_util)
            self.strategy_sum[infoset][a] += own_reach * strategy[a]
        return node_util

    def train(self, iterations):
        for _ in range(iterations):
            self._cfr(self.game.initial_history(), 1.0, 1.0, 1.0)

    def average_strategy(self):
        avg = {}
        for infoset, ssum in self.strategy_sum.items():
            total = sum(ssum.values())
            if total > 0.0:
                avg[infoset] = {a: ssum[a] / total for a in ssum}
            else:
                n = len(ssum)
                avg[infoset] = {a: 1.0 / n for a in ssum}
        return avg


def expected_value(game, strategy):
    def walk(h):
        if game.is_terminal(h):
            return game.utility(h)
        if game.is_chance(h):
            return sum(pr * walk(game.next_history(h, a)) for a, pr in game.chance_outcomes(h))
        sigma = strategy[game.infoset_key(h)]
        return sum(sigma[a] * walk(game.next_history(h, a)) for a in game.legal_actions(h))

    return walk(game.initial_history())


def best_response_value(game, br_player, opp_strategy):
    infoset_hist = defaultdict(list)

    def enumerate_tree(h, reach_opp):
        if game.is_terminal(h):
            return
        if game.is_chance(h):
            for a, pr in game.chance_outcomes(h):
                enumerate_tree(game.next_history(h, a), reach_opp * pr)
            return
        player = game.current_player(h)
        if player == br_player:
            infoset_hist[game.infoset_key(h)].append((h, reach_opp))
            for a in game.legal_actions(h):
                enumerate_tree(game.next_history(h, a), reach_opp)
        else:
            sigma = opp_strategy[game.infoset_key(h)]
            for a in game.legal_actions(h):
                enumerate_tree(game.next_history(h, a), reach_opp * sigma[a])

    enumerate_tree(game.initial_history(), 1.0)

    br_action = {}

    def subtree_value(h):
        if game.is_terminal(h):
            u = game.utility(h)
            return u if br_player == 0 else -u
        if game.is_chance(h):
            return sum(pr * subtree_value(game.next_history(h, a)) for a, pr in game.chance_outcomes(h))
        player = game.current_player(h)
        if player == br_player:
            a = br_action[game.infoset_key(h)]
            return subtree_value(game.next_history(h, a))
        sigma = opp_strategy[game.infoset_key(h)]
        return sum(sigma[a] * subtree_value(game.next_history(h, a)) for a in game.legal_actions(h))

    for infoset in sorted(infoset_hist, key=lambda k: len(infoset_hist[k][0][0]), reverse=True):
        histories = infoset_hist[infoset]
        actions = game.legal_actions(histories[0][0])
        q = {a: 0.0 for a in actions}
        for h, reach in histories:
            for a in actions:
                q[a] += reach * subtree_value(game.next_history(h, a))
        br_action[infoset] = max(q, key=q.get)

    return subtree_value(game.initial_history())


def exploitability(game, strategy):
    br0 = best_response_value(game, 0, strategy)
    br1 = best_response_value(game, 1, strategy)
    return (br0 + br1) / 2.0
