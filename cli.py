#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
约当棋 (Jordan Chess) —— 命令行交互版
=====================================

运行:
  python3 cli.py [棋盘大小] [--ai [黑|白]]
    棋盘大小 = 每边方格数(默认 10, 可选 2~30), 格点数为 大小+1
    --ai        = 人机模式: 人类执黑先手, AI 执白
    --ai white  = 人机模式: 人类执白(后手), AI 执黑先走

操作方式:
  "x y"        在格点 (x, y) 落子, 如 "5 5"(坐标范围 0~大小, 支持 "5,5")
  a            切换 人机模式 / 双人模式
  a b / a w    人机模式, 并选择人类执黑(先手) / 执白(后手)
  u / undo     悔棋
  n / new      新局(保持当前棋盘大小);  n 13 表示以 13×13 开新局
  h / help     显示帮助
  q / quit     退出
"""

import sys

from engine import JordanChess, BLACK, WHITE, EMPTY, COLOR_NAME
from ai import JordanAI

SYMBOL = {EMPTY: '·', BLACK: '●', WHITE: '○'}

DEFAULT_SIZE = 10
MIN_SIZE = 2
MAX_SIZE = 30


def parse_args(argv):
    """解析命令行参数: (棋盘大小, 是否人机, 人类执子颜色)。非法返回 None。"""
    size, ai_mode, human_color = DEFAULT_SIZE, False, BLACK
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == '--ai':
            ai_mode, human_color = True, BLACK
            if i + 1 < len(argv) and argv[i + 1] in ('black', 'white', '黑', '白'):
                i += 1
                human_color = WHITE if argv[i] in ('white', '白') else BLACK
        elif a in ('--ai=white', '--ai-w', '--aiw'):
            ai_mode, human_color = True, WHITE
        elif a in ('--ai=black', '--ai-b', '--aib'):
            ai_mode, human_color = True, BLACK
        elif a.lstrip('-').isdigit():
            s = int(a)
            if not MIN_SIZE <= s <= MAX_SIZE:
                print(f'棋盘大小需在 {MIN_SIZE}~{MAX_SIZE} 之间, 收到 {s}')
                return None
            size = s
        else:
            print(f'无法识别的参数: {a}')
            print('用法: python3 cli.py [棋盘大小] [--ai [黑|白]]')
            return None
        i += 1
    return size, ai_mode, human_color


def render(game):
    """打印棋盘: (大小+1)×(大小+1) 格点, y 从上到下, 每格 3 字符宽。"""
    n = game.n
    lines = [f'      ' + ''.join(f'{x:>3}' for x in range(n))]
    for y in range(n):
        row = f'  {y:>3} ' + ''.join(
            f'  {SYMBOL[game.board[x][y]]}' for x in range(n))
        lines.append(row)
    return '\n'.join(lines)


def main(argv):
    parsed = parse_args(argv)
    if parsed is None:
        return
    size, ai_mode, human_color = parsed
    ai_color = WHITE if human_color == BLACK else BLACK
    game = JordanChess(size=size)
    ai = None

    def ai_think():
        """AI 走一步(若轮到 AI)。"""
        nonlocal ai
        if game.winner is not None or game.turn != ai_color:
            return
        if ai is None or ai.game is not game:
            ai = JordanAI(game, ai_color, seed=1)
        print('AI 思考中…')
        mv = ai.choose_move()
        r = game.place(*mv)
        print(f'AI 落子: {mv}')
        if r['loops']:
            print(f'★ AI 形成闭环 {len(r["loops"])} 个 —— 立即获胜!')

    def new_game(new_size):
        nonlocal game, ai
        game = JordanChess(size=new_size)
        ai = None

    print('=' * 56)
    print('约当棋 (Jordan Chess) —— 基于约当曲线定理的双人零和棋')
    print(f'棋盘 {game.size}×{game.size} 方格 → {game.n}×{game.n} 格点; '
          '黑方先手, 形成任何闭环即获胜')
    print('输入 "x y" 落子; a 人机/双人; a b/a w 执黑/执白; u 悔棋; '
          'n 新局(n 13 = 13×13); h 帮助; q 退出')
    print('=' * 56)
    while True:
        print()
        print(render(game))
        if game.winner is not None:
            if game.winner == 'DRAW':
                print(f'棋盘已满且从未成环 —— 平局! '
                      f'(u 悔棋继续 / n 新局 / q 退出)')
            else:
                print(f'{COLOR_NAME[game.winner]}方获胜! '
                      f'(u 悔棋继续 / n 新局 / q 退出)')
        else:
            turn_txt = f'轮到 {COLOR_NAME[game.turn]}方'
            if game.last_loops:
                turn_txt += f'   上一步新形成闭环 {len(game.last_loops)} 个'
            if ai_mode:
                turn_txt += f'   [人机: 你执{COLOR_NAME[human_color]}, ' \
                            f'AI 执{COLOR_NAME[ai_color]}]'
            print(turn_txt)

        # AI 轮次自动走子
        if ai_mode:
            ai_think()
            if game.winner is not None:
                continue

        try:
            cmd = input('> ').strip().lower()
        except (EOFError, KeyboardInterrupt):
            print('\n再见!')
            return
        if cmd in ('q', 'quit', 'exit'):
            print('再见!')
            return
        if cmd in ('a', 'ai'):
            ai_mode = not ai_mode
            print('已切换为 人机模式。' if ai_mode else '已切换为 双人模式。')
            if ai_mode:
                ai_think()
            continue
        if cmd in ('a b', 'a w', 'ab', 'aw', 'a 黑', 'a 白'):
            human_color = WHITE if cmd.split()[1] in ('w', '白') else BLACK
            ai_color = WHITE if human_color == BLACK else BLACK
            ai_mode = True
            new_game(game.size)
            print(f'人机模式: 你执{COLOR_NAME[human_color]}, '
                  f'AI 执{COLOR_NAME[ai_color]}。')
            ai_think()
            continue
        if cmd in ('u', 'undo'):
            if game.undo():
                print('已悔棋。')
            else:
                print('没有可撤销的步骤。')
            continue
        if cmd in ('n', 'new'):
            new_game(game.size)
            print(f'新局开始({game.size}×{game.size}), 黑方先手。')
            if ai_mode:
                ai_think()
            continue
        if cmd.startswith('n ') or cmd.startswith('new '):
            try:
                s = int(cmd.split()[1])
            except (ValueError, IndexError):
                print('用法: n 13 表示以 13×13 开新局(2~30)')
                continue
            if not MIN_SIZE <= s <= MAX_SIZE:
                print(f'棋盘大小需在 {MIN_SIZE}~{MAX_SIZE} 之间')
                continue
            new_game(s)
            print(f'新局开始({game.size}×{game.size}), 黑方先手。')
            if ai_mode:
                ai_think()
            continue
        if cmd in ('h', 'help'):
            print('输入 "x y" 落子(如 "5 5"); a 人机/双人; a b/a w 执黑/执白; '
                  'u 悔棋; n 新局(保持大小); n 13 新局(13×13); q 退出')
            continue
        parts = cmd.replace(',', ' ').split()
        if len(parts) == 2 and all(p.lstrip('-').isdigit() for p in parts):
            x, y = int(parts[0]), int(parts[1])
            r = game.place(x, y)
            if not r['ok']:
                print(f'非法落子: {r["reason"]}')
            elif r['loops']:
                print(f'★ 形成闭环 {len(r["loops"])} 个 —— 立即获胜!')
            elif r['winner'] == 'DRAW':
                print('棋盘已满, 平局。')
        else:
            print('无法识别的输入。输入 h 查看帮助。')


if __name__ == '__main__':
    main(sys.argv[1:])
