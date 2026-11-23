import test from 'node:test';
import assert from 'node:assert/strict';
import { createRosterSummary, heatChip } from '../../../../applications/fleet/web/roster-presentation.js';

test('the card shows heat only when CORE slows or stops the robot', () => {
  assert.deepEqual(heatChip({ safety: { thermal: 'warm' } }), ['열: 감속', 'warn']);
  assert.deepEqual(heatChip({ safety: { thermal: 'hot' } }), ['열: 정지', 'crit']);
  assert.equal(heatChip({ safety: { thermal: 'ok' } }), null);
  assert.equal(heatChip({ safety: {} }), null);            // older CORE: no field
  assert.equal(heatChip(undefined), null);
});

test('rendered thermal chips follow robot freshness and recover with fresh state', () => {
  class Text {
    constructor(data) { this.nodeType = 3; this.data = String(data ?? ''); this.parentNode = null; }
    get nextSibling() {
      if (!this.parentNode) return null;
      const list = this.parentNode.childNodes;
      return list[list.indexOf(this) + 1] || null;
    }
    get textContent() { return this.data; }
    set textContent(v) { this.data = String(v ?? ''); }
  }
  class Node {
    constructor(tag) {
      this.tag = tag; this.nodeType = 1; this.localName = tag; this.nodeName = tag.toUpperCase();
      this.childNodes = []; this.dataset = {}; this.attrs = {}; this.parentNode = null;
      this.classList = { add() {}, remove() {}, toggle() {} };
    }
    get children() { return this.childNodes.filter((c) => c.nodeType === 1); }
    get firstChild() { return this.childNodes[0] || null; }
    get nextSibling() {
      if (!this.parentNode) return null;
      const list = this.parentNode.childNodes;
      return list[list.indexOf(this) + 1] || null;
    }
    get textContent() { return this.childNodes.map((c) => (c.nodeType === 3 ? c.data : c.textContent)).join(''); }
    set textContent(v) {
      for (const c of this.childNodes) c.parentNode = null;
      this.childNodes = [];
      if (v !== '' && v !== null && v !== undefined) this.appendChild(new Text(v));
    }
    _attach(child, before = null) {
      const node = typeof child === 'string' || typeof child === 'number' ? new Text(child) : child;
      if (node.parentNode) node.parentNode.removeChild(node);
      node.parentNode = this;
      const idx = before ? this.childNodes.indexOf(before) : -1;
      if (idx >= 0) this.childNodes.splice(idx, 0, node);
      else this.childNodes.push(node);
      return node;
    }
    append(...children) { for (const c of children) this._attach(c); }
    appendChild(child) { return this._attach(child); }
    insertBefore(child, before) { return this._attach(child, before || null); }
    removeChild(child) {
      const idx = this.childNodes.indexOf(child);
      if (idx >= 0) { this.childNodes.splice(idx, 1); child.parentNode = null; }
      return child;
    }
    replaceChildren(...children) {
      for (const c of this.childNodes) c.parentNode = null;
      this.childNodes = [];
      for (const c of children) this._attach(c);
    }
    setAttribute(k, v) { this.attrs[k] = String(v); }
    getAttribute(k) { return Object.hasOwn(this.attrs, k) ? this.attrs[k] : null; }
    removeAttribute(k) { delete this.attrs[k]; }
    addEventListener() {}
    removeEventListener() {}
  }
  const previousDocument = globalThis.document;
  globalThis.document = {
    createElement: (tag) => new Node(tag),
    createTextNode: (text) => new Text(text),
  };
  try {
    const view = { colors: ['pink'], receivedAtMs: Date.now() };
    const summary = createRosterSummary({ scope: { guard: (handler) => handler }, view,
      openCard() {}, render() {}, attentionItems: () => [], motorHealth: { summary: () => new Node('span') } });
    const tags = (node) => [...(node.tag === 'ui-tag' ? [node.textContent] : []), ...node.children.flatMap(tags)];
    const unavailable = [
      ['stale', (robot) => { robot.state_age_s = 10; }],
      ['offline', (robot) => { robot.online = false; }],
      ['missing state', (robot) => { robot.state = null; }],
      ['Fleet unavailable', () => { view.stateUnavailable = true; }],
    ];
    for (const [thermal, label] of [['warm', '열: 감속'], ['hot', '열: 정지']]) {
      const robot = { robot_id: 'fixture-robot' };
      const fresh = () => {
        Object.assign(robot, { online: true, state_age_s: 0, state: { safety: { estop: false, thermal } } });
        view.stateUnavailable = false;
        view.receivedAtMs = Date.now();
      };
      for (const [reason, invalidate] of unavailable) {
        fresh();
        assert.ok(tags(summary(robot, 0)).includes(label));
        invalidate(robot);
        const current = tags(summary(robot, 0));
        assert.ok(current.includes('안전 확인 불가'), reason);
        assert.ok(!current.includes(label), `${reason}: old thermal state must not appear current`);
        fresh();
        assert.ok(tags(summary(robot, 0)).includes(label), `${reason}: fresh state recovers`);
      }
    }
  } finally {
    if (previousDocument === undefined) delete globalThis.document;
    else globalThis.document = previousDocument;
  }
});
