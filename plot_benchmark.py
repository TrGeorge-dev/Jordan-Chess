#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 benchmark_ai.py 的结果生成无第三方依赖的 SVG 对比图。"""

import argparse
import csv
import html
import json
from pathlib import Path


BLUE = '#2474B5'
ORANGE = '#D67A2D'
GREY = '#B7BDC5'
INK = '#22262B'
MUTED = '#59616A'
GRID = '#E5E8EC'
BG = '#FAFAF8'


class Svg:
    def __init__(self, width=1600, height=1000):
        self.width = width
        self.height = height
        self.parts = [
            f'<svg xmlns="http://www.w3.org/2000/svg" '
            f'width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
            '<style>'
            'text{font-family:-apple-system,BlinkMacSystemFont,"PingFang SC",'
            '"Hiragino Sans GB","Microsoft YaHei",Arial,sans-serif;fill:#22262B}'
            '.mono{font-family:ui-monospace,SFMono-Regular,Menlo,monospace}'
            '</style>',
            f'<rect width="{width}" height="{height}" fill="{BG}"/>',
        ]

    def rect(self, x, y, w, h, fill, stroke='none', sw=1, rx=0):
        self.parts.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" '
            f'height="{h:.1f}" rx="{rx}" fill="{fill}" '
            f'stroke="{stroke}" stroke-width="{sw}"/>')

    def line(self, x1, y1, x2, y2, stroke, sw=1, dash=None):
        extra = f' stroke-dasharray="{dash}"' if dash else ''
        self.parts.append(
            f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" '
            f'y2="{y2:.1f}" stroke="{stroke}" stroke-width="{sw}"{extra}/>')

    def circle(self, x, y, r, fill, stroke=INK, sw=1):
        self.parts.append(
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r}" fill="{fill}" '
            f'stroke="{stroke}" stroke-width="{sw}"/>')

    def text(self, x, y, value, size=20, weight=400, fill=INK,
             anchor='start', cls='', opacity=1):
        safe = html.escape(str(value))
        self.parts.append(
            f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" '
            f'font-weight="{weight}" fill="{fill}" text-anchor="{anchor}" '
            f'opacity="{opacity}" class="{cls}">{safe}</text>')

    def finish(self):
        return '\n'.join(self.parts + ['</svg>'])


