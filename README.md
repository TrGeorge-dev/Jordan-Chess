# 约当棋 (Jordan Chess)

基于**八连通闭环**的双人零和棋。同色棋子（含斜向相邻）形成内部含格点的闭合折线即获胜。

## 规则（ADR-0001：八连通；ADR-0002：环内含格点）

| 项目 | 规则 |
|---|---|
| 棋盘 | N×N 方格 → (N+1)×(N+1) 格点，默认 10×10（可自定义 2~30），棋子落在交叉点上 |
| 行棋 | 黑先白后，轮流在空白格点放 1 枚己方棋子；棋子不可移动 |
| 连通 | 上下左右**及斜对角**相邻均视为连通（八连通，切比雪夫距离 1） |
| 闭环 | 顶点互异的闭合折线：相邻点八连通、至少 4 个顶点、允许斜边交叉，**且环内包含 ≥1 个格点**（4 子方格/X 形内部无格点，无效；4 子斜菱形有效） |
| **胜负** | **落子形成含格点闭环即立即获胜**，无需包围对方棋子 |
| 平局 | 棋盘下满且从未成环 |
| 悔棋 | 可撤销任意步 |

最短获胜：黑方第 4 手用 4 枚棋子形成斜菱形（内部恰有 1 个格点）即可获胜；对手可以通过抢占关键格点阻止闭环。

## 文件

```
jordan-chess/
├── engine.py        核心引擎（纯 Python，无依赖）—— 棋盘/连通性/环路检测/胜负结算/悔棋
├── ai.py            默认导出 V3 AI，并保留旧版 AI 供回归对战
├── ai_v3.py         增量连通状态 + PVS 搜索核心（Python）
├── cli.py           命令行版（python3 cli.py [大小] [--ai]）
├── gui.py           pygame 图形界面版（pip install pygame，python3 gui.py [大小]）
├── index.html       浏览器版（单文件，自适应移动端，含 AI）
├── test_engine.py   引擎自测（python3 test_engine.py [-v]）
├── test_ai.py       AI 自测（python3 test_ai.py [-v]）
├── test_ai_v3.py    V3 数学状态、撤销、威胁与搜索专项测试
├── test_browser_ai.mjs  浏览器 AI 无头自测（Node.js，可选）
├── test_cross_language_ai.py  Python/HTML 逐项同步测试
├── benchmark_ai.py  新旧 AI 成对换色对战，输出 CSV/JSON
├── benchmark_html_port.py  HTML 迁移版与旧 Python AI 成对换色对战
├── benchmark_v3.py  V3 与修改前默认 AI 的多棋盘换色对战
├── plot_benchmark.py 对战数据生成 SVG 图（无第三方依赖）
├── plot_html_port_results.py  多棋盘对战汇总并生成 PNG/SVG
├── html_ai_bridge.mjs  测试时调用 index.html 真实 AI
└── README.md
```

浏览器版：双击 index.html 即可(无需安装, 推荐分享方式)

## Python 开发环境

项目使用本地 `.venv` 隔离测试与绘图依赖；虚拟环境本身不会提交到 Git，
可通过依赖清单在任意电脑重建：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
```

退出虚拟环境时运行 `deactivate`。

## AI 对手（人机对战）

**启动方式**
```bash
# 命令行: 人类执黑先手, AI 执白
python3 cli.py --ai             # 10×10, 默认你执黑
python3 cli.py --ai white      # 你执白(后手), AI 执黑先走
python3 cli.py 13 --ai       # 13×13; 局内按 a 可切换 人机/双人

# pygame 版: 底部 [AI:OFF] 按钮切换人机模式
python3 gui.py --ai          # 或运行时点按钮

# 浏览器版: 点「人机」+「执黑/执白」选边；点「AI-AI」观看自动对弈
```

**AI 算法**（V3 `JordanAI` 在 Python/HTML 中保持同步）

威胁体系（成环 = 落子形成内部含格点的有效闭环）：
- **T1 一步威胁**：某空点落子即成环。AI 必走/必堵（永不错过直接胜负）。
- **T2 两步威胁**：落子后产生 1 个 T1，迫使对手应对（争夺先手）。
- **fork 双威胁**：落子后产生 ≥2 个 T1。对手只能堵一个 → **两步内必胜**；AI 会主动制造 fork 并抢占对手的 fork 点。

V3 使用可撤销并查集增量维护双方连通分量，先快速筛出可能成环的落点，再用射线法和有预算的绕行路径搜索精确验证“环内含格点”。T2/fork 会在可撤销的模拟局面上再次精确过滤，避免把单位方格等无效小环当作威胁。

决策使用迭代加深 PVS（主变搜索）：第一条主变化使用完整窗口，其余走法先用窄窗口验证，必要时再重新搜索。置换表复用重复局面，历史启发和杀手走法改善剪枝顺序，深度边界仍有强制威胁时进行有限战术延伸。所有战术点都会进入候选集合，普通走法才受宽度限制；超时只丢弃未完成层。

威胁判定核心：同分量邻居只代表“可能形成图上的环”；只有找到至少 4 个顶点、且内部包含格点的闭合路径才算有效 T1。Python 与浏览器版默认最多搜索 12 层，并保持中间分析结果一致。修改前的实现保留为 `HybridJordanAI` / `ThreatJordanAI`，仅用于回归对战。

AI-AI 观赏模式会为每盘生成独立种子，只在评分接近的非强制候选中引入变化；变化度在开局较高并随手数衰减。立即获胜、唯一防守等强制战术不随机，人机模式也保持确定性。

**自测**：`python3 test_ai.py` 10 项，`python3 -m unittest test_ai_v3.py -v` 11 项；浏览器 AI 可用 `node test_browser_ai.mjs` 运行 7 项无头测试（包含精确 T2/fork、路径颜色过滤、绕行闭环、受控变化、AI-AI 自动落子及暂停检查）。`python3 test_cross_language_ai.py` 会核对两端的立即胜点、后续威胁映射、评价特征、候选顺序和固定深度搜索结果。

**新旧 AI 对战与可视化**：每个开局走两盘并交换黑白，双方使用相同单步时间上限，避免先手优势误导结果。

```bash
python3 benchmark_ai.py --pairs 20 --budget 0.08 --output-dir benchmark-output
python3 plot_benchmark.py benchmark-output/ai_benchmark_games.csv \
  benchmark-output/ai_benchmark_summary.json benchmark-output/ai_benchmark.svg
