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

// 对手已有唯一有效斜菱形威胁，必须占住闭环点。
{
  const game = new JordanChess(10);
  for (const [x,y] of [[5,4],[4,5],[6,5]]) game.board[x][y] = BLACK;
  game.board[0][0] = WHITE;
  game.turn = WHITE;
  game.history = [[5,4,BLACK],[0,0,WHITE],[4,5,BLACK],[0,1,WHITE],[6,5,BLACK]];
  const ai = new JordanAI(game, WHITE, 0.2, 8, 1);
  assert.ok(sameMove(ai.chooseMove(), [5,6]));
}

// 立即完成含一个内部格点的斜菱形。
{
  const game = new JordanChess(10);
  game.board[2][1] = BLACK;
  game.board[1][2] = BLACK;
  game.board[3][2] = BLACK;
  const ai = new JordanAI(game, BLACK, 0.1, 6, 1);
  assert.ok(sameMove(ai.chooseMove(), [2, 3]));
}

// T2/fork 增量图必须与逐手模拟的精确含格点环判定一致。
{
  const game = new JordanChess(5);
  for (const [x,y] of [[2,2],[2,3],[3,3]]) game.board[x][y] = BLACK;
  const ai = new JordanAI(game, BLACK, 5, 6, 1);
  ai.deadline = performance.now() + 5000;
  ai._prepare();
  const fast = [...ai._tacticalMap(BLACK).entries()];
  const brute = [];
  for (const move of ai.state.frontierMoves()) {
    const token = ai.state.play(move, BLACK);
    let wins;
    try { wins = ai.state.winningMoves(BLACK, 3); }
    finally { ai.state.undo(token); }
    if (wins.length) brute.push([move, wins]);
  }
  assert.equal(JSON.stringify(fast), JSON.stringify(brute));
}

