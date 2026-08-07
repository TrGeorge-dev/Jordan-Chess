#!/usr/bin/env python3
"""Validate V3 tournament data and render PNG/SVG without extra packages."""

import argparse
import csv
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


COLORS = {
    "v3": "#2F67E8", "draw": "#D8DEE8", "current": "#ED7D31",
    "ink": "#172033", "muted": "#647089", "panel": "#F6F8FB",
    "grid": "#E3E7EE", "white": "#FFFFFF",
}


def font(size, bold=False):
    for path in ("/System/Library/Fonts/PingFang.ttc",
                 "/System/Library/Fonts/STHeiti Medium.ttc"):
        try:
            return ImageFont.truetype(path, size=size, index=1 if bold else 0)
        except OSError:
            pass
    return ImageFont.load_default()


def validate(rows, summary):
    assert len(rows) == summary["games"]
    keys = {(row["board_size"], row["pair_id"], row["game_in_pair"])
            for row in rows}
    assert len(keys) == len(rows)
    for size in sorted({row["board_size"] for row in rows}):
        subset = [row for row in rows if row["board_size"] == size]
        for pair_id in sorted({row["pair_id"] for row in subset}):
            pair = [row for row in subset if row["pair_id"] == pair_id]
            assert len(pair) == 2 and pair[0]["opening"] == pair[1]["opening"]
            assert {row["v3_color"] for row in pair} == {"black", "white"}
    wins = sum(row["winner"] == "v3" for row in rows)
    losses = sum(row["winner"] == "current" for row in rows)
    draws = len(rows) - wins - losses
    assert (wins, draws, losses) == (
        summary["v3_wins"], summary["draws"], summary["current_wins"])
    assert abs((wins + .5 * draws) / len(rows)
               - summary["v3_score_rate"]) < 1e-12


def groups(summary):
    return [
        ("8×8 棋盘", summary["size_8"]),
        ("10×10 棋盘", summary["size_10"]),
        ("两种棋盘合计", summary),
    ]


def draw_png(summary, output):
    image = Image.new("RGB", (1600, 960), COLORS["white"])
    draw = ImageDraw.Draw(image)
    title, subtitle = font(42, True), font(21)
    body, label = font(20), font(24, True)
    value, score_font = font(22, True), font(27, True)
    small, heading = font(16), font(21, True)
    draw.text((95, 48), "V3 AI 与修改前默认 AI 的对战结果",
              font=title, fill=COLORS["ink"])
    draw.text((95, 108),
              "48 局（24 组成对开局并交换黑白）｜双方每步最多 0.12 秒",
              font=subtitle, fill=COLORS["muted"])
    draw.rounded_rectangle((95, 168, 1505, 238), radius=16,
                           fill=COLORS["panel"])
    for x, color, text in ((135, COLORS["v3"], "V3 获胜"),
                           (310, COLORS["draw"], "平局"),
                           (430, COLORS["current"], "修改前 AI 获胜")):
        draw.ellipse((x-10, 193, x+10, 213), fill=color)
        draw.text((x+22, 187), text, font=body, fill=COLORS["ink"])
    draw.text((1040, 187), "得分率 =（胜 + 0.5×平）/ 总局",
              font=body, fill=COLORS["muted"])

    bar_x, bar_w, bar_h = 430, 850, 74
    for (name, data), y in zip(groups(summary), (300, 440, 580)):
        draw.text((95, y+18), name, font=label, fill=COLORS["ink"])
        counts = (("v3", data["v3_wins"], "胜"),
                  ("draw", data["draws"], "和"),
                  ("current", data["current_wins"], "负"))
        total = sum(item[1] for item in counts)
        x = bar_x
        for kind, count, prefix in counts:
            width = bar_w * count / total
            if width:
                draw.rectangle((x, y, x+width, y+bar_h), fill=COLORS[kind])
                text = f"{prefix}{count}"
                box = draw.textbbox((0, 0), text, font=value)
                if width >= 58:
                    draw.text((x+width/2-(box[2]-box[0])/2,
                               y+bar_h/2-(box[3]-box[1])/2-3),
                              text, font=value,
                              fill=COLORS["ink"] if kind == "draw"
                              else COLORS["white"])
            x += width
        draw.rectangle((bar_x, y, bar_x+bar_w, y+bar_h),
                       outline=COLORS["ink"])
        draw.text((1320, y+7), "V3 得分率", font=body,
                  fill=COLORS["muted"])
        draw.text((1320, y+37), f"{data['v3_score_rate']:.1%}",
                  font=score_font, fill=COLORS["ink"])

    draw.rounded_rectangle((95, 700, 785, 818), radius=18,
                           fill=COLORS["panel"], outline=COLORS["grid"])
    draw.text((128, 719), "24 组换色开局", font=heading,
              fill=COLORS["ink"])
    draw.text((128, 765), f"占优 {summary['paired_better']} 组",
              font=label, fill=COLORS["v3"])
    draw.text((355, 768), f"持平 {summary['paired_equal']} 组",
              font=body, fill=COLORS["muted"])
    draw.text((555, 768), f"落后 {summary['paired_worse']} 组",
              font=body, fill=COLORS["current"])

    draw.rounded_rectangle((815, 700, 1505, 818), radius=18,
                           fill=COLORS["panel"], outline=COLORS["grid"])
    draw.text((848, 719), "平均完整搜索深度", font=heading,
              fill=COLORS["ink"])
    draw.text((848, 765), f"V3  {summary['v3_avg_depth']:.2f} 层",
              font=label, fill=COLORS["v3"])
    draw.text((1115, 768),
              f"修改前  {summary['current_avg_depth']:.2f} 层",
              font=body, fill=COLORS["current"])

    draw.text((95, 858), "结果摘要", font=heading, fill=COLORS["ink"])
    result = (f"V3 合计 {summary['v3_wins']} 胜、{summary['draws']} 和、"
              f"{summary['current_wins']} 负，得分率 "
              f"{summary['v3_score_rate']:.1%}；两种棋盘均领先。")
    draw.text((95, 895), result, font=body, fill=COLORS["muted"])
    draw.text((95, 929),
              "注：这是等时间加速赛，说明算法方向改善；不是完整 Elo 评级。",
              font=small, fill=COLORS["muted"])
    image.save(output)


