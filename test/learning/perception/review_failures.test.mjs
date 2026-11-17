import test from 'node:test';
import assert from 'node:assert/strict';
import {createFailureTracker} from '../../../learning/curation/perception/review_app_web/review-failures.js';

function tracker(options) {
  const log = [];
  return {log, t: createFailureTracker((m) => log.push(['show', m]), () => log.push(['clear']), options)};
}

test('one healthy endpoint does not close the alert while another still fails', () => {
  const {log, t} = tracker();
  t.fail('/api/a', 'boom');
  t.fail('/api/b', 'boom b');
  t.recover('/api/accounts/options');  // never failed: no effect
  assert.equal(t.down(), true);
  t.recover('/api/a');
  assert.equal(t.down(), true);
  assert.deepEqual(log.at(-1), ['show', 'boom b']);  // the remaining failure's text takes over
  t.recover('/api/b');
  assert.equal(t.down(), false);
  assert.deepEqual(log.at(-1), ['clear']);
});

test('the same failure repeated by polling publishes once', () => {
  const {log, t} = tracker();
  for (let i = 0; i < 5; i++) t.fail('/api/a', 'boom');
  assert.deepEqual(log, [['show', 'boom']]);
});

test('recovering an endpoint that never failed does nothing', () => {
  const {log, t} = tracker();
  t.recover('/api/a');
  assert.deepEqual(log, []);
});

test('a one-shot failure that never repeats stops pinning the alert after the ttl, a polled one does not', () => {
  let clock = 0;
  const {log, t} = tracker({ttlMs: 1000, now: () => clock});
  t.fail('/api/once', 'once');
  t.fail('/api/poll', 'poll');
  clock = 900; t.fail('/api/poll', 'poll');
  clock = 1500; t.recover('/api/healthy');
  assert.equal(t.down(), true);  // /api/once expired, /api/poll still failing
  assert.deepEqual(log.at(-1), ['show', 'poll']);
  clock = 1600; t.recover('/api/poll');
  assert.equal(t.down(), false);
  assert.deepEqual(log.at(-1), ['clear']);
});
