import test from 'node:test';
import assert from 'node:assert/strict';

// B-3 — 셀 팔 예외 줄: createCellObservation의 onSummary 우선순위, 같은 폴링 무음,
// focusArm의 카드 초점, clear()의 즉시 숨김을 지킨다. 가짜 DOM만 쓴다.
import {createCellObservation} from '../../../../applications/fleet/web/cell/cell-observation.js';

function node(tag = '') {
  const element = {
    tagName: tag.toUpperCase(), children: [], parentNode: null, listeners: {}, dataset: {}, attributes: {},
    textContent: '', className: '', hidden: false, open: false, title: '', value: '', classes: new Set(),
    classList: {
      add: (...names) => names.forEach(name => element.classes.add(name)),
      remove: (...names) => names.forEach(name => element.classes.delete(name)),
      toggle: (name, on) => { (on === undefined ? !element.classes.has(name) : on) ? element.classes.add(name) : element.classes.delete(name); },
      contains: name => element.classes.has(name),
    },
    append(...children) { for (const child of children) element.insertBefore(child, null); },
    insertBefore(child, before) {
      child.remove?.();
      const index = before ? element.children.indexOf(before) : element.children.length;
      assert.ok(index >= 0);
      element.children.splice(index, 0, child); child.parentNode = element;
    },
    remove() { if (element.parentNode) element.parentNode.children = element.parentNode.children.filter(c => c !== element); element.parentNode = null; },
    replaceChildren(...children) { for (const child of element.children) child.parentNode = null; element.children = []; element.append(...children); },
    replaceWith(next) {
      const parent = element.parentNode;
      if (!parent) return;
      parent.children.splice(parent.children.indexOf(element), 1, next);
      next.parentNode = parent; element.parentNode = null;
    },
    setAttribute(name, value) { element.attributes[name] = String(value); },
    getAttribute(name) { return name in element.attributes ? element.attributes[name] : null; },
    addEventListener(type, callback) { element.listeners[type] = callback; },
    removeEventListener() {},
    scrollIntoView(options) { element.scrolled = options; },
    focus(options) { element.focused = options; },
    querySelector(selector) { return match(element, selector); },
  };
  return element;
}

// 이 모듈이 쓰는 선택자는 [data-arm-source="x"], [data-robot-profile], details 세 가지다.
const datasetKey = name => name.replace(/^data-/, '').replace(/-(\w)/g, (_, c) => c.toUpperCase());
function matchesToken(element, token) {
  if (/^[\w-]+$/.test(token)) return element.tagName === token.toUpperCase();
  const attr = /^\[([-\w]+)(?:="(.*)")?\]$/.exec(token);
  if (!attr) return false;
  const key = datasetKey(attr[1]);
  return Object.hasOwn(element.dataset, key) && (attr[2] === undefined || element.dataset[key] === attr[2]);
}
function firstMatch(element, tokens, index) {
  for (const child of element.children) {
    if (matchesToken(child, tokens[index])) {
      if (index === tokens.length - 1) return child;
      const nested = firstMatch(child, tokens, index + 1);
      if (nested) return nested;
    } else {
      const nested = firstMatch(child, tokens, index);
      if (nested) return nested;
    }
  }
  return null;
}
const match = (element, selector) => firstMatch(element, selector.split(' ').filter(Boolean), 0);

const heldIncident = {incident_id: 'i1', state: 'open', reported_at: 60,
  decision: {hold: true, reason: 'joint torque hold'}, frames: [], evidence: []};
const namingIncident = {incident_id: 'i2', state: 'open', reported_at: 61,
  decision: {hold: false, reason: 'guard stop handled by recovery'}, frames: [], evidence: []};
const faultHealth = {schema_version: 'rosy.motor-health.v1', status: 'fault', stop_reasons: ['토크 유지'],
  motors: [], evidence: 'delayed', sample_age_s: 0.5, stale_after_s: 2};
const arm = overrides => ({source_id: 'arm_a', arm_id: 'omx_a', label: '팔 arm_a', binding_sha256: null,
  faults: [], incidents: [], motor_health: null, fresh: true, source_age_s: 0, receipt_age_s: 0,
  positions: {joints: [0.1, 0.2]}, sequence: 3, ...overrides});
const body = arms => ({workcells: [{workcell_id: 'cell_ab', label: 'S5 셀', arms, cameras: []}]});

