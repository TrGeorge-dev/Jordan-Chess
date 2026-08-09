#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""约当棋引擎自测（规则: 形成任何闭环即获胜）。运行: python3 test_engine.py [-v]"""

import random
import sys
import traceback

from engine import JordanChess, BLACK, WHITE, EMPTY


# ---------------------------------------------------------------------------
# 白盒测试辅助
# ---------------------------------------------------------------------------
def setup(game, pieces, turn=BLACK):
    """直接写入指定棋盘状态并设定轮次(绕过回合交替)。"""
    for (x, y), c in pieces.items():
        game.board[x][y] = c
    game.turn = turn


def check_cycle(game, cycle, color):
    """校验闭环: 顶点互异、相邻顶点八连通(切比雪夫距离 1)、全为同色。"""
    assert len(cycle) >= 4, f'闭环至少 4 个顶点: {cycle}'
    assert len(set(cycle)) == len(cycle), f'闭环存在重复顶点: {cycle}'
    for i in range(len(cycle)):
        a, b = cycle[i], cycle[(i + 1) % len(cycle)]
        assert max(abs(a[0] - b[0]), abs(a[1] - b[1])) == 1, \
            f'闭环相邻顶点不相连: {a} - {b}'
        assert game.board[a[0]][a[1]] == color, f'闭环顶点 {a} 非己方棋子'


# ---------------------------------------------------------------------------
# 基础落子规则
# ---------------------------------------------------------------------------
def test_place_basics():
    g = JordanChess()
    assert g.turn == BLACK                     # 黑方先手
    r = g.place(5, 5)
    assert r['ok'] and r['winner'] is None and r['loops'] == []
    assert g.turn == WHITE and g.get(5, 5) == BLACK
    assert not g.place(5, 5)['ok']             # 已占用格点禁止重复落子
    assert not g.place(-1, 0)['ok']            # 越界
    assert not g.place(0, 11)['ok']
    assert g.place(0, 0)['ok'] and g.turn == BLACK
    assert g.place(10, 10)['ok'] and g.turn == WHITE
    assert len(g.history) == 3                 # 历史记录(仅记成功落子)


def test_no_cycle_scattered():
    g = JordanChess()
    setup(g, {(2, 2): BLACK, (5, 5): BLACK, (8, 8): BLACK,
              (2, 8): WHITE, (8, 2): WHITE, (3, 3): WHITE}, turn=WHITE)
    r = g.place(9, 9)
    assert r['ok'] and r['loops'] == []
    assert g.winner is None and g.turn == BLACK


def test_triangle_not_a_loop():
    """3 顶点三角形(八连通)不算闭环: 环至少 4 个顶点。"""
    g = JordanChess()
    setup(g, {(2, 2): BLACK, (3, 3): BLACK}, turn=BLACK)
    r = g.place(2, 3)          # (2,2)-(2,3)-(3,3) 三角形, 3 顶点
    assert r['ok'] and r['loops'] == [] and g.winner is None


def test_diagonal_connectivity():
    """斜向相邻现在视为连通(ADR-0001 八连通)。"""
    g = JordanChess()
    setup(g, {(1, 1): BLACK, (2, 2): BLACK, (5, 5): BLACK,
              (6, 5): BLACK, (9, 9): WHITE})
    comp = g._component((1, 1), avoid=None, color=BLACK)
    assert comp == {(1, 1), (2, 2)}            # 斜对角连通
    assert g._component((5, 5), avoid=None, color=BLACK) == {(5, 5), (6, 5)}


def test_x_shape_no_win():
    """X 形 4 子(两条对角线交叉)内部无格点 → 不构成闭环(ADR-0002)。"""
    g = JordanChess()
    setup(g, {(2, 2): BLACK, (3, 3): BLACK, (3, 2): BLACK}, turn=BLACK)
    r = g.place(2, 3)          # 第 4 子: X 形 (2,2)(3,3)(3,2)(2,3)
    assert r['ok'] and r['winner'] is None and r['loops'] == []
    assert g.turn == WHITE


def test_checkerboard_inevitably_loops():
    """棋盘格填色在八连通下必然存在环(斜对角同色) —— 旧平局形态消失。"""
    g = JordanChess()
    for x in range(11):
        for y in range(11):
            g.board[x][y] = BLACK if (x + y) % 2 == 0 else WHITE
    g.board[5][5] = EMPTY
    g.turn = BLACK
    r = g.place(5, 5)          # 棋盘格中任意落子即成环
    assert r['ok'] and r['winner'] == BLACK and len(r['loops']) >= 1


