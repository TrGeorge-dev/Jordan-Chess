#!/usr/bin/env python3
"""验证默认 Python AI 与 index.html AI 的行为同步。"""

import json
import os
import random
import shutil
import subprocess
import time
import unittest
from pathlib import Path

from ai_v3 import JordanSearchAI
from engine import BLACK, WHITE, JordanChess


ROOT = Path(__file__).resolve().parent


class HtmlBridge:
    def __init__(self):
        node = os.environ.get('NODE_BINARY') or shutil.which('node')
        if node is None:
            bundled = Path(
                '/Applications/ChatGPT.app/Contents/Resources/cua_node/bin/node')
            node = str(bundled) if bundled.exists() else 'node'
        self.process = subprocess.Popen(
            [node, str(ROOT / 'html_ai_bridge.mjs')], cwd=ROOT,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, bufsize=1)
        self.request_id = 0

    def request(self, payload):
        self.request_id += 1
        request = {'id': self.request_id, **payload}
        self.process.stdin.write(json.dumps(request) + '\n')
        self.process.stdin.flush()
        response = json.loads(self.process.stdout.readline())
        if not response['ok']:
            raise AssertionError(response['error'])
        return response['result']

    def close(self):
        if self.process.poll() is None:
            self.process.stdin.close()
            self.process.wait(timeout=5)


def payload(game, color, op='analyze', **extra):
    return {
        'op': op,
        'size': game.size,
        'board': game.board,
        'turn': game.turn,
        'history': game.history,
        'color': color,
        'seed': 1,
        **extra,
    }


class CrossLanguageParityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bridge = HtmlBridge()

    @classmethod
    def tearDownClass(cls):
        cls.bridge.close()

    def assert_analysis_equal(self, game, color):
        py = JordanSearchAI(game, color, time_budget=30,
                            max_depth=12, seed=1)
        py.deadline = time.perf_counter() + 30
        py._prepare()
        mine = py._tactical_map(color)
        opp = WHITE if color == BLACK else BLACK
        theirs = py._tactical_map(opp)
        html = self.bridge.request(payload(game, color))
        self.assertEqual([list(py.state.xy(move))
                          for move in py._winning_moves(color)],
                         html['threats'])
        expected_mine = [
            [list(py.state.xy(move)),
             [list(py.state.xy(point)) for point in wins]]
            for move, wins in mine.items()
        ]
        expected_theirs = [
            [list(py.state.xy(move)),
             [list(py.state.xy(point)) for point in wins]]
            for move, wins in theirs.items()
        ]
        self.assertEqual(expected_mine, html['tactical'])
        self.assertEqual(expected_theirs, html['opponentTactical'])
        expected_moves = [list(py.state.xy(move)) for move in
                          py._ordered_moves(color, 1, 0, root=True)]
        self.assertEqual(expected_moves,
                         html['moves'])
        self.assertEqual(py._evaluate(color), html['evaluation'])
        features = py._features(color)
        self.assertEqual([
            features.forks, features.t2, features.merge_points,
            features.frontier_edges, features.component_square,
            features.largest_component, features.open_square_one,
            features.open_square_two, features.center,
        ], html['features'])

    def test_random_positions_match_all_intermediate_results(self):
        rng = random.Random(20260807)
        for sample in range(16):
            game = JordanChess(size=4)
            target = 4 + sample % 9
            attempts = 0
            while len(game.history) < target and attempts < 200:
                attempts += 1
                moves = list(game.moves())
                if not moves:
                    break
                result = game.place(*rng.choice(moves))
                if result['winner'] is not None:
                    game.undo()
            for color in (BLACK, WHITE):
                with self.subTest(sample=sample, color=color):
                    self.assert_analysis_equal(game, color)

    def test_fixed_depth_search_matches(self):
        rng = random.Random(8817)
        for sample in range(8):
            game = JordanChess(size=4)
            for _ in range(5 + sample % 4):
                move = rng.choice(list(game.moves()))
                if game.place(*move)['winner'] is not None:
                    game.undo()
            color = game.turn
            py = JordanSearchAI(game, color, time_budget=30,
                                max_depth=2, seed=1)
            py.deadline = time.perf_counter() + 30
            py._prepare()
            moves = py._ordered_moves(color, 1, 0, root=True)
            if moves:
                py_move, py_score = py._search_root(2, moves)
            else:
                py_move, py_score = None, 0
            html = self.bridge.request(payload(
                game, color, op='fixed_depth', depth=2))
            with self.subTest(sample=sample):
                expected = (list(py.state.xy(py_move))
                            if py_move is not None else None)
                self.assertEqual(expected, html['move'])
                self.assertEqual(py_score, html['score'])

    def test_reported_trap_and_multiple_fork_defense_match(self):
        trap = JordanChess(size=10)
        for x, y in ((4, 4), (5, 4), (6, 4)):
            trap.board[x][y] = BLACK
        trap.board[5][3] = WHITE
        trap.turn = WHITE
        trap.history = [(4, 4, BLACK)]

        defense = JordanChess(size=4)
        for move in ((0,0),(2,2),(3,1),(2,3),(2,0),(0,3),(3,3),
                     (4,2),(1,1),(4,3),(4,4),(4,0),(1,2)):
            self.assertIsNone(defense.place(*move)['winner'])

        for game, color, expected in ((trap, WHITE, (5, 5)),
                                      (defense, WHITE, (1, 0))):
            py = JordanSearchAI(game, color, time_budget=2.0,
                                max_depth=12, seed=1)
            py_move = py.choose_move()
            html = self.bridge.request(payload(
                game, color, op='choose', budget=2.0, maxDepth=8))
            self.assertEqual(expected, py_move)
            self.assertEqual(list(expected), html['move'])


if __name__ == '__main__':
    unittest.main()
