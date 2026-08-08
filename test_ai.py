#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""约当棋 AI 自测。运行: python3 test_ai.py [-v]"""

import random
import sys
import time
import traceback

from engine import JordanChess, BLACK, WHITE, EMPTY
from ai import JordanAI, LegacyJordanAI


def setup(game, pieces, turn=BLACK):
    for (x, y), c in pieces.items():
        game.board[x][y] = c
    game.turn = turn


def play(size=10, black_ai=False, white_ai=False, seed=1, max_moves=300,
         time_budget=0.2, max_depth=3):
    """AI vs 随机/双 AI 对局, 返回终局。AI 走法必须合法。"""
    g = JordanChess(size=size)
    rng = random.Random(seed)
    ais = {}
    if black_ai:
        ais[BLACK] = JordanAI(g, BLACK, time_budget=time_budget,
                              max_depth=max_depth, seed=seed)
    if white_ai:
        ais[WHITE] = JordanAI(g, WHITE, time_budget=time_budget,
                              max_depth=max_depth, seed=seed + 1000)
    steps = 0
    while g.winner is None and steps < max_moves:
        moves = list(g.moves())
        if not moves:
            break
        if g.turn in ais:
            mv = ais[g.turn].choose_move()
            r = g.place(*mv)
            assert r['ok'], f'AI 走法非法: {mv} → {r}'
        else:
            g.place(*rng.choice(moves))
        steps += 1
    return g


# ---------------------------------------------------------------------------
# 威胁推理基础
# ---------------------------------------------------------------------------
def test_ai_takes_immediate_win():
    """AI 有一步成环点 → 直接走出获胜。"""
    g = JordanChess()
    setup(g, {(2, 2): BLACK, (2, 3): BLACK, (3, 3): BLACK}, turn=BLACK)
    ai = JordanAI(g, BLACK, seed=1)
    mv = ai.choose_move()
    assert mv == (3, 2), f'应走闭环点 (3,2), 实际 {mv}'
    r = g.place(*mv)
    assert r['winner'] == BLACK


def test_ai_blocks_single_threat():
    """对手有一个威胁点 → AI 必须堵。"""
    g = JordanChess()
    setup(g, {(4, 4): WHITE, (4, 5): WHITE, (5, 5): WHITE,
              (6, 4): BLACK, (6, 5): BLACK, (6, 6): BLACK,
              (5, 6): BLACK, (4, 6): BLACK}, turn=BLACK)
    ai = JordanAI(g, BLACK, seed=1)
    threats_white = ai._threats(WHITE, limit=5)
    assert threats_white, '构造的局面对手应存在威胁点'
    mv = ai.choose_move()
    assert mv in threats_white, f'应堵白方威胁点 {threats_white}, 实际走 {mv}'


def test_ai_detects_single_neighbor_t2():
    """单邻居延伸也可能在相邻空点制造 T1，不能被 T2 预筛选漏掉。"""
    g = JordanChess(size=5)
    setup(g, {
        (2, 1): BLACK, (1, 1): BLACK, (0, 1): BLACK, (0, 2): BLACK,
        (0, 3): BLACK, (0, 4): BLACK, (1, 4): BLACK, (2, 4): BLACK,
        (1, 2): WHITE, (1, 3): WHITE,
    }, turn=BLACK)
    ai = JordanAI(g, BLACK, time_budget=0.1, seed=1)
    assert ai._threats(BLACK) == []
    t2, _ = ai._t2_and_forks(BLACK)
    assert (2, 2) in t2, f'单邻居延伸点 (2,2) 应是 T2，实际 {t2}'

    # 旧版正是因为要求至少两个同色邻居而漏掉这个位置。
    legacy = LegacyJordanAI(g, BLACK, time_budget=0.1, seed=1)
    old_t2, old_forks = legacy._t2_and_forks(BLACK)
    assert (2, 2) not in old_t2 and (2, 2) not in old_forks


def test_ai_compares_multiple_fork_defenses():
    """多个对手 fork 并存时，应选择能同时化解它们的位置。"""
    g = JordanChess(size=4)
    for move in ((0, 0), (2, 2), (3, 1), (2, 3), (2, 0), (0, 3),
                 (3, 3), (4, 2), (1, 1), (4, 3), (4, 4), (4, 0),
                 (1, 2)):
        r = g.place(*move)
        assert r['ok'] and r['winner'] is None
    assert g.turn == WHITE

    ai = JordanAI(g, WHITE, time_budget=0.2, max_depth=8, seed=1)
    _, opponent_forks = ai._t2_and_forks(BLACK)
    assert set(opponent_forks) == {(0, 1), (1, 0), (2, 1)}
    assert ai.choose_move() == (1, 0)

    # 旧版任取第一个 (0,1)，黑方随后走 (2,1) 即产生双 T1。
    legacy = LegacyJordanAI(g, WHITE, time_budget=0.2,
                            max_depth=3, seed=1)
    assert legacy.choose_move() == (0, 1)


