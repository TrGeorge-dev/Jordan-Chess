#!/usr/bin/env python3
"""Jordan Chess V3: a clean game-search architecture.

The game is a finite deterministic two-player zero-sum game.  This module
separates four concerns which were interleaved in the original AI:

* ``SearchState`` owns reversible board state and exact connectivity.
* threat-space helpers identify wins and forcing continuations.
* ``JordanSearchAI`` performs iterative-deepening PVS with a TT.
* ``EvalWeights`` is the single tunable strategic model.

The existing ``ai.py`` remains untouched as the benchmark opponent until V3
has demonstrated higher playing strength.
"""

from __future__ import annotations

import random
import time
from collections import defaultdict
from dataclasses import dataclass
from itertools import combinations

from engine import BLACK, EMPTY, WHITE


MATE = 1_000_000
INF = 1_100_000


def _point_in_polygon(px, py, poly):
    """射线法(与引擎一致): 半开区间规则, 奇数→内部。"""
    inside = False
    m = len(poly)
    for i in range(m):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % m]
        if (y1 > py) != (y2 > py):
            xi = x1 + (py - y1) * (x2 - x1) / (y2 - y1)
            if xi > px:
                inside = not inside
    return inside


def _cycle_contains_lattice_point(cycle_xy):
    """环(坐标列表)内部是否包含 ≥1 个格点(顶点不算, 有无棋子都算)。ADR-0002。"""
    on_loop = set(cycle_xy)
    xs = [p[0] for p in cycle_xy]
    ys = [p[1] for p in cycle_xy]
    for x in range(min(xs), max(xs) + 1):
        for y in range(min(ys), max(ys) + 1):
            if (x, y) in on_loop:
                continue
            if _point_in_polygon(x, y, cycle_xy):
                return True
    return False


class SearchTimeout(Exception):
    """Raised only to discard an unfinished iterative-deepening pass."""


class RollbackDSU:
    """Disjoint-set union supporting snapshots and exact rollback."""

    __slots__ = ("parent", "size", "stack")

    def __init__(self, count):
        self.parent = [-1] * count
        self.size = [0] * count
        self.stack = []

    def active(self, item):
        return self.parent[item] >= 0

    def find(self, item):
        # No path compression: rollback stays O(1) per union.  Union by size
        # keeps tree height logarithmic.
        while self.parent[item] != item:
            item = self.parent[item]
        return item

    def snapshot(self):
        return len(self.stack)

    def activate(self, item):
        if self.parent[item] >= 0:
            raise ValueError(f"point {item} is already active")
        self.stack.append(("a", item))
        self.parent[item] = item
        self.size[item] = 1

    def union(self, first, second):
        root_a = self.find(first)
        root_b = self.find(second)
        if root_a == root_b:
            return False
        if self.size[root_a] < self.size[root_b]:
            root_a, root_b = root_b, root_a
        self.stack.append(("u", root_b, root_a, self.size[root_a]))
        self.parent[root_b] = root_a
        self.size[root_a] += self.size[root_b]
        return True

    def rollback(self, snapshot):
        while len(self.stack) > snapshot:
            event = self.stack.pop()
            if event[0] == "a":
                item = event[1]
                self.parent[item] = -1
                self.size[item] = 0
            else:
                _, child, root, old_size = event
                self.parent[child] = child
                self.size[root] = old_size

    def clear_history(self):
        self.stack.clear()


@dataclass(frozen=True)
class UndoToken:
    move: int
    color: int
    dsu_snapshot: int
    won: bool