def draw_svg(summary, output):
    bar_x, bar_w, bar_h = 430, 850, 74
    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="960">',
        '<rect width="1600" height="960" fill="#fff"/>',
        '<style>text{font-family:-apple-system,BlinkMacSystemFont,"PingFang SC",sans-serif;fill:#172033}</style>',
        '<text x="95" y="82" font-size="42" font-weight="700">V3 AI 与修改前默认 AI 的对战结果</text>',
        '<text x="95" y="127" font-size="21" fill="#647089">48 局（24 组成对开局并交换黑白）｜双方每步最多 0.12 秒</text>',
        '<rect x="95" y="168" width="1410" height="70" rx="16" fill="#F6F8FB"/>',
        '<circle cx="135" cy="203" r="10" fill="#2F67E8"/><text x="157" y="210" font-size="20">V3 获胜</text>',
        '<circle cx="310" cy="203" r="10" fill="#D8DEE8"/><text x="332" y="210" font-size="20">平局</text>',
        '<circle cx="430" cy="203" r="10" fill="#ED7D31"/><text x="452" y="210" font-size="20">修改前 AI 获胜</text>',
    ]
    for (name, data), y in zip(groups(summary), (300, 440, 580)):
        parts.append(f'<text x="95" y="{y+45}" font-size="24" font-weight="700">{name}</text>')
        total = data["v3_wins"] + data["draws"] + data["current_wins"]
        x = bar_x
        for kind, count, prefix in (("v3", data["v3_wins"], "胜"),
                                    ("draw", data["draws"], "和"),
                                    ("current", data["current_wins"], "负")):
            width = bar_w * count / total
            color = COLORS[kind]
            parts.append(f'<rect x="{x:.2f}" y="{y}" width="{width:.2f}" height="{bar_h}" fill="{color}"/>')
            if width >= 58:
                text_color = COLORS["ink"] if kind == "draw" else "#fff"
                parts.append(f'<text x="{x+width/2:.2f}" y="{y+47}" text-anchor="middle" font-size="22" font-weight="700" fill="{text_color}">{prefix}{count}</text>')
            x += width
        parts.append(f'<rect x="{bar_x}" y="{y}" width="{bar_w}" height="{bar_h}" fill="none" stroke="#172033"/>')
        parts.append(f'<text x="1320" y="{y+29}" font-size="20" fill="#647089">V3 得分率</text>')
        parts.append(f'<text x="1320" y="{y+61}" font-size="27" font-weight="700">{data["v3_score_rate"]:.1%}</text>')
    parts.extend([
        '<rect x="95" y="700" width="690" height="118" rx="18" fill="#F6F8FB" stroke="#E3E7EE"/>',
        '<text x="128" y="740" font-size="21" font-weight="700">24 组换色开局</text>',
        f'<text x="128" y="785" font-size="24" font-weight="700" fill="#2F67E8">占优 {summary["paired_better"]} 组</text>',
        f'<text x="355" y="785" font-size="20" fill="#647089">持平 {summary["paired_equal"]} 组</text>',
        f'<text x="555" y="785" font-size="20" fill="#ED7D31">落后 {summary["paired_worse"]} 组</text>',
        '<rect x="815" y="700" width="690" height="118" rx="18" fill="#F6F8FB" stroke="#E3E7EE"/>',
        '<text x="848" y="740" font-size="21" font-weight="700">平均完整搜索深度</text>',
        f'<text x="848" y="785" font-size="24" font-weight="700" fill="#2F67E8">V3 {summary["v3_avg_depth"]:.2f} 层</text>',
        f'<text x="1115" y="785" font-size="20" fill="#ED7D31">修改前 {summary["current_avg_depth"]:.2f} 层</text>',
        '<text x="95" y="880" font-size="21" font-weight="700">结果摘要</text>',
        f'<text x="95" y="917" font-size="20" fill="#647089">V3 合计 {summary["v3_wins"]} 胜、{summary["draws"]} 和、{summary["current_wins"]} 负，得分率 {summary["v3_score_rate"]:.1%}；两种棋盘均领先。</text>',
        '<text x="95" y="947" font-size="16" fill="#647089">注：这是等时间加速赛，说明算法方向改善；不是完整 Elo 评级。</text>',
        '</svg>',
    ])
    output.write_text("\n".join(parts), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("games", type=Path)
    parser.add_argument("summary", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    with args.games.open(encoding="utf-8") as file:
        rows = list(csv.DictReader(file))
    summary = json.loads(args.summary.read_text(encoding="utf-8"))
    validate(rows, summary)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    draw_png(summary, args.output)
    draw_svg(summary, args.output.with_suffix(".svg"))
    print(args.output)


if __name__ == "__main__":
    main()
