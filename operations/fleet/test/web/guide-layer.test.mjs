// D-540 4: the site map and the 관제 map draw the same /guide marks; the view turn rotates them.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {guideMarks, poseLabel} from '../../fleet/server/web/shared/guide-layer.js';
import {fitView} from '../../fleet/server/web/shared/site-map-model.js';

const MAP = {places: [{id: 'A', x: 0, y: 0}, {id: 'B', x: 2, y: 1.2}], edges: []};
const GUIDE = {robots: [
  {robot_id: 'rosy_01', online: true, body_radius_m: 0.1, worst: 'warn', findings: [{severity: 'warn', target: {x: 1, y: 1, yaw: 0}}],
   pose: {x: 2, y: 0.6, yaw: Math.PI / 2, u_m: 0.05, state: 'LOCALIZED'}},
  {robot_id: 'rosy_02', online: true, body_radius_m: 0.1, worst: null, findings: [], pose: null},
  {robot_id: 'rosy_03', online: false, body_radius_m: 0.1, worst: 'info', findings: [],
   pose: {x: 0.5, y: 0, yaw: null, u_m: 0.2, state: 'DEGRADED'}},
]};
const points = turn => { const view = fitView(MAP, 800, 480, 24, turn); return (x, y) => { const [px, py] = view.toPx(x, y); return {x: px, y: py}; }; };

test('placed robots only, in guide order, at the map pose', () => {
  const toPoint = points(0);
  const marks = guideMarks(GUIDE, toPoint);
  assert.deepEqual(marks.map(m => [m.row.robot_id, m.index]), [['rosy_01', 0], ['rosy_03', 2]]);
  assert.deepEqual(marks[0].p, toPoint(2, 0.6));
  assert.ok(marks[0].ring > marks[0].r && marks[0].r >= 4);
  assert.equal(marks[0].alert, 'warn');
  assert.equal(marks[1].alert, '');            // info is not an alert
  assert.equal(marks[1].tip, null);            // no yaw, no heading
  assert.deepEqual(marks[0].target.q, toPoint(1, 1));
  assert.deepEqual(guideMarks(null, toPoint), []);
});

test('view turn rotates positions and heading clockwise on screen', () => {
  const [a0, b0] = guideMarks(GUIDE, points(0));
  const [a90, b90] = guideMarks(GUIDE, points(90));
  const unit = (p, q) => { const d = Math.hypot(q.x - p.x, q.y - p.y); return [(q.x - p.x) / d, (q.y - p.y) / d]; };
  const near = (u, v) => assert.ok(Math.abs(u[0] - v[0]) < 1e-9 && Math.abs(u[1] - v[1]) < 1e-9, `${u} vs ${v}`);
  const [hx, hy] = unit(a0.p, a0.tip);
  near(unit(a0.p, a0.tip), [0, -1]);           // yaw +90° = +y = up at turn 0
  near(unit(a90.p, a90.tip), [-hy, hx]);       // up turns to right
  const [dx, dy] = unit(a0.p, b0.p);
  near(unit(a90.p, b90.p), [-dy, dx]);
});

test('chip text names the robot and its uncertainty', () => {
  assert.equal(poseLabel(GUIDE.robots[0]), 'rosy_01 · ±0.05 m');
  assert.equal(poseLabel(GUIDE.robots[1]), 'rosy_02 · 위치 모름');
  assert.equal(poseLabel(GUIDE.robots[2]), 'rosy_03 · ±0.20 m · 추정');
});

test('fitView keeps robot rings inside the view at every turn', () => {
  const discs = [{x: -0.5, y: 0.6, r: 0.3}, {x: 2.4, y: 1.5, r: 0.2}];
  for (const turn of [0, 90, 180, 270]) {
    const view = fitView(MAP, 800, 480, 24, turn, discs);
    for (const {x, y, r} of discs) {
      const [px, py] = view.toPx(x, y), rpx = r * view.scale;
      assert.ok(px - rpx >= 23.9 && px + rpx <= 776.1 && py - rpx >= 23.9 && py + rpx <= 456.1, `${turn} ${x},${y}`);
    }
  }
});