class SearchState:
    """Reversible flat-board representation with exact cycle detection.

    The rollback DSU provides a cheap necessary condition for a cycle: two
    same-colour neighbours of the move must already belong to one component.
    ADR-0002 adds a geometric condition, so DSU candidates are always verified
    by the enclosing-cycle detector before they are treated as wins.
    """

    def __init__(self, game):
        self.size = game.size
        self.n = game.n
        self.count = self.n * self.n
        self.board = [game.board[x][y]
                      for x in range(self.n) for y in range(self.n)]
        self.to_move = game.turn
        self.empty_count = sum(value == EMPTY for value in self.board)
        self.dsu = {
            BLACK: RollbackDSU(self.count),
            WHITE: RollbackDSU(self.count),
        }
        self.neighbors = tuple(self._make_neighbors(index)
                               for index in range(self.count))
        self.zobrist = self._make_zobrist()
        self.hash = 0
        self._build_components()

    def _make_neighbors(self, index):
        """八连通邻居表(ADR-0001: 含对角)。用 index 加减定位。"""
        x, y = divmod(index, self.n)
        result = []
        if x > 0:
            result.append(index - self.n)
        if x + 1 < self.n:
            result.append(index + self.n)
        if y > 0:
            result.append(index - 1)
        if y + 1 < self.n:
            result.append(index + 1)
        if x > 0 and y > 0:
            result.append(index - self.n - 1)
        if x > 0 and y + 1 < self.n:
            result.append(index - self.n + 1)
        if x + 1 < self.n and y > 0:
            result.append(index + self.n - 1)
        if x + 1 < self.n and y + 1 < self.n:
            result.append(index + self.n + 1)
        return tuple(result)

    def _make_zobrist(self):
        rng = random.Random(0x4A4F5244414E ^ self.n)
        return tuple((rng.getrandbits(64), rng.getrandbits(64))
                     for _ in range(self.count))

    def _build_components(self):
        for index, color in enumerate(self.board):
            if color == EMPTY:
                continue
            self.dsu[color].activate(index)
            self.hash ^= self.zobrist[index][color - 1]
        for index, color in enumerate(self.board):
            if color == EMPTY:
                continue
            for nb in self.neighbors[index]:
                if self.board[nb] == color:
                    self.dsu[color].union(index, nb)
        self.dsu[BLACK].clear_history()
        self.dsu[WHITE].clear_history()

    def xy(self, index):
        return divmod(index, self.n)

    def index(self, move):
        return move[0] * self.n + move[1]

    def same_color_roots(self, move, color):
        dsu = self.dsu[color]
        return tuple(dsu.find(nb) for nb in self.neighbors[move]
                     if self.board[nb] == color)

    def bfs_path(self, start, target, avoid, color, min_edges=1):
        """BFS 返回 start→target 最短简单路径(避开 avoid); 不可达返回 None。"""
        parent = {start: None}
        queue = [start]
        head = 0
        while head < len(queue):
            cur = queue[head]
            head += 1
            if cur == target:
                break
            for nb in self.neighbors[cur]:
                if nb == avoid or nb in parent:
                    continue
                if self.board[nb] != color:
                    continue
                if min_edges > 1 and cur == start and nb == target:
                    continue
                parent[nb] = cur
                queue.append(nb)
        if target not in parent:
            return None
        path = []
        cur = target
        while cur is not None:
            path.append(cur)
            cur = parent[cur]
        path.reverse()
        return path

    def enclosing_cycle_exists(self, move, color, budget=None):
        """是否存在经过 move 的闭环且环内 ≥1 格点(ADR-0002)。

        对每对邻居 (u,w): BFS 最短路径环含格点 → True;
        否则 DFS 枚举绕行路径补找(预算保护)。
        """
        nbrs = [nb for nb in self.neighbors[move]
                if self.board[nb] == color]
        if len(nbrs) < 2:
            return False

        # Only neighbours in the same pre-move component can close a cycle.
        # Grouping first avoids BFS/DFS work for the overwhelmingly common
        # disconnected pairs.
        groups = defaultdict(list)
        dsu = self.dsu[color]
        for nb in nbrs:
            groups[dsu.find(nb)].append(nb)
        groups = [group for group in groups.values() if len(group) >= 2]
        if not groups:
            return False

        steps = [budget if budget is not None else 1200]

        def check(path):
            cycle = [move] + path
            cy = [self.xy(i) for i in cycle]
            return _cycle_contains_lattice_point(cy)

        for group in groups:
            for i in range(len(group)):
                for j in range(i + 1, len(group)):
                    if steps[0] <= 0:
                        return False
                    u, w = group[i], group[j]
                    path = self.bfs_path(u, w, move, color, min_edges=2)
                    if path is not None and check(path):
                        return True
                    # The shortest path can make a tiny invalid loop while a
                    # longer detour encloses a lattice point. Stop on the first
                    # valid detour instead of materialising every simple path.
                    if self._enclosing_path_exists(
                            u, w, move, color, move, steps):
                        return True
        return False

    def _enclosing_path_exists(self, start, target, avoid, color,
                               closing_vertex, steps):
        """Budgeted DFS for a detour that encloses at least one lattice point."""
        visited = {start}
        MAX_LEN = 14

        def dfs(cur, path):
            steps[0] -= 1
            if steps[0] <= 0:
                return False
            if len(path) > MAX_LEN:
                return False
            if cur == target:
                if len(path) < 3:  # cycle must contain at least four vertices
                    return False
                cycle = [closing_vertex] + path
                return _cycle_contains_lattice_point(
                    [self.xy(index) for index in cycle])
            for nb in self.neighbors[cur]:
                if nb == avoid or nb in visited:
                    continue
                if self.board[nb] != color:
                    continue
                visited.add(nb)
                path.append(nb)
                found = dfs(nb, path)
                path.pop()
                visited.discard(nb)
                if found:
                    return True
            return False

        return dfs(start, [start])

    def is_winning_move(self, move, color):
        """落 move 是否形成有效闭环(环内 ≥1 格点, ADR-0002)。"""
        if self.board[move] != EMPTY:
            return False
        roots = self.same_color_roots(move, color)
        if len(roots) < 2 or len(set(roots)) == len(roots):
            return False
        return self.enclosing_cycle_exists(move, color)

    def winning_moves(self, color, limit=None):
        result = []
        for move, value in enumerate(self.board):
            if value == EMPTY and self.is_winning_move(move, color):
                result.append(move)
                if limit is not None and len(result) >= limit:
                    break
        return tuple(result)

    def play(self, move, color, check_win=True):
        if self.board[move] != EMPTY:
            raise ValueError(f"occupied move: {self.xy(move)}")
        dsu = self.dsu[color]
        snapshot = dsu.snapshot()
        won = self.is_winning_move(move, color) if check_win else False
        self.board[move] = color
        self.empty_count -= 1
        self.hash ^= self.zobrist[move][color - 1]
        dsu.activate(move)
        for neighbor in self.neighbors[move]:
            if self.board[neighbor] == color:
                dsu.union(move, neighbor)
        return UndoToken(move, color, snapshot, won)

    def undo(self, token):
        self.dsu[token.color].rollback(token.dsu_snapshot)
        self.hash ^= self.zobrist[token.move][token.color - 1]
        self.board[token.move] = EMPTY
        self.empty_count += 1

    def frontier_moves(self):
        """Empty points adjacent to either player's existing structure."""
        result = []
        for move, value in enumerate(self.board):
            if value != EMPTY:
                continue
            if any(self.board[nb] != EMPTY for nb in self.neighbors[move]):
                result.append(move)
        return result