def main():
    parser = argparse.ArgumentParser(description='绘制新旧 AI 对战图')
    parser.add_argument('csv_path', type=Path)
    parser.add_argument('summary_path', type=Path)
    parser.add_argument('output_path', type=Path)
    args = parser.parse_args()

    with args.csv_path.open(encoding='utf-8') as f:
        rows = list(csv.DictReader(f))
    with args.summary_path.open(encoding='utf-8') as f:
        summary = json.load(f)
    if len(rows) != summary['games']:
        raise ValueError('CSV 盘数与汇总 JSON 不一致')

    svg = Svg()
    config = summary['config']
    svg.text(60, 70, 'Jordan Chess AI：新旧版本对战', 34, 700)
    svg.text(
        60, 108,
        f"{summary['games']} 盘（{summary['pairs']} 组成对开局并交换黑白） · "
        f"{config['size']}×{config['size']} 棋盘 · "
        f"双方每步最多 {config['budget']:.2f} 秒",
        18, fill=MUTED)

    # 左上：总体 100% 堆叠条。
    svg.text(60, 175, '总胜负结果', 24, 700)
    total = summary['games']
    x0, y0, bar_w, bar_h = 60, 215, 700, 94
    segments = [
        ('新 AI 胜', summary['new_wins'], BLUE, '#FFFFFF'),
        ('旧 AI 胜', summary['legacy_wins'], ORANGE, '#FFFFFF'),
        ('平局', summary['draws'], GREY, INK),
    ]
    left = x0
    for label, value, color, text_color in segments:
        width = bar_w * value / total if total else 0
        if width:
            svg.rect(left, y0, width, bar_h, color, INK, 1)
            if width >= 70:
                svg.text(left + width / 2, y0 + 38, label, 18, 700,
                         text_color, 'middle')
                svg.text(left + width / 2, y0 + 68,
                         f'{value} 盘 · {value / total:.0%}', 17, 600,
                         text_color, 'middle', 'mono')
        left += width
    for tick in range(0, total + 1, max(1, total // 4)):
        x = x0 + bar_w * tick / total
        svg.line(x, y0 + bar_h, x, y0 + bar_h + 8, INK)
        svg.text(x, y0 + bar_h + 31, tick, 14, fill=MUTED,
                 anchor='middle', cls='mono')

    # 右上：新旧 AI 执黑/白获胜盘数，四个类别。
    chart_x, chart_y, chart_w, chart_h = 865, 175, 675, 255
    svg.text(chart_x, chart_y, '不同执子颜色下的胜局', 24, 700)
    role_labels = ['新 AI·黑', '新 AI·白', '旧 AI·黑', '旧 AI·白']
    role_values = [summary['new_black_wins'], summary['new_white_wins'],
                   summary['legacy_black_wins'], summary['legacy_white_wins']]
    max_v = max(role_values + [1])
    base_y = chart_y + chart_h
    plot_top = chart_y + 48
    for i in range(4):
        gy = base_y - (base_y - plot_top) * i / 3
        value = max_v * i / 3
        svg.line(chart_x, gy, chart_x + chart_w, gy, GRID)
        svg.text(chart_x - 12, gy + 5, f'{value:.0f}', 13,
                 fill=MUTED, anchor='end', cls='mono')
    gap = chart_w / 4
    for i, (label, value) in enumerate(zip(role_labels, role_values)):
        bar_x = chart_x + i * gap + 34
        height = (base_y - plot_top) * value / max_v
        color = BLUE if i < 2 else ORANGE
        svg.rect(bar_x, base_y - height, gap - 68, height,
                 color, INK, 1)
        svg.text(bar_x + (gap - 68) / 2, base_y - height - 12,
                 value, 18, 700, anchor='middle', cls='mono')
        svg.text(bar_x + (gap - 68) / 2, base_y + 28,
                 label, 15, 600, anchor='middle')

    # 下半：每组成对开局的两盘得分。
    px, py, pw, ph = 90, 535, 1420, 275
    svg.text(60, 490, '每组成对开局的得分', 24, 700)
    svg.text(330, 490, '胜=1，平=0.5，负=0；每组共两盘', 16,
             fill=MUTED)
    for tick in (0, 0.5, 1, 1.5, 2):
        y = py + ph - ph * tick / 2
        svg.line(px, y, px + pw, y, '#7C848D' if tick == 1 else GRID,
                 1.2, '7 6' if tick == 1 else None)
        svg.text(px - 18, y + 5, tick, 14, fill=MUTED,
                 anchor='end', cls='mono')
    pairs = summary['pair_scores']
    count = len(pairs)
    for i, item in enumerate(pairs):
        x = px + (pw * i / (count - 1) if count > 1 else pw / 2)
        new_y = py + ph - ph * item['new_points'] / 2
        old_y = py + ph - ph * item['legacy_points'] / 2
        svg.line(x, new_y, x, old_y, GREY, 3)
        svg.circle(x, new_y, 7, BLUE, INK, 1)
        svg.circle(x, old_y, 7, BG, ORANGE, 3)
        svg.text(x, py + ph + 29, item['pair_id'], 13,
                 fill=MUTED, anchor='middle', cls='mono')
    svg.text(px + pw / 2, py + ph + 66, '成对开局编号', 15,
             fill=MUTED, anchor='middle')

    # 图例与方法说明。
    legend_y = 860
    svg.circle(85, legend_y, 7, BLUE, INK, 1)
    svg.text(103, legend_y + 6, '新 AI', 16, 600)
    svg.circle(195, legend_y, 7, BG, ORANGE, 3)
    svg.text(213, legend_y + 6, '旧 AI', 16, 600)
    svg.line(305, legend_y, 345, legend_y, '#7C848D', 1.2, '7 6')
    svg.text(355, legend_y + 6, '两盘各胜一盘', 16, fill=MUTED)

    svg.text(
        60, 915,
        f"新 AI 总得分率 {summary['new_score_rate']:.1%} · "
        f"需搜索时平均完成深度 {summary['new_avg_completed_depth']:.1f} · "
        f"平均每步 {summary['new_avg_move_seconds']:.3f} 秒；"
        f"旧 AI 平均每步 {summary['legacy_avg_move_seconds']:.3f} 秒。",
        17, 600)
    svg.text(
        60, 953,
        '方法：每组使用完全相同的开局走两盘，并交换新旧 AI 的黑白颜色；'
        '图中所有数值来自随附 CSV 原始逐盘记录。',
        15, fill=MUTED)

    args.output_path.parent.mkdir(parents=True, exist_ok=True)
    args.output_path.write_text(svg.finish(), encoding='utf-8')
    print(args.output_path)


if __name__ == '__main__':
    main()
