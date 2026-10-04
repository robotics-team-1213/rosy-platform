import test from 'node:test';
import assert from 'node:assert/strict';
import {createPageScope} from '../../scope.js';

function harness() {
  const events = new EventTarget();
  const timers = new Map();
  let sequence = 0;
  const clock = {
    setInterval(fn, ms) { const id = ++sequence; timers.set(id, {fn, ms}); return id; },
    clearInterval(id) { timers.delete(id); },
    setTimeout(fn, ms) { const id = ++sequence; timers.set(id, {fn, ms}); return id; },
    clearTimeout(id) { timers.delete(id); },
  };
  const scope = createPageScope({events, clock});
  function emit(type, persisted = true) {
    const event = new Event(type);
    Object.defineProperty(event, 'persisted', {value: persisted});
    events.dispatchEvent(event);
  }
  return {scope, timers, emit};
}

test('pagehide cancels the epoch and removes polling and subscriptions', () => {
  const {scope, timers, emit} = harness();
  const target = new EventTarget();
  let actions = 0;
  scope.listen(target, 'click', () => actions++);
  scope.interval(() => actions++, 1000);
  const heldTick = [...timers.values()][0].fn;
  const ticket = scope.capture();
  emit('pagehide');
  assert.equal(ticket.signal.aborted, true);
  assert.equal(ticket.current(), false);
  assert.throws(ticket.check, {name: 'AbortError'});
  assert.equal(timers.size, 0);
  target.dispatchEvent(new Event('click'));
  heldTick();
  assert.equal(actions, 0);
  scope.dispose();
});

test('BFCache restore builds a new epoch and invokes only owner supplied resume work', () => {
  const {scope, timers, emit} = harness();
  const target = new EventTarget();
  let commands = 0;
  let reads = 0;
  scope.listen(target, 'click', () => commands++);
  scope.interval(() => reads++, 1500);
  scope.onResume(() => reads++);
  const old = scope.capture();
  emit('pagehide');
  emit('pageshow', false);
  assert.equal(timers.size, 0);
  emit('pageshow');
  emit('pageshow');
  assert.equal(reads, 1);
  assert.equal(commands, 0);
  assert.equal(old.current(), false);
  assert.equal(scope.capture().current(), true);
  assert.equal(timers.size, 1);
  target.dispatchEvent(new Event('click'));
  assert.equal(commands, 1, 'one new explicit input is dispatched once');
  scope.dispose();
});

test('token invalidation refuses old async results and rearms each resource once', () => {
  const {scope, timers} = harness();
  let cleaned = 0;
  const unregister = scope.onDispose(() => cleaned++);
  const old = scope.capture();
  scope.interval(() => {}, 5000);
  scope.invalidate();
  assert.equal(old.signal.aborted, true);
  assert.equal(old.current(), false);
  assert.equal(scope.capture().current(), true);
  assert.equal(cleaned, 1);
  assert.equal(timers.size, 1);
  unregister();
  scope.dispose();
  assert.equal(cleaned, 1);
});

test('dispose is terminal even if pageshow arrives later', () => {
  const {scope, timers, emit} = harness();
  let resumed = 0;
  scope.interval(() => {}, 1000);
  scope.onResume(() => resumed++);
  scope.dispose();
  scope.dispose();
  emit('pageshow');
  assert.equal(resumed, 0);
  assert.equal(timers.size, 0);
  assert.equal(scope.capture().current(), false);
  assert.throws(() => scope.invalidate(), /disposed/);
});

test('unsubscribing before a restore does not resurrect a listener or poll', () => {
  const {scope, timers, emit} = harness();
  const target = new EventTarget();
  let actions = 0;
  const off = scope.listen(target, 'click', () => actions++);
  const cancel = scope.interval(() => actions++, 1000);
  off();
  cancel();
  emit('pagehide');
  emit('pageshow');
  target.dispatchEvent(new Event('click'));
  assert.equal(timers.size, 0);
  assert.equal(actions, 0);
  scope.dispose();
});

test('dynamic guarded handlers do not require retaining detached elements', () => {
  const {scope, emit} = harness();
  let actions = 0;
  const callback = scope.guard(() => actions++);
  callback();
  emit('pagehide');
  callback();
  assert.equal(actions, 1);
  emit('pageshow');
  callback();
  assert.equal(actions, 1, 'a detached handler from the old epoch stays retired');
  scope.guard(() => actions++)();
  assert.equal(actions, 2);
  scope.dispose();
});

test('a listener absorbs cancellation after an asynchronous user confirmation', async () => {
  const {scope, emit} = harness();
  const target = new EventTarget();
  let release;
  const waiting = new Promise(resolve => { release = resolve; });
  let commands = 0;
  const callback = scope.guard(async () => {
    const task = scope.capture();
    await waiting;
    task.check();
    commands++;
  });
  const pending = callback();
  emit('pagehide');
  release();
  await pending;
  assert.equal(commands, 0);
  scope.dispose();
});

test('pending one-shot callbacks and waits are cancelled rather than replayed on restore', async () => {
  const {scope, timers, emit} = harness();
  let commands = 0;
  scope.timeout(() => commands++, 5000);
  const waiting = scope.sleep(1000);
  emit('pagehide');
  await assert.rejects(waiting, {name: 'AbortError'});
  emit('pageshow');
  assert.equal(timers.size, 0);
  assert.equal(commands, 0);
  scope.dispose();
});

test('external subscriptions are disconnected and reacquired once', () => {
  const {scope, emit} = harness();
  let subscriptions = 0;
  let cleanups = 0;
  scope.subscribe(() => { subscriptions++; return () => cleanups++; });
  emit('pagehide');
  assert.equal(cleanups, 1);
  emit('pageshow');
  assert.equal(subscriptions, 2);
  scope.dispose();
  assert.equal(cleanups, 2);
});
