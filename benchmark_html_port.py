#!/usr/bin/env python3
"""HTML 迁移版 Python AI 与迁移前 Python AI 的成对换色对战。"""

import argparse
import csv
import json
import statistics
import time
from pathlib import Path

from ai import HybridJordanAI, ThreatJordanAI
from benchmark_ai import generate_opening
from engine import BLACK, WHITE, JordanChess


def mean(values):
    return statistics.fmean(values) if values else 0.0


def play_one(size, opening, ported_color, budget, max_depth, seed):
    game = JordanChess(size=size)
    for move in opening:
        result = game.place(*move)
        if not result['ok'] or result['winner'] is not None:
            raise ValueError(f'非法基准开局: {opening}')

    previous_color = WHITE if ported_color == BLACK else BLACK
    players = {
        ported_color: ('ported', HybridJordanAI(
            game, ported_color, time_budget=budget,
            max_depth=max_depth, seed=seed + 1000)),
        previous_color: ('previous', ThreatJordanAI(
            game, previous_color, time_budget=budget,
            max_depth=max_depth, seed=seed + 2000)),
    }
    move_times = {'ported': [], 'previous': []}
    depths = {'ported': [], 'previous': []}
    nodes = {'ported': [], 'previous': []}
    moves_after_opening = 0
    limit = game.n * game.n - len(opening)

    while game.winner is None and moves_after_opening < limit:
        name, ai = players[game.turn]
        started = time.perf_counter()
        move = ai.choose_move()
        move_times[name].append(time.perf_counter() - started)
        depths[name].append(ai.last_stats['completed_depth'])
        nodes[name].append(ai.last_stats['nodes'])
        if move is None:
            raise AssertionError(f'{name} 在未满盘时返回空走法')
        result = game.place(*move)
        if not result['ok']:
            raise AssertionError(f'{name} 返回非法走法 {move}: {result}')
        moves_after_opening += 1

    if game.winner == 'DRAW' or game.winner is None:
        winner = 'draw'
        winner_color = 'draw'
    else:
        winner = players[game.winner][0]
        winner_color = 'black' if game.winner == BLACK else 'white'

    return {
        'winner': winner,
        'winner_color': winner_color,
        'total_moves': len(game.history),
        'moves_after_opening': moves_after_opening,
        'ported_move_count': len(move_times['ported']),
        'previous_move_count': len(move_times['previous']),
        'ported_total_seconds': sum(move_times['ported']),
        'previous_total_seconds': sum(move_times['previous']),
        'ported_avg_move_seconds': mean(move_times['ported']),
        'previous_avg_move_seconds': mean(move_times['previous']),
        'ported_avg_completed_depth': mean(
            [depth for depth in depths['ported'] if depth > 0]),
        'previous_avg_completed_depth': mean(
            [depth for depth in depths['previous'] if depth > 0]),
        'ported_avg_nodes': mean(nodes['ported']),
        'previous_avg_nodes': mean(nodes['previous']),
    }


def run_benchmark(pairs, size, opening_plies, budget, max_depth, seed):
    rows = []
    for pair_id in range(1, pairs + 1):
        opening_seed = seed + pair_id * 7919
        opening = generate_opening(size, opening_plies, opening_seed)
        opening_text = ' '.join(f'{x},{y}' for x, y in opening)
        for game_in_pair, ported_color in enumerate(
                (BLACK, WHITE), start=1):
            row = play_one(size, opening, ported_color, budget,
                           max_depth, opening_seed + game_in_pair)
            row.update({
                'pair_id': pair_id,
                'game_in_pair': game_in_pair,
                'opening_seed': opening_seed,
                'opening': opening_text,
                'board_size': size,
                'opening_plies': len(opening),
                'time_budget_seconds': budget,
                'max_depth': max_depth,
                'ported_color': ('black' if ported_color == BLACK
                                  else 'white'),
                'previous_color': ('white' if ported_color == BLACK
                                    else 'black'),
            })
            rows.append(row)
            print(f'pair {pair_id:02d}/{pairs} game {game_in_pair}: '
                  f'ported={row["ported_color"]} winner={row["winner"]} '
                  f'moves={row["total_moves"]}', flush=True)
    return rows


