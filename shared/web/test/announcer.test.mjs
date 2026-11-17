// C25 announcer: one polite + one assertive region per document, change-only, throttled, urgent never delayed.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {createAnnouncer, getAnnouncer} from '../announcer.js';

function fakeDoc() {
  const regions = [];
  return {
    regions,
    createElement: () => {
      const attrs = {};
      return {className: '', textContent: '', setAttribute: (k, v) => { attrs[k] = v; }, attrs};
    },
    body: {append: (el) => regions.push(el)},
  };
}
function clock() {
  let t = 10000, queue = [];
  return {
    now: () => t,
    setTimer: (fn, ms) => { queue.push({at: t + ms, fn}); return queue.length; },
    clearTimer: () => { queue = []; },
    advance(ms) { t += ms; const due = queue.filter((q) => q.at <= t); queue = queue.filter((q) => q.at > t); due.forEach((q) => q.fn()); },
  };
}
const polite = (doc) => doc.regions.find((r) => r.attrs.role === 'status');
const assertive = (doc) => doc.regions.find((r) => r.attrs.role === 'alert');

test('regions are created lazily, once, and the singleton is reused per document', () => {
  const doc = fakeDoc();
  const a = getAnnouncer(doc);
  assert.equal(getAnnouncer(doc), a);
  assert.equal(doc.regions.length, 0);
  a.announce('하나'); a.announce('긴급', {urgent: true}); a.announce('둘', {urgent: true});
  assert.equal(doc.regions.length, 2);
  assert.equal(polite(doc).attrs['aria-live'], 'polite');
  assert.equal(assertive(doc).attrs['aria-live'], 'assertive');
  assert.notEqual(getAnnouncer(fakeDoc()), a);
});

test('polite text is change-only and the first one is written at once', () => {
  const doc = fakeDoc(), c = clock();
  const a = createAnnouncer(doc, c);
  a.announce('연결됨');
  assert.equal(polite(doc).textContent, '연결됨');
  c.advance(5000);
  a.announce('연결됨');
  assert.equal(polite(doc).textContent, '연결됨');
  a.announce('   ');
  a.announce('끊김');
  assert.equal(polite(doc).textContent, '끊김');
});

test('polite updates inside the throttle window wait, the newest wins, and an unchanged result is dropped', () => {
  const doc = fakeDoc(), c = clock();
  const a = createAnnouncer(doc, {...c, throttleMs: 2000});
  a.announce('A');
  c.advance(500);
  a.announce('B'); a.announce('C');
  assert.equal(polite(doc).textContent, 'A');
  c.advance(1400);
  assert.equal(polite(doc).textContent, 'A');
  c.advance(200);
  assert.equal(polite(doc).textContent, 'C');
  a.announce('D'); a.announce('C');  // back to the text on screen before the window ends: nothing to say
  c.advance(2500);
  assert.equal(polite(doc).textContent, 'C');
});

test('urgent is never delayed or dropped, even inside the window and when repeated', () => {
  const doc = fakeDoc(), c = clock();
  const writes = [];
  const a = createAnnouncer(doc, c);
  a.announce('상태');
  a.announce('비상정지', {urgent: true});
  assert.equal(assertive(doc).textContent, '비상정지');
  const region = assertive(doc);
  Object.defineProperty(region, 'textContent', {get: () => '', set: (v) => writes.push(v)});
  a.announce('비상정지', {urgent: true});
  assert.deepEqual(writes, ['', '비상정지']);  // cleared then written: re-read
  assert.equal(polite(doc).textContent, '상태');  // the polite region is untouched by urgent
});
