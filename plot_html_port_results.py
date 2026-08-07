#!/usr/bin/env python3
"""汇总两个棋盘尺寸的 HTML 迁移版对战，并生成 PNG/SVG。"""

import argparse
import csv
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


COLORS = {
    'ported': '#2563EB',
    'draw': '#D7DCE3',
    'previous': '#E98236',
    'ink': '#172033',
    'muted': '#667085',
    'grid': '#E6EAF0',
    'panel': '#F7F9FC',
    'white': '#FFFFFF',
}


def load_inputs(csv_paths, summary_paths):
    groups = []
    all_rows = []
    for csv_path, summary_path in zip(csv_paths, summary_paths):
        with csv_path.open(encoding='utf-8') as file:
            rows = list(csv.DictReader(file))
        summary = json.loads(summary_path.read_text(encoding='utf-8'))
        if len(rows) != summary['games']:
            raise ValueError(f'{csv_path} 与 {summary_path} 盘数不一致')
        size = summary['config']['size']
        for row in rows:
            row = dict(row)
            row['dataset'] = f'{size}x{size}'
            all_rows.append(row)
        groups.append({
            'label': f'{size}×{size} 棋盘',
            'size': size,
            **summary,
        })
    groups.sort(key=lambda item: item['size'])
    return groups, all_rows


def combined_summary(groups, rows):
    wins = sum(group['ported_wins'] for group in groups)
    losses = sum(group['previous_wins'] for group in groups)
    draws = sum(group['draws'] for group in groups)
    games = wins + losses + draws
    ported_moves = sum(int(row['ported_move_count']) for row in rows)
    previous_moves = sum(int(row['previous_move_count']) for row in rows)
    ported_seconds = sum(float(row['ported_total_seconds']) for row in rows)
    previous_seconds = sum(float(row['previous_total_seconds']) for row in rows)
    ported_nodes = sum(float(row['ported_avg_nodes']) *
                       int(row['ported_move_count']) for row in rows)
    previous_nodes = sum(float(row['previous_avg_nodes']) *
                         int(row['previous_move_count']) for row in rows)
    better = tied = worse = 0
    for group in groups:
        for pair in group['pair_scores']:
            if pair['ported_points'] > pair['previous_points']:
                better += 1
            elif pair['ported_points'] < pair['previous_points']:
                worse += 1
            else:
                tied += 1
    return {
        'label': '两种棋盘合计',
        'games': games,
        'pairs': games // 2,
        'ported_wins': wins,
        'previous_wins': losses,
        'draws': draws,
        'ported_score_rate': (wins + 0.5 * draws) / games,
        'ported_avg_move_seconds': ported_seconds / ported_moves,
        'previous_avg_move_seconds': previous_seconds / previous_moves,
        'ported_avg_nodes': ported_nodes / ported_moves,
        'previous_avg_nodes': previous_nodes / previous_moves,
        'pair_better': better,
        'pair_tied': tied,
        'pair_worse': worse,
        'config': {
            'sizes': [group['size'] for group in groups],
            'budget': groups[0]['config']['budget'],
            'max_depth': groups[0]['config']['max_depth'],
        },
    }


def write_outputs(groups, combined, rows, output_dir):
    all_csv = output_dir / 'html_port_benchmark_all_games.csv'
    with all_csv.open('w', encoding='utf-8', newline='') as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    summary = {'groups': groups, 'combined': combined}
    (output_dir / 'html_port_benchmark_all_summary.json').write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    summary_rows = []
    for item in groups + [combined]:
        summary_rows.append({
            'label': item['label'],
            'games': item['games'],
            'ported_wins': item['ported_wins'],
            'draws': item['draws'],
            'previous_wins': item['previous_wins'],
            'ported_score_rate': item['ported_score_rate'],
            'ported_avg_move_seconds': item['ported_avg_move_seconds'],
            'previous_avg_move_seconds': item['previous_avg_move_seconds'],
            'ported_avg_nodes': item['ported_avg_nodes'],
            'previous_avg_nodes': item['previous_avg_nodes'],
        })
    with (output_dir / 'html_port_benchmark_summary.csv').open(
            'w', encoding='utf-8', newline='') as file:
        writer = csv.DictWriter(file, fieldnames=list(summary_rows[0]))
        writer.writeheader()
        writer.writerows(summary_rows)


