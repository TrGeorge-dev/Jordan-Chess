#!/usr/bin/env python3
"""Paired-color tournament: clean V3 search versus the current default AI."""

import argparse
import csv
import json
import statistics
import time
from pathlib import Path

from ai import HybridJordanAI
from ai_v3 import JordanSearchAI
from benchmark_ai import generate_opening
from engine import BLACK, WHITE, JordanChess


def mean(values):
    return statistics.fmean(values) if values else 0.0


def play_game(size, opening, v3_color, budget, max_depth, seed):
    game = JordanChess(size=size)
    for move in opening:
        result = game.place(*move)
        if not result["ok"] or result["winner"] is not None:
            raise ValueError(f"invalid benchmark opening: {opening}")
    current_color = WHITE if v3_color == BLACK else BLACK
    players = {
        v3_color: ("v3", JordanSearchAI(
            game, v3_color, time_budget=budget, max_depth=max_depth,
            seed=seed + 1000)),
        current_color: ("current", HybridJordanAI(
            game, current_color, time_budget=budget, max_depth=max_depth,
            seed=seed + 2000)),
    }
    stats = {
        name: {"time": [], "depth": [], "nodes": []}
        for name in ("v3", "current")
    }
    moves = []
    while game.winner is None:
        name, ai = players[game.turn]
        started = time.perf_counter()
        move = ai.choose_move()
        elapsed = time.perf_counter() - started
        if move is None:
            raise AssertionError(f"{name} returned no move on a live board")
        result = game.place(*move)
        if not result["ok"]:
            raise AssertionError(f"{name} returned illegal move {move}: {result}")
        stats[name]["time"].append(elapsed)
        stats[name]["depth"].append(ai.last_stats["completed_depth"])
        stats[name]["nodes"].append(ai.last_stats["nodes"])
        moves.append(f"{name[0]}:{move[0]},{move[1]}")

    winner = ("draw" if game.winner == "DRAW"
              else players[game.winner][0])
    row = {
        "winner": winner,
        "winner_color": ("draw" if game.winner == "DRAW" else
                         "black" if game.winner == BLACK else "white"),
        "total_moves": len(game.history),
        "continuation": " ".join(moves),
    }
    for name in ("v3", "current"):
        row[f"{name}_move_count"] = len(stats[name]["time"])
        row[f"{name}_total_seconds"] = sum(stats[name]["time"])
        row[f"{name}_avg_move_seconds"] = mean(stats[name]["time"])
        row[f"{name}_avg_depth"] = mean(stats[name]["depth"])
        row[f"{name}_avg_nodes"] = mean(stats[name]["nodes"])
    return row


def run_tournament(pairs, sizes, opening_plies, budget, max_depth, seed):
    rows = []
    for size in sizes:
        for pair_id in range(1, pairs + 1):
            opening_seed = seed + size * 100003 + pair_id * 7919
            opening = generate_opening(size, opening_plies, opening_seed)
            opening_text = " ".join(f"{x},{y}" for x, y in opening)
            for game_in_pair, v3_color in enumerate(
                    (BLACK, WHITE), start=1):
                row = play_game(size, opening, v3_color, budget,
                                max_depth, opening_seed + game_in_pair)
                row.update({
                    "board_size": size,
                    "pair_id": pair_id,
                    "game_in_pair": game_in_pair,
                    "opening_seed": opening_seed,
                    "opening": opening_text,
                    "opening_plies": len(opening),
                    "budget": budget,
                    "max_depth": max_depth,
                    "v3_color": "black" if v3_color == BLACK else "white",
                    "current_color": ("white" if v3_color == BLACK
                                      else "black"),
                })
                rows.append(row)
                print(f"size={size} pair={pair_id:02d}/{pairs} "
                      f"v3={row['v3_color']} winner={row['winner']} "
                      f"moves={row['total_moves']}", flush=True)
    return rows


def summarize(rows):
    games = len(rows)
    wins = sum(row["winner"] == "v3" for row in rows)
    losses = sum(row["winner"] == "current" for row in rows)
    draws = games - wins - losses
    result = {
        "games": games,
        "pairs": games // 2,
        "v3_wins": wins,
        "draws": draws,
        "current_wins": losses,
        "v3_score_rate": (wins + .5 * draws) / games if games else 0,
    }
    for size in sorted({row["board_size"] for row in rows}):
        subset = [row for row in rows if row["board_size"] == size]
        sw = sum(row["winner"] == "v3" for row in subset)
        sl = sum(row["winner"] == "current" for row in subset)
        sd = len(subset) - sw - sl
        result[f"size_{size}"] = {
            "games": len(subset), "v3_wins": sw, "draws": sd,
            "current_wins": sl,
            "v3_score_rate": (sw + .5 * sd) / len(subset),
        }
    for name in ("v3", "current"):
        move_count = sum(row[f"{name}_move_count"] for row in rows)
        result[f"{name}_avg_move_seconds"] = (
            sum(row[f"{name}_total_seconds"] for row in rows) / move_count)
        result[f"{name}_avg_depth"] = mean(
            row[f"{name}_avg_depth"] for row in rows)
        result[f"{name}_avg_nodes"] = mean(
            row[f"{name}_avg_nodes"] for row in rows)
    paired = []
    for size in sorted({row["board_size"] for row in rows}):
        for pair_id in sorted({row["pair_id"] for row in rows
                               if row["board_size"] == size}):
            subset = [row for row in rows
                      if row["board_size"] == size
                      and row["pair_id"] == pair_id]
            v3_points = sum(1 if row["winner"] == "v3" else
                            .5 if row["winner"] == "draw" else 0
                            for row in subset)
            paired.append(v3_points)
    result["paired_better"] = sum(points > 1 for points in paired)
    result["paired_equal"] = sum(points == 1 for points in paired)
    result["paired_worse"] = sum(points < 1 for points in paired)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pairs", type=int, default=12)
    parser.add_argument("--sizes", default="8,10")
    parser.add_argument("--opening-plies", type=int, default=4)
    parser.add_argument("--budget", type=float, default=.12)
    parser.add_argument("--max-depth", type=int, default=12)
    parser.add_argument("--seed", type=int, default=20260808)
    parser.add_argument("--output-dir", type=Path,
                        default=Path("benchmark-v3"))
    args = parser.parse_args()
    sizes = [int(value) for value in args.sizes.split(",")]
    rows = run_tournament(args.pairs, sizes, args.opening_plies,
                          args.budget, args.max_depth, args.seed)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = args.output_dir / "v3_games.csv"
    json_path = args.output_dir / "v3_summary.json"
    with csv_path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    summary = summarize(rows)
    summary["config"] = {
        "pairs": args.pairs, "sizes": sizes,
        "opening_plies": args.opening_plies, "budget": args.budget,
        "max_depth": args.max_depth, "seed": args.seed,
    }
    with json_path.open("w", encoding="utf-8") as file:
        json.dump(summary, file, ensure_ascii=False, indent=2)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(csv_path)
    print(json_path)


if __name__ == "__main__":
    main()