```

输出包括逐盘 CSV、汇总 JSON 和可直接用浏览器打开的 SVG 图。

HTML 迁移版 Python AI 与迁移前 Python AI 的换色对战：

```bash
python3 benchmark_html_port.py --pairs 12 --size 10 --budget 0.12 \
  --output-dir benchmark-output
```

V3 与修改前默认 AI 的多棋盘换色对战：

```bash
python3 benchmark_v3.py --pairs 12 --sizes 8,10 --budget 0.12 \
  --output-dir benchmark-v3
python3 plot_v3_results.py benchmark-v3/v3_games.csv \
  benchmark-v3/v3_summary.json benchmark-v3/v3_results.png
```

算法选择、失败方案和消融实验记录见 `AI_RESEARCH.md`。

## 启动方式

```bash
# 命令行版（任意环境）—— 棋盘大小可选(2~30, 默认 10), --ai 人机模式
python3 cli.py [棋盘大小] [--ai]   # 例: python3 cli.py 13 --ai
# 输入 "x y" 落子，如 "5 5"；a 人机/双人切换；u 悔棋；n 新局(保持大小)；
# n 13 以 13×13 开新局；q 退出

# 图形界面版（需 pygame）—— 棋盘大小可选
pip install pygame
python3 gui.py [棋盘大小]
# 鼠标点击格点落子；[◀][▶] 调整棋盘大小(自动开新局)；[AI] 人机模式；
# Undo 悔棋；New 新局

# 浏览器版
# 直接用浏览器打开 index.html；顶部"棋盘"输入框可改大小(2~30)，点"新局"生效；
# 点「人机」与 AI 对战；点「AI-AI」让两个 V3 AI 自动对弈，再点一次暂停
```

## 引擎 API

```python
from engine import JordanChess, BLACK, WHITE

g = JordanChess(size=13)       # 自定义棋盘: 13×13 方格 → 14×14 格点(默认 10)
r = g.place(5, 5)              # 落子 → {'ok', 'reason', 'color', 'loops', 'winner'}
g.get(x, y)                    # 查询格点：EMPTY(0)/BLACK(1)/WHITE(2)
g.undo()                       # 悔棋
g.moves()                      # 枚举全部合法落子点
g.history                      # 历史 [(x, y, color), ...]
g.last_loops                   # 上一步形成的闭环（顶点坐标有序序列，UI 高亮用）
```

## 核心算法说明

**1. 环路检测**：新落子 v 必然位于所有新形成的环上。枚举 v 的八连通同色邻居对（至多 C(8,2)=28 对），先在去掉 v 的图中用 BFS 找最短路径；若该小环内部没有格点，再用带路径长度、候选数和总步数预算的 DFS 补找绕行路径，避免短弦遮住外围有效环。

**2. 射线法（Ray Casting）**：`_point_in_polygon` 使用半开区间规则 `(y1>py)!=(y2>py)` 防止顶点重复计数；引擎会扫描环的包围盒，确认至少一个非环顶点格点位于内部。

**3. 性能**：引擎和 AI 都先用邻居数/并查集做必要条件预筛，仅对可能成环的位置执行几何搜索；搜索层使用缓存、置换表和超时回滚保证给定预算内返回合法落子。

## 自测

```bash
python3 test_engine.py -v    # 27 项：落子规则/含格点闭环/绕行补找/多环检出/射线法/悔棋/平局/
                             #       自定义棋盘大小(2/3/5/8/12/非法值)/随机对局/性能
```

测试覆盖：单位方格/X 形无效、斜菱形与 2×2 大环有效、短弦不遮挡外围有效环、真实回合下黑方第 4 手获胜、环内棋子不移除、带尾巴/贴边/多环、射线法、悔棋、平局、自定义尺寸、随机对局不变式及密集棋盘性能。