def svg_chart(items, combined, output_path):
    width, height = 1600, 960
    bar_x, bar_w, bar_h = 430, 850, 74
    ys = (300, 440, 580)
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="1600" height="960" fill="#FFFFFF"/>',
        '<style>text{font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif;fill:#172033}.mono{font-family:ui-monospace,SFMono-Regular,Menlo,monospace}</style>',
        '<text x="95" y="82" font-size="42" font-weight="700">HTML 迁移版 Python AI 对战结果</text>',
        (f'<text x="95" y="127" font-size="21" fill="#667085">'
         f'{combined["games"]} 局（{combined["pairs"]} 组成对开局并交换黑白）｜8×8 与 10×10 棋盘｜每步 {combined["config"]["budget"]:.2f} 秒｜最大 {combined["config"]["max_depth"]} 层</text>'),
        '<rect x="95" y="168" width="1410" height="70" rx="16" fill="#F7F9FC"/>',
        '<circle cx="135" cy="203" r="10" fill="#2563EB"/><text x="157" y="210" font-size="20">迁移版胜</text>',
        '<circle cx="315" cy="203" r="10" fill="#D7DCE3"/><text x="337" y="210" font-size="20">平局</text>',
        '<circle cx="445" cy="203" r="10" fill="#E98236"/><text x="467" y="210" font-size="20">旧 Python 胜</text>',
        '<text x="1440" y="210" text-anchor="end" font-size="20" fill="#667085">迁移版得分率 =（胜 + 0.5×平）/ 总局</text>',
    ]
    for item, y in zip(items, ys):
        parts.append(f'<text x="95" y="{y+45}" font-size="24" font-weight="600">{item["label"]}</text>')
        x = bar_x
        for kind, count, label in (
                ('ported',item['ported_wins'],'胜'),
                ('draw',item['draws'],'和'),
                ('previous',item['previous_wins'],'负')):
            seg = bar_w * count / item['games']
            if seg:
                parts.append(f'<rect x="{x:.2f}" y="{y}" width="{seg:.2f}" height="{bar_h}" fill="{COLORS[kind]}"/>')
                color = '#172033' if kind == 'draw' else '#FFFFFF'
                if seg >= 58:
                    parts.append(f'<text x="{x+seg/2:.2f}" y="{y+46}" text-anchor="middle" font-size="22" font-weight="700" fill="{color}">{label}{count}</text>')
            x += seg
        parts.append(f'<rect x="{bar_x}" y="{y}" width="{bar_w}" height="{bar_h}" fill="none" stroke="#172033"/>')
        parts.append(f'<text x="1325" y="{y+28}" font-size="18" fill="#667085">迁移版得分率</text>')
        parts.append(f'<text class="mono" x="1325" y="{y+60}" font-size="27" font-weight="700">{item["ported_score_rate"]*100:.1f}%</text>')
    parts.extend([
        '<rect x="95" y="700" width="690" height="118" rx="18" fill="#F7F9FC" stroke="#E6EAF0"/>',
        '<text x="128" y="739" font-size="21" font-weight="700">成对开局结果</text>',
        f'<text x="128" y="779" font-size="25" font-weight="700" fill="#2563EB">提高 {combined["pair_better"]} 组</text>',
        f'<text x="345" y="779" font-size="22" fill="#667085">持平 {combined["pair_tied"]} 组</text>',
        f'<text x="542" y="779" font-size="22" fill="#E98236">降低 {combined["pair_worse"]} 组</text>',
        '<rect x="815" y="700" width="690" height="118" rx="18" fill="#F7F9FC" stroke="#E6EAF0"/>',
        '<text x="848" y="739" font-size="21" font-weight="700">平均每步耗时</text>',
        f'<text x="848" y="779" font-size="24" font-weight="700" fill="#2563EB">迁移版 {combined["ported_avg_move_seconds"]:.3f} 秒</text>',
        f'<text x="1120" y="779" font-size="22" fill="#E98236">旧版 {combined["previous_avg_move_seconds"]:.3f} 秒</text>',
        '<text x="95" y="875" font-size="21" font-weight="700">结果摘要</text>',
        f'<text x="95" y="910" font-size="20" fill="#667085">两种棋盘上迁移版均领先；合计 {combined["ported_wins"]} 胜、{combined["draws"]} 和、{combined["previous_wins"]} 负，得分率 {combined["ported_score_rate"]*100:.1f}%。</text>',
        '<text x="95" y="942" font-size="16" fill="#667085">注：这是等时间加速赛；结果证明方向改善，但仍需更长时间预算和更多开局继续验证。</text>',
        '</svg>',
    ])
    output_path.write_text('\n'.join(parts), encoding='utf-8')


def font(size, bold=False):
    for path in ('/System/Library/Fonts/PingFang.ttc',
                 '/System/Library/Fonts/STHeiti Medium.ttc'):
        try:
            return ImageFont.truetype(path, size=size, index=1 if bold else 0)
        except OSError:
            pass
    return ImageFont.load_default()


