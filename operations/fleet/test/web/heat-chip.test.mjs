import test from 'node:test';
import assert from 'node:assert/strict';

// roster-presentation 은 /common·/console/assets 를 import 한다: 단독 node --test 도 그대로 돌게 로더를 먼저 건다.
const { register } = await import('node:module');
register('./common-loader.mjs', import.meta.url);
register('./resolve-console-assets.mjs', import.meta.url);
const { createRosterSummary, heatChip } = await import('../../../../applications/fleet/web/robot/roster-presentation.js');

test('the card shows heat only when CORE slows or stops the robot', () => {
  assert.deepEqual(heatChip({ safety: { thermal: 'warm' } }), ['열: 감속', 'warn']);
  assert.deepEqual(heatChip({ safety: { thermal: 'hot' } }), ['열: 정지', 'crit']);
  assert.equal(heatChip({ safety: { thermal: 'ok' } }), null);
  assert.equal(heatChip({ safety: {} }), null);            // older CORE: no field
  assert.equal(heatChip(undefined), null);
});

test('rendered thermal chips follow robot freshness and recover with fresh state', () => {
  class Node {
    constructor(tag) {
      this.tag = tag; this.children = []; this.dataset = {}; this.classList = { add() {} };
    }
    append(...children) { this.children.push(...children.filter(c => c && typeof c === 'object')); }
    setAttribute() {}
    toggleAttribute() {}
    addEventListener() {}
  }
  const previousDocument = globalThis.document;
  globalThis.document = { createElement: (tag) => new Node(tag) };
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