# ---------------------------------------------------------------------------
# 闭环即胜: 核心规则
# ---------------------------------------------------------------------------
def test_unit_square_no_win():
    """4 子单位方格内部无格点 → 不构成闭环(ADR-0002: 环内需 ≥1 格点)。"""
    g = JordanChess()
    setup(g, {(2, 2): BLACK, (2, 3): BLACK, (3, 3): BLACK}, turn=BLACK)
    r = g.place(3, 2)
    assert r['ok'] and r['winner'] is None and r['loops'] == []
    assert g.turn == WHITE


def test_diamond_wins():
    """4 子斜菱形(内部恰 1 格点) → 立即获胜(ADR-0002 下最小有效环)。"""
    g = JordanChess()
    setup(g, {(2, 1): BLACK, (1, 2): BLACK, (3, 2): BLACK}, turn=BLACK)
    r = g.place(2, 3)          # 斜菱形 (2,1)(1,2)(3,2)(2,3), 内部 (2,2)
    assert r['ok'] and r['winner'] == BLACK
    assert len(r['loops']) >= 1
    for loop in r['loops']:
        check_cycle(g, loop, BLACK)


def test_four_move_first_win():
    """真实回合交替下, 黑方第 4 手即可获胜(对手未阻挡时, 斜菱形)。"""
    g = JordanChess()
    assert g.place(2, 1)['ok']   # 黑 1
    assert g.place(0, 0)['ok']   # 白 1
    assert g.place(1, 2)['ok']   # 黑 2
    assert g.place(0, 1)['ok']   # 白 2
    assert g.place(3, 2)['ok']   # 黑 3
    assert g.place(0, 2)['ok']   # 白 3
    r = g.place(2, 3)                          # 黑 4: 斜菱形完成, 内部 (2,2)
    assert r['ok'] and r['winner'] == BLACK and len(r['loops']) >= 1


def test_loop_around_opponent_no_removal():
    """闭环内部虽有对方棋子, 但只判胜负、不移除任何棋子。"""
    g = JordanChess()
    setup(g, {(4, 4): BLACK, (5, 4): BLACK, (6, 4): BLACK, (6, 5): BLACK,
              (6, 6): BLACK, (5, 6): BLACK, (4, 6): BLACK,
              (5, 5): WHITE}, turn=BLACK)
    r = g.place(4, 5)
    assert r['ok'] and r['winner'] == BLACK
    assert len(r['loops']) >= 1                # 八连通下斜边产生多个环
    assert g.get(5, 5) == WHITE                # 被围白子不移除
    assert g.get(4, 5) == BLACK


def test_three_sides_no_loop():
    """缺一边的 U 形不是闭环, 不成环即不获胜。"""
    g = JordanChess()
    setup(g, {(0, 0): BLACK, (1, 0): BLACK, (2, 0): BLACK, (3, 0): BLACK,
              (3, 1): BLACK, (3, 2): BLACK, (2, 2): BLACK, (1, 2): BLACK,
              (1, 1): WHITE}, turn=BLACK)
    r = g.place(0, 2)                          # 缺 (0,1) 无法闭合
    assert r['ok'] and r['loops'] == []
    assert g.winner is None and g.turn == WHITE


def test_loop_with_tail():
    """环外带"尾巴"分支不影响闭环判定与获胜。"""
    g = JordanChess()
    setup(g, {(2, 2): BLACK, (3, 2): BLACK, (4, 2): BLACK, (4, 3): BLACK,
              (4, 4): BLACK, (3, 4): BLACK, (2, 4): BLACK,
              (2, 1): BLACK,                    # 尾巴
              (3, 3): WHITE}, turn=BLACK)
    r = g.place(2, 3)
    assert r['ok'] and r['winner'] == BLACK
    assert len(r['loops']) >= 1                # 八连通下环形态多样
    assert g.get(3, 3) == WHITE                # 环内棋子不移除


def test_loop_touching_border_valid():
    """环完全由棋子闭合, 贴着棋盘边缘也是有效闭环。"""
    g = JordanChess()
    setup(g, {(0, 0): BLACK, (1, 0): BLACK, (2, 0): BLACK, (2, 1): BLACK,
              (2, 2): BLACK, (1, 2): BLACK, (0, 2): BLACK,
              (1, 1): WHITE}, turn=BLACK)
    r = g.place(0, 1)
    assert r['ok'] and r['winner'] == BLACK
    assert len(r['loops']) >= 1


