#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
约当棋 AI 对手 —— HTML 同步版 + 威胁搜索实验版
=============================================

【威胁体系】(成环 = 落子即构成约当曲线, 立即获胜)
  T1   一步威胁: 某空点落子即成环。轮到自己走 = 直接获胜; 轮到对手 = 必须堵。
  T2   两步威胁: 落子后产生 1 个 T1 → 对手被迫堵, 形成追击。
  fork 双威胁:   落子后产生 ≥2 个 T1 → 对手堵不完, 必胜。

【威胁判定】空点 v 是 c 色的 T1 ⟺ v 的两个同色邻居在同一连通分量
  (用并查集 O(1) 判定; 与引擎的环路检测"每对邻居 BFS 连通"完全等价,
   因为 v 为空点, 邻居间的连通路径必然不经过 v)。

【默认 JordanAI】与 index.html 保持同一套候选生成、结构评分、
  迭代加深、α-β 剪枝和战术延伸规则。

【ThreatJordanAI】保留此前 Python 的完整威胁搜索版本，便于回归对战。
  两个 AI 都只读棋盘并自行模拟，不产生任何副作用。
"""

import random
import time
from collections import defaultdict
from dataclasses import dataclass
from itertools import combinations

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


class LegacyJordanAI:
    """旧版 AI，保留用于回归测试和新旧版本强度对比。"""

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


# ============================================================================
# 第二代 AI
# ============================================================================


class _SearchTimeout(Exception):
    """搜索时间耗尽；只用于丢弃未完成的迭代。"""


@dataclass(frozen=True)
class _ColorAnalysis:
    """某一颜色在当前局面的连通结构和立即获胜点。"""

    threats: tuple
    move_roots: dict
    frontiers: dict
    component_sizes: tuple


class ThreatJordanAI(LegacyJordanAI):
    """约当棋第二代 AI：完整威胁识别 + 迭代加深 α-β 搜索。

    与旧版相比：
      * 单邻居延伸也会参与 T2/fork 判定，不再漏掉绕行成环战术；
      * 对方存在多个 fork 时交给搜索比较全部防守/反击，不任取第一个；
      * 逐层加深，只采用完整搜索完的一层，超时不会污染最终结果；
      * 使用局面分析缓存和置换表，减少相同局面的重复计算；
      * 深度用尽后若仍有强制威胁，会继续搜索有限步数再评分。
    """

    TT_EXACT = 0
    TT_LOWER = 1
    TT_UPPER = 2

    def __init__(self, game, color, time_budget=2.5, max_depth=8, seed=None):
        super().__init__(game, color, time_budget=time_budget,
                         max_depth=max_depth, seed=seed)
        self._deadline = 0.0
        self._hash = 0
        self._nodes = 0
        self._tt_hits = 0
        self._analysis_cache = {}
        self._threat_map_cache = {}
        self._tt = {}
        self._zobrist = self._make_zobrist()
        self.last_stats = {
            'completed_depth': 0,
            'nodes': 0,
            'tt_hits': 0,
            'elapsed': 0.0,
            'score': 0,
        }

    # ------------------------------------------------------------------
    # 棋盘指纹 / 安全模拟
    # ------------------------------------------------------------------
    def _make_zobrist(self):
        """为每个格点和颜色生成固定随机数，用作局面指纹。"""
        rng = random.Random(0x4A4F5244414E + self.game.n)
        return [[rng.getrandbits(64), rng.getrandbits(64)]
                for _ in range(self.game.n * self.game.n)]

    def _compute_hash(self):
        h = 0
        n = self.game.n
        for x in range(n):
            for y in range(n):
                c = self.game.board[x][y]
                if c != EMPTY:
                    h ^= self._zobrist[self._idx(x, y)][c - 1]
        return h

    def _play(self, move, color):
        x, y = move
        self.game.board[x][y] = color
        self._hash ^= self._zobrist[self._idx(x, y)][color - 1]

    def _unplay(self, move, color):
        x, y = move
        self._hash ^= self._zobrist[self._idx(x, y)][color - 1]
        self.game.board[x][y] = EMPTY

    def _check_time(self):
        if time.perf_counter() >= self._deadline:
            raise _SearchTimeout

    # ------------------------------------------------------------------
    # 完整威胁分析
    # ------------------------------------------------------------------
    def _analyze_color_uncached(self, color):
        """一次扫描得到连通分量、T1 和各空点邻接的分量。

        move_roots[p] 是空点 p 四周接触到的不同同色连通分量。
        若 p 同时接触同一分量中的两枚棋子，p 就是立即获胜点。
        """
        g = self.game
        n = g.n
        b = g.board
        dsu = self._build_dsu(color)
        idx = self._idx
        move_roots = {}
        frontiers = defaultdict(set)
        threats = []
        component_sizes = defaultdict(int)

        for x in range(n):
            for y in range(n):
                if b[x][y] == color:
                    component_sizes[dsu.find(idx(x, y))] += 1

        for x in range(n):
            for y in range(n):
                if b[x][y] != EMPTY:
                    continue
                roots = []
                if x > 0 and b[x - 1][y] == color:
                    roots.append(dsu.find(idx(x - 1, y)))
                if x < n - 1 and b[x + 1][y] == color:
                    roots.append(dsu.find(idx(x + 1, y)))
                if y > 0 and b[x][y - 1] == color:
                    roots.append(dsu.find(idx(x, y - 1)))
                if y < n - 1 and b[x][y + 1] == color:
                    roots.append(dsu.find(idx(x, y + 1)))
                unique = frozenset(roots)
                move_roots[(x, y)] = unique
                if len(unique) < len(roots):
                    threats.append((x, y))
                for root in unique:
                    frontiers[root].add((x, y))

        return _ColorAnalysis(
            threats=tuple(threats),
            move_roots=move_roots,
            frontiers={root: frozenset(points)
                       for root, points in frontiers.items()},
            component_sizes=tuple(sorted(component_sizes.values(),
                                         reverse=True)),
        )

    def _color_analysis(self, color):
        key = (self._hash, color)
        value = self._analysis_cache.get(key)
        if value is None:
            value = self._analyze_color_uncached(color)
            self._analysis_cache[key] = value
        return value

    def _threats(self, color, limit=None):
        """兼容旧接口；修正旧版 limit 只跳出内层循环的问题。"""
        # choose_move 之外也可能被测试直接调用，因此按实际棋盘重新计算。
        analysis = self._analyze_color_uncached(color)
        result = list(analysis.threats)
        return result if limit is None else result[:limit]

    def _threat_map(self, color):
        """返回 {候选落点: 落子后产生的 T1 点集合}。

        这是 T2/fork 的精确增量判定。单邻居延伸会检查新棋周围的空点；
        多分量合并还会检查这些分量原有边界的交集，因此远处新出现的
        T1 也不会漏掉。
        """
        key = (self._hash, color)
        cached = self._threat_map_cache.get(key)
        if cached is not None:
            return cached

        analysis = self._color_analysis(color)
        if analysis.threats:
            # 已有一步胜点时应直接获胜，不需要另找 T2。
            self._threat_map_cache[key] = {}
            return {}

        n = self.game.n
        b = self.game.board
        result = {}
        for move, joined_roots in analysis.move_roots.items():
            if not joined_roots:
                continue
            x, y = move
            created = set()

            # 新棋把多个原本分离的分量连接后，它们共同接触的空点会成 T1。
            if len(joined_roots) >= 2:
                for a, c in combinations(joined_roots, 2):
                    created.update(analysis.frontiers.get(a, ()) &
                                   analysis.frontiers.get(c, ()))

            # 即使只接触一个己方分量，也可能在新棋旁边制造 T1。
            for nx, ny in ((x - 1, y), (x + 1, y),
                           (x, y - 1), (x, y + 1)):
                if not (0 <= nx < n and 0 <= ny < n):
                    continue
                q = (nx, ny)
                if b[nx][ny] != EMPTY or q == move:
                    continue
                if analysis.move_roots.get(q, frozenset()) & joined_roots:
                    created.add(q)

            created.discard(move)  # move 落子后已不再是空点。
            if created:
                result[move] = tuple(sorted(created))

        self._threat_map_cache[key] = result
        return result

    def _t2_and_forks(self, color):
        """兼容公开测试接口，使用新的完整 T2/fork 判定。"""
        old_hash = self._hash
        self._hash = self._compute_hash()
        try:
            mapping = self._threat_map(color)
            t2 = [move for move, wins in mapping.items() if len(wins) == 1]
            forks = [move for move, wins in mapping.items() if len(wins) >= 2]
            return sorted(t2), sorted(forks)
        finally:
            self._hash = old_hash

    # ------------------------------------------------------------------
    # 走法生成和静态评分
    # ------------------------------------------------------------------
    def _positional_score(self, move, color):
        """普通走法排序；只影响搜索先后，不直接决定胜负。"""
        x, y = move
        b = self.game.board
        n = self.game.n
        opp = WHITE if color == BLACK else BLACK
        mine = theirs = 0
        for nx, ny in ((x - 1, y), (x + 1, y),
                       (x, y - 1), (x, y + 1)):
            if 0 <= nx < n and 0 <= ny < n:
                c = b[nx][ny]
                if c == color:
                    mine += 1
                elif c == opp:
                    theirs += 1
        center = (n - 1) / 2.0
        centrality = 2 * n - abs(x - center) - abs(y - center)
        return 30 * mine + 20 * theirs + centrality

    def _candidate_moves(self, to_move, depth, root=False,
                         tactical_only=False, tt_move=None):
        """关键战术走法全部保留，只限制普通走法数量。"""
        mine = self._color_analysis(to_move)
        opp = WHITE if to_move == BLACK else BLACK
        theirs = self._color_analysis(opp)
        b = self.game.board
        n = self.game.n

        # 对手已有唯一 T1 时只有占住该点才能活下来。
        if len(theirs.threats) == 1:
            return [theirs.threats[0]]

        my_map = self._threat_map(to_move)
        opp_map = self._threat_map(opp)
        my_forks = {m for m, wins in my_map.items() if len(wins) >= 2}
        opp_forks = {m for m, wins in opp_map.items() if len(wins) >= 2}
        my_t2 = set(my_map) - my_forks
        opp_t2 = set(opp_map) - opp_forks
        future_blocks = {point for move in opp_forks
                         for point in opp_map[move]}

        tactical = my_forks | opp_forks | my_t2 | opp_t2 | future_blocks
        tactical = {m for m in tactical if b[m[0]][m[1]] == EMPTY}

        scored = {}
        for move in tactical:
            score = self._positional_score(move, to_move)
            if move in my_forks:
                score += 120000
            if move in opp_forks:
                score += 90000
            if move in my_t2:
                score += 60000
            if move in opp_t2:
                score += 42000
            if move in future_blocks:
                score += 30000
            scored[move] = score

        if not tactical_only:
            quiet = []
            for x in range(n):
                for y in range(n):
                    if b[x][y] != EMPTY or (x, y) in scored:
                        continue
                    s = self._positional_score((x, y), to_move)
                    # 非空局面优先研究双方棋形附近；根节点仍保留较宽选择。
                    adjacent = False
                    for nx, ny in ((x - 1, y), (x + 1, y),
                                   (x, y - 1), (x, y + 1)):
                        if 0 <= nx < n and 0 <= ny < n \
                                and b[nx][ny] != EMPTY:
                            adjacent = True
                            break
                    if adjacent or not self.game.history:
                        quiet.append((s, (x, y)))
            quiet.sort(key=lambda item: (-item[0], item[1]))
            if root:
                quiet_limit = 28 if n <= 15 else 20
            elif depth >= 5:
                quiet_limit = 10
            elif depth >= 3:
                quiet_limit = 14
            else:
                quiet_limit = 18
            for s, move in quiet[:quiet_limit]:
                scored[move] = s

        if not scored:
            # 极稀疏或残局兜底。
            for x in range(n):
                for y in range(n):
                    if b[x][y] == EMPTY:
                        scored[(x, y)] = self._positional_score(
                            (x, y), to_move)

        if tt_move in scored:
            scored[tt_move] += 250000
        return [move for move, _ in sorted(
            scored.items(), key=lambda item: (-item[1], item[0]))]

    def _evaluate_position(self, me):
        """在没有立即胜负时评价双方未来制造威胁的能力。"""
        opp = WHITE if me == BLACK else BLACK
        mine = self._color_analysis(me)
        theirs = self._color_analysis(opp)
        my_map = self._threat_map(me)
        opp_map = self._threat_map(opp)
        my_forks = sum(len(wins) >= 2 for wins in my_map.values())
        opp_forks = sum(len(wins) >= 2 for wins in opp_map.values())
        my_t2 = len(my_map) - my_forks
        opp_t2 = len(opp_map) - opp_forks
        my_bridges = sum(len(roots) >= 2
                         for roots in mine.move_roots.values())
        opp_bridges = sum(len(roots) >= 2
                          for roots in theirs.move_roots.values())
        my_frontier = sum(bool(roots) for roots in mine.move_roots.values())
        opp_frontier = sum(bool(roots)
                           for roots in theirs.move_roots.values())
        my_largest = mine.component_sizes[0] if mine.component_sizes else 0
        opp_largest = theirs.component_sizes[0] if theirs.component_sizes else 0
        return (12000 * (my_forks - opp_forks)
                + 750 * (my_t2 - opp_t2)
                + 80 * (my_bridges - opp_bridges)
                + 10 * (my_frontier - opp_frontier)
                + 6 * (my_largest - opp_largest))

    # ------------------------------------------------------------------
    # 迭代加深 α-β 搜索
    # ------------------------------------------------------------------
    def _negamax(self, depth, alpha, beta, to_move, extension=4):
        self._nodes += 1
        self._check_time()
        alpha_start = alpha
        mine = self._color_analysis(to_move)
        opp = WHITE if to_move == BLACK else BLACK
        theirs = self._color_analysis(opp)

        if mine.threats:
            return WIN
        if len(theirs.threats) >= 2:
            return LOSS
        if not mine.move_roots:
            return 0                              # 满盘且无人成环：平局

        tt_key = (self._hash, to_move)
        tt_entry = self._tt.get(tt_key)
        tt_move = None
        if tt_entry is not None:
            tt_depth, tt_score, tt_flag, tt_move = tt_entry
            if tt_depth >= depth and depth > 0:
                self._tt_hits += 1
                if tt_flag == self.TT_EXACT:
                    return tt_score
                if tt_flag == self.TT_LOWER:
                    alpha = max(alpha, tt_score)
                else:
                    beta = min(beta, tt_score)
                if alpha >= beta:
                    return tt_score

        tactical_only = False
        if depth <= 0:
            my_map = self._threat_map(to_move)
            opp_map = self._threat_map(opp)
            forcing = any(len(wins) >= 2 for wins in my_map.values()) \
                or any(len(wins) >= 2 for wins in opp_map.values()) \
                or bool(my_map)
            if extension <= 0 or not forcing:
                return self._evaluate_position(to_move)
            tactical_only = True

        moves = self._candidate_moves(
            to_move, depth, tactical_only=tactical_only, tt_move=tt_move)
        if tactical_only:
            moves = moves[:10]
        if not moves:
            return 0

        best = LOSS
        best_move = moves[0]
        for move in moves:
            self._check_time()
            self._play(move, to_move)
            try:
                if depth > 0:
                    value = -self._negamax(depth - 1, -beta, -alpha,
                                           opp, extension)
                else:
                    value = -self._negamax(0, -beta, -alpha,
                                           opp, extension - 1)
            finally:
                self._unplay(move, to_move)
            if value > best:
                best, best_move = value, move
            alpha = max(alpha, value)
            if alpha >= beta:
                break

        if depth > 0:
            if best <= alpha_start:
                flag = self.TT_UPPER
            elif best >= beta:
                flag = self.TT_LOWER
            else:
                flag = self.TT_EXACT
            self._tt[tt_key] = (depth, best, flag, best_move)
        return best

    def _search_root(self, depth, moves):
        alpha = LOSS
        beta = WIN
        best_score = LOSS
        best_move = moves[0]
        # 上一层根节点最佳走法优先搜索。
        tt_entry = self._tt.get((self._hash, self.color))
        if tt_entry and tt_entry[3] in moves:
            preferred = tt_entry[3]
            moves = [preferred] + [m for m in moves if m != preferred]

        for move in moves:
            self._check_time()
            self._play(move, self.color)
            try:
                value = -self._negamax(depth - 1, -beta, -alpha,
                                       self.opp, extension=4)
            finally:
                self._unplay(move, self.color)
            if value > best_score:
                best_score, best_move = value, move
            alpha = max(alpha, value)
            if value >= WIN:
                break
        self._tt[(self._hash, self.color)] = (
            depth, best_score, self.TT_EXACT, best_move)
        return best_move, best_score

    def choose_move(self):
        """在时间预算内返回最后一次完整搜索得到的最佳落子。"""
        started = time.perf_counter()
        self._deadline = started + max(0.01, self.time_budget)
        self._hash = self._compute_hash()
        self._nodes = 0
        self._tt_hits = 0
        self._analysis_cache = {}
        self._threat_map_cache = {}
        self._tt = {}

        fallback = self._any_empty()
        if fallback is None:
            return None

        try:
            mine = self._color_analysis(self.color)
            if mine.threats:
                best = mine.threats[0]
                self._finish_stats(started, 0, WIN)
                return best
            theirs = self._color_analysis(self.opp)
            if len(theirs.threats) == 1:
                best = theirs.threats[0]
                self._finish_stats(started, 0, 0)
                return best
            if len(theirs.threats) >= 2:
                # 理论败势：至少堵住一个，延长对局并等待对手失误。
                best = theirs.threats[0]
                self._finish_stats(started, 0, LOSS)
                return best

            root_moves = self._candidate_moves(
                self.color, depth=1, root=True)
            if not root_moves:
                self._finish_stats(started, 0, 0)
                return fallback
            completed_move = root_moves[0]
            completed_score = LOSS
            completed_depth = 0

            for depth in range(1, self.max_depth + 1):
                self._check_time()
                move, score = self._search_root(depth, root_moves)
                completed_move = move
                completed_score = score
                completed_depth = depth
                # 已证明必胜，无需继续消耗时间。
                if score >= WIN:
                    break
            self._finish_stats(started, completed_depth, completed_score)
            return completed_move
        except _SearchTimeout:
            # 当前迭代没有完成，只使用上一层完整结果。
            if 'completed_move' not in locals():
                completed_move = fallback
                completed_depth = 0
                completed_score = 0
            self._finish_stats(started, completed_depth, completed_score)
            return completed_move

    def _finish_stats(self, started, depth, score):
        self.last_stats = {
            'completed_depth': depth,
            'nodes': self._nodes,
            'tt_hits': self._tt_hits,
            'elapsed': time.perf_counter() - started,
            'score': score,
        }


# ============================================================================
# 默认 AI：与 index.html 同步的混合版
# ============================================================================


class JordanAI(LegacyJordanAI):
    """浏览器 AI 的 Python 同步版。

    保留 HTML 版在实战中更有效的轻量棋形评分和窄候选搜索，同时补齐：
      * 单邻居延伸 T2/fork 检测；
      * 逐层加深，只采用完整搜索完的一层；
      * 置换表和强制战术延伸；
      * 超时后可靠恢复棋盘。

    `ThreatJordanAI` 保留迁移前的完整威胁版，供回归和强度对比。
    """

    TT_EXACT = 0
    TT_LOWER = 1
    TT_UPPER = 2

    def __init__(self, game, color, time_budget=2.0, max_depth=8, seed=None):
        super().__init__(game, color, time_budget=time_budget,
                         max_depth=max_depth, seed=seed)
        self._tt = {}
        self._nodes = 0
        self._tt_hits = 0
        self.last_stats = {
            'completed_depth': 0,
            'nodes': 0,
            'tt_hits': 0,
            'elapsed': 0.0,
            'score': 0,
        }

    # ------------------------------------------------------------------
    # 与 HTML 对齐的基础工具
    # ------------------------------------------------------------------
    def _check_time(self):
        if self._deadline > 0 and time.perf_counter() >= self._deadline:
            raise _SearchTimeout

    def _state_key(self, to_move):
        board_key = bytes(cell for row in self.game.board for cell in row)
        return to_move, board_key

    def _board_full(self):
        return all(cell != EMPTY for row in self.game.board for cell in row)

    def _threats(self, color, limit=None):
        """与 HTML 一样，达到 limit 后立即返回，不继续扫描棋盘。"""
        n = self.game.n
        b = self.game.board
        dsu = self._build_dsu(color)
        idx = self._idx
        result = []
        for x in range(n):
            for y in range(n):
                if b[x][y] != EMPTY:
                    continue
                neighbors = []
                if x > 0 and b[x - 1][y] == color:
                    neighbors.append(idx(x - 1, y))
                if x < n - 1 and b[x + 1][y] == color:
                    neighbors.append(idx(x + 1, y))
                if y > 0 and b[x][y - 1] == color:
                    neighbors.append(idx(x, y - 1))
                if y < n - 1 and b[x][y + 1] == color:
                    neighbors.append(idx(x, y + 1))
                if len(neighbors) < 2:
                    continue
                hit = False
                for i in range(len(neighbors) - 1):
                    root = dsu.find(neighbors[i])
                    for j in range(i + 1, len(neighbors)):
                        if root == dsu.find(neighbors[j]):
                            hit = True
                            break
                    if hit:
                        break
                if hit:
                    result.append((x, y))
                    if limit is not None and len(result) >= limit:
                        return result
        return result

    # ------------------------------------------------------------------
    # HTML 的完整战术预计算
    # ------------------------------------------------------------------
    def _t2_and_forks(self, color):
        """检查所有至少接触一枚同色棋子的空点，和 HTML 完全一致。"""
        n = self.game.n
        b = self.game.board
        candidates = []
        for x in range(n):
            for y in range(n):
                if b[x][y] != EMPTY:
                    continue
                count = 0
                if x > 0 and b[x - 1][y] == color: count += 1
                if x < n - 1 and b[x + 1][y] == color: count += 1
                if y > 0 and b[x][y - 1] == color: count += 1
                if y < n - 1 and b[x][y + 1] == color: count += 1
                if count >= 1:
                    candidates.append((x, y))

        t2, forks = [], []
        for move in candidates:
            self._check_time()
            x, y = move
            b[x][y] = color
            try:
                threats = self._threats(color, limit=3)
            finally:
                b[x][y] = EMPTY
            if len(threats) >= 2:
                forks.append(move)
            elif len(threats) == 1:
                t2.append(move)
        return t2, forks

    # ------------------------------------------------------------------
    # HTML 的候选位置排序
    # ------------------------------------------------------------------
    def _gen_moves(self, color, top=14):
        n = self.game.n
        b = self.game.board
        opp = WHITE if color == BLACK else BLACK
        scored = []
        for x in range(n):
            for y in range(n):
                if b[x][y] != EMPTY:
                    continue
                mine = theirs = 0
                if x > 0:
                    c = b[x - 1][y]
                    if c == color: mine += 1
                    elif c == opp: theirs += 1
                if x < n - 1:
                    c = b[x + 1][y]
                    if c == color: mine += 1
                    elif c == opp: theirs += 1
                if y > 0:
                    c = b[x][y - 1]
                    if c == color: mine += 1
                    elif c == opp: theirs += 1
                if y < n - 1:
                    c = b[x][y + 1]
                    if c == color: mine += 1
                    elif c == opp: theirs += 1
                if mine == 0 and theirs == 0:
                    continue
                centrality = 0.3 * (
                    n - abs(2 * x - (n - 1))
                    + n - abs(2 * y - (n - 1)))
                scored.append((mine * 5 + theirs * 3 + centrality,
                               (x, y)))
        scored.sort(key=lambda item: (-item[0], item[1]))
        return [move for _, move in scored[:top]]

    def _root_candidates(self, t2m, fm, t2o, fo):
        n = self.game.n
        b = self.game.board
        tactical = {}
        quiet = {}

        def put(pool, move, score):
            if move not in pool or pool[move] < score:
                pool[move] = score

        for move in fm: put(tactical, move, 5000)
        for move in fo: put(tactical, move, 4600)
        for move in t2m: put(tactical, move, 3000)
        for move in t2o: put(tactical, move, 2800)

        for x in range(n):
            for y in range(n):
                c = b[x][y]
                if c == EMPTY:
                    continue
                base = 1200 if c == self.color else 800
                for nx, ny in ((x - 1, y), (x + 1, y),
                               (x, y - 1), (x, y + 1)):
                    move = (nx, ny)
                    if not (0 <= nx < n and 0 <= ny < n):
                        continue
                    if b[nx][ny] != EMPTY or move in tactical:
                        continue
                    put(quiet, move, base)

        center = (n - 1) / 2.0

        def rank(pool):
            values = [
                (score + 20 * (n - abs(move[0] - center)
                               - abs(move[1] - center)), move, score)
                for move, score in pool.items()
            ]
            values.sort(key=lambda item: (-item[0], item[1]))
            return values

        forced = rank(tactical)
        room = max(0, self._cand_limit - len(forced))
        normal = rank(quiet)[:room]
        return [(move, score) for _, move, score in forced + normal]

    def _tactical_candidates(self, to_move):
        opp = WHITE if to_move == BLACK else BLACK
        mine = self._t2_and_forks(to_move)
        theirs = self._t2_and_forks(opp)
        values = {}

        def put(move, score):
            if move not in values or values[move] < score:
                values[move] = score

        for move in mine[1]: put(move, 5000)
        for move in theirs[1]: put(move, 4600)
        for move in mine[0]: put(move, 3000)
        for move in theirs[0]: put(move, 2800)
        return [move for move, _ in sorted(
            values.items(), key=lambda item: (-item[1], item[0]))]

    # ------------------------------------------------------------------
    # 与 HTML 对齐的逐层加深搜索
    # ------------------------------------------------------------------
    def _negamax(self, depth, alpha, beta, to_move, extension=3):
        self._nodes += 1
        self._check_time()
        alpha_start, beta_start = alpha, beta
        if self._threats(to_move, limit=1):
            return WIN
        opp = WHITE if to_move == BLACK else BLACK
        opponent_wins = self._threats(opp, limit=2)
        if len(opponent_wins) >= 2:
            return LOSS
        if self._board_full():
            return 0

        key = self._state_key(to_move)
        entry = self._tt.get(key)
        tt_move = None
        if entry is not None:
            tt_depth, tt_score, tt_flag, tt_move = entry
            if tt_depth >= depth and depth > 0:
                self._tt_hits += 1
                if tt_flag == self.TT_EXACT:
                    return tt_score
                if tt_flag == self.TT_LOWER:
                    alpha = max(alpha, tt_score)
                else:
                    beta = min(beta, tt_score)
                if alpha >= beta:
                    return tt_score

        next_depth = depth - 1
        next_extension = extension
        if len(opponent_wins) == 1:
            moves = [opponent_wins[0]]
        elif depth <= 0:
            if extension <= 0:
                return self._evaluate(to_move)
            moves = self._tactical_candidates(to_move)[:10]
            if not moves:
                return self._evaluate(to_move)
            next_depth = 0
            next_extension = extension - 1
        else:
            moves = self._gen_moves(to_move, top=self._cand_limit)
        if not moves:
            return 0

        if tt_move in moves:
            moves = [tt_move] + [move for move in moves if move != tt_move]

        best = LOSS
        best_move = moves[0]
        for move in moves:
            self._check_time()
            x, y = move
            self.game.board[x][y] = to_move
            try:
                value = -self._negamax(
                    next_depth, -beta, -alpha, opp, next_extension)
            finally:
                self.game.board[x][y] = EMPTY
            if value > best:
                best, best_move = value, move
            alpha = max(alpha, value)
            if alpha >= beta:
                break

        if depth > 0:
            flag = (self.TT_UPPER if best <= alpha_start else
                    self.TT_LOWER if best >= beta_start else self.TT_EXACT)
            self._tt[key] = (depth, best, flag, best_move)
        return best

    def _search_root(self, depth, candidates):
        moves = [item[0] for item in candidates]
        root_key = self._state_key(self.color)
        entry = self._tt.get(root_key)
        if entry is not None and entry[3] in moves:
            preferred = entry[3]
            moves = [preferred] + [move for move in moves
                                   if move != preferred]

        alpha = LOSS
        best_score = LOSS
        best_move = moves[0]
        for move in moves:
            self._check_time()
            x, y = move
            self.game.board[x][y] = self.color
            try:
                value = -self._negamax(
                    depth - 1, LOSS, -alpha, self.opp, extension=3)
            finally:
                self.game.board[x][y] = EMPTY
            if value > best_score:
                best_score, best_move = value, move
            alpha = max(alpha, value)
            if value >= WIN:
                break
        self._tt[root_key] = (
            depth, best_score, self.TT_EXACT, best_move)
        return best_move, best_score

    def choose_move(self):
        started = time.perf_counter()
        self._deadline = started + max(0.01, self.time_budget)
        self._tt = {}
        self._nodes = 0
        self._tt_hits = 0
        fallback = self._any_empty()
        if fallback is None:
            return None
        completed_move = fallback
        completed_depth = 0
        completed_score = 0

        try:
            mine = self._threats(self.color, limit=1)
            if mine:
                completed_move = mine[0]
                completed_score = WIN
            else:
                theirs = self._threats(self.opp, limit=3)
                if len(theirs) == 1:
                    completed_move = theirs[0]
                elif len(theirs) >= 2:
                    completed_move = theirs[0]
                    completed_score = LOSS
                else:
                    t2m, fm = self._t2_and_forks(self.color)
                    t2o, fo = self._t2_and_forks(self.opp)
                    if fm:
                        completed_move = fm[0]
                        completed_score = WIN
                    else:
                        candidates = self._root_candidates(
                            t2m, fm, t2o, fo)
                        if candidates:
                            completed_move = candidates[0][0]
                            for depth in range(1, self.max_depth + 1):
                                self._check_time()
                                move, score = self._search_root(
                                    depth, candidates)
                                completed_move = move
                                completed_score = score
                                completed_depth = depth
                                if completed_score >= WIN:
                                    break
        except _SearchTimeout:
            pass

        self.last_stats = {
            'completed_depth': completed_depth,
            'nodes': self._nodes,
            'tt_hits': self._tt_hits,
            'elapsed': time.perf_counter() - started,
            'score': completed_score,
        }
        return completed_move