@dataclass(frozen=True)
class EvalWeights:
    """All strategic assumptions live here and can be trained by self-play."""

    fork: int = 18_000
    t2: int = 620
    merge_point: int = 170
    frontier_edge: int = 26
    component_square: int = 3
    largest_component: int = 8
    open_diamond_one: int = 10
    open_diamond_two: int = 210
    center: int = 1


@dataclass(frozen=True)
class PositionFeatures:
    forks: int
    t2: int
    merge_points: int
    frontier_edges: int
    component_square: int
    largest_component: int
    open_diamond_one: int
    open_diamond_two: int
    center: int

    def weighted(self, weights):
        return (self.forks * weights.fork
                + self.t2 * weights.t2
                + self.merge_points * weights.merge_point
                + self.frontier_edges * weights.frontier_edge
                + self.component_square * weights.component_square
                + self.largest_component * weights.largest_component
                + self.open_diamond_one * weights.open_diamond_one
                + self.open_diamond_two * weights.open_diamond_two
                + self.center * weights.center)


@dataclass(frozen=True)
class ColorAnalysis:
    threats: tuple
    move_roots: dict
    frontiers: dict
    component_sizes: tuple


@dataclass
class TTEntry:
    depth: int
    score: int
    flag: int
    move: int | None


class JordanSearchAI:
    """Iterative-deepening PVS plus exact threat-space extensions."""

    EXACT = 0
    LOWER = 1
    UPPER = 2

    def __init__(self, game, color, time_budget=2.0, max_depth=12,
                 seed=None, weights=None, variety=0.0):
        self.game = game
        self.color = color
        self.opp = WHITE if color == BLACK else BLACK
        self.time_budget = time_budget
        self.max_depth = max_depth
        self.seed = 1 if seed is None else int(seed)
        self.variety = max(0.0, min(1.0, float(variety)))
        self.rng = random.Random(self.seed)
        self.weights = weights or EvalWeights()
        self.state = None
        self.deadline = 0.0
        self.tt = {}
        self.analysis_cache = {}
        self.tactical_cache = {}
        self.feature_cache = {}
        self.history_scores = [[0] * (game.n * game.n) for _ in range(3)]
        self.killers = {}
        self.root_scores = ()
        self.nodes = 0
        self.tt_hits = 0
        self.cutoffs = 0
        self.last_stats = {
            "completed_depth": 0,
            "nodes": 0,
            "tt_hits": 0,
            "cutoffs": 0,
            "elapsed": 0.0,
            "score": 0,
            "pv": [],
        }

    @staticmethod
    def other(color):
        return WHITE if color == BLACK else BLACK

    def _check_time(self):
        if time.perf_counter() >= self.deadline:
            raise SearchTimeout

    def _prepare(self):
        """Build a fresh reversible state for one search or parity test."""
        self.state = SearchState(self.game)
        self.tt = {}
        self.analysis_cache = {}
        self.tactical_cache = {}
        self.feature_cache = {}
        self.killers = {}
        self.root_scores = ()
        self.nodes = self.tt_hits = self.cutoffs = 0

    def _varied_root_order(self, moves):
        """Shuffle only the strongest root prefix in exhibition mode."""
        ordered = list(moves)
        if self.variety <= 0 or len(ordered) < 2:
            return ordered
        width = min(len(ordered), 2 + int(round(4 * self.variety)))
        prefix = ordered[:width]
        self.rng.shuffle(prefix)
        return prefix + ordered[width:]

    def _varied_fallback(self, moves):
        """Pick a strong root fallback when no full search layer completes."""
        if self.variety <= 0 or len(moves) < 2:
            return moves[0]
        width = min(len(moves), 2 + int(round(4 * self.variety)))
        # Geometric rank bias keeps stronger candidates more likely while
        # allowing each match seed to explore a different opening.
        weights = [0.62 ** rank for rank in range(width)]
        return self.rng.choices(moves[:width], weights=weights, k=1)[0]

    def _varied_completed_move(self, best_move, best_score):
        """Sample among near-equal searched moves, never across forced tactics."""
        if self.variety <= 0 or not self.root_scores:
            return best_move
        if abs(best_score) >= MATE - 100:
            return best_move
        margin = max(40, int(600 * self.variety))
        candidates = [(move, score) for move, score in self.root_scores
                      if score >= best_score - margin and score > -MATE // 2]
        if len(candidates) < 2:
            return best_move
        temperature = max(20.0, margin * 0.55)
        weights = [pow(2.718281828, (score - best_score) / temperature)
                   for _, score in candidates]
        return self.rng.choices(
            [move for move, _ in candidates], weights=weights, k=1)[0]

    def _threats(self, color, limit=None):
        """Compatibility API returning coordinate-form immediate wins."""
        self.deadline = time.perf_counter() + max(1.0, self.time_budget)
        self._prepare()
        return [self.state.xy(move)
                for move in self._winning_moves(color, limit)]

    def _t2_and_forks(self, color):
        """Compatibility API returning coordinate-form T2 and fork moves."""
        self.deadline = time.perf_counter() + max(1.0, self.time_budget)
        self._prepare()
        tactical = self._tactical_map(color)
        t2 = [self.state.xy(move) for move, wins in tactical.items()
              if len(wins) == 1]
        forks = [self.state.xy(move) for move, wins in tactical.items()
                 if len(wins) >= 2]
        return t2, forks

    def _analysis(self, color):
        """Build all connectivity facts for one colour in a single scan."""
        key = (self.state.hash, color)
        cached = self.analysis_cache.get(key)
        if cached is not None:
            return cached
        dsu = self.state.dsu[color]
        component_sizes = defaultdict(int)
        for move, value in enumerate(self.state.board):
            if value == color:
                component_sizes[dsu.find(move)] += 1
        threats = []
        move_roots = {}
        frontiers = defaultdict(set)
        for move, value in enumerate(self.state.board):
            if value != EMPTY:
                continue
            self._check_time()               # 预算检查: 防止分析拖垮搜索
            roots = [dsu.find(nb) for nb in self.state.neighbors[move]
                     if self.state.board[nb] == color]
            unique = tuple(sorted(set(roots)))
            move_roots[move] = unique
            # A repeated root is the cheap graph-theoretic precondition for a
            # new cycle. Only those candidates need the geometric ADR-0002
            # check, which keeps exact threat scans fast on sparse boards.
            if len(roots) > len(unique) and \
                    self.state.enclosing_cycle_exists(move, color):
                threats.append(move)
            for root in unique:
                frontiers[root].add(move)
        result = ColorAnalysis(
            tuple(threats), move_roots,
            {root: frozenset(points) for root, points in frontiers.items()},
            tuple(sorted(component_sizes.values(), reverse=True)))
        self.analysis_cache[key] = result
        return result

    def _winning_moves(self, color, limit=None):
        threats = self._analysis(color).threats
        return threats if limit is None else threats[:limit]

    def _tactical_map(self, color):
        """Map a move to the *exact* T1 points it creates after being played.

        Component/frontier intersections cheaply generate a complete set of
        graph-cycle candidates. ADR-0002 means that connectivity alone is no
        longer sufficient, so every candidate is verified on the reversible
        post-move state before it is exposed as a T2/fork.
        """
        key = (self.state.hash, color)
        cached = self.tactical_cache.get(key)
        if cached is not None:
            return cached
        analysis = self._analysis(color)
        if analysis.threats:
            self.tactical_cache[key] = {}
            return {}
        result = {}
        for move, joined_roots in analysis.move_roots.items():
            self._check_time()
            if not joined_roots:
                continue
            created = set()
            if len(joined_roots) >= 2:
                for first, second in combinations(joined_roots, 2):
                    created.update(analysis.frontiers.get(first, ()) &
                                   analysis.frontiers.get(second, ()))
            joined = set(joined_roots)
            for neighbor in self.state.neighbors[move]:
                if self.state.board[neighbor] != EMPTY:
                    continue
                if joined.intersection(
                        analysis.move_roots.get(neighbor, ())):
                    created.add(neighbor)
            created.discard(move)
            if not created:
                continue

            # ``analysis.threats`` is empty, so ``move`` cannot already win.
            # Skip that duplicate check, update the rollback DSU once, and
            # geometrically filter only the small candidate set above.
            token = self.state.play(move, color, check_win=False)
            try:
                exact = []
                for point in sorted(created):
                    self._check_time()
                    if self.state.is_winning_move(point, color):
                        exact.append(point)
            finally:
                self.state.undo(token)
            if exact:
                result[move] = tuple(exact)
        self.tactical_cache[key] = result
        return result

    def _component_sizes(self, color):
        return self._analysis(color).component_sizes

    def _features(self, color):
        key = (self.state.hash, color)
        cached = self.feature_cache.get(key)
        if cached is not None:
            return cached
        opp = self.other(color)
        analysis = self._analysis(color)
        tactical = self._tactical_map(color)
        forks = sum(len(wins) >= 2 for wins in tactical.values())
        t2 = len(tactical) - forks
        merge_points = frontier_edges = center_score = 0
        center = (self.state.n - 1) / 2.0
        for move, value in enumerate(self.state.board):
            if value == EMPTY:
                roots = analysis.move_roots[move]
                merge_points += len(roots) >= 2
                frontier_edges += sum(
                    self.state.board[nb] == color
                    for nb in self.state.neighbors[move])
            elif value == color:
                x, y = self.state.xy(move)
                center_score += int(2 * self.state.n
                                    - abs(x - center) - abs(y - center))
        sizes = self._component_sizes(color)
        component_square = sum(size * size for size in sizes)
        largest = max(sizes, default=0)
        diamond_one = diamond_two = 0
        n = self.state.n
        board = self.state.board
        # The smallest valid ADR-0002 loop is a radius-one diamond around a
        # lattice point. Unit-square templates are deliberately not rewarded:
        # they contain no lattice point and cannot win under the current rule.
        for x in range(1, n - 1):
            for y in range(1, n - 1):
                values = (board[(x - 1) * n + y],
                          board[x * n + y - 1],
                          board[(x + 1) * n + y],
                          board[x * n + y + 1])
                if opp in values:
                    continue
                count = values.count(color)
                diamond_one += count == 1
                diamond_two += count == 2
        result = PositionFeatures(
            forks, t2, merge_points, frontier_edges, component_square,
            largest, diamond_one, diamond_two, center_score)
        self.feature_cache[key] = result
        return result

    def _evaluate(self, color):
        opponent = self.other(color)
        return (self._features(color).weighted(self.weights)
                - self._features(opponent).weighted(self.weights))

    def _positional_order(self, move, color):
        opponent = self.other(color)
        mine = len(self.state.same_color_roots(move, color))
        theirs = len(self.state.same_color_roots(move, opponent))
        x, y = self.state.xy(move)
        center = (self.state.n - 1) / 2.0
        centrality = int(4 * self.state.n
                         - 2 * abs(x - center) - 2 * abs(y - center))
        diamond_gain = 0
        n = self.state.n
        # A move can be one of four vertices for each adjacent diamond centre.
        for cx, cy in ((x - 1, y), (x + 1, y),
                       (x, y - 1), (x, y + 1)):
            if not (1 <= cx < n - 1 and 1 <= cy < n - 1):
                continue
            points = ((cx - 1) * n + cy, cx * n + cy - 1,
                      (cx + 1) * n + cy, cx * n + cy + 1)
            values = [self.state.board[p] for p in points]
            if opponent not in values:
                diamond_gain += 16 * values.count(color)
            if color not in values:
                diamond_gain += 13 * values.count(opponent)
        return 60 * mine + 42 * theirs + centrality + diamond_gain

    def _ordered_moves(self, color, depth, ply, tactical_only=False,
                       tt_move=None, root=False):
        opponent = self.other(color)
        my_tactical = self._tactical_map(color)
        opp_tactical = self._tactical_map(opponent)
        scored = {}

        def add(move, score):
            if self.state.board[move] == EMPTY:
                scored[move] = max(scored.get(move, -INF), score)

        for move, wins in my_tactical.items():
            add(move, 700_000 if len(wins) >= 2 else 500_000)
        for move, wins in opp_tactical.items():
            add(move, 620_000 if len(wins) >= 2 else 430_000)
            if len(wins) >= 2:
                # A defender can sometimes pre-occupy one future winning point
                # instead of occupying the fork point itself.
                for block in wins:
                    add(block, 390_000)

        if not tactical_only:
            quiet = []
            frontier = set(self.state.frontier_moves())
            # Root keeps a few global alternatives; interior nodes stay local.
            if root:
                empties = [i for i, value in enumerate(self.state.board)
                           if value == EMPTY]
                empties.sort(key=lambda move: (-self._positional_order(
                    move, color), move))
                frontier.update(empties[:6])
            for move in frontier:
                if move not in scored:
                    quiet.append((self._positional_order(move, color), move))
            quiet.sort(key=lambda item: (-item[0], item[1]))
            if root:
                total_limit = 20
            elif depth >= 6:
                total_limit = 10
            elif depth >= 4:
                total_limit = 12
            else:
                total_limit = 16
            room = max(0, total_limit - len(scored))
            for score, move in quiet[:room]:
                add(move, score + self.history_scores[color][move])

        for rank, killer in enumerate(self.killers.get(ply, ())):
            if killer in scored:
                scored[killer] += 100_000 - rank * 1_000
        if tt_move in scored:
            scored[tt_move] += 1_000_000
        return [move for move, _ in sorted(
            scored.items(), key=lambda item: (-item[1], item[0]))]

    def _record_cutoff(self, color, move, depth, ply):
        self.cutoffs += 1
        self.history_scores[color][move] += max(1, depth * depth)
        killers = list(self.killers.get(ply, ()))
        if move in killers:
            killers.remove(move)
        killers.insert(0, move)
        self.killers[ply] = tuple(killers[:2])

    def _pvs(self, depth, alpha, beta, color, ply, qdepth=4):
        self.nodes += 1
        self._check_time()
        alpha_start = alpha
        opponent = self.other(color)

        my_wins = self._winning_moves(color, limit=1)
        if my_wins:
            return MATE - ply
        opponent_wins = self._winning_moves(opponent, limit=2)
        if len(opponent_wins) >= 2:
            return -MATE + ply
        if self.state.empty_count == 0:
            return 0

        key = (self.state.hash, color)
        entry = self.tt.get(key)
        tt_move = entry.move if entry else None
        if entry is not None and entry.depth >= depth and depth > 0:
            self.tt_hits += 1
            if entry.flag == self.EXACT:
                return entry.score
            if entry.flag == self.LOWER:
                alpha = max(alpha, entry.score)
            else:
                beta = min(beta, entry.score)
            if alpha >= beta:
                return entry.score

        forced = len(opponent_wins) == 1
        if forced:
            moves = [opponent_wins[0]]
            next_depth = max(0, depth - 1)
            next_qdepth = qdepth
        elif depth <= 0:
            if qdepth <= 0:
                return self._evaluate(color)
            tactical = self._tactical_map(color)
            forcing = {move for move, wins in tactical.items() if wins}
            if not forcing:
                return self._evaluate(color)
            moves = self._ordered_moves(
                color, depth, ply, tactical_only=True, tt_move=tt_move)
            moves = [move for move in moves if move in forcing][:10]
            if not moves:
                return self._evaluate(color)
            next_depth = 0
            next_qdepth = qdepth - 1
        else:
            moves = self._ordered_moves(
                color, depth, ply, tt_move=tt_move)
            next_depth = depth - 1
            next_qdepth = qdepth
        if not moves:
            return 0

        best = -INF
        best_move = moves[0]
        for index, move in enumerate(moves):
            self._check_time()
            # This node already proved there is no immediate winning move, so
            # repeating the expensive geometry check for every child is waste.
            token = self.state.play(move, color, check_win=False)
            try:
                if token.won:
                    score = MATE - ply
                elif index == 0:
                    score = -self._pvs(next_depth, -beta, -alpha,
                                      opponent, ply + 1, next_qdepth)
                else:
                    score = -self._pvs(next_depth, -alpha - 1, -alpha,
                                      opponent, ply + 1, next_qdepth)
                    if alpha < score < beta:
                        score = -self._pvs(next_depth, -beta, -alpha,
                                          opponent, ply + 1, next_qdepth)
            finally:
                self.state.undo(token)
            if score > best:
                best, best_move = score, move
            if score > alpha:
                alpha = score
            if alpha >= beta:
                self._record_cutoff(color, move, depth, ply)
                break

        if depth > 0:
            flag = (self.UPPER if best <= alpha_start else
                    self.LOWER if best >= beta else self.EXACT)
            self.tt[key] = TTEntry(depth, best, flag, best_move)
        return best

    def _search_root(self, depth, moves):
        root_key = (self.state.hash, self.color)
        entry = self.tt.get(root_key)
        if entry and entry.move in moves:
            moves = [entry.move] + [move for move in moves
                                    if move != entry.move]
        alpha, beta = -INF, INF
        best, best_move = -INF, moves[0]
        scores = []
        for index, move in enumerate(moves):
            self._check_time()
            token = self.state.play(move, self.color, check_win=False)
            try:
                if token.won:
                    score = MATE
                elif index == 0:
                    score = -self._pvs(depth - 1, -beta, -alpha,
                                      self.opp, 1)
                else:
                    score = -self._pvs(depth - 1, -alpha - 1, -alpha,
                                      self.opp, 1)
                    if alpha < score < beta:
                        score = -self._pvs(depth - 1, -beta, -alpha,
                                          self.opp, 1)
            finally:
                self.state.undo(token)
            scores.append((move, score))
            if score > best:
                best, best_move = score, move
            alpha = max(alpha, score)
            if score >= MATE - 2:
                break
        self.root_scores = tuple(scores)
        self.tt[root_key] = TTEntry(depth, best, self.EXACT, best_move)
        return best_move, best

    def _principal_variation(self, limit=16):
        result = []
        tokens = []
        color = self.color
        try:
            for _ in range(limit):
                entry = self.tt.get((self.state.hash, color))
                if entry is None or entry.move is None:
                    break
                move = entry.move
                if self.state.board[move] != EMPTY:
                    break
                result.append(self.state.xy(move))
                token = self.state.play(move, color)
                tokens.append(token)
                if token.won:
                    break
                color = self.other(color)
        finally:
            for token in reversed(tokens):
                self.state.undo(token)
        return result

    def choose_move(self):
        started = time.perf_counter()
        self.deadline = started + max(0.01, self.time_budget)
        self._prepare()

        empties = [move for move, value in enumerate(self.state.board)
                   if value == EMPTY]
        if not empties:
            return None
        fallback = min(empties, key=lambda move: (
            abs(self.state.xy(move)[0] - (self.state.n - 1) / 2)
            + abs(self.state.xy(move)[1] - (self.state.n - 1) / 2), move))
        completed_move = fallback
        completed_score = 0
        completed_depth = 0

        try:
            mine = self._winning_moves(self.color, limit=1)
            if mine:
                completed_move, completed_score = mine[0], MATE
            else:
                theirs = self._winning_moves(self.opp, limit=3)
                if len(theirs) == 1:
                    completed_move = theirs[0]
                elif len(theirs) >= 2:
                    completed_move, completed_score = theirs[0], -MATE
                else:
                    tactical = self._tactical_map(self.color)
                    forks = [move for move, wins in tactical.items()
                             if len(wins) >= 2]
                    if forks:
                        completed_move = (self.rng.choice(forks)
                                          if self.variety > 0 else forks[0])
                        completed_score = MATE - 2
                    else:
                        moves = self._ordered_moves(
                            self.color, depth=1, ply=0, root=True)
                        if moves:
                            moves = self._varied_root_order(moves)
                            completed_move = self._varied_fallback(moves)
                            for depth in range(1, self.max_depth + 1):
                                self._check_time()
                                move, score = self._search_root(depth, moves)
                                completed_move, completed_score = move, score
                                completed_depth = depth
                                if score >= MATE - 2:
                                    break
        except SearchTimeout:
            pass

        if completed_depth > 0:
            completed_move = self._varied_completed_move(
                completed_move, completed_score)

        pv = self._principal_variation()
        self.last_stats = {
            "completed_depth": completed_depth,
            "nodes": self.nodes,
            "tt_hits": self.tt_hits,
            "cutoffs": self.cutoffs,
            "elapsed": time.perf_counter() - started,
            "score": completed_score,
            "pv": pv,
        }
        return self.state.xy(completed_move)