def test_multiple_loops_detected():
    """新落子同时闭合两个环 + 一个外包大环 → 全部检出并获胜。"""
    g = JordanChess()
    setup(g, {
        (2, 2): BLACK, (3, 2): BLACK, (4, 2): BLACK, (4, 3): BLACK,
        (3, 4): BLACK, (2, 4): BLACK, (2, 3): BLACK,
        (5, 4): BLACK, (5, 5): BLACK, (5, 6): BLACK, (4, 6): BLACK,
        (3, 6): BLACK, (3, 5): BLACK,
        (3, 3): WHITE, (4, 5): WHITE, (7, 7): WHITE,
    }, turn=BLACK)
    r = g.place(4, 4)                          # v: 两环的公共端点
    assert r['ok'] and r['winner'] == BLACK
    assert len(r['loops']) >= 3                # 八连通下环数只多不少
    for loop in r['loops']:
        check_cycle(g, loop, BLACK)


def test_figure8_shared_vertex_no_big_loop():
    """两个环仅共享顶点 v: 不构成"8字形"大简单环, 只检出两个小环。"""
    g = JordanChess()
    setup(g, {
        (2, 2): BLACK, (3, 2): BLACK, (4, 2): BLACK, (4, 3): BLACK,
        (3, 4): BLACK, (2, 4): BLACK, (2, 3): BLACK,
        (5, 4): BLACK, (6, 4): BLACK, (6, 5): BLACK, (6, 6): BLACK,
        (5, 6): BLACK, (4, 6): BLACK, (4, 5): BLACK,
        (3, 3): WHITE, (5, 5): WHITE,
    }, turn=BLACK)
    r = g.place(4, 4)
    assert r['ok'] and r['winner'] == BLACK
    assert len(r['loops']) >= 2                # 八连通下环数只多不少


# ---------------------------------------------------------------------------
# 射线法单元测试(数学工具, 规则变体可用)
# ---------------------------------------------------------------------------
def test_ray_casting():
    pt = JordanChess._point_in_polygon
    square = [(0, 0), (1, 0), (1, 1), (0, 1)]
    assert pt(0.5, 0.5, square)                # 内部
    assert not pt(2, 2, square)                # 外部
    assert not pt(1.5, 0.5, square)
    assert not pt(-1, 0.5, square)

    cshape = [(0, 0), (2, 0), (2, 2), (1, 2), (1, 1), (0, 1)]   # C 形凹多边形
    assert pt(0.5, 0.5, cshape)                # 凹多边形内
    assert pt(1.5, 1.5, cshape)
    assert not pt(0.5, 1.5, cshape)            # 凹口内(外)
    assert not pt(3, 3, cshape)

    big = [(0, 0), (3, 0), (3, 3), (0, 3)]     # 射线恰好穿过顶点高度的情形
    assert pt(1.5, 1, big)
    assert not pt(4, 1, big)
    assert pt(2.5, 2.5, big)

    stair = [(0, 0), (1, 0), (2, 0), (2, 1), (2, 2), (1, 2), (1, 1), (0, 1)]
    assert pt(1.5, 1.5, stair)                 # 阶梯形多边形
    assert not pt(0.5, 1.5, stair)


# ---------------------------------------------------------------------------
# 历史回溯 / 平局
# ---------------------------------------------------------------------------
def test_undo():
    g = JordanChess()
    g.place(5, 5)
    g.place(0, 0)
    g.place(10, 10)
    assert g.turn == WHITE
    assert g.undo()
    assert g.get(10, 10) == EMPTY and g.turn == BLACK
    assert g.undo() and g.undo()
    assert len(g.history) == 0
    assert all(cell == EMPTY for row in g.board for cell in row)
    assert g.turn == BLACK
    assert not g.undo()                        # 无可撤销


def test_undo_after_win():
    """悔棋可撤销获胜一步: 闭环消失, 对局继续。"""
    g = JordanChess()
    setup(g, {(2, 1): BLACK, (1, 2): BLACK, (3, 2): BLACK}, turn=BLACK)
    r = g.place(2, 3)                          # 斜菱形获胜
    assert r['winner'] == BLACK
    assert g.undo()
    assert g.winner is None
    assert g.get(2, 3) == EMPTY                # 获胜落子撤销
    assert g.turn == BLACK                     # 回到黑方
    # 原三子仍在, 可继续对局
    assert g.get(2, 1) == BLACK and g.get(3, 2) == BLACK