def png_chart(items, combined, output_path):
    image = Image.new('RGB', (1600, 960), COLORS['white'])
    draw = ImageDraw.Draw(image)
    title, subtitle = font(42, True), font(21)
    body, label = font(20), font(24, True)
    value, score = font(22, True), font(27, True)
    small, heading = font(16), font(21, True)
    draw.text((95,48),'HTML 迁移版 Python AI 对战结果',font=title,fill=COLORS['ink'])
    sub=(f'{combined["games"]} 局（{combined["pairs"]} 组成对开局并交换黑白）｜'
         f'8×8 与 10×10 棋盘｜每步 {combined["config"]["budget"]:.2f} 秒｜'
         f'最大 {combined["config"]["max_depth"]} 层')
    draw.text((95,108),sub,font=subtitle,fill=COLORS['muted'])
    draw.rounded_rectangle((95,168,1505,238),radius=16,fill=COLORS['panel'])
    for x,color,text_value in ((135,COLORS['ported'],'迁移版胜'),
                               (315,COLORS['draw'],'平局'),
                               (445,COLORS['previous'],'旧 Python 胜')):
        draw.ellipse((x-10,193,x+10,213),fill=color)
        draw.text((x+22,187),text_value,font=body,fill=COLORS['ink'])
    draw.text((1035,187),'迁移版得分率 =（胜 + 0.5×平）/ 总局',
              font=body,fill=COLORS['muted'])
    bar_x,bar_w,bar_h=430,850,74
    for item,y in zip(items,(300,440,580)):
        draw.text((95,y+18),item['label'],font=label,fill=COLORS['ink'])
        x=bar_x
        for kind,count,prefix in (('ported',item['ported_wins'],'胜'),
                                  ('draw',item['draws'],'和'),
                                  ('previous',item['previous_wins'],'负')):
            seg=bar_w*count/item['games']
            if seg:
                draw.rectangle((x,y,x+seg,y+bar_h),fill=COLORS[kind])
                text_value=f'{prefix}{count}'
                box=draw.textbbox((0,0),text_value,font=value)
                if seg>=58:
                    draw.text((x+seg/2-(box[2]-box[0])/2,
                               y+bar_h/2-(box[3]-box[1])/2-3),
                              text_value,font=value,
                              fill=COLORS['ink'] if kind=='draw' else COLORS['white'])
            x+=seg
        draw.rectangle((bar_x,y,bar_x+bar_w,y+bar_h),outline=COLORS['ink'])
        draw.text((1325,y+7),'迁移版得分率',font=body,fill=COLORS['muted'])
        draw.text((1325,y+37),f'{item["ported_score_rate"]*100:.1f}%',
                  font=score,fill=COLORS['ink'])
    draw.rounded_rectangle((95,700,785,818),radius=18,
                           fill=COLORS['panel'],outline=COLORS['grid'])
    draw.text((128,719),'成对开局结果',font=heading,fill=COLORS['ink'])
    draw.text((128,765),f'提高 {combined["pair_better"]} 组',font=label,fill=COLORS['ported'])
    draw.text((345,768),f'持平 {combined["pair_tied"]} 组',font=body,fill=COLORS['muted'])
    draw.text((542,768),f'降低 {combined["pair_worse"]} 组',font=body,fill=COLORS['previous'])
    draw.rounded_rectangle((815,700,1505,818),radius=18,
                           fill=COLORS['panel'],outline=COLORS['grid'])
    draw.text((848,719),'平均每步耗时',font=heading,fill=COLORS['ink'])
    draw.text((848,765),f'迁移版 {combined["ported_avg_move_seconds"]:.3f} 秒',
              font=label,fill=COLORS['ported'])
    draw.text((1135,768),f'旧版 {combined["previous_avg_move_seconds"]:.3f} 秒',
              font=body,fill=COLORS['previous'])
    draw.text((95,858),'结果摘要',font=heading,fill=COLORS['ink'])
    result=(f'两种棋盘上迁移版均领先；合计 {combined["ported_wins"]} 胜、'
            f'{combined["draws"]} 和、{combined["previous_wins"]} 负，'
            f'得分率 {combined["ported_score_rate"]*100:.1f}%。')
    draw.text((95,895),result,font=body,fill=COLORS['muted'])
    draw.text((95,929),'注：这是等时间加速赛；结果证明方向改善，但仍需更长时间预算和更多开局继续验证。',
              font=small,fill=COLORS['muted'])
    image.save(output_path)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--csv',type=Path,action='append',required=True)
    parser.add_argument('--summary',type=Path,action='append',required=True)
    parser.add_argument('--output-dir',type=Path,required=True)
    args=parser.parse_args()
    if len(args.csv)!=len(args.summary):
        raise ValueError('--csv 与 --summary 数量必须相同')
    args.output_dir.mkdir(parents=True,exist_ok=True)
    groups,rows=load_inputs(args.csv,args.summary)
    combined=combined_summary(groups,rows)
    write_outputs(groups,combined,rows,args.output_dir)
    items=groups+[combined]
    svg_chart(items,combined,args.output_dir/'html_port_benchmark.svg')
    png_chart(items,combined,args.output_dir/'html_port_benchmark.png')


if __name__=='__main__':
    main()
