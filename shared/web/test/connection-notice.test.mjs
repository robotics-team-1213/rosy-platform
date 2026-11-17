// C7 (R2-01): createConnectionNotice makes its element a polite live region unless the caller already chose one.
// connection-notice.js pulls ui.js (custom elements + document wiring) at import time, so the minimal DOM that
// import touches is stubbed before the dynamic import — static imports would run first and miss the stubs.
import {test} from 'node:test';
import assert from 'node:assert/strict';

globalThis.HTMLElement = class {};
globalThis.Element = class {};
globalThis.customElements = {get: () => undefined, define() {}};
globalThis.MutationObserver = class {observe() {} disconnect() {}};
globalThis.window = {addEventListener() {}};
globalThis.document = {addEventListener() {}, querySelectorAll: () => [], documentElement: {}, body: {}};

const {createConnectionNotice} = await import('../connection-notice.js');

function fakeElement(attributes = {}) {
  const attrs = new Map(Object.entries(attributes));
  return {
    dataset: {}, firstElementChild: null, textContent: '',
    hasAttribute: name => attrs.has(name),
    getAttribute: name => attrs.get(name) ?? null,
    setAttribute(name, value) { attrs.set(name, String(value)); },
    removeAttribute: name => attrs.delete(name),
    replaceChildren(...nodes) { this.firstElementChild = nodes[0] ?? null; this.textContent = String(nodes[0] ?? ''); },
  };
}

test('a plain element becomes a polite status region', () => {
  const element = fakeElement();
  createConnectionNotice(element);
  assert.equal(element.getAttribute('role'), 'status');
  assert.equal(element.getAttribute('aria-live'), 'polite');
});

test('a caller that already set a role or aria-live keeps it', () => {
  const alert = fakeElement({role: 'alert'});
  createConnectionNotice(alert);
  assert.equal(alert.getAttribute('role'), 'alert');
  assert.equal(alert.getAttribute('aria-live'), null);

  const assertive = fakeElement({'aria-live': 'assertive'});
  createConnectionNotice(assertive);
  assert.equal(assertive.getAttribute('role'), null);
  assert.equal(assertive.getAttribute('aria-live'), 'assertive');
});