def test_draw():
    g = JordanChess()
    # 棋盘格填色(黑白交错, 同色互不相邻 → 永不成环), 保留一个黑方格位
    empty_cell = None
    for x in range(11):
        for y in range(11):
            if (x + y) % 2 == 0 and empty_cell is None:
                empty_cell = (x, y)
                continue
            g.board[x][y] = BLACK if (x + y) % 2 == 0 else WHITE
    g.turn = BLACK
    r = g.place(*empty_cell)
    assert r['ok'] and r['winner'] == 'DRAW' and r['loops'] == []
    assert not g.place(0, 0)['ok']             # 游戏结束


# ---------------------------------------------------------------------------
# 自定义棋盘大小
# ---------------------------------------------------------------------------
def test_custom_size_basics():
    g = JordanChess(size=5)                  # 5×5 方格 → 6×6 格点
    assert g.n == 6
    assert g.place(0, 0)['ok']
    assert g.place(5, 5)['ok']               # 边界坐标合法
    assert not g.place(6, 0)['ok']           # 越界
    assert not g.place(0, -1)['ok']
    assert g.undo()


def test_custom_size_loop():
    g = JordanChess(size=2)                  # 最小可成环棋盘: 3×3 格点
    setup(g, {(0, 1): BLACK, (1, 0): BLACK, (2, 1): BLACK}, turn=BLACK)
    r = g.place(1, 2)                        # 斜菱形闭环, 内部 (1,1)
    assert r['ok'] and r['winner'] == BLACK
    assert len(r['loops']) >= 1


def test_custom_size_draw():
    g = JordanChess(size=3)                  # 4×4 格点棋盘格填色 → 平局
    for x in range(4):
        for y in range(4):
            g.board[x][y] = BLACK if (x + y) % 2 == 0 else WHITE
    g.board[0][0] = EMPTY
    g.turn = BLACK
    r = g.place(0, 0)
    assert r['ok'] and r['winner'] == 'DRAW' and r['loops'] == []


def test_custom_size_random():
    random.seed(7)
    for _ in range(20):
        size = random.choice([2, 3, 5, 8, 12])
        g = JordanChess(size=size)
        steps = 0
        while g.winner is None and steps < 300:
            moves = list(g.moves())
            if not moves:
                break
            g.place(*random.choice(moves))
            steps += 1
        for x in range(g.n):
            for y in range(g.n):
                assert g.board[x][y] in (EMPTY, BLACK, WHITE)


def test_invalid_size():
    for bad in (0, -3, 1.5, '10'):
        try:
            JordanChess(size=bad)
            assert False, f'size={bad!r} 应被拒绝'
        except ValueError:
            pass


# ---------------------------------------------------------------------------
# 随机对局 + 性能
# ---------------------------------------------------------------------------
def test_random_games():
    random.seed(42)
    for _ in range(60):
        g = JordanChess()
        steps = 0
        while g.winner is None and steps < 200:
            moves = list(g.moves())
            if not moves:
                break
            g.place(*random.choice(moves))
            steps += 1
            if random.random() < 0.15:
                g.undo()
        for x in range(11):
            for y in range(11):
                assert g.board[x][y] in (EMPTY, BLACK, WHITE)


def test_performance_dense():
    """极端密集棋盘(119 黑 + 1 白)下的落子耗时上限。"""
    g = JordanChess()
    for x in range(11):
        for y in range(11):
            g.board[x][y] = BLACK
    g.board[10][10] = WHITE
    g.board[5][5] = EMPTY
    g.turn = BLACK
    t0 = time.time()
    r = g.place(5, 5)
    dt = time.time() - t0
    assert r['ok'], r
    assert r['winner'] == BLACK                # 密集棋盘必然成环
    assert dt < 3.0, f'密集棋盘落子过慢: {dt:.3f}s'


import time  # noqa: E402  (供 test_performance_dense 使用)


# ---------------------------------------------------------------------------
# 测试运行器
# ---------------------------------------------------------------------------
def run_all(verbose=True):
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
    return failed == 0


if __name__ == '__main__':
    ok = run_all(verbose='-v' in sys.argv)
    sys.exit(0 if ok else 1)
