import test from 'node:test';
import assert from 'node:assert/strict';
import {
  capabilityReason, chooseConvoyLeader, chooseLeader, formationReason, leaderPathKind, noRobotServesGrid,
} from '../../fleet/server/web/motion-readiness.js';

test('motor runtime explains why autonomous actions are unavailable', () => {
  const caps = {runtime: {mode: 'motor'}, navigation: {goal_navigation: false}};
  assert.match(capabilityReason(caps, 'navigation.goal_navigation'), /수동 주행/);
});

test('unknown and malformed capabilities never enable a new-server action', () => {
  for (const caps of [null, {}, {swarm: 'true'}, {swarm: {follow: 'true'}}]) {
    assert.notEqual(capabilityReason(caps, 'swarm.follow'), '');
  }
  assert.equal(capabilityReason({swarm: {follow: true}}, 'swarm.follow'), '');
  assert.equal(capabilityReason(undefined, 'swarm.follow'), ''); // old Fleet server
});

test('formation checks the selected leader and followers independently', () => {
  const leader = {robot_id: 'one', online: true, capabilities: {swarm: {lead: true}}};
  const follower = {robot_id: 'two', online: true, capabilities: {swarm: {follow: false}}};
  assert.match(formationReason([leader, follower], 'one', ['one', 'two']), /two/);
  follower.capabilities.swarm.follow = true;
  assert.equal(formationReason([leader, follower], 'one', ['one', 'two']), '');
  assert.notEqual(formationReason([leader, follower], 'two', ['one', 'two']), '');
  assert.notEqual(formationReason([leader], 'one', ['one']), '');
  follower.online = false;
  assert.match(formationReason([leader, follower], 'one', ['one', 'two']), /오프라인/);
});

function lead(id, { online = true, can = true, x, y, yaw, frame = 'map', estop = false, line = null, goal = false } = {}) {
  const located = x !== undefined;
  const localization = located ? { state: 'LOCALIZED', pose_frame: frame } : undefined;
  return {
    robot_id: id,
    online,
    capabilities: { swarm: { lead: can }, navigation: { goal_navigation: goal } },
    localization,
    state: {
      safety: { estop },
      pose: located ? { x, y, yaw } : undefined,
      localization,
      line_follow: line ? { mode: line } : undefined,
    },
  };
}

test('the leader is the robot furthest along a shared heading', () => {
  const choice = chooseLeader([
    lead('rosy_02', { x: 0, y: 0, yaw: 0, goal: true }),
    lead('rosy_60', { x: 1, y: 0, yaw: 0.1, goal: true }),
  ]);
  assert.deepEqual(choice, { id: 'rosy_60', by: 'ahead' });
});

test('lane convoy ranks open repeat leaders without requiring formation support', () => {
  const robots = [lead('rosy_40', { can: false }), lead('rosy_41', { can: false }), lead('rosy_1')];
  const leaders = ['rosy_41', 'rosy_40'];
  const guide = { robots: robots.map((robot, i) => ({ robot_id: robot.robot_id,
    pose: { state: 'LOCALIZED', map_id: 'floor', age_s: 0.1, x: i, y: 0, yaw: 0 } })) };
  assert.deepEqual(chooseConvoyLeader(robots, leaders, guide, 'floor'), { id: 'rosy_41', by: 'ahead' });
  guide.robots[1].pose.map_id = 'other';
  assert.deepEqual(chooseConvoyLeader(robots, leaders, guide, 'floor'), { id: 'rosy_40', by: 'number' });
  guide.robots[1].pose.map_id = 'floor';
  guide.robots[1].pose.age_s = 3;
  assert.deepEqual(chooseConvoyLeader(robots, leaders, guide, 'floor'), { id: 'rosy_40', by: 'number' });
  robots[0].online = false;
  assert.equal(chooseConvoyLeader(robots, leaders, guide, 'floor').id, 'rosy_41');
  assert.deepEqual(chooseLeader(robots.slice(0, 2)), { id: '', by: '' });
});

test('a missing direction or a pack within one body uses the smaller robot number', () => {
  assert.deepEqual(chooseLeader([
    lead('rosy_10'), lead('rosy_2'), lead('pinky'),
  ]), { id: 'rosy_2', by: 'number' });
  assert.deepEqual(chooseLeader([
    lead('rosy_09', { x: 0, y: 0, yaw: 0 }),
    lead('rosy_01', { x: 1, y: 0, yaw: Math.PI }),
  ]), { id: 'rosy_01', by: 'number' });
  const tie = chooseLeader([
    lead('rosy_08', { x: 0, y: 0, yaw: 0 }),
    lead('rosy_03', { x: 0.1, y: 0, yaw: 0 }),
  ]);
  assert.deepEqual(tie, { id: 'rosy_03', by: 'number' });
});

test('odom and a robot that cannot lead do not take the front', () => {
  const choice = chooseLeader([
    lead('rosy_01', { x: 5, y: 0, yaw: 0, frame: 'odom' }),
    lead('rosy_02', { online: false, x: 0, y: 0, yaw: 0 }),
    lead('rosy_03', { can: false, x: 4, y: 0, yaw: 0 }),
    lead('rosy_04', { x: 0, y: 0, yaw: 0 }),
    lead('rosy_05', { x: 1, y: 0, yaw: 0 }),
  ]);
  assert.deepEqual(choice, { id: 'rosy_05', by: 'ahead' });
  assert.deepEqual(chooseLeader([]), { id: '', by: '' });
});

test('a leader path is a map goal, or a lane trip when the floor is following a line', () => {
  const ready = lead('rosy_01', { goal: true, estop: false });
  assert.deepEqual(leaderPathKind(ready, { map: true, places: 2 }), { kind: 'goal', reason: '' });
  const lane = lead('rosy_01', { goal: true, line: 'CAMERA_LINE' });
  assert.deepEqual(leaderPathKind(lane, { map: true, places: 2 }), { kind: 'trip', reason: '' });
  assert.match(leaderPathKind(lane, { map: true, places: 0 }).reason, /차선 추종/);
  assert.equal(leaderPathKind(lead('rosy_01', { estop: true }), { map: true }).kind, '');
});

test('the console skips the map request only when every robot says it serves no grid', () => {
  const manual = {capabilities: {runtime: {mode: 'motor', maps: {occupancy: false}}}};
  assert.equal(noRobotServesGrid([manual, manual]), true);
  assert.equal(noRobotServesGrid([]), false);
  assert.equal(noRobotServesGrid([manual, {capabilities: null}]), false);  // unknown robot: keep asking
  assert.equal(noRobotServesGrid([manual, {capabilities: {runtime: {maps: {occupancy: true}}}}]), false);
});