def summarize(rows):
    games = len(rows)
    wins = sum(row['winner'] == 'ported' for row in rows)
    losses = sum(row['winner'] == 'previous' for row in rows)
    draws = sum(row['winner'] == 'draw' for row in rows)
    ported_moves = sum(row['ported_move_count'] for row in rows)
    previous_moves = sum(row['previous_move_count'] for row in rows)
    pair_scores = []
    for pair_id in sorted({row['pair_id'] for row in rows}):
        pair = [row for row in rows if row['pair_id'] == pair_id]
        pair_scores.append({
            'pair_id': pair_id,
            'ported_points': sum(
                1 if row['winner'] == 'ported' else
                0.5 if row['winner'] == 'draw' else 0 for row in pair),
            'previous_points': sum(
                1 if row['winner'] == 'previous' else
                0.5 if row['winner'] == 'draw' else 0 for row in pair),
        })
    return {
        'games': games,
        'pairs': games // 2,
        'ported_wins': wins,
        'previous_wins': losses,
        'draws': draws,
        'ported_score_rate': ((wins + 0.5 * draws) / games
                              if games else 0.0),
        'ported_black_wins': sum(
            row['winner'] == 'ported' and row['ported_color'] == 'black'
            for row in rows),
        'ported_white_wins': sum(
            row['winner'] == 'ported' and row['ported_color'] == 'white'
            for row in rows),
        'previous_black_wins': sum(
            row['winner'] == 'previous' and row['previous_color'] == 'black'
            for row in rows),
        'previous_white_wins': sum(
            row['winner'] == 'previous' and row['previous_color'] == 'white'
            for row in rows),
        'ported_avg_move_seconds': (
            sum(row['ported_total_seconds'] for row in rows) /
            ported_moves if ported_moves else 0.0),
        'previous_avg_move_seconds': (
            sum(row['previous_total_seconds'] for row in rows) /
            previous_moves if previous_moves else 0.0),
        'ported_avg_completed_depth': statistics.fmean(
            row['ported_avg_completed_depth'] for row in rows),
        'previous_avg_completed_depth': statistics.fmean(
            row['previous_avg_completed_depth'] for row in rows),
        'ported_avg_nodes': statistics.fmean(
            row['ported_avg_nodes'] for row in rows),
        'previous_avg_nodes': statistics.fmean(
            row['previous_avg_nodes'] for row in rows),
        'pair_scores': pair_scores,
    }


def main():
    parser = argparse.ArgumentParser(description='HTML 迁移版与旧 Python AI 对战')
    parser.add_argument('--pairs', type=int, default=12)
    parser.add_argument('--size', type=int, default=10)
    parser.add_argument('--opening-plies', type=int, default=4)
    parser.add_argument('--budget', type=float, default=0.12)
    parser.add_argument('--max-depth', type=int, default=8)
    parser.add_argument('--seed', type=int, default=20260807)
    parser.add_argument('--output-dir', type=Path, default=Path('.'))
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    rows = run_benchmark(args.pairs, args.size, args.opening_plies,
                         args.budget, args.max_depth, args.seed)
    csv_path = args.output_dir / 'html_port_benchmark_games.csv'
    json_path = args.output_dir / 'html_port_benchmark_summary.json'
    with csv_path.open('w', encoding='utf-8', newline='') as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    summary = summarize(rows)
    summary['config'] = {
        'pairs': args.pairs,
        'games': args.pairs * 2,
        'size': args.size,
        'opening_plies': args.opening_plies,
        'budget': args.budget,
        'max_depth': args.max_depth,
        'seed': args.seed,
    }
    with json_path.open('w', encoding='utf-8') as file:
        json.dump(summary, file, ensure_ascii=False, indent=2)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f'CSV: {csv_path}')
    print(f'JSON: {json_path}')


if __name__ == '__main__':
    main()
