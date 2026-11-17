// C25 alert center: the rules (createAlertStore, shouldToast, isOnScreen) and the thin drawing.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {createAlertCenter, createAlertStore, shouldToast, isOnScreen, MAX_ITEMS, MERGE_WINDOW_MS} from '../alert-center.js';

function fakeEl() {
  const el = {children: [], dataset: {}, attrs: {}, listeners: {}, className: '', hidden: false, _text: '',
    get textContent() { return this._text; },
    set textContent(v) { this._text = String(v); },
    setAttribute(k, v) { this.attrs[k] = v; },
    addEventListener(t, fn) { this.listeners[t] = fn; },
    append(...n) { this.children.push(...n); },
    replaceChildren(...n) { this.children = n; }};
  return el;
}
const fakeDoc = () => ({createElement: () => fakeEl()});
function setup({onScreen = true} = {}) {
  const doc = fakeDoc();
  const listEl = fakeEl(), toastEl = fakeEl(), bellEl = fakeEl();
  listEl.ownerDocument = doc;
  const said = [];
  const state = {onScreen};
  const center = createAlertCenter({listEl, toastEl, bellEl, announcer: {announce: (t, o) => said.push([t, !!o?.urgent])}, isOnScreen: () => state.onScreen});
  return {center, listEl, toastEl, bellEl, said, state};
}
const crit = (key, extra = {}) => ({kind: 'crit', key, title: '긴급', message: `${key} 문제`, ...extra});
const keysOf = (el) => el.children.map((c) => c.dataset.alertKey);

test('the same key is one item with a count', () => {
  const s = createAlertStore();
  s.publish(crit('a')); s.publish(crit('a')); s.publish(crit('a'));
  assert.equal(s.getItems().length, 1);
  assert.equal(s.getItems()[0].count, 3);
});

test('items sort safety > crit > warn > info, newest first within a kind', () => {
  const s = createAlertStore();
  for (const [k, kind] of [['i', 'info'], ['w1', 'warn'], ['c1', 'crit'], ['w2', 'warn'], ['s', 'safety'], ['c2', 'crit']]) s.publish({kind, key: k, message: k});
  assert.deepEqual(s.getItems().map((x) => x.key), ['s', 'c2', 'c1', 'w2', 'w1', 'i']);
});

test('a warn that becomes crit moves up and counts as fresh again', () => {
  const s = createAlertStore();
  s.publish({kind: 'crit', key: 'c', message: 'c'});
  s.publish({kind: 'warn', key: 'w', message: 'w'});
  const r = s.publish({kind: 'crit', key: 'w', message: 'w'});
  assert.equal(r.fresh, true);
  assert.deepEqual(s.getItems().map((x) => x.key), ['w', 'c']);
});

test('the cap is 12: the oldest lowest-priority item goes, safety is never dropped for room', () => {
  const s = createAlertStore();
  s.publish({kind: 'safety', key: 's', message: 's'});
  for (let i = 0; i < MAX_ITEMS + 3; i += 1) s.publish({kind: i % 2 ? 'warn' : 'crit', key: `k${i}`, message: 'm'});
  const items = s.getItems();
  assert.equal(items.length, MAX_ITEMS);
  assert.equal(items[0].key, 's');
  const all = createAlertStore({cap: 2});
  for (const k of ['a', 'b', 'c']) all.publish({kind: 'safety', key: k, message: k});
  assert.equal(all.getItems().length, 3);  // only safety left: nothing to drop
});

test('oneShot failures merge inside the 1500 ms window and toast again after it', () => {
  let t = 0;
  const s = createAlertStore({now: () => t});
  const first = s.publish(crit('cmd', {oneShot: true}));
  assert.equal(first.toast, true);
  s.dismissToast('cmd');
  t = MERGE_WINDOW_MS - 1;
  const merged = s.publish(crit('cmd', {oneShot: true}));
  assert.equal(merged.merged, true);
  assert.equal(merged.toast, false);
  assert.equal(s.getToasts().length, 0);
  t = MERGE_WINDOW_MS - 1 + MERGE_WINDOW_MS;
  assert.equal(s.publish(crit('cmd', {oneShot: true})).toast, true);
  const again = s.publish(crit('cmd', {oneShot: true}));  // toast still open: count, no second card
  assert.equal(again.merged, true);
  assert.equal(s.getToasts().length, 1);
  assert.equal(s.getToasts()[0].count, 2);
  assert.equal(s.getItems().length, 0, 'a oneShot failure is not in the list');
});

