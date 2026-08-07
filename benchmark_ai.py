#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""新旧 AI 公平对战基准。

每个随机开局进行两盘：第一盘新 AI 执黑，第二盘交换黑白。
双方使用相同的单步时间上限。结果写入 CSV 和 JSON，供 plot_benchmark.py
生成可视化。
"""

import argparse
import csv
import json
import random
import statistics
import time
from pathlib import Path

from ai import JordanAI, LegacyJordanAI
from engine import BLACK, WHITE, JordanChess


def generate_opening(size, plies, seed):
    """生成靠近中心和已有棋形的无胜负开局。"""
    game = JordanChess(size=size)
    rng = random.Random(seed)
    center = (game.n - 1) / 2.0
    while len(game.history) < plies:
        candidates = []
        for move in game.moves():
            x, y = move
            adjacent = 0
            for nx, ny in ((x - 1, y), (x + 1, y),
                           (x, y - 1), (x, y + 1)):
                if 0 <= nx < game.n and 0 <= ny < game.n \
                        and game.board[nx][ny] != 0:
                    adjacent += 1
            distance = abs(x - center) + abs(y - center)
            # 既包含局部接触，也保留少量分散开局。
            weight = 1.0 + 4.0 * adjacent + max(0.0, game.n - distance)
            candidates.append((move, weight))
        if not candidates:
            break
        moves, weights = zip(*candidates)
        move = rng.choices(moves, weights=weights, k=1)[0]
        result = game.place(*move)
        if result['winner'] is not None:
            game.undo()
    return [entry[:2] for entry in game.history]


def play_one(size, opening, new_color, budget, max_depth, seed):
    game = JordanChess(size=size)
    for move in opening:
        result = game.place(*move)
        if not result['ok'] or result['winner'] is not None:
            raise ValueError(f'非法基准开局: {opening}')

    old_color = WHITE if new_color == BLACK else BLACK
    players = {
        new_color: ('new', JordanAI(
            game, new_color, time_budget=budget,
            max_depth=max_depth, seed=seed + 1000)),
        old_color: ('legacy', LegacyJordanAI(
            game, old_color, time_budget=budget,
            max_depth=3, seed=seed + 2000)),
    }
    think_time = {'new': [], 'legacy': []}
    new_depths = []
    new_nodes = []
    moves_after_opening = 0
    limit = game.n * game.n - len(opening)

    while game.winner is None and moves_after_opening < limit:
        name, ai = players[game.turn]
        started = time.perf_counter()
        move = ai.choose_move()
        elapsed = time.perf_counter() - started
        think_time[name].append(elapsed)
        if name == 'new':
            if ai.last_stats['completed_depth'] > 0:
                new_depths.append(ai.last_stats['completed_depth'])
            new_nodes.append(ai.last_stats['nodes'])
        result = game.place(*move)
        if not result['ok']:
            raise AssertionError(f'{name} 返回非法走法 {move}: {result}')
        moves_after_opening += 1

    if game.winner == 'DRAW' or game.winner is None:
        winner = 'draw'
    else:
        winner = players[game.winner][0]

    def mean(values):
        return statistics.fmean(values) if values else 0.0

    return {
        'winner': winner,
        'winner_color': game.winner,
        'total_moves': len(game.history),
        'moves_after_opening': moves_after_opening,
        'new_move_count': len(think_time['new']),
        'legacy_move_count': len(think_time['legacy']),
        'new_search_move_count': len(new_depths),
        'new_forced_move_count': len(think_time['new']) - len(new_depths),
        'new_total_think_seconds': sum(think_time['new']),
        'legacy_total_think_seconds': sum(think_time['legacy']),
        'new_completed_depth_total': sum(new_depths),
        'new_nodes_total': sum(new_nodes),
        'new_avg_move_seconds': mean(think_time['new']),
        'legacy_avg_move_seconds': mean(think_time['legacy']),
        'new_avg_completed_depth': mean(new_depths),
        'new_avg_nodes': mean(new_nodes),
    }


def run_benchmark(pairs, size, opening_plies, budget, max_depth, seed):
    rows = []
    for pair_id in range(1, pairs + 1):
        opening_seed = seed + pair_id * 7919
        opening = generate_opening(size, opening_plies, opening_seed)
        opening_text = ' '.join(f'{x},{y}' for x, y in opening)
        for game_in_pair, new_color in enumerate((BLACK, WHITE), start=1):
            row = play_one(size, opening, new_color, budget,
                           max_depth, opening_seed + game_in_pair)
            row.update({
                'pair_id': pair_id,
                'game_in_pair': game_in_pair,
                'opening_seed': opening_seed,
                'opening': opening_text,
                'board_size': size,
                'opening_plies': len(opening),
                'time_budget_seconds': budget,
                'new_color': 'black' if new_color == BLACK else 'white',
                'legacy_color': 'white' if new_color == BLACK else 'black',
            })
            rows.append(row)
            print(f'pair {pair_id:02d}/{pairs} game {game_in_pair}: '
                  f'new={row["new_color"]} winner={row["winner"]} '
                  f'moves={row["total_moves"]}', flush=True)
    return rows


def summarize(rows):
    total = len(rows)
    counts = {name: sum(row['winner'] == name for row in rows)
              for name in ('new', 'legacy', 'draw')}
    role_counts = {}
    for ai_name in ('new', 'legacy'):
        for color in ('black', 'white'):
            role_counts[f'{ai_name}_{color}_wins'] = sum(
                row['winner'] == ai_name and row[f'{ai_name}_color'] == color
                for row in rows)
    pair_scores = []
    for pair_id in sorted({row['pair_id'] for row in rows}):
        games = [row for row in rows if row['pair_id'] == pair_id]
        pair_scores.append({
            'pair_id': pair_id,
            'new_points': sum(1 if row['winner'] == 'new'
                              else 0.5 if row['winner'] == 'draw' else 0
                              for row in games),
            'legacy_points': sum(1 if row['winner'] == 'legacy'
                                 else 0.5 if row['winner'] == 'draw' else 0
                                 for row in games),
        })
    new_moves = sum(row['new_move_count'] for row in rows)
    legacy_moves = sum(row['legacy_move_count'] for row in rows)
    search_moves = sum(row['new_search_move_count'] for row in rows)
    forced_moves = sum(row['new_forced_move_count'] for row in rows)
    return {
        'games': total,
        'pairs': total // 2,
        'new_wins': counts['new'],
        'legacy_wins': counts['legacy'],
        'draws': counts['draw'],
        'new_score_rate': ((counts['new'] + 0.5 * counts['draw']) / total
                           if total else 0.0),
        **role_counts,
        'new_moves': new_moves,
        'legacy_moves': legacy_moves,
        'new_search_moves': search_moves,
        'new_forced_moves': forced_moves,
        'new_forced_move_rate': forced_moves / new_moves if new_moves else 0.0,
        'new_avg_move_seconds': (
            sum(row['new_total_think_seconds'] for row in rows) / new_moves
            if new_moves else 0.0),
        'legacy_avg_move_seconds': (
            sum(row['legacy_total_think_seconds'] for row in rows) /
            legacy_moves if legacy_moves else 0.0),
        'new_avg_completed_depth': (
            sum(row['new_completed_depth_total'] for row in rows) /
            search_moves if search_moves else 0.0),
        'new_avg_nodes': (
            sum(row['new_nodes_total'] for row in rows) / new_moves
            if new_moves else 0.0),
        'pair_scores': pair_scores,
    }


def main():
    parser = argparse.ArgumentParser(description='Jordan Chess 新旧 AI 对战')
    parser.add_argument('--pairs', type=int, default=20)
    parser.add_argument('--size', type=int, default=10)
    parser.add_argument('--opening-plies', type=int, default=4)
    parser.add_argument('--budget', type=float, default=0.08)
    parser.add_argument('--max-depth', type=int, default=8)
    parser.add_argument('--seed', type=int, default=20260807)
    parser.add_argument('--output-dir', type=Path, default=Path('.'))
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    rows = run_benchmark(args.pairs, args.size, args.opening_plies,
                         args.budget, args.max_depth, args.seed)
    csv_path = args.output_dir / 'ai_benchmark_games.csv'
    json_path = args.output_dir / 'ai_benchmark_summary.json'
    with csv_path.open('w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    summary = summarize(rows)
    summary['config'] = vars(args).copy()
    summary['config']['output_dir'] = str(summary['config']['output_dir'])
    with json_path.open('w', encoding='utf-8') as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f'CSV: {csv_path}')
    print(f'JSON: {json_path}')


if __name__ == '__main__':
    main()