function setup(t, initial) {
  const saved = {document: globalThis.document, CSS: globalThis.CSS};
  globalThis.document = {createElement: node, hidden: false, visibilityState: 'visible',
    addEventListener() {}, removeEventListener() {}};
  globalThis.CSS = {escape: value => value.replace(/[^A-Za-z0-9_-]/g, character => '\\' + character)};
  let current = initial, failure = null;
  const root = node('div');
  const summaries = [];
  const request = async path => {
    if (failure) throw Object.assign(new Error('unavailable'), {status: failure});
    if (path === '/api/fleet/workcell-observations') return current;
    return {profile: null, source_binding_status: null, device_id: null};
  };
  const observations = createCellObservation({request, root, credential: () => '',
    onSummary: items => summaries.push(items.map(item => ({...item})))});
  t.after(() => { observations.dispose(); Object.assign(globalThis, saved); });
  return {root, summaries, observations,
    setBody: value => { current = value; }, failWith: status => { failure = status; }};
}

test('exceptions are ordered held, naming wait, motor health, stale feedback', async t => {
  const env = setup(t, body([arm({incidents: [heldIncident, namingIncident], motor_health: faultHealth, positions: null})]));
  await env.observations.refresh();
  assert.deepEqual(env.summaries[0], []);  // 첫 배치는 빈 요약으로 시작한다
  assert.deepEqual(env.summaries[1].map(item => [item.key, item.severity]), [
    ['inc:arm_a', 'danger'], ['name:arm_a', 'warn'], ['health:arm_a:crit', 'danger'], ['stale:arm_a', 'warn']]);
  assert.deepEqual(env.summaries[1].map(item => [item.label, item.detail, item.sourceId]), [
    ['팔 arm_a', '보류 사건 1건 · 확인 후 해제 필요', 'arm_a'],
    ['팔 arm_a', '원인 기록 대기 1건', 'arm_a'],
    ['팔 arm_a', '모터 중단 기록 · 토크 유지', 'arm_a'],
    ['팔 arm_a', '엔코더 피드백 만료 · 최신 값 없음', 'arm_a']]);
});

test('an identical poll does not re-fire the summary callback', async t => {
  const env = setup(t, body([arm({incidents: [heldIncident]})]));
  await env.observations.refresh();
  assert.equal(env.summaries.length, 2);
  await env.observations.refresh();
  assert.equal(env.summaries.length, 2);  // 서명이 같으면 조용하다
});

test('a freshness flip re-emits only when the summary changed', async t => {
  const env = setup(t, body([arm({})]));
  await env.observations.refresh();
  assert.deepEqual(env.summaries, [[]]);  // 빈 요약은 한 번만 나간다(재배치 때의 빈 발행과 같은 서명)
  env.setBody(body([arm({positions: null})]));
  await env.observations.refresh();
  assert.equal(env.summaries.length, 2);
  assert.equal(env.summaries[1][0].key, 'stale:arm_a');
});

test('unconfigured 503 stays quiet without prior cells; dropped observation connection is one warn row, auth loss clears the strip', async t => {
  const unconfigured = setup(t, body([arm({})]));
  unconfigured.failWith(503);
  await unconfigured.observations.refresh();
  assert.deepEqual(unconfigured.summaries, [[]]);  // 미구성 서버 503은 상단 경고를 띄우지 않는다

  const env = setup(t, body([arm({})]));
  await env.observations.refresh();
  env.failWith(503);
  await env.observations.refresh();
  assert.deepEqual(env.summaries.at(-1), [{key: 'obs:disconnected', severity: 'warn', label: '셀 관측',
    detail: '관측 연결 확인 중 · 오래된 값은 표시하지 않습니다', sourceId: ''}]);
  // 끊긴 동안 100 ms 만료 타이머가 옛 팔 목록으로 만료 행을 되살리지 않는다.
  await new Promise(resolve => setTimeout(resolve, 250));
  assert.equal(env.summaries.at(-1)[0].key, 'obs:disconnected');
  env.failWith(401);
  await env.observations.refresh();
  assert.deepEqual(env.summaries.at(-1), []);  // 접속 끊기면 줄이 곧 사라진다
});