test('toast rules: only (a) new safety|crit with the list off screen and (b) oneShot safety|crit', () => {
  assert.equal(shouldToast({kind: 'crit', fresh: true, listOnScreen: false}), true);
  assert.equal(shouldToast({kind: 'safety', fresh: true, listOnScreen: false}), true);
  assert.equal(shouldToast({kind: 'crit', fresh: true, listOnScreen: true}), false);
  assert.equal(shouldToast({kind: 'crit', fresh: false, listOnScreen: false}), false);
  assert.equal(shouldToast({kind: 'crit', oneShot: true, listOnScreen: true}), true);
  for (const kind of ['warn', 'info']) {
    for (const oneShot of [false, true]) for (const listOnScreen of [false, true]) assert.equal(shouldToast({kind, oneShot, fresh: true, listOnScreen}), false);
  }
  const s = createAlertStore();
  assert.equal(s.publish({kind: 'warn', key: 'w', message: 'w'}, {listOnScreen: false}).toast, false);
  assert.equal(s.publish({kind: 'info', key: 'i', message: 'i'}, {listOnScreen: false}).toast, false);
  assert.equal(s.publish(crit('c'), {listOnScreen: false}).toast, true);
  assert.equal(s.publish(crit('c'), {listOnScreen: false}).toast, false, 'a repeat is not a new toast');
});

test('resolve closes item, toast and bell count in the same update', () => {
  const {center, listEl, toastEl, bellEl, state} = setup({onScreen: false});
  center.publish(crit('c'));
  assert.deepEqual(keysOf(listEl), ['c']);
  assert.deepEqual(keysOf(toastEl), ['c']);
  assert.equal(bellEl.textContent, '1');
  center.resolve('c');
  assert.deepEqual([keysOf(listEl), keysOf(toastEl), bellEl.textContent], [[], [], '0']);
  assert.equal(state.onScreen, false);
});

test('safety survives resolve until acknowledged; acknowledge closes it and its toast', () => {
  const {center, listEl, toastEl, bellEl} = setup({onScreen: false});
  center.publish({kind: 'safety', key: 'estop', title: '비상정지', message: 'rosy_42 정지'});
  center.resolve('estop');
  assert.deepEqual(keysOf(listEl), ['estop']);
  assert.deepEqual(keysOf(toastEl), ['estop']);
  assert.equal(bellEl.textContent, '1');
  center.acknowledge('estop', '운영자');
  assert.deepEqual([keysOf(listEl), keysOf(toastEl), bellEl.textContent], [[], [], '0']);
  center.publish({kind: 'safety', key: 'estop2', message: 'x'});
  center.acknowledge('estop2', '운영자');  // acknowledged while the condition lasts: still listed, no longer unread
  assert.deepEqual(keysOf(listEl), ['estop2']);
  assert.equal(bellEl.textContent, '0');
  center.resolve('estop2');
  assert.deepEqual(keysOf(listEl), []);
});

test('a list toast closes when the list is back on screen; a oneShot toast stays', () => {
  const {center, toastEl, state} = setup({onScreen: false});
  center.publish(crit('c'));
  center.publish(crit('cmd', {oneShot: true}));
  assert.deepEqual(keysOf(toastEl).sort(), ['c', 'cmd']);
  state.onScreen = true;
  center.syncVisibility();
  assert.deepEqual(keysOf(toastEl), ['cmd']);
});

test('a new safety|crit item is announced once, urgent, even with the list on screen; warn polite; info never', () => {
  const {center, said, toastEl} = setup({onScreen: true});
  center.publish(crit('c'));
  center.publish(crit('c'));
  center.publish({kind: 'safety', key: 's', title: '안전', message: '정지'});
  center.publish({kind: 'warn', key: 'w', title: '주의', message: '배터리'});
  center.publish({kind: 'info', key: 'i', message: '안내'});
  assert.deepEqual(said, [['긴급: c 문제', true], ['안전: 정지', true], ['주의: 배터리', false]]);
  assert.equal(toastEl.children.length, 0);
});

test('a oneShot failure is announced once and a merged repeat is not', () => {
  const {center, said} = setup();
  center.publish(crit('cmd', {oneShot: true}));
  center.publish(crit('cmd', {oneShot: true}));
  assert.equal(said.length, 1);
});

test('the toast region has no aria-live and unread counts items not yet acknowledged', () => {
  const {center, toastEl, listEl, bellEl} = setup({onScreen: false});
  center.publish(crit('a')); center.publish({kind: 'warn', key: 'b', message: 'b'});
  assert.equal(toastEl.attrs['aria-live'], undefined);
  assert.equal(toastEl.attrs.role, undefined);
  assert.equal(bellEl.dataset.count, '2');
  assert.equal(listEl.children.length, 2);
  center.acknowledge('b');
  assert.equal(bellEl.dataset.count, '1');
});

test('repeat publishes keep the same card node (no focus-losing rebuild)', () => {
  const {center, listEl} = setup();
  center.publish(crit('a'));
  const node = listEl.children[0];
  center.publish(crit('a'));
  assert.equal(listEl.children[0], node);
  assert.equal(node.children[0].children[2].textContent, '×2');
});

test('isOnScreen needs overlap with every clipping rect', () => {
  const rect = {top: 10, bottom: 50, left: 0, right: 100};
  assert.equal(isOnScreen(rect, [{top: 0, bottom: 100, left: 0, right: 100}]), true);
  assert.equal(isOnScreen(rect, [{top: 60, bottom: 100, left: 0, right: 100}]), false);
  assert.equal(isOnScreen(rect, []), false);
  assert.equal(isOnScreen(null, [{top: 0, bottom: 1, left: 0, right: 1}]), false);
});
