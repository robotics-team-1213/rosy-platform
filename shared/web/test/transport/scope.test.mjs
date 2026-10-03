import test from 'node:test';
import assert from 'node:assert/strict';
import {createScope} from '../../scope.js';
import {createRequest} from '../../request.js';

test('dispose aborts one scope and cleans subscriptions exactly once', () => {
  const scope = createScope();
  const calls = [];
  scope.onDispose(() => calls.push('timer'));
  scope.onDispose(() => calls.push('subscription'));
  assert.equal(scope.signal.aborted, false);
  scope.dispose();
  scope.dispose();
  assert.equal(scope.signal.aborted, true);
  assert.deepEqual(calls, ['timer', 'subscription']);
});

test('unregistering a cleanup removes it and late registrations are cleaned immediately', () => {
  const scope = createScope();
  let calls = 0;
  const remove = scope.onDispose(() => calls++);
  remove();
  remove();
  scope.dispose();
  assert.equal(calls, 0);
  scope.onDispose(() => calls++);
  assert.equal(calls, 1);
});

test('a queued handler cannot issue another request or repaint after disposal', () => {
  const scope = createScope();
  let polls = 0;
  const handler = scope.guard(() => ++polls);
  assert.equal(handler(), 1);
  scope.dispose();
  assert.equal(handler(), undefined);
  assert.equal(polls, 1);
});

test('generation change rejects an older result and disposal rejects every result', () => {
  const scope = createScope();
  const old = scope.capture();
  assert.equal(scope.isCurrent(old), true);
  const latest = scope.advance();
  assert.equal(scope.isCurrent(old), false);
  assert.equal(scope.isCurrent(latest), true);
  scope.dispose();
  assert.equal(scope.isCurrent(latest), false);
  assert.throws(() => scope.advance(), /disposed/);
});

test('one failing cleanup does not prevent the remaining cleanup or abort', () => {
  const scope = createScope();
  const failure = new Error('cleanup failed');
  let second = false;
  scope.onDispose(() => { throw failure; });
  scope.onDispose(() => { second = true; });
  assert.throws(() => scope.dispose(), error => error instanceof AggregateError && error.errors[0] === failure);
  assert.equal(second, true);
  assert.equal(scope.signal.aborted, true);
  scope.dispose();
});

test('scope disposal rejects a late network result while another scope stays independent', async () => {
  const first = createScope();
  const second = createScope();
  const finishes = [];
  const request = createRequest({origin: 'https://robot.test',
    fetchImpl: () => new Promise(resolve => finishes.push(resolve))});
  const a = request('/state', {signal: first.signal});
  const b = request('/state', {signal: second.signal});
  first.dispose();
  for (const finish of finishes) finish(new Response(JSON.stringify({done: true}), {status: 200}));
  await assert.rejects(a, {name: 'AbortError'});
  assert.deepEqual(await b, {status: 200, ok: true, body: {done: true}});
  assert.equal(second.signal.aborted, false);
  second.dispose();
});
