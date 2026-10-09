import test from 'node:test';
import assert from 'node:assert/strict';
import {drawTrails, mapPose, mergePath, pathQuery, tripFor} from '../../fleet/server/web/trail-view.js';
import {quarterTurn} from '../../fleet/server/web/site-layer.js';

const LOCALIZED = {state: 'LOCALIZED', pose_frame: 'map'};
const at = (x, y, id = 'a', localization = LOCALIZED) => [{robot_id: id, state: {pose: {x, y, yaw: 0}, localization}}];
const pt = (t, x, state = 'LOCALIZED', seg = 0) => ({t, x, y: 0, state, seg});
const recordingCtx = () => {
  const lines = [], dashes = [], strokes = [], arcs = [];
  return {lines, dashes, strokes, arcs, save() {}, restore() {}, beginPath() {}, fill() {},
    setLineDash(d) { dashes.push(d); }, moveTo(x, y) { lines.push([x, y]); }, lineTo(x, y) { lines.push([x, y]); },
    arc(x, y) { arcs.push([x, y]); }, stroke() { strokes.push(this.strokeStyle); }};
};

test('only a LOCALIZED map report is a map pose; motor mode (localization null) may be odom', () => {
  assert.deepEqual(mapPose(at(1, 2)[0]), {x: 1, y: 2, yaw: 0});
  assert.equal(mapPose(at(1, 2, 'a', null)[0]), null);
  assert.equal(mapPose(at(1, 2, 'a', {state: 'LOCALIZED', pose_frame: 'odom'})[0]), null);
  assert.equal(mapPose(at(1, 2, 'a', {state: 'CANDIDATES', pose_frame: 'map'})[0]), null);
});

test('the first page asks for the range, later pages only for what came after the last point', () => {
  assert.equal(pathQuery('120', null, undefined, '120:'), 'last_s=120');
  assert.equal(pathQuery('trip', 'trip 1', undefined, 'trip:trip 1'), 'trip_id=trip%201');
  const entry = {key: '600:', points: [pt(5, 0), pt(9, 1)]};
  assert.equal(pathQuery('600', null, entry, '600:'), 'since=9');
  assert.equal(pathQuery('120', null, entry, '120:'), 'last_s=120');           // another range starts over
  assert.equal(pathQuery('trip', 't', {key: 'trip:t', points: [pt(3, 0)]}, 'trip:t'), 'trip_id=t&since=3');
});

test('pages merge without duplicates and a time range drops what fell out by the server clock', () => {
  let entry = mergePath(undefined, '120:', {now: 200, points: [pt(70, 0), pt(100, 1), pt(150, 2)]}, 120);
  assert.deepEqual(entry.points.map(p => p.t), [100, 150]);
  entry = mergePath(entry, '120:', {now: 230, points: [pt(150, 2), pt(229, 3)]}, 120);
  assert.deepEqual(entry.points.map(p => p.t), [150, 229]);
  entry = mergePath(entry, 'trip:x', {now: 999, points: [pt(1, 0)]}, null);   // a new key replaces
  assert.deepEqual(entry.points.map(p => p.t), [1]);
});

test('this trip is the open one, else the most recent for that robot', () => {
  const trips = {open: [{robot_id: 'b', trip_id: 'b-open', created_at: '2026-10-10T01:00:00Z'}],
    trips: [{robot_id: 'a', trip_id: 'a-old', created_at: '2026-10-09T01:00:00Z'},
      {robot_id: 'a', trip_id: 'a-new', created_at: '2026-10-10T00:00:00Z'}]};
  assert.equal(tripFor(trips, 'a'), 'a-new');
  assert.equal(tripFor(trips, 'b'), 'b-open');
  assert.equal(tripFor(trips, 'c'), null);
});

test('line style is the recorded state and a recording gap is not joined', () => {
  globalThis.window = {RosyPalette: {cssColor: name => name}};
  const ctx = recordingCtx();
  const points = [pt(1, 0), pt(2, 1), pt(3, 2, 'DEGRADED'), pt(4, 3, 'CAMERA_ONLY'), pt(5, 4, 'LOCALIZED', 9)];
  const view = {robots: at(4, 0), colors: ['c'], trailRange: 'trip', paths: new Map([['a', {now: 5, points}]]), watchAge: 0.5};
  drawTrails(ctx, view, (x, y) => ({x, y}), 2);
  assert.deepEqual(ctx.dashes.slice(0, 3), [[], [8, 6], [2, 5]]);
  assert.equal(window.__trailOverlay.segments, 3);
  view.trailHidden = new Set(['a']);
  drawTrails(ctx, view, (x, y) => ({x, y}), 2);
  assert.equal(window.__trailOverlay.segments, 0);
});

