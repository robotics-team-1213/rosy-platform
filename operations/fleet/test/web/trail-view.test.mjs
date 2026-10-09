import test from 'node:test';
import assert from 'node:assert/strict';
import {recordTrails, drawTrails, TRAIL_MAX, TRAIL_S} from '../../fleet/server/web/trail-view.js';
import {quarterTurn} from '../../fleet/server/web/site-layer.js';

const at = (x, y, id = 'a') => [{robot_id: id, state: {pose: {x, y, yaw: 0}}}];

test('a trail point needs 1 cm of travel', () => {
  const trails = new Map();
  recordTrails(trails, at(0, 0), 0);
  recordTrails(trails, at(0.005, 0), 1000);
  recordTrails(trails, at(0.012, 0), 2000);
  assert.deepEqual(trails.get('a').map(p => p.x), [0, 0.012]);
});

test('odom-frame poses never join the map trail', () => {
  const trails = new Map();
  const odom = [{robot_id: 'a', state: {pose: {x: 1, y: 1}, localization: {pose_frame: 'odom'}}}];
  recordTrails(trails, at(0, 0), 0);
  recordTrails(trails, odom, 1000);
  assert.deepEqual(trails.get('a').map(p => p.x), [0]);
});

test('the trail keeps the last 120 s and at most 600 points; a dropped robot loses its trail', () => {
  const trails = new Map();
  for (let i = 0; i <= TRAIL_MAX + 50; i += 1) recordTrails(trails, at(i * 0.02, 0), i);
  assert.equal(trails.get('a').length, TRAIL_MAX);
  recordTrails(trails, at(100, 0), TRAIL_MAX + 50 + TRAIL_S * 1000 + 1);
  assert.equal(trails.get('a').length, 1);
  recordTrails(trails, [], 0);
  assert.equal(trails.size, 0);
});

test('trail and tether draw through the caller projection, so they turn with the map', () => {
  globalThis.window = {RosyPalette: {cssColor: name => name}};
  const lines = [], arcs = [], strokes = [];
  const ctx = {save() {}, restore() {}, beginPath() {}, setLineDash() {}, fill() {},
    moveTo(x, y) { lines.push([x, y]); }, lineTo(x, y) { lines.push([x, y]); },
    arc(x, y) { arcs.push([x, y]); }, stroke() { strokes.push(this.strokeStyle); }};
  const turn = quarterTurn(90, 100, 50);
  const toPx = (x, y) => turn.point(x, y);
  const now = Date.now();
  const view = {robots: at(30, 0), colors: ['robot-colour'], trails: new Map([['a', [{x: 10, y: 0, t: now}]]]), watchAge: 0.5,
    tethers: [{robot_id: 'a', anchor_xy: [10, 20], radius_m: 5}]};
  drawTrails(ctx, view, toPx, 1);
  assert.deepEqual(lines.slice(0, 2), [toPx(10, 0), toPx(30, 0)].map(p => [p.x, p.y]));
  assert.deepEqual(arcs, [[toPx(10, 20).x, toPx(10, 20).y]]);
  assert.deepEqual(strokes, ['robot-colour', '--status-warn']); // robot 30 m from anchor: outside
  assert.deepEqual(window.__trailOverlay, {segments: 1, tethers: 1, tripped: [], watchRunning: true});
});

test('a D-526 watch trip draws the tether in the danger colour', () => {
  globalThis.window = {RosyPalette: {cssColor: name => name}};
  const strokes = [];
  const ctx = {save() {}, restore() {}, beginPath() {}, setLineDash() {}, fill() {}, moveTo() {}, lineTo() {},
    arc() {}, stroke() { strokes.push(this.strokeStyle); }};
  const view = {robots: at(10, 20), colors: ['robot-colour'], trails: new Map(), watchAge: 0.5,
    tethers: [{robot_id: 'a', anchor_xy: [10, 20], radius_m: 5, watch: {state: 'tripped', trip: 'tether_turn'}}]};
  drawTrails(ctx, view, (x, y) => ({x, y}), 1);
  assert.deepEqual(strokes, ['--status-crit']); // inside the circle, but the watch stopped it
  assert.deepEqual(window.__trailOverlay.tripped, ['a']);
});

test('a stopped or dead D-526 watch loop draws the tether in the danger colour', () => {
  globalThis.window = {RosyPalette: {cssColor: name => name}};
  for (const watchAge of [null, undefined, 7]) {
    const strokes = [];
    const ctx = {save() {}, restore() {}, beginPath() {}, setLineDash() {}, fill() {}, moveTo() {}, lineTo() {},
      arc() {}, stroke() { strokes.push(this.strokeStyle); }};
    const view = {robots: at(10, 20), colors: ['robot-colour'], trails: new Map(), watchAge,
      tethers: [{robot_id: 'a', anchor_xy: [10, 20], radius_m: 5, watch: {state: 'watching'}}]};
    drawTrails(ctx, view, (x, y) => ({x, y}), 1);
    assert.deepEqual(strokes, ['--status-crit']);
    assert.equal(window.__trailOverlay.watchRunning, false);
  }
});
