#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
约当棋 (Jordan Chess) —— pygame 图形界面版
==========================================

运行: python3 gui.py [棋盘大小]     (需要 pygame: pip install pygame / apk add py3-pygame)

操作:
  鼠标左键点击格点落子
  [◀] [▶] 调整棋盘大小(2~30, 自动开新局);   [Undo] 悔棋;   [New] 新局
界面说明:
  黄圈 = 最近一步落子;  红色多边形 = 最近形成的闭环;  顶部横幅 = 胜负结果
"""

import sys

import pygame

from engine import JordanChess, BLACK, WHITE, EMPTY
from ai import JordanAI

# ---- 布局(窗口固定, 棋盘随大小自适应缩放居中) ----
STATUS_H = 56
BTN_H = 60
AREA = 640                 # 棋盘绘制区最大边长(像素)
MARGIN = 60
W = MARGIN * 2 + AREA
H = MARGIN * 2 + AREA + STATUS_H + BTN_H

MIN_SIZE = 2
MAX_SIZE = 30

# ---- 配色 ----
BG = (240, 240, 235)
LINE = (60, 60, 60)
BLACK_C = (25, 25, 25)
WHITE_C = (250, 250, 250)
OUTLINE = (120, 120, 120)
LAST_MOVE = (240, 190, 40)
LOOP_C = (210, 40, 40)
HOVER = (140, 200, 255)
BTN_BG = (210, 210, 205)
BTN_ACT = (185, 205, 235)
TEXT = (30, 30, 30)


class GameUI:
    """约当棋图形界面(逻辑与渲染分离, 便于无头测试)。"""

    def __init__(self, game=None):
        pygame.init()
        self.game = game or JordanChess()
        self.size = self.game.size
        self.ai_mode = False       # 人机模式
        self.human_color = BLACK   # 人类执子颜色(默认黑先手)
        self.ai = None
        self.ai_busy = False
        self.screen = pygame.display.set_mode((W, H))
        self.font = pygame.font.SysFont('arial', 22)
        self.font_big = pygame.font.SysFont('arial', 34, bold=True)
        self.hover = None          # 悬停格点
        self.msg = ''              # 最近一次操作提示
        self._layout()
        pygame.display.set_caption(
            f'约当棋 Jordan Chess ({self.size}×{self.size})')

    @property
    def ai_color(self):
        return WHITE if self.human_color == BLACK else BLACK

    # ---- 布局(棋盘随大小缩放, 居中) ----
    def _layout(self):
        self.cell = min(64.0, AREA / self.size)
        self.grid = self.cell * self.size
        self.ox = (W - self.grid) // 2
        self.oy = MARGIN + STATUS_H
        cy = H - BTN_H + 12
        sx = W // 2 - 300
        self.size_minus_rect = pygame.Rect(sx, cy, 44, 40)
        self.size_text_rect = pygame.Rect(sx + 52, cy, 110, 40)
        self.size_plus_rect = pygame.Rect(sx + 170, cy, 44, 40)
        self.undo_rect = pygame.Rect(sx + 222, cy, 92, 40)
        self.new_rect = pygame.Rect(sx + 322, cy, 92, 40)
        self.ai_rect = pygame.Rect(sx + 422, cy, 76, 40)
        self.side_rect = pygame.Rect(sx + 506, cy, 94, 40)

    def _ensure_ai(self):
        if self.ai is None or self.ai.game is not self.game:
            self.ai = JordanAI(self.game, self.ai_color, seed=1)
        return self.ai

    def _new_game(self):
        self.game = JordanChess(size=self.size)
        self.ai = None

    def set_size(self, new_size):
        """更换棋盘大小并自动开新局。"""
        new_size = max(MIN_SIZE, min(MAX_SIZE, new_size))
        if new_size == self.size:
            return
        self.size = new_size
        self._new_game()
        self._layout()
        self.msg = f'新局: {new_size}×{new_size} 棋盘'
        pygame.display.set_caption(
            f'约当棋 Jordan Chess ({self.size}×{self.size})')

    # ---- 坐标换算 ----
    def lattice_xy(self, x, y):
        return self.ox + x * self.cell, self.oy + y * self.cell

    def screen_to_lattice(self, mx, my):
        """把屏幕坐标吸附到最近格点; 距离过远返回 None。"""
        best, best_d = None, self.cell * 0.45
        for x in range(self.game.n):
            for y in range(self.game.n):
                px, py = self.lattice_xy(x, y)
                d = ((mx - px) ** 2 + (my - py) ** 2) ** 0.5
                if d < best_d:
                    best, best_d = (x, y), d
        return best

    # ---- 事件 ----
    def handle_event(self, ev):
        if ev.type == pygame.QUIT:
            return 'quit'
        if ev.type == pygame.MOUSEMOTION:
            self.hover = self.screen_to_lattice(*ev.pos)
        elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            if self.size_minus_rect.collidepoint(ev.pos):
                self.set_size(self.size - 1)
                return
            if self.size_plus_rect.collidepoint(ev.pos):
                self.set_size(self.size + 1)
                return
            if self.ai_rect.collidepoint(ev.pos):
                self.ai_mode = not self.ai_mode
                self.msg = ('人机模式: 你执黑, AI 执白。'
                            if self.ai_mode else '双人模式。')
                return
            if self.side_rect.collidepoint(ev.pos):
                if not self.ai_mode:
                    self.msg = '请先开启人机模式(AI 按钮), 再选择执子颜色。'
                    return
                self.human_color = WHITE if self.human_color == BLACK else BLACK
                self._new_game()
                self.msg = f'你执{("黑" if self.human_color == BLACK else "白")}, ' \
                           f'AI 执{("白" if self.human_color == BLACK else "黑")}。'
                return
            if self.undo_rect.collidepoint(ev.pos):
                if self.game.undo():
                    self.msg = '悔棋成功。'
                else:
                    self.msg = '没有可撤销的步骤。'
                return
            if self.new_rect.collidepoint(ev.pos):
                self._new_game()
                self.msg = f'新局开始, 黑方先手({self.size}×{self.size})。'
                return
            p = self.screen_to_lattice(*ev.pos)
            if p is None or self.game.winner is not None:
                return
            x, y = p
            r = self.game.place(x, y)
            if not r['ok']:
                self.msg = r['reason']
            elif r['loops']:
                self.msg = f'★ 形成闭环 {len(r["loops"])} 个 —— 立即获胜!'
            else:
                self.msg = ''
        return None

    def ai_move(self):
        """人机模式下 AI 走一步。"""
        if not self.ai_mode or self.game.winner is not None \
                or self.game.turn != self.ai_color:
            return
        self.ai_busy = True
        self.msg = 'AI 思考中…'
        self.draw()
        mv = self._ensure_ai().choose_move()
        r = self.game.place(*mv)
        if r['loops']:
            self.msg = f'★ AI 形成闭环 {len(r["loops"])} 个 —— AI 获胜!'
        else:
            self.msg = f'AI 落子: {mv}'
        self.ai_busy = False

    # ---- 渲染 ----
    def draw(self, surface=None):
        surf = surface or self.screen
        surf.fill(BG)

        # 网格线
        for i in range(self.game.n):
            x = self.ox + i * self.cell
            y = self.oy + i * self.cell
            pygame.draw.line(surf, LINE, (x, self.oy), (x, self.oy + self.grid), 1)
            pygame.draw.line(surf, LINE, (self.ox, y), (self.ox + self.grid, y), 1)
            surf.blit(self.font.render(str(i), True, LINE),
                      (x - 8, self.oy - 24))
            surf.blit(self.font.render(str(i), True, LINE),
                      (self.ox - 28, y - 10))

        # 闭环高亮(画在棋子下层)
        for loop in self.game.last_loops:
            pts = [self.lattice_xy(x, y) for x, y in loop]
            if len(pts) >= 3:
                pygame.draw.polygon(surf, (255, 200, 200), pts, 0)
                pygame.draw.polygon(surf, LOOP_C, pts, 3)

        # 棋子
        for x in range(self.game.n):
            for y in range(self.game.n):
                c = self.game.board[x][y]
                if c == EMPTY:
                    continue
                px, py = self.lattice_xy(x, y)
                color = BLACK_C if c == BLACK else WHITE_C
                pygame.draw.circle(surf, color, (px, py), self.cell * 0.38)
                pygame.draw.circle(surf, OUTLINE, (px, py), self.cell * 0.38, 2)

        # 悬停提示
        if self.hover and self.game.winner is None:
            x, y = self.hover
            if self.game.board[x][y] == EMPTY:
                px, py = self.lattice_xy(x, y)
                pygame.draw.circle(surf, HOVER, (px, py), self.cell * 0.38, 2)

        # 最近一步
        if self.game.last_move:
            px, py = self.lattice_xy(*self.game.last_move)
            pygame.draw.circle(surf, LAST_MOVE, (px, py), self.cell * 0.38 + 5, 3)

        # 状态栏
        if self.game.winner is not None:
            if self.game.winner == 'DRAW':
                text = 'Draw! Board full.'
            else:
                name = 'Black' if self.game.winner == BLACK else 'White'
                text = f'{name} wins!'
            banner = self.font_big.render(text, True, LOOP_C)
            surf.blit(banner, (W // 2 - banner.get_width() // 2, 10))
        else:
            name = 'Black' if self.game.turn == BLACK else 'White'
            t = self.font.render(f'{name} to move', True, TEXT)
            surf.blit(t, (MARGIN, 12))
        if self.msg:
            m = self.font.render(self.msg, True, (120, 60, 20))
            surf.blit(m, (MARGIN + 160, 12))

        # 底部按钮
        for rect in (self.size_minus_rect, self.size_text_rect,
                     self.size_plus_rect, self.undo_rect, self.new_rect,
                     self.ai_rect, self.side_rect):
            pygame.draw.rect(surf, BTN_BG, rect, border_radius=8)
            pygame.draw.rect(surf, OUTLINE, rect, 1, border_radius=8)
        surf.blit(self.font.render('◀', True, TEXT),
                  (self.size_minus_rect.x + 14, self.size_minus_rect.y + 7))
        surf.blit(self.font.render(f'Size {self.size}', True, TEXT),
                  (self.size_text_rect.x + 14, self.size_text_rect.y + 8))
        surf.blit(self.font.render('▶', True, TEXT),
                  (self.size_plus_rect.x + 14, self.size_plus_rect.y + 7))
        surf.blit(self.font.render('Undo', True, TEXT),
                  (self.undo_rect.x + 20, self.undo_rect.y + 8))
        surf.blit(self.font.render('New', True, TEXT),
                  (self.new_rect.x + 26, self.new_rect.y + 8))
        ai_txt = 'AI:ON' if self.ai_mode else 'AI:OFF'
        surf.blit(self.font.render(ai_txt, True, TEXT),
                  (self.ai_rect.x + 12, self.ai_rect.y + 8))
        side_txt = ('You:Black' if self.human_color == BLACK
                    else 'You:White')
        surf.blit(self.font.render(side_txt, True, TEXT),
                  (self.side_rect.x + 8, self.side_rect.y + 8))

        if surface is None:
            pygame.display.flip()


def main(argv):
    size = 10
    ai_on = False
    for a in argv:
        if a == '--ai':
            ai_on = True
        elif a.lstrip('-').isdigit():
            size = int(a)
            if not MIN_SIZE <= size <= MAX_SIZE:
                print(f'棋盘大小需在 {MIN_SIZE}~{MAX_SIZE} 之间')
                return
        else:
            print(f'无法识别的参数: {a}')
            print('用法: python3 gui.py [棋盘大小] [--ai]')
            return
    ui = GameUI(JordanChess(size=size))
    if ai_on:
        ui.ai_mode = True
        ui.msg = '人机模式: 你执黑, AI 执白。'
    clock = pygame.time.Clock()
    running = True
    while running:
        for ev in pygame.event.get():
            if ui.handle_event(ev) == 'quit':
                running = False
        if ui.ai_mode and not ui.ai_busy \
                and ui.game.winner is None and ui.game.turn == ui.ai_color:
            ui.ai_move()
        ui.draw()
        clock.tick(60)
    pygame.quit()


if __name__ == '__main__':
    main(sys.argv[1:])