test('paths are fetched from Fleet for each shown robot, not built from polled poses', async () => {
  globalThis.window = {RosyPalette: {cssColor: name => name}};
  const asked = [];
  const call = async (url) => {
    asked.push(url);
    return url.startsWith('/api/fleet/robots/') ? {now: 10, points: [pt(9, 0), pt(10, 1)]} : {tethers: []};
  };
  const view = {robots: [...at(5, 5, 'a', null), ...at(1, 1, 'b')], colors: ['c'], trailHidden: new Set(['b'])};
  drawTrails(recordingCtx(), view, (x, y) => ({x, y}), 1, call);
  await new Promise(resolve => setTimeout(resolve, 0));
  assert.deepEqual(asked.filter(u => u.includes('/path')), ['/api/fleet/robots/a/path?last_s=120']);
  assert.deepEqual(view.paths.get('a').points.map(p => p.x), [0, 1]);   // never the polled (odom) 5, 5
});

test('trail and tether draw through the caller projection, so they turn with the map', () => {
  globalThis.window = {RosyPalette: {cssColor: name => name}};
  const ctx = recordingCtx();
  const turn = quarterTurn(90, 100, 50);
  const toPx = (x, y) => turn.point(x, y);
  const view = {robots: at(30, 0), colors: ['robot-colour'], trailRange: '120', watchAge: 0.5,
    paths: new Map([['a', {now: 100, points: [pt(99, 10), pt(100, 30)]}]]),
    tethers: [{robot_id: 'a', anchor_xy: [10, 20], radius_m: 5}]};
  drawTrails(ctx, view, toPx, 1);
  assert.deepEqual(ctx.lines.slice(0, 2), [toPx(10, 0), toPx(30, 0)].map(p => [p.x, p.y]));
  assert.deepEqual(ctx.arcs, [[toPx(10, 20).x, toPx(10, 20).y]]);
  assert.deepEqual(ctx.strokes, ['robot-colour', '--status-warn']); // robot 30 m from anchor: outside
  assert.deepEqual(window.__trailOverlay, {segments: 1, tethers: 1, tripped: [], watchRunning: true});
});

test('an unlocalized robot is never judged outside its tether from a maybe-odom pose', () => {
  globalThis.window = {RosyPalette: {cssColor: name => name}};
  const ctx = recordingCtx();
  const view = {robots: at(30, 0, 'a', null), colors: ['c'], watchAge: 0.5,
    tethers: [{robot_id: 'a', anchor_xy: [10, 20], radius_m: 5}]};
  drawTrails(ctx, view, (x, y) => ({x, y}), 1);
  assert.deepEqual(ctx.strokes, ['--ink-quiet']);
});

test('a D-526 watch trip draws the tether in the danger colour', () => {
  globalThis.window = {RosyPalette: {cssColor: name => name}};
  const ctx = recordingCtx();
  const view = {robots: at(10, 20), colors: ['robot-colour'], watchAge: 0.5,
    tethers: [{robot_id: 'a', anchor_xy: [10, 20], radius_m: 5, watch: {state: 'tripped', trip: 'tether_turn'}}]};
  drawTrails(ctx, view, (x, y) => ({x, y}), 1);
  assert.deepEqual(ctx.strokes, ['--status-crit']); // inside the circle, but the watch stopped it
  assert.deepEqual(window.__trailOverlay.tripped, ['a']);
});

test('a stopped or dead D-526 watch loop draws the tether in the danger colour', () => {
  globalThis.window = {RosyPalette: {cssColor: name => name}};
  for (const watchAge of [null, undefined, 7]) {
    const ctx = recordingCtx();
    const view = {robots: at(10, 20), colors: ['robot-colour'], watchAge,
      tethers: [{robot_id: 'a', anchor_xy: [10, 20], radius_m: 5, watch: {state: 'watching'}}]};
    drawTrails(ctx, view, (x, y) => ({x, y}), 1);
    assert.deepEqual(ctx.strokes, ['--status-crit']);
    assert.equal(window.__trailOverlay.watchRunning, false);
  }
});
