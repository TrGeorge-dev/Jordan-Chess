#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
约当棋 AI 对手 —— 基于威胁推理 + α-β 剪枝
==========================================

【威胁体系】(成环 = 落子即构成约当曲线, 立即获胜)
  T1   一步威胁: 某空点落子即成环。轮到自己走 = 直接获胜; 轮到对手 = 必须堵。
  T2   两步威胁: 落子后产生 1 个 T1 → 对手被迫堵, 形成追击。
  fork 双威胁:   落子后产生 ≥2 个 T1 → 对手堵不完, 必胜。

【威胁判定】空点 v 是 c 色的 T1 ⟺ v 的两个同色邻居在同一连通分量
  (用并查集 O(1) 判定; 与引擎的环路检测"每对邻居 BFS 连通"完全等价,
   因为 v 为空点, 邻居间的连通路径必然不经过 v)。

【搜索】根节点做精确 T1/T2/fork 攻防推理并排序候选;
  内层 α-β 剪枝 + 强制走法(对手有 T1 必须堵, 分支骤减);
  叶子用威胁差 + 结构评估; 时间预算控制搜索宽度, 超时返回当前最佳。
  AI 只读棋盘并自行模拟, 不产生任何副作用。
"""

import random
import time

from engine import JordanChess, BLACK, WHITE, EMPTY

WIN = 10 ** 6          # 必胜分值
LOSS = -10 ** 6


class _DSU:
    """并查集: 同色棋子连通分量查询(find 均摊 O(1))。"""

    def __init__(self, size):
        self.p = list(range(size))

    def find(self, x):
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[ra] = rb


class JordanAI:
    """约当棋 AI: 威胁推理 + α-β 搜索。"""

    def __init__(self, game, color, time_budget=2.5, max_depth=3, seed=None):
        self.game = game
        self.color = color
        self.opp = WHITE if color == BLACK else BLACK
        self.time_budget = time_budget
        self.max_depth = max_depth
        self._rng = random.Random(seed)
        self._deadline = 0.0
        self._cand_limit = 14

    # ------------------------------------------------------------------
    # 基础工具
    # ------------------------------------------------------------------
    def _idx(self, x, y):
        return x * self.game.n + y

    def _build_dsu(self, color):
        """构建 color 色棋子的连通分量并查集。"""
        g = self.game
        n = g.n
        b = g.board
        dsu = _DSU(n * n)
        for x in range(n):
            for y in range(n):
                if b[x][y] != color:
                    continue
                i = self._idx(x, y)
                if x > 0 and b[x - 1][y] == color:
                    dsu.union(i, self._idx(x - 1, y))
                if x < n - 1 and b[x + 1][y] == color:
                    dsu.union(i, self._idx(x + 1, y))
                if y > 0 and b[x][y - 1] == color:
                    dsu.union(i, self._idx(x, y - 1))
                if y < n - 1 and b[x][y + 1] == color:
                    dsu.union(i, self._idx(x, y + 1))
        return dsu

    # ------------------------------------------------------------------
    # 威胁检测
    # ------------------------------------------------------------------
    def _threats(self, color, limit=None):
        """返回 color 色的 T1 威胁点(落子即成环的空点)。

        判定: 空点 v 的任意两个同色邻居在同一连通分量。
        limit: 最多返回几个(胜负判断用, 找够即停)。
        """
        g = self.game
        n = g.n
        b = g.board
        dsu = self._build_dsu(color)
        idx = self._idx
        res = []
        for x in range(n):
            for y in range(n):
                if b[x][y] != EMPTY:
                    continue
                nbr = []
                if x > 0 and b[x - 1][y] == color:
                    nbr.append(idx(x - 1, y))
                if x < n - 1 and b[x + 1][y] == color:
                    nbr.append(idx(x + 1, y))
                if y > 0 and b[x][y - 1] == color:
                    nbr.append(idx(x, y - 1))
                if y < n - 1 and b[x][y + 1] == color:
                    nbr.append(idx(x, y + 1))
                if len(nbr) < 2:
                    continue
                hit = False
                for i in range(len(nbr) - 1):
                    ri = dsu.find(nbr[i])
                    for j in range(i + 1, len(nbr)):
                        if ri == dsu.find(nbr[j]):
                            hit = True
                            break
                    if hit:
                        break
                if hit:
                    res.append((x, y))
                    if limit is not None and len(res) >= limit:
                        break
        return res

    def _t2_and_forks(self, color):
        """返回 (t2_points, fork_points):
        fork = 落 color 子后产生 ≥2 个 T1 的空点(双威胁 → 必胜);
        t2   = 落 color 子后产生 1 个 T1 的空点(两步威胁)。

        必要条件: 只有"同色邻居 ≥2 个"的空点才可能因落子产生新威胁
        (单邻居落子只会延伸原分量, 不会创造新的威胁点), 故只检查这些点。
        """
        g = self.game
        n = g.n
        b = g.board
        cands = set()
        for x in range(n):
            for y in range(n):
                if b[x][y] != EMPTY:
                    continue
                cnt = 0
                if x > 0 and b[x - 1][y] == color: cnt += 1
                if x < n - 1 and b[x + 1][y] == color: cnt += 1
                if y > 0 and b[x][y - 1] == color: cnt += 1
                if y < n - 1 and b[x][y + 1] == color: cnt += 1
                if cnt >= 2:
                    cands.add((x, y))
        t2, forks = [], []
        for (x, y) in cands:
            b[x][y] = color                 # 模拟落子
            t = self._threats(color, limit=3)
            b[x][y] = EMPTY                 # 恢复
            if len(t) >= 2:
                forks.append((x, y))
            elif len(t) == 1:
                t2.append((x, y))
        return t2, forks

    # ------------------------------------------------------------------
    # 走法生成
    # ------------------------------------------------------------------
    def _gen_moves(self, color, top=12):
        """候选走法: 与任一棋子相邻的空点, 按 己方扩展>对方防御>中心 排序。"""
        g = self.game
        n = g.n
        b = g.board
        opp = WHITE if color == BLACK else BLACK
        scored = []
        for x in range(n):
            for y in range(n):
                if b[x][y] != EMPTY:
                    continue
                nm = no = 0
                if x > 0:
                    c = b[x - 1][y]
                    if c == color: nm += 1
                    elif c == opp: no += 1
                if x < n - 1:
                    c = b[x + 1][y]
                    if c == color: nm += 1
                    elif c == opp: no += 1
                if y > 0:
                    c = b[x][y - 1]
                    if c == color: nm += 1
                    elif c == opp: no += 1
                if y < n - 1:
                    c = b[x][y + 1]
                    if c == color: nm += 1
                    elif c == opp: no += 1
                if nm == 0 and no == 0:
                    continue
                s = (nm * 5 + no * 3
                     + 0.3 * ((n - abs(2 * x - (n - 1)))
                              + (n - abs(2 * y - (n - 1))))
                     + self._rng.uniform(-0.5, 0.5))
                scored.append((s, (x, y)))
        scored.sort(reverse=True)
        return [mv for _, mv in scored[:top]]

    def _root_candidates(self, t2m, fm, t2o, fo):
        """根节点候选: 精确 T2/fork 推理 + 机动性点, 按价值排序。"""
        g = self.game
        n = g.n
        b = g.board
        pool = {}
        for v in fm:
            pool[v] = 5000                       # 己方双威胁(必胜)
        for v in fo:
            pool[v] = 4600                       # 抢占对手双威胁点
        for v in t2m:
            pool[v] = 3000                       # 己方两步威胁
        for v in t2o:
            pool[v] = 2800                       # 堵对手两步威胁
        for x in range(n):
            for y in range(n):
                c = b[x][y]
                if c == EMPTY:
                    continue
                base = 1200 if c == self.color else 800
                if x > 0 and b[x - 1][y] == EMPTY and (x - 1, y) not in pool:
                    pool[(x - 1, y)] = base
                if x < n - 1 and b[x + 1][y] == EMPTY and (x + 1, y) not in pool:
                    pool[(x + 1, y)] = base
                if y > 0 and b[x][y - 1] == EMPTY and (x, y - 1) not in pool:
                    pool[(x, y - 1)] = base
                if y < n - 1 and b[x][y + 1] == EMPTY and (x, y + 1) not in pool:
                    pool[(x, y + 1)] = base
        cx = cy = (n - 1) / 2.0
        items = [(s + 20.0 * (n - abs(x - cx) - abs(y - cy))
                  + self._rng.uniform(-0.5, 0.5), (x, y))
                 for (x, y), s in pool.items()]
        items.sort(reverse=True)
        return [(mv, pool[mv]) for _, mv in items[:self._cand_limit]]

    def _any_empty(self):
        """兜底: 任意空点(优先中心)。"""
        g = self.game
        n = g.n
        b = g.board
        best, bd = None, 10 ** 9
        for x in range(n):
            for y in range(n):
                if b[x][y] == EMPTY:
                    d = abs(x - (n - 1) / 2) + abs(y - (n - 1) / 2)
                    if d < bd:
                        bd, best = d, (x, y)
        return best

    # ------------------------------------------------------------------
    # 静态评估
    # ------------------------------------------------------------------
    def _evaluate(self, me):
        """静态评估(me 视角)。

        胜负层: 任一方 T1 威胁存在性(一步成环)。
        结构层: 连接潜力(空点连接到的同色连通分量数 —— 造环/造 fork 的种子)
               + 机动性 + 材料。
        """
        opp = WHITE if me == BLACK else BLACK
        g = self.game
        n = g.n
        b = g.board
        dsu_m = self._build_dsu(me)
        dsu_o = self._build_dsu(opp)
        idx = self._idx
        my_conn = opp_conn = 0
        my_seeds = opp_seeds = 0     # fork 种子: 邻接 ≥2 个同色分量的空点
        my_mob = opp_mob = 0
        my_cnt = opp_cnt = 0
        opp_t1 = 0
        for x in range(n):
            for y in range(n):
                c = b[x][y]
                if c == me:
                    my_cnt += 1
                    if x > 0 and b[x - 1][y] == EMPTY: my_mob += 1
                    if x < n - 1 and b[x + 1][y] == EMPTY: my_mob += 1
                    if y > 0 and b[x][y - 1] == EMPTY: my_mob += 1
                    if y < n - 1 and b[x][y + 1] == EMPTY: my_mob += 1
                elif c == opp:
                    opp_cnt += 1
                    if x > 0 and b[x - 1][y] == EMPTY: opp_mob += 1
                    if x < n - 1 and b[x + 1][y] == EMPTY: opp_mob += 1
                    if y > 0 and b[x][y - 1] == EMPTY: opp_mob += 1
                    if y < n - 1 and b[x][y + 1] == EMPTY: opp_mob += 1
                elif c == EMPTY:
                    m_roots = set()
                    o_roots = set()
                    m_n = o_n = 0
                    if x > 0:
                        cc = b[x - 1][y]
                        if cc == me:
                            m_n += 1
                            m_roots.add(dsu_m.find(idx(x - 1, y)))
                        elif cc == opp:
                            o_n += 1
                            o_roots.add(dsu_o.find(idx(x - 1, y)))
                    if x < n - 1:
                        cc = b[x + 1][y]
                        if cc == me:
                            m_n += 1
                            m_roots.add(dsu_m.find(idx(x + 1, y)))
                        elif cc == opp:
                            o_n += 1
                            o_roots.add(dsu_o.find(idx(x + 1, y)))
                    if y > 0:
                        cc = b[x][y - 1]
                        if cc == me:
                            m_n += 1
                            m_roots.add(dsu_m.find(idx(x, y - 1)))
                        elif cc == opp:
                            o_n += 1
                            o_roots.add(dsu_o.find(idx(x, y - 1)))
                    if y < n - 1:
                        cc = b[x][y + 1]
                        if cc == me:
                            m_n += 1
                            m_roots.add(dsu_m.find(idx(x, y + 1)))
                        elif cc == opp:
                            o_n += 1
                            o_roots.add(dsu_o.find(idx(x, y + 1)))
                    if m_n >= 2 and len(m_roots) < m_n:
                        return WIN               # me 有一步成环点
                    if o_n >= 2 and len(o_roots) < o_n:
                        opp_t1 += 1
                        if opp_t1 >= 2:
                            return LOSS         # 对手双威胁, 必输
                    my_conn += len(m_roots)
                    opp_conn += len(o_roots)
                    if len(m_roots) >= 2:
                        my_seeds += 1          # 落子可合并 ≥2 分量的点(造 fork 前提)
                    if len(o_roots) >= 2:
                        opp_seeds += 1
        score = (250 * (my_seeds - opp_seeds)
                 + 30 * (my_conn - opp_conn)
                 + 20 * (my_mob - opp_mob)
                 + 2 * (my_cnt - opp_cnt))
        if opp_t1 == 1:
            score -= 120        # 对手有 1 个威胁: 被迫应对, 丢先手
        return score

    # ------------------------------------------------------------------
    # α-β 搜索
    # ------------------------------------------------------------------
    def _negamax(self, depth, alpha, beta, to_move):
        """返回从 to_move 视角的最佳分数(在当前 self.game 棋盘上模拟)。"""
        if time.time() > self._deadline:
            return 0
        if self._threats(to_move, limit=1):
            return WIN                          # to_move 一步成环即胜
        opp = WHITE if to_move == BLACK else BLACK
        t1o = self._threats(opp, limit=2)
        if len(t1o) >= 2:
            return LOSS                         # 对手双威胁, 堵不完
        if depth <= 0:
            return self._evaluate(to_move)
        if t1o:
            cands = t1o[:1]                    # 强制走法: 必堵唯一威胁点
        else:
            cands = self._gen_moves(to_move, top=self._cand_limit)
        g = self.game
        best = LOSS
        for mv in cands:
            if time.time() > self._deadline:
                break
            x, y = mv
            g.board[x][y] = to_move
            v = -self._negamax(depth - 1, -beta, -alpha, opp)
            g.board[x][y] = EMPTY
            if v > best:
                best = v
            if v > alpha:
                alpha = v
            if alpha >= beta:
                break
        return best

    # ------------------------------------------------------------------
    # 主入口
    # ------------------------------------------------------------------
    def choose_move(self):
        """返回 AI 的最佳落子 (x, y)。只读棋盘, 无副作用。

        决策梯子(威胁层级, 自上而下):
          1. 己方 T1    → 一步成环, 直接获胜
          2. 对方 T1    → 必堵(唯一威胁点)
          3. 己方 fork  → 落子产生双威胁, 对手只能堵一个 → 两步内必胜
          4. 对方 fork  → 必须抢占(否则对方两步内必胜)
          5. 自由局面   → 根候选(精确 T2/fork 排序) + α-β 搜索
        """
        self._deadline = time.time() + self.time_budget
        g = self.game
        n = g.n
        self._cand_limit = 14 if n <= 15 else 12

        # 1) 直接胜利: 有一步成环点就走
        t1 = self._threats(self.color, limit=1)
        if t1:
            return t1[0]

        # 2) 强制防守: 对手有 T1 必须堵
        t1o = self._threats(self.opp, limit=3)
        if len(t1o) == 1:
            return t1o[0]
        if len(t1o) >= 2:
            cands = self._gen_moves(self.color, top=6)   # 已输定, 走最不差的
            return cands[0] if cands else self._any_empty()

        # 精确 T2/fork 推理(一次计算, 供 3/4/5 步共用)
        t0 = time.time()
        t2m, fm = self._t2_and_forks(self.color)
        t2o, fo = self._t2_and_forks(self.opp)
        # 搜索预算 = 总预算 - 预计算耗时, 保证搜索真正有预算可用
        self._deadline = time.time() + max(0.05, self.time_budget - (time.time() - t0))

        # 3) 己方双威胁: 必走(对手只能堵一个, 两步内必胜)
        if fm:
            return fm[0]

        # 4) 对方双威胁: 必堵
        if fo:
            return fo[0]

        # 5) 自由局面: 根候选 + α-β 搜索
        cands = self._root_candidates(t2m, fm, t2o, fo)
        if not cands:
            return self._any_empty()
        depth = self._pick_depth()
        best_move, best_prio = cands[0]
        best_val = LOSS - 1
        for mv, prio in cands:
            if time.time() > self._deadline:
                break
            x, y = mv
            g.board[x][y] = self.color
            v = -self._negamax(depth - 1, LOSS, WIN, self.opp)
            g.board[x][y] = EMPTY
            # 值相近时偏向威胁优先级更高的走法(保持进攻性)
            if v > best_val + 25 or \
                    (best_val - 25 <= v and prio > best_prio):
                best_val, best_move, best_prio = v, mv, prio
            if v >= WIN:
                break                            # 找到必胜走法
        return best_move

    def _pick_depth(self):
        """按棋盘大小选择搜索深度。"""
        n = self.game.n
        if n <= 6:
            return min(self.max_depth, 4)
        if n <= 9:
            return min(self.max_depth, 4)
        if n <= 13:
            return min(self.max_depth, 3)
        return min(self.max_depth, 3)