def test_ai_timeout_keeps_board_unchanged():
    """无论在哪一层超时，所有模拟棋子都必须被恢复。"""
    g = JordanChess(size=10)
    for move in ((5, 5), (4, 5), (5, 6), (4, 6)):
        assert g.place(*move)['ok']
    before = [row[:] for row in g.board]
    ai = JordanAI(g, g.turn, time_budget=0.01, max_depth=20, seed=1)
    mv = ai.choose_move()
    assert g.board == before
    assert g.get(*mv) == EMPTY
    assert ai.last_stats['elapsed'] < 0.2


def test_ai_threat_detection_agrees_with_engine():
    """威胁判定(并查集)与引擎环路检测(逐对 BFS)必须完全一致。"""
    rng = random.Random(3)
    for _ in range(40):
        g = JordanChess()
        for _ in range(rng.randint(6, 30)):
            moves = list(g.moves())
            if not moves:
                break
            g.place(*rng.choice(moves))
        if g.winner is not None:
            continue
        ai = JordanAI(g, g.turn, seed=1)
        for color in (BLACK, WHITE):
            pts = set(ai._threats(color))
            for (x, y) in list(pts)[:20]:
                g.turn = color             # 按对应颜色落子验证
                r = g.place(x, y)
                ok = (r['ok'] and r['loops'])
                g.undo()
                assert ok, f'威胁点 {(x, y)} 落子未成环, 与引擎不一致'
            for (x, y) in list(g.moves())[:10]:
                if (x, y) in pts:
                    continue
                g.turn = color
                r = g.place(x, y)
                if r['ok']:
                    assert not r['loops'], \
                        f'非威胁点 {(x, y)} 落子却成环, 与引擎不一致'
                    g.undo()


# ---------------------------------------------------------------------------
# 对局强度
# ---------------------------------------------------------------------------
def test_ai_beats_random_as_black():
    for seed in range(5):
        g = play(size=10, black_ai=True, seed=seed)
        assert g.winner == BLACK, \
            f'AI(黑) 对随机(白) 应全胜, seed={seed} 结果 {g.winner}'


def test_ai_beats_random_as_white():
    for seed in range(5):
        g = play(size=10, white_ai=True, seed=seed + 50)
        assert g.winner == WHITE, \
            f'AI(白) 对随机(黑) 应全胜, seed={seed} 结果 {g.winner}'


def test_ai_vs_ai_completes():
    for seed in range(3):
        g = play(size=10, black_ai=True, white_ai=True, seed=seed)
        assert g.winner is not None, f'AI 对 AI 应分出胜负, seed={seed}'


def test_ai_vs_ai_larger_board():
    for seed in range(2):
        g = play(size=15, black_ai=True, white_ai=True, seed=seed)
        assert g.winner is not None, f'15 路 AI 对 AI 应分出胜负, seed={seed}'


def test_ai_always_legal_and_fast():
    """AI 走法始终合法, 且耗时在预算内。"""
    g = JordanChess(size=10)
    ai = JordanAI(g, BLACK, time_budget=1.5, max_depth=3, seed=1)
    rng = random.Random(11)
    for _ in range(40):
        if g.winner is not None:
            break
        if g.turn == BLACK:
            t0 = time.time()
            mv = ai.choose_move()
            dt = time.time() - t0
            assert dt < 3.0, f'AI 超时: {dt:.2f}s'
            assert g.place(*mv)['ok']
        else:
            g.place(*rng.choice(list(g.moves())))


if __name__ == '__main__':
    verbose = '-v' in sys.argv
    tests = [(name, fn) for name, fn in sorted(globals().items())
             if name.startswith('test_') and callable(fn)]
    passed = failed = 0
    for name, fn in tests:
        try:
            fn()
            passed += 1
            if verbose:
                print(f'  ✓ {name}')
        except Exception as e:
            failed += 1
            print(f'  ✗ {name}: {type(e).__name__}: {e}')
            if verbose:
                traceback.print_exc()
    print(f'\n共 {len(tests)} 项测试: {passed} 通过, {failed} 失败')
    sys.exit(0 if failed == 0 else 1)
