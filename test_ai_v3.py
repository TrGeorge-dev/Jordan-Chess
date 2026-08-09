#!/usr/bin/env python3
"""Correctness and tactical tests for the independent V3 search core."""

import random
import time
import unittest

from ai_v3 import JordanSearchAI, SearchState
from engine import BLACK, EMPTY, WHITE, JordanChess


class SearchStateTests(unittest.TestCase):
    def test_threats_match_engine_on_random_legal_positions(self):
        rng = random.Random(31173)
        for sample in range(36):
            game = JordanChess(size=5)
            for _ in range(4 + sample % 17):
                moves = list(game.moves())
                if not moves:
                    break
                result = game.place(*rng.choice(moves))
                if result["winner"] is not None:
                    game.undo()
            state = SearchState(game)
            for color in (BLACK, WHITE):
                actual = set(state.xy(move) for move in
                             state.winning_moves(color))
                expected = set()
                for x, y in game.moves():
                    game.turn = color
                    result = game.place(x, y)
                    if result["loops"]:
                        expected.add((x, y))
                    game.undo()
                self.assertEqual(expected, actual)

    def test_play_undo_restores_all_state(self):
        game = JordanChess(size=6)
        for move in ((3, 3), (2, 3), (3, 4), (2, 4), (4, 4)):
            game.place(*move)
        state = SearchState(game)
        before_board = state.board[:]
        before_hash = state.hash
        before_threats = {
            color: state.winning_moves(color) for color in (BLACK, WHITE)}
        tokens = []
        for move, color in (((4, 3), WHITE), ((1, 3), BLACK),
                            ((1, 4), WHITE)):
            tokens.append(state.play(state.index(move), color))
        for token in reversed(tokens):
            state.undo(token)
        self.assertEqual(before_board, state.board)
        self.assertEqual(before_hash, state.hash)
        self.assertEqual(before_threats, {
            color: state.winning_moves(color) for color in (BLACK, WHITE)})

    def test_cycle_is_reported_on_the_winning_play(self):
        game = JordanChess(size=5)
        game.board[2][2] = BLACK
        game.board[2][3] = BLACK
        game.board[3][3] = BLACK
        state = SearchState(game)
        move = state.index((3, 2))
        self.assertTrue(state.is_winning_move(move, BLACK))
        token = state.play(move, BLACK)
        self.assertTrue(token.won)
        state.undo(token)


class SearchAITests(unittest.TestCase):
    def test_incremental_tactical_map_matches_simulation(self):
        rng = random.Random(9481)
        for sample in range(20):
            game = JordanChess(size=5)
            for _ in range(3 + sample % 12):
                move = rng.choice(list(game.moves()))
                if game.place(*move)["winner"] is not None:
                    game.undo()
            ai = JordanSearchAI(game, game.turn, time_budget=5)
            ai.state = SearchState(game)
            ai.deadline = time.perf_counter() + 5
            for color in (BLACK, WHITE):
                if ai.state.winning_moves(color):
                    continue
                fast = ai._tactical_map(color)
                brute = {}
                for move in ai.state.frontier_moves():
                    token = ai.state.play(move, color)
                    try:
                        wins = ai.state.winning_moves(color, limit=3)
                    finally:
                        ai.state.undo(token)
                    if wins:
                        brute[move] = wins
                self.assertEqual(brute, fast)

    def test_takes_immediate_win(self):
        game = JordanChess(size=5)
        game.board[2][2] = BLACK
        game.board[2][3] = BLACK
        game.board[3][3] = BLACK
        game.turn = BLACK
        ai = JordanSearchAI(game, BLACK, time_budget=0.2)
        self.assertEqual((3, 2), ai.choose_move())

    def test_blocks_reported_three_stone_trap(self):
        game = JordanChess(size=10)
        for x, y in ((4, 4), (5, 4), (6, 4)):
            game.board[x][y] = BLACK
        game.board[5][3] = WHITE
        game.turn = WHITE
        ai = JordanSearchAI(game, WHITE, time_budget=0.4)
        self.assertEqual((5, 5), ai.choose_move())

    def test_search_does_not_mutate_game(self):
        game = JordanChess(size=8)
        for move in ((4, 4), (3, 4), (4, 5), (3, 5)):
            game.place(*move)
        board = [row[:] for row in game.board]
        ai = JordanSearchAI(game, game.turn, time_budget=0.03,
                            max_depth=20)
        move = ai.choose_move()
        self.assertEqual(board, game.board)
        self.assertEqual(EMPTY, game.get(*move))
        self.assertLess(time.perf_counter() -
                        (time.perf_counter() - ai.last_stats["elapsed"]), .2)

    def test_always_returns_legal_move(self):
        rng = random.Random(817)
        game = JordanChess(size=6)
        for _ in range(20):
            if game.winner is not None:
                break
            ai = JordanSearchAI(game, game.turn, time_budget=0.03,
                                max_depth=8)
            move = ai.choose_move()
            self.assertIn(move, set(game.moves()))
            result = game.place(*move)
            self.assertTrue(result["ok"])
            if game.winner is None:
                # Add occasional different play so the test is not pure mirror.
                move = rng.choice(list(game.moves()))
                game.place(*move)


if __name__ == "__main__":
    unittest.main(verbosity=2)
