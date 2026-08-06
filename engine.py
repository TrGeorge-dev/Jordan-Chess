#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
约当棋 (Jordan Chess) —— 游戏引擎
=================================

【数学依据: 约当曲线定理 (Jordan Curve Theorem)】
平面上任意一条不自交的闭合连续曲线, 将平面唯一划分为"内部"与"外部"两个区域,
从内部到外部的任意连续路径必然穿过该曲线。

【游戏内等价定义】
同色棋子按四连通(曼哈顿距离为 1 的上下左右相邻)连成的不自交闭合路径,
等价于一条约当曲线; 被该路径完全包围的对方棋子位于严格内部区域。

【棋盘】
10×10 方格对应的格点矩阵 → 11×11 格点坐标体系, 坐标 (x, y) ∈ 0..10,
共 121 个可落子点。棋子放置在格点(方格交叉点)上, 而非方格内部。
黑方先手, 双方交替落子, 每回合在任意空白格点放置 1 枚己方棋子;
棋子一经放置不可移动、不可主动移除, 仅在被对方包围时被动移除。

【每步结算流程】
1. 落子: 在空白格点放置己方棋子
2. 环路检测: 新落子 v 必然位于所有"新形成"的闭环上; 枚举 v 的两个同色邻居
   u、w, 在去掉 v 的同色连通图中找 u→w 的简单路径, 拼接 [v]+路径 即得简单环
3. 胜负结算: 形成任何闭环(约当曲线) → 落子方立即获胜, 无需包围对方棋子;
   棋盘下满且从未成环 → 平局

