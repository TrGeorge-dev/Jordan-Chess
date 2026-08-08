#!/usr/bin/env node
// 浏览器 AI 无头回归测试。运行: node test_browser_ai.mjs

import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {performance} from 'node:perf_hooks';

const html = fs.readFileSync(new URL('./index.html', import.meta.url), 'utf8');
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];
const core = script.split('// ================= 界面 =================')[0] +
  '\nglobalThis.__jordan = {JordanChess, JordanAI, LegacyJordanAI, BLACK, WHITE, EMPTY};';
const context = vm.createContext({console, performance});
vm.runInContext(core, context, {filename: 'index.html'});
const {JordanChess, JordanAI, LegacyJordanAI, BLACK, WHITE, EMPTY} =
  context.__jordan;

function sameMove(a, b) {
  return a[0] === b[0] && a[1] === b[1];
}

// 用户报告的“三子一排”陷阱：一侧已封，必须占住另一侧的双将点。
{
  const game = new JordanChess(10);
  for (const [x,y] of [[4,4],[5,4],[6,4]]) game.board[x][y] = BLACK;
  game.board[5][3] = WHITE;
  game.turn = WHITE;
  game.history = [[4,4,BLACK],[5,3,WHITE],[5,4,BLACK],[0,0,WHITE],[6,4,BLACK]];
  const ai = new JordanAI(game, WHITE, 0.2, 8, 1);
  assert.ok(sameMove(ai.chooseMove(), [5,5]));
}

// 立即获胜。
{
  const game = new JordanChess(10);
  game.board[2][2] = BLACK;
  game.board[2][3] = BLACK;
  game.board[3][3] = BLACK;
  const ai = new JordanAI(game, BLACK, 0.1, 6, 1);
  assert.ok(sameMove(ai.chooseMove(), [3, 2]));
}

// 单邻居延伸 T2：旧版漏掉，新版必须识别。
{
  const game = new JordanChess(5);
  const black = [[2,1],[1,1],[0,1],[0,2],[0,3],[0,4],[1,4],[2,4]];
  const white = [[1,2],[1,3]];
  for (const [x,y] of black) game.board[x][y] = BLACK;
  for (const [x,y] of white) game.board[x][y] = WHITE;
  const ai = new JordanAI(game, BLACK, 0.2, 6, 1);
  ai.deadline = performance.now() + 1000;
  ai._prepare();
  const t2 = [...ai._tacticalMap(BLACK).entries()]
    .filter(item => item[1].length === 1).map(item => ai.state.xy(item[0]));
  assert.ok(t2.some(move => sameMove(move, [2,2])));
  const old = new LegacyJordanAI(game, BLACK, 0.2, 3, 1);
  const [oldT2, oldForks] = old._t2AndForks(BLACK);
  assert.ok(!oldT2.concat(oldForks).some(move => sameMove(move, [2,2])));
}

// 多 fork 防守：新版比较后选择 (1,0)，旧版任取 (0,1)。
{
  const game = new JordanChess(4);
  const history = [[0,0],[2,2],[3,1],[2,3],[2,0],[0,3],[3,3],
                   [4,2],[1,1],[4,3],[4,4],[4,0],[1,2]];
  for (const move of history) {
    const result = game.place(...move);
    assert.equal(result.winner, null);
  }
  const before = JSON.stringify(game.board);
  const ai = new JordanAI(game, WHITE, 0.4, 8, 1);
  assert.ok(sameMove(ai.chooseMove(), [1,0]));
  assert.equal(JSON.stringify(game.board), before);
  const old = new LegacyJordanAI(game, WHITE, 0.2, 3, 1);
  assert.ok(sameMove(old.chooseMove(), [0,1]));
}

// 极短预算也必须恢复全部模拟棋子。
{
  const game = new JordanChess(10);
  for (const move of [[5,5],[4,5],[5,6],[4,6]]) game.place(...move);
  const before = JSON.stringify(game.board);
  const ai = new JordanAI(game, game.turn, 0.01, 20, 1);
  const move = ai.chooseMove();
  assert.equal(JSON.stringify(game.board), before);
  assert.equal(game.board[move[0]][move[1]], EMPTY);
}

console.log('浏览器 AI: 5 项测试全部通过');
