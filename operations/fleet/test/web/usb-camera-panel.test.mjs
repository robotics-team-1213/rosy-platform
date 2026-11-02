import test from 'node:test';
import assert from 'node:assert/strict';
import { decisionBody, suggestionText } from '../../../../applications/fleet/web/installation/usb-camera.js';

test('a decision carries only a valid role name, trimmed', () => {
  assert.deepEqual(decisionBody(' arm_b_wrist '), {role: 'arm_b_wrist'});
  for (const bad of ['', '1top', 'a b', '../x', 'x'.repeat(65), null, 7]) assert.equal(decisionBody(bad), null);
});

test('the suggestion says where it came from', () => {
  assert.equal(suggestionText({suggest: null, roles: ['a']}), '');
  assert.match(suggestionText({suggest: 'arm_a_wrist', hub_arm: 'arm_a', roles: []}), /같은 USB 허브의 팔/);
  assert.match(suggestionText({suggest: 'top', hub_arm: null, roles: ['top']}), /같은 모델이 빠진 역할/);
});
