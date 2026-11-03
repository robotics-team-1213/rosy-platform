import test from 'node:test';
import assert from 'node:assert/strict';
import { heatChip } from '../../../../applications/fleet/web/roster-presentation.js';

test('the card shows heat only when CORE slows or stops the robot', () => {
  assert.deepEqual(heatChip({ safety: { thermal: 'warm' } }), ['열: 감속', 'warn']);
  assert.deepEqual(heatChip({ safety: { thermal: 'hot' } }), ['열: 정지', 'crit']);
  assert.equal(heatChip({ safety: { thermal: 'ok' } }), null);
  assert.equal(heatChip({ safety: {} }), null);            // older CORE: no field
  assert.equal(heatChip(undefined), null);
});