【可选数学模块】
类方法 _point_in_polygon 提供射线法点在多边形内判定, 供规则变体
(如"包围移除对方棋子"类玩法)或外部调用使用, 当前规则下不参与结算。
"""

from itertools import combinations

EMPTY = 0
BLACK = 1
WHITE = 2

COLOR_NAME = {EMPTY: '空', BLACK: '黑', WHITE: '白'}


class JordanChess:
    """约当棋引擎: 棋盘状态管理 + 连通性/环路检测 + 胜负结算。"""

    def __init__(self, size=10):
        if not isinstance(size, int) or size < 1:
            raise ValueError(f'棋盘大小必须为正整数(方格数), 收到 {size!r}')
        self.size = size                  # 每边方格数
        self.n = size + 1                 # 每边格点数(坐标 0..size)
        self.board = [[EMPTY] * self.n for _ in range(self.n)]
        self.turn = BLACK                 # 黑方先手
        self.winner = None                # None(进行中) / BLACK / WHITE / 'DRAW'
        self.history = []                 # 历史: (x, y, color)
        self.last_move = None             # 最近一步落子 (x, y)
        self.last_loops = []              # 最近一步新形成的闭环(顶点有序序列)

    # ------------------------------------------------------------------
    # 棋盘状态管理
    # ------------------------------------------------------------------
    def get(self, x, y):
        """查询格点状态: EMPTY / BLACK / WHITE。"""
        return self.board[x][y]

    def is_inside(self, x, y):
        return 0 <= x < self.n and 0 <= y < self.n

    def is_full(self):
        return all(cell != EMPTY for row in self.board for cell in row)

    def moves(self):
        """枚举全部合法落子点(空白格点)生成器。"""
        if self.winner is not None:
            return
        for x in range(self.n):
            for y in range(self.n):
                if self.board[x][y] == EMPTY:
                    yield (x, y)

    # ------------------------------------------------------------------
    # 落子 + 结算
    # ------------------------------------------------------------------
    def place(self, x, y):
        """在格点 (x, y) 落子并完成本轮结算。

        返回字典: {'ok': bool, 'reason': str|None, 'color': int|None,
                  'loops': list, 'winner': int|None}
        """
        if not self.is_inside(x, y):
            return {'ok': False, 'reason': f'坐标越界: ({x},{y}) 超出 0~{self.size}'}
        if self.board[x][y] != EMPTY:
            return {'ok': False, 'reason': f'格点 ({x},{y}) 已有棋子'}
        if self.winner is not None:
            return {'ok': False, 'reason': '游戏已结束'}

        color = self.turn
        self.board[x][y] = color

        # ① 环路检测: 所有"新形成"的环必然经过新落子点
        loops = self._find_new_cycles(x, y, color)

        # ② 胜负结算: 形成任何闭环(约当曲线)即获胜, 无需包围对方棋子
        if loops:
            self.winner = color
        elif self.is_full():
            self.winner = 'DRAW'          # 棋盘下满且从未成环 → 平局
        else:
            self.turn = WHITE if color == BLACK else BLACK

        self.last_move = (x, y)
        self.last_loops = loops
        self.history.append((x, y, color))

        return {'ok': True, 'color': color, 'loops': loops,
                'winner': self.winner}

    def undo(self):
        """悔棋: 撤销最近一步, 支持历史回溯。"""
        if not self.history:
            return False
        x, y, color = self.history.pop()
        self.board[x][y] = EMPTY
        self.winner = None
        self.turn = color
        self.last_move = self.history[-1][:2] if self.history else None
        self.last_loops = []
        return True

    # ------------------------------------------------------------------
    # 连通性检测 (BFS/DFS)
    # ------------------------------------------------------------------
    def _same_color_neighbors(self, x, y, color):
        """返回 (x,y) 的四连通同色邻居(上下左右, 曼哈顿距离 1)。"""
        nbrs = []
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = x + dx, y + dy
            if 0 <= nx < self.n and 0 <= ny < self.n and self.board[nx][ny] == color:
                nbrs.append((nx, ny))
        return nbrs

    def _component(self, start, avoid, color):
        """BFS: 求 start 所在同色连通分量(可指定避开的格点)。"""
        seen = {start}
        stack = [start]
        while stack:
            cur = stack.pop()
            for nb in self._same_color_neighbors(*cur, color):
                if nb == avoid or nb in seen:
                    continue
                seen.add(nb)
                stack.append(nb)
        return seen

    # ------------------------------------------------------------------
    # 闭合环路检测
    # ------------------------------------------------------------------
    def _find_new_cycles(self, x, y, color):
        """找出经过新落子点 (x, y) 的闭环, 每对邻居至多返回一个代表环。

        数学逻辑: 简单环 = 一条首尾相接的简单路径。新落子 v 加入后, 任何
        "新形成"的环必然包含 v(不含 v 的环在 v 加入前已存在, 不算新环)。
        简单环在 v 处恰好使用两条边, 因此:
          1. 枚举 v 的两个同色邻居 u, w(至多 C(4,2)=6 对);
          2. 在去掉 v 的同色连通图中 BFS 求 u→w 的最短简单路径;
          3. [v] + 路径 构成一个不自交闭合环(约当曲线)。
        当前规则下形成任何闭环即获胜, 找到任一代表环即可判定胜负;
        BFS 天然有界(≤连通分量大小), 无指数级搜索风险。
        """
        neighbors = self._same_color_neighbors(x, y, color)
        cycles = []
        seen_keys = set()
        for u, w in combinations(neighbors, 2):
            path = self._shortest_path(u, w, avoid=(x, y), color=color)
            if path is None:
                continue
            cycle = [(x, y)] + path          # v → u → ... → w → v(闭合)
            key = frozenset(cycle)
            if key not in seen_keys:
                seen_keys.add(key)
                cycles.append(cycle)
        return cycles

    def _shortest_path(self, start, target, avoid, color):
        """BFS 求 start→target 的最短简单路径(避开 avoid); 不可达返回 None。"""
        parent = {start: None}
        queue = [start]
        head = 0
        while head < len(queue):
            cur = queue[head]
            head += 1
            if cur == target:
                break
            for nb in self._same_color_neighbors(*cur, color):
                if nb == avoid or nb in parent:
                    continue
                parent[nb] = cur
                queue.append(nb)
        if target not in parent:
            return None
        path = []                            # 沿 parent 回溯还原路径
        cur = target
        while cur is not None:
            path.append(cur)
            cur = parent[cur]
        path.reverse()
        return path

    # ------------------------------------------------------------------
    # 点在多边形内判定: 射线法 (Ray Casting Algorithm)
    # ------------------------------------------------------------------
    @staticmethod
    def _point_in_polygon(px, py, poly):
        """射线法: 从点 (px, py) 向右作水平射线, 统计与多边形边的交点个数,
        奇数 → 内部, 偶数 → 外部(约当曲线定理的离散化应用:
        从内部到外部必经曲线, 射线每穿过一次边界就切换一次内外)。

        为避免射线恰好穿过多边形顶点时重复计数, 采用"半开区间"规则:
        边 (x1,y1)-(x2,y2) 与射线相交当且仅当 (y1 > py) != (y2 > py),
        即两端点恰好一个严格在射线上方——顶点处两条边最多一条被计数,
        凸角/凹角/切线情形均得到正确奇偶性; 水平边永不计数。
        本游戏环路全为水平/垂直单位边, 交点横坐标计算精确无浮点误差。
        """
        inside = False
        m = len(poly)
        for i in range(m):
            x1, y1 = poly[i]
            x2, y2 = poly[(i + 1) % m]
            if (y1 > py) != (y2 > py):
                x_intersect = x1 + (py - y1) * (x2 - x1) / (y2 - y1)
                if x_intersect > px:
                    inside = not inside
        return inside
