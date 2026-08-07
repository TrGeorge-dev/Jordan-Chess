#!/usr/bin/env node
// 从 Python 测试/基准调用 index.html 中的真实 AI（JSON Lines 协议）。

import fs from 'node:fs';
import readline from 'node:readline';
import vm from 'node:vm';
import {performance} from 'node:perf_hooks';

const html = fs.readFileSync(new URL('./index.html', import.meta.url), 'utf8');
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];
const core = script.split('// ================= 界面 =================')[0] +
  '\nglobalThis.__jordan = {JordanChess, JordanAI, LegacyJordanAI, BLACK, WHITE, EMPTY};';
const context = vm.createContext({console, performance});
vm.runInContext(core, context, {filename:'index.html'});
const {JordanChess, JordanAI} = context.__jordan;

function makeGame(request) {
  const game = new JordanChess(request.size);
  game.board = request.board.map(row => row.slice());
  game.turn = request.turn;
  game.history = (request.history || []).map(item => item.slice());
  return game;
}

function analyze(request) {
  const game = makeGame(request);
  const ai = new JordanAI(game, request.color,
    request.budget ?? 2.0, request.maxDepth ?? 8, request.seed ?? 1);
  ai.deadline = performance.now() + 30000;
  ai._prepare();
  const mine = ai._tacticalMap(request.color);
  const opp = request.color === 1 ? 2 : 1;
  const theirs = ai._tacticalMap(opp);
  const mapping = map => [...map.entries()].map(([move,wins]) =>
    [ai.state.xy(move), wins.map(point => ai.state.xy(point))]);
  return {
    threats:ai._winningMoves(request.color).map(move => ai.state.xy(move)),
    tactical:mapping(mine),
    opponentTactical:mapping(theirs),
    moves:ai._orderedMoves(request.color, 1, 0, false, null, true)
      .map(move => ai.state.xy(move)),
    evaluation:ai._evaluate(request.color),
    features:(()=>{const f=ai._features(request.color); return [
      f.forks,f.t2,f.mergePoints,f.frontierEdges,f.componentSquare,
      f.largestComponent,f.openSquareOne,f.openSquareTwo,f.center];})(),
  };
}

function fixedDepth(request) {
  const game = makeGame(request);
  const ai = new JordanAI(game, request.color, 30, request.depth, request.seed ?? 1);
  ai.deadline = performance.now() + 30000;
  ai._prepare();
  const moves = ai._orderedMoves(request.color, 1, 0, false, null, true);
  if (!moves.length) return {move:null, score:0};
  const result = ai._searchRoot(request.depth, moves);
  return {move:ai.state.xy(result[0]), score:result[1]};
}

function choose(request) {
  const game = makeGame(request);
  const ai = new JordanAI(game, request.color,
    request.budget ?? 2.0, request.maxDepth ?? 8, request.seed ?? 1);
  const before = JSON.stringify(game.board);
  const move = ai.chooseMove();
  if (JSON.stringify(game.board) !== before)
    throw new Error('HTML AI 搜索后没有恢复棋盘');
  return {move, stats:ai.lastStats};
}

function handle(request) {
  if (request.op === 'analyze') return analyze(request);
  if (request.op === 'fixed_depth') return fixedDepth(request);
  return choose(request);
}

const lines = readline.createInterface({input:process.stdin, crlfDelay:Infinity});
for await (const line of lines) {
  if (!line.trim()) continue;
  let request;
  try {
    request = JSON.parse(line);
    process.stdout.write(JSON.stringify({id:request.id, ok:true,
                                         result:handle(request)}) + '\n');
  } catch (error) {
    process.stdout.write(JSON.stringify({id:request?.id, ok:false,
                                         error:String(error?.stack || error)}) + '\n');
  }
}