test('focusArm opens the incident details, focuses the card and refuses unknown ids', async t => {
  const env = setup(t, body([arm({incidents: [namingIncident]})]));
  await env.observations.refresh();
  const card = env.root.querySelector('[data-arm-source="arm_a"]');
  const incidents = card.children.find(child => child.children[0]?.textContent.includes('팔 사건'));
  assert.equal(incidents.open, false);  // 보류 없음: 펼쳐 두지 않는다
  assert.equal(env.observations.focusArm('arm_a'), true);
  assert.equal(incidents.open, true);
  assert.equal(card.tabIndex, -1);
  assert.ok(card.focused && card.scrolled);
  assert.equal(env.observations.focusArm('arm_b'), false);
  assert.equal(env.observations.focusArm(''), false);
});

test('clear() emits an empty summary at once', async t => {
  const env = setup(t, body([arm({incidents: [heldIncident]})]));
  await env.observations.refresh();
  assert.ok(env.summaries.at(-1).length);
  env.observations.clear();
  assert.deepEqual(env.summaries.at(-1), []);
});

test('idle arms hide until toggled or focused, and cleared incidents fold cleanly', async t => {
  const clearedList = Array.from({length: 4}, (_, idx) => ({
    incident_id: `c${idx}`, state: 'cleared', reported_at: 10 + idx,
    decision: {hold: true, reason: `old-${idx}`}, frames: [], evidence: [],
    cleared: {by: 'op-1', at: 20 + idx, note: 'checked', cause: 'blocked', basis: 'seen'},
  }));
  const env = setup(t, {
    workcells: [{
      workcell_id: 'cell_ab', label: 'S5 셀',
      arms: [
        arm({source_id: 'arm_a', label: '팔 A', fresh: false, positions: null, incidents: clearedList}),
        arm({source_id: 'arm_b', label: '팔 B', incidents: [heldIncident, ...clearedList.slice(0, 2)]}),
      ],
      cameras: [{source_id: 'cam_1', label: '상단', role: 'overhead', stream: 'color', arm_id: null}],
    }],
  });
  await env.observations.refresh();
  const armACard = env.root.querySelector('[data-arm-source="arm_a"]');
  const armBCard = env.root.querySelector('[data-arm-source="arm_b"]');
  assert.equal(armACard.hidden, true);
  assert.equal(armBCard.hidden, false);
  assert.equal(armBCard.dataset.armHeld, 'true');

  // arm B has 1 open + 2 cleared -> cleared fold renders 2 older items while keeping summary[0] first
  const armBInc = armBCard.children.find(child => child.children[0]?.textContent.includes('팔 사건'));
  assert.equal(armBInc.children.length, 3);
  assert.match(armBInc.children[2].children[0].textContent, /해제된 이전 사건 2건 보기/);

  // focusing an idle arm unhides it
  assert.equal(env.observations.focusArm('arm_a'), true);
  assert.equal(armACard.hidden, false);
});

test('clearIncident encodes special characters in incident_id', async t => {
  const saved = {document: globalThis.document, CSS: globalThis.CSS, fetch: globalThis.fetch};
  const calls = [];
  const nodeWithClick = (tag = '') => {
    const el = node(tag);
    el.addEventListener = (type, cb) => { (el.listeners[type] ??= []).push(cb); };
    return el;
  };
  globalThis.document = {createElement: nodeWithClick, hidden: false, visibilityState: 'visible',
    addEventListener() {}, removeEventListener() {}};
  globalThis.CSS = {escape: v => v};
  globalThis.fetch = async (url) => { calls.push(String(url)); return new Response(new Blob()); };
  const root = nodeWithClick('div');
  const obs = createCellObservation({
    request: async (path, opts) => {
      if (opts?.method === 'POST') { calls.push(String(path)); return {}; }
      return body([arm({incidents: [{
        incident_id: 'inc/1?x=2', state: 'open', reported_at: 60,
        decision: {hold: true, reason: 'hold'}, frames: [{role: 'top'}], evidence: [],
      }]})]);
    },
    root,
    credential: () => '',
  });
  t.after(() => { obs.dispose(); Object.assign(globalThis, saved); });

  await obs.refresh();
  const card = root.querySelector('[data-arm-source="arm_a"]');
  const li = card.querySelector('ol').children.at(-1);
  const input = li.children.find(c => c.tagName === 'INPUT');
  const btn = li.children.find(c => c.tagName === 'UI-BUTTON');
  input.value = 'inspected';
  await btn.listeners.click[0]();
  assert.ok(calls.some(u => u.includes('/incidents/inc%2F1%3Fx%3D2/clear')));
  assert.ok(calls.some(u => u.includes('/incidents/inc%2F1%3Fx%3D2/frames/top')));
});
