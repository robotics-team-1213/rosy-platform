import test from 'node:test';
import assert from 'node:assert/strict';
import { capabilityReason, formationReason, noRobotServesGrid } from '../../fleet/server/web/motion-readiness.js';

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

test('the console skips the map request only when every robot says it serves no grid', () => {
  const manual = {capabilities: {runtime: {mode: 'motor', maps: {occupancy: false}}}};
  assert.equal(noRobotServesGrid([manual, manual]), true);
  assert.equal(noRobotServesGrid([]), false);
  assert.equal(noRobotServesGrid([manual, {capabilities: null}]), false);  // unknown robot: keep asking
  assert.equal(noRobotServesGrid([manual, {capabilities: {runtime: {maps: {occupancy: true}}}}]), false);
});