// 单位方格无效；中心弦也不能遮住外围有效斜菱形。
{
  const square = new JordanChess(2);
  for (const [x,y] of [[0,0],[0,1],[1,1]]) square.board[x][y] = BLACK;
  square.turn = BLACK;
  assert.equal(square.place(1,0).winner, null);

  const detour = new JordanChess(2);
  for (const [x,y] of [[1,0],[1,1],[1,2],[2,1]]) detour.board[x][y] = BLACK;
  detour.turn = BLACK;
  assert.equal(detour.place(0,1).winner, BLACK);

  const blocked = new JordanChess(2);
  blocked.board[0][0] = blocked.board[0][2] = BLACK;
  blocked.board[0][1] = WHITE;
  const ai = new JordanAI(blocked, BLACK, 1, 2, 1);
  ai.deadline = performance.now() + 1000; ai._prepare();
  assert.equal(ai.state.bfsPath(0, 2, 8, BLACK), null);
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

// 观赏模式随机性可复现、不同种子有变化，且不会覆盖强制胜着。
{
  const opening = seed => {
    const game = new JordanChess(30);
    return new JordanAI(game, BLACK, 0.2, 0, seed, 0.9).chooseMove().join(",");
  };
  assert.equal(opening(17), opening(17));
  assert.ok(new Set(Array.from({length:8},(_,i)=>opening(i+1))).size >= 3);

  const forced = new JordanChess(5);
  for (const [x,y] of [[2,1],[1,2],[3,2]]) forced.board[x][y] = BLACK;
  assert.ok(sameMove(new JordanAI(forced, BLACK, 0.2, 8, 99, 1).chooseMove(), [2,3]));
}

// AI-AI 界面模式：两个颜色必须自动轮流落子，暂停后旧计时器不得继续走。
{
  class FakeElement {
    constructor() {
      this.listeners = new Map(); this.style = {}; this.textContent = '';
      this.value = '10'; this.width = 0; this.height = 0;
      const classes = new Set();
      this.classList = {
        add: name => classes.add(name),
        remove: name => classes.delete(name),
        toggle: (name, force) => force === undefined
          ? (classes.has(name) ? (classes.delete(name), false) : (classes.add(name), true))
          : (force ? classes.add(name) : classes.delete(name), force),
        contains: name => classes.has(name),
      };
    }
    addEventListener(type, listener) { this.listeners.set(type, listener); }
    click() { this.listeners.get('click')?.({}); }
    getBoundingClientRect() { return {left:0, top:0, width:660, height:660}; }
  }
  const elements = Object.fromEntries(
    ['board','status','size','new','undo','ai','aivai','side']
      .map(id => [id, new FakeElement()]));
  const drawing = new Proxy({}, {get: () => () => {}});
  drawing.setTransform = drawing.clearRect = drawing.beginPath = drawing.moveTo =
    drawing.lineTo = drawing.stroke = drawing.fillText = drawing.closePath =
    drawing.fill = drawing.arc = () => {};
  elements.board.getContext = () => drawing;
  const timers = [];
  const schedule = callback => {
    const task = {callback, cancelled:false};
    timers.push(task); return task;
  };
  const runNextTimer = () => {
    const task = timers.shift();
    if (task && !task.cancelled) task.callback();
  };
  const workers = [];
  class FakeWorker {
    constructor() { this.terminated = false; this.request = null; workers.push(this); }
    postMessage(request) {
      this.request = request;
      schedule(() => {
        if (this.terminated) return;
        let move = null;
        outer: for (let x=0;x<request.board.length;x++)
          for (let y=0;y<request.board.length;y++)
            if (request.board[x][y] === EMPTY) { move=[x,y]; break outer; }
        this.onmessage?.({data:{id:request.id, ok:true, move,
          historyScores:request.historyScores}});
      });
    }
    terminate() { this.terminated = true; }
  }
  const uiContext = vm.createContext({
    console, performance,
    window:{devicePixelRatio:1, innerWidth:800, addEventListener:()=>{}},
    document:{currentScript:{textContent:script}, getElementById:id => elements[id]},
    Blob:class {},
    URL:{createObjectURL:()=>"blob:test-ai-worker", revokeObjectURL:()=>{}},
    Worker:FakeWorker,
    setTimeout:schedule,
    clearTimeout:task => { if (task) task.cancelled = true; },
  });
  vm.runInContext(script + `\n;globalThis.__ui = {
    JordanAI, BLACK, WHITE,
    getGame: () => game, getMode: () => gameMode,
    MODE_AI_AI, workerSource:AI_WORKER_SOURCE
  };`, uiContext, {filename:'index.html'});
  const workerMessages = [];
  const workerSelf = {postMessage:message => workerMessages.push(message)};
  const workerContext = vm.createContext({console, performance, self:workerSelf});
  vm.runInContext(uiContext.__ui.workerSource, workerContext,
    {filename:'jordan-ai-worker.js'});
  workerSelf.onmessage({data:{
    id:99, size:4,
    board:Array.from({length:5},()=>Array(5).fill(EMPTY)),
    turn:BLACK, history:[], color:BLACK,
    timeBudget:0.02, maxDepth:4, seed:1, historyScores:null,
  }});
  assert.equal(workerMessages[0].ok, true);
  assert.equal(workerMessages[0].id, 99);
  assert.equal(workerMessages[0].move.length, 2);

  // 在 Worker 已开始思考、尚未返回结果时点击暂停，必须立即终止且不落子。
  elements.aivai.click();
  assert.equal(uiContext.__ui.getMode(), uiContext.__ui.MODE_AI_AI);
  assert.ok(elements.aivai.classList.contains('on'));
  runNextTimer();
  assert.equal(workers.length, 1);
  assert.ok(workers[0].request.variety > 0);
  assert.ok(Number.isInteger(workers[0].request.seed));
  elements.aivai.click();
  while (timers.length) runNextTimer();
  assert.equal(workers[0].terminated, true);
  assert.equal(uiContext.__ui.getGame().history.length, 0);
  assert.equal(elements.aivai.textContent, 'AI-AI');

  // 恢复后仍能由黑、白两个 AI 连续各下一步。
  elements.aivai.click();
  for (let i=0;i<4;i++) runNextTimer();
  assert.deepEqual(
    Array.from(uiContext.__ui.getGame().history, move => move[2]),
    [uiContext.__ui.BLACK, uiContext.__ui.WHITE]);
  elements.aivai.click();
  const moveCount = uiContext.__ui.getGame().history.length;
  while (timers.length) runNextTimer();
  assert.equal(uiContext.__ui.getGame().history.length, moveCount);
  assert.equal(elements.aivai.textContent, 'AI-AI');
}

console.log('浏览器 AI: 7 项测试全部通过');
