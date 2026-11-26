import test from 'node:test';
import assert from 'node:assert/strict';
import { webcrypto } from 'node:crypto';
import { readFile } from 'node:fs/promises';

globalThis.crypto ??= webcrypto;

const source = new URL('../../../../applications/fleet/web/charge-bays-view.js', import.meta.url);
const gate = new URL('../../../../applications/fleet/web/shared/poll-gate.js', import.meta.url);
const model = new URL('../../../../applications/fleet/web/cell/charge-bays-model.js', import.meta.url);
const frames = new URL('../../../../applications/fleet/web/shared/cell-frames.js', import.meta.url);
const causeLine = new URL('../../../../shared/web/cause-line.js', import.meta.url);
const controlDom = new URL('../../../../shared/web/control-dom.js', import.meta.url);
const code = (await readFile(source, 'utf8')).replace('/console/assets/poll-gate.js', gate.href)
  .replaceAll('/console/assets/charge-bays-model.js', model.href)
  .replaceAll('/console/assets/cell-frames.js', frames.href)
  .replaceAll('/common/cause-line.js', causeLine.href)
  .replaceAll('/common/control-dom.js', controlDom.href);
const { register } = await import('node:module');
register('./resolve-console-assets.mjs', import.meta.url);
const { createChargeBaysView, chargeBayRows, inspectorTargetsFromRows, formatArmLiveJointText, armIncidentRowKey } = await import(`data:text/javascript,${encodeURIComponent(code)}`);

const plan = {
  thresholds: { go_percent: 15, leave_percent: 80, rate_pct_per_min: null },
  bays: [
    { bay: 'C1', x: -0.414, y: 0.47, state: 'charging', robot_id: 'rosy_40' },
    { bay: 'C2', x: -0.19, y: 0.47, state: 'planned', robot_id: 'rosy_60' },
    { bay: 'C3', x: 0.032, y: 0.47, state: 'free', robot_id: null },
  ],
  actions: [
    { robot_id: 'rosy_60', action: 'go', bay: 'C2', reason: 'low_battery' },
    { robot_id: 'rosy_40', action: 'stay', bay: 'C1', arrived_percent: 12.4, reason: 'charge_rate_not_measured' },
  ],
  dispatch: false,
};

test('bays and actions read as plain Korean rows, and the plan is marked view-only', () => {
  const rows = chargeBayRows(plan);
  assert.deepEqual(rows.bays.map((b) => [b.id, b.text, b.status]), [
    ['C1', '충전 중 · rosy_40', 'active'], ['C2', '배정됨 · rosy_60', 'warn'], ['C3', '비어 있음', 'neutral']]);
  assert.deepEqual(rows.actions.map((a) => a.text), [
    '충전 칸으로 · C2 · 배터리 낮음', '칸에 머무름 · 도착 12% · 충전 속도 미측정']);
  assert.match(rows.summary, /15% 이하면 충전 · 80%면 나감 · 충전 속도 미측정 · 보기 전용/);
});

test('an estimate wins over the arrival percent, and unknown codes are shown as given', () => {
  const rows = chargeBayRows({ bays: [{ bay: 'C9', state: 'new_state' }],
    actions: [{ robot_id: 'a', action: 'leave', arrived_percent: 14, estimated_percent: 80, reason: 'charged' },
      { robot_id: 'b', action: 'later', reason: 'why' }] });
  assert.equal(rows.bays[0].text, '알 수 없음');
  assert.deepEqual(rows.actions.map((a) => a.text), ['충전 끝 · 나가도 됨 · 추정 80% · 목표 충전 도달', 'later · why']);
});

test('a bay whose robot lost its pose reads as unknown, never as empty', () => {
  const rows = chargeBayRows({ bays: [{ bay: 'C1', state: 'unknown', robot_id: 'rosy_45' }],
    actions: [{ robot_id: 'rosy_45', action: 'stay', bay: 'C1', reason: 'pose_unknown' }] });
  assert.equal(rows.bays[0].text, '확인 불가 · 비어 있다고 볼 수 없음 · rosy_45');
  assert.equal(rows.bays[0].status, 'warn');
  assert.equal(rows.actions[0].text, '칸에 머무름 · 로봇 위치를 확인할 수 없음 · 칸을 직접 확인');
});

test('an empty bay that cannot be called free says so', () => {
  const rows = chargeBayRows({ bays: [{ bay: 'C2', state: 'unknown', robot_id: null }],
    actions: [{ robot_id: 'low', action: 'wait', reason: 'bay_unknown' }] });
  assert.equal(rows.bays[0].text, '확인 불가 · 비어 있다고 볼 수 없음');
  assert.match(rows.actions[0].text, /칸이 비었는지 확인 불가/);
});

test('centerline docking evaluation and misaligned reseat render in Korean', () => {
  const rows = chargeBayRows({
    bays: [{ bay: 'C1', state: 'arrived', robot_id: 'rosy_60' }],
    actions: [{
      robot_id: 'rosy_60', action: 'reseat', bay: 'C1', arrived_percent: 14,
      reason: 'misaligned_on_bay',
      docking: { verdict: 'RETRY_FROM_P', offset_m: 0.034, yaw_err_deg: 11.2 },
    }],
  });
  assert.match(rows.actions[0].text, /중심선 정렬 불량 · 전진 후 재접안 필요/);
  assert.match(rows.actions[0].text, /이탈 · 재정렬 필요 34mm 11\.2°/);
});

test('OMX cell gates and cell-blocked actions render in Korean', () => {
  const rows = chargeBayRows({
    actions: [{ robot_id: 'rosy_60', action: 'wait', reason: 'locked_by_cell',
      blocked_by_cell: true, cell_id: 'cell_s' }],
    omx_cells: {
      cell_s: { station: { station_place: 'S3' }, gate: {
        phase: 'ARM_IN_BED_ZONE', robot_id: 'rosy_60', amr_motion_inhibited: true,
      } },
      cell_ab: { station: { station_place: 'S5' }, gate: { phase: 'IDLE' } },
    },
  });
  assert.deepEqual(rows.cells, [
    { id: 'cell_s', text: 'OMX 작업 중 · AMR 잠금 · S3 · rosy_60', status: 'active' },
    { id: 'cell_ab', text: '대기 중 · S5', status: 'neutral' },
  ]);
  assert.match(rows.actions[0].text, /OMX 셀 작업 중 구동 잠금/);
  assert.match(rows.actions[0].text, /OMX 셀\(cell_s\) 잠금/);
});

test('pipeline cards carry cell telemetry and one-click robot actions without changing legacy rows', () => {
  const rows = chargeBayRows({
    ...plan,
    omx_cells: {
      cell_s: {gate: {phase: 'ARM_IN_BED_ZONE'}},
      cell_ab: {gate: {phase: 'IDLE'}},
    },
    omx_cell_tasks: [
      {task_id: 'old', cell_id: 'cell_s', status: 'COMPLETED', created_at: 1},
      {task_id: 'new', cell_id: 'cell_s', status: 'RUNNING', created_at: 2, arm_id: 'arm_s'},
    ],
  });
  assert.equal(rows.bays.length, 3);
  assert.equal(rows.actions.length, 2);
  assert.equal(rows.cells.length, 2);
  assert.match(rows.summary, /15%/);
  assert.equal(rows.cards.length, 2);
  assert.deepEqual(rows.cards[0].cameraViews.map(v => v.id), ['arm_s_top', 'arm_s_wrist']);
  assert.deepEqual(rows.cards[1].cameraViews.map(v => v.id), ['top', 'side', 'arm_a_wrist', 'arm_b_wrist']);
  assert.ok(rows.cards.every(c => !c.cameraUrl), '카드는 Fleet 중계 URL을 들지 않는다(D-136)');
  assert.equal(rows.cards[0].title, 'cell_s · S3 하역 셔틀 (arm_s)');
  assert.equal(rows.cards[0].phase, 'ARM_IN_BED_ZONE');
  assert.equal(rows.cards[0].task.task_id, 'new');
  assert.deepEqual(rows.cards[0].buttons.map(b => b.preset),
    ['s3_shuttle', 's3_act_policy', 's3_recover_belt_far', 's3_recover_floor_front']);
  assert.equal(rows.cards[0].buttons[1].requiresPresence, true);
  assert.equal(rows.cards[1].title, 'cell_ab · S5 팔레트 적재 (arm_a·arm_b)');
  assert.deepEqual(rows.cards[1].buttons.map(b => b.preset),
    ['s5_tier1_arm_a', 's5_tier2_arm_b', 's5_tier1_arm_a_act_policy', 's5_tier1_arm_b_act_policy', 's5_tier3_arm_a', 'full_s3_to_s5_pipeline']);
  assert.equal(rows.cards[0].quickControls[0].decisionSubject, 'cell_s');
  assert.equal(rows.cards[0].quickControls[1].humanSafetyCell, 'cell_s');
  assert.equal(rows.cards[0].quickControls[2].zoneId, 'EXP_S3_BELT');
  assert.equal(rows.cards[0].quickControls[3].visionCheckCell, 'cell_s');
  assert.equal(rows.cards[0].quickControls[4].armIncident, 'cell_s');
  assert.equal(rows.cards[0].cameraViews.length, 2);
  assert.equal(rows.cards[1].cameraViews.length, 4);
  assert.deepEqual(chargeBayRows({}).cards.map(c => c.id), ['cell_s', 'cell_ab']);

  const unlinkedTargets = inspectorTargetsFromRows(rows);
  assert.deepEqual(unlinkedTargets.map(t => t.id), ['arm_s', 'arm_a', 'arm_b', 'cell_s', 'cell_ab']);
  assert.equal(unlinkedTargets[0].robot_id, null);
  assert.ok(!unlinkedTargets[0].cameraViews.some(v => v.id === 'pinky_dock'));

  const occupiedRows = chargeBayRows({
    ...plan,
    omx_cells: {
      cell_s: { gate: { phase: 'ARM_IN_BED_ZONE', robot_id: 'rosy_60' } },
      cell_ab: { gate: { phase: 'IDLE' } },
    },
  });
  const targets = inspectorTargetsFromRows({
    ...occupiedRows,
    armLiveStates: {
      arm_s: { joints_deg: [0.0, -58.0, 50.0, 50.0, -5.0, 58.1], folded: true, temp_c: 31.2, current_ma: 44.0, age_s: 2.0, fresh: true, substage: 'Fold Home 대기' },
    },
  });
  assert.deepEqual(targets.map(t => t.id), ['arm_s', 'arm_a', 'arm_b', 'cell_s', 'cell_ab']);
  assert.equal(targets[0].robot_id, 'rosy_60');
  assert.equal(targets[0].cameraViews[0].id, 'arm_s_wrist');
  assert.equal(targets[0].cameraViews.at(-1).roiTarget, 'rosy_60');
  assert.equal(targets[1].cameraViews[0].id, 'arm_a_wrist');
  assert.equal(targets[2].cameraViews[0].id, 'arm_b_wrist');
  assert.deepEqual(targets[0].dualPair, ['arm_s_top', 'arm_s_wrist']);
  assert.deepEqual(targets[1].dualPair, ['top', 'arm_a_wrist']);
  assert.deepEqual(targets[2].dualPair, ['top', 'arm_b_wrist']);
  assert.match(targets[0].jointLiveText, /\[LIVE · 2초 전\]/);
  assert.match(targets[0].jointLiveText, /J1:0\.0°/);
  assert.match(formatArmLiveJointText('arm_s', { arm_s: { joints_deg: [1, 2, 3, 4, 5, 6], folded: false, fresh: false, age_s: 25 } }), /\[스냅샷 · 25초 전\]/);
  assert.ok(targets[0].quickControls.some(c => c.armIncident === 'arm_s'));
  assert.ok(targets[1].quickControls.some(c => c.armIncident === 'arm_a'));
  assert.ok(targets[2].quickControls.some(c => c.armIncident === 'arm_b'));

  const emptyTargets = inspectorTargetsFromRows({ cards: [] });
  assert.doesNotMatch(emptyTargets[0].jointLiveText, /folded: true|홈 대기/);
  assert.equal(emptyTargets[0].jointLiveText, '관절 관측 없음 · 홈 여부 미확인');
  assert.equal(formatArmLiveJointText('arm_s', {}), '관절 관측 없음 · 홈 여부 미확인');
  assert.match(formatArmLiveJointText('arm_s', { arm_s: { joints_deg: [1, 2, 3, 4, 5, 6], folded: false, age_s: 5 } }), /\[신선도 미확인 · 5초 전\]/);
  const blankCardTargets = inspectorTargetsFromRows({ cards: [{ id: 'cell_s', healthText: '' }, { id: 'cell_ab', healthText: '' }] });
  assert.equal(blankCardTargets[3].jointLiveText, '관절 관측 없음 · 홈 여부 미확인');
  assert.equal(blankCardTargets[4].jointLiveText, '관절 관측 없음 · 홈 여부 미확인');
});

test('charge-bays stop receipts latch warning across refreshes, keep retry human_detected=true, and keep vision enabled without occupant', async () => {
  const mkNode = (tag = 'DIV') => {
    const el = {
      tagName: String(tag).toUpperCase(), dataset: {}, style: {}, attributes: {}, listeners: {}, children: [],
      hidden: false, value: '', textContent: '', className: '', open: false, selected: false,
      get firstElementChild() { return el.children[0] || null; },
      get childElementCount() { return el.children.length; },
      classList: {add() {}, remove() {}, toggle() {}, contains: () => false},
      append(...nodes) { for (const n of nodes) if (typeof n !== 'string') { n.parentNode = el; el.children.push(n); } },
      replaceChildren(...nodes) { el.children = []; el.append(...nodes); },
      addEventListener(type, cb) { (el.listeners[type] ??= []).push(cb); },
      setAttribute(k, v) { el.attributes[k] = String(v); },
      getAttribute(k) { return el.attributes[k] ?? null; },
      hasAttribute(k) { return k in el.attributes; },
      removeAttribute(k) { delete el.attributes[k]; },
      querySelector: () => null, querySelectorAll: () => [],
    };
    return el;
  };
  const prevDoc = globalThis.document;
  globalThis.document = {createElement: mkNode, hidden: false, querySelectorAll: () => []};
  try {
    const els = {};
    let held = false;
    let stopMode = 'unconfirmed';
    const posts = [];
    const view = createChargeBaysView({
      scope: {capture: () => ({check() {}, signal: null}), listen() {}, onDispose() {}},
      el: id => (els[id] ??= mkNode('DIV')),
      auth: {locked: false},
      call: async (path, opts) => {
        if (opts?.method === 'POST') {
          posts.push({path, body: JSON.parse(opts.body)});
          held = true;
          if (stopMode === 'throw') throw new Error('HTTP 503');
          if (stopMode === 'confirmed') return {ok: true, stop_confirmed: true, unconfirmed_pinky_stops: []};
          if (stopMode === 'missing_ack') return {ok: true};
          return {ok: false, stop_confirmed: false, unconfirmed_pinky_stops: ['t-cb']};
        }
        return {
          ...plan,
          human_safety: {human_detected: {cell_s: held}},
          omx_cells: {
            cell_s: {gate: {phase: held ? 'HUMAN_HOLD' : 'IDLE', robot_id: null}},
            cell_ab: {gate: {phase: 'IDLE', robot_id: null}},
          },
        };
      },
    });
    await view.refresh();
    const findButtons = (node, pred, out = []) => {
      for (const c of node.children || []) {
        if ((c.tagName === 'BUTTON' || c.tagName === 'UI-BUTTON') && pred(c)) out.push(c);
        findButtons(c, pred, out);
      }
      return out;
    };
    const visionBtn = findButtons(els['omx-right-inspector'], b => b.textContent.includes('비전 안전 비상정지'))[0];
    assert.ok(visionBtn && !visionBtn.hasAttribute('disabled'), 'vision button enabled even without robot_id');
    await visionBtn.listeners.click[0]();
    assert.equal(posts[0].body.human_detected, true);
    assert.ok(posts[0].body.intrusion_score >= 0.35);
    assert.match(els['charge-bays-hint'].textContent, /정지 미확인\(t-cb\)/);
    await view.refresh();
    assert.match(els['charge-bays-hint'].textContent, /정지 미확인\(t-cb\)/);
    // Held cell retry button sends human_detected: true; missing_ack / thrown 503 preserve warning across refresh()
    stopMode = 'missing_ack';
    const retryBtn = findButtons(els['omx-right-inspector'], b => b.textContent.includes('비상정지 재전송'))[0];
    assert.ok(retryBtn, 'held cell renders retry button');
    await retryBtn.listeners.click[0]();
    assert.equal(posts[1].body.human_detected, true);
    assert.match(els['charge-bays-hint'].textContent, /정지 미확인/);
    stopMode = 'throw';
    await retryBtn.listeners.click[0]();
    assert.match(els['charge-bays-hint'].textContent, /정지 미확인/);
    await view.refresh();
    assert.match(els['charge-bays-hint'].textContent, /정지 미확인/);
    // Explicit stop_confirmed: true clears the sticky warning
    stopMode = 'confirmed';
    await findButtons(els['omx-right-inspector'], b => b.textContent.includes('비상정지 재전송'))[0].listeners.click[0]();
    assert.doesNotMatch(els['charge-bays-hint'].textContent, /정지 미확인/);
  } finally {
    globalThis.document = prevDoc;
  }
});

test('the arm hold control opens the shared alert-drawer row and never posts a clear of its own', async () => {
  const { normalizeWorkcellObservations } = await import('/console/assets/cell-obs-model.js');
  const obs = normalizeWorkcellObservations({ workcells: [{ arms: [
    { arm_id: 'arm_s', source_id: 'omx_arm_s', incidents: [] },
    { arm_id: 'arm_b', source_id: 'omx_arm_b', incidents: [
      { incident_id: 'w1', state: 'open', decision: { hold: false, reason: 'guard stop handled' } },
      { incident_id: 'c1', state: 'open', decision: { hold: true, reason: 'arm incident not cleared' } },
    ] },
  ] }] });
  assert.equal(armIncidentRowKey('cell_ab', obs), 'omx_arm_b|arm-incident-c1', 'held incident first');
  assert.equal(armIncidentRowKey('arm_b', obs), 'omx_arm_b|arm-incident-c1');
  assert.equal(armIncidentRowKey('arm_s', obs), null, 'no open incident: no drawer row');
  assert.equal(armIncidentRowKey('cell_s', null), null);
  assert.doesNotMatch(code, /arm-holds\/clear/, 'the console card leaves clearing to the drawer and the cell page');
});

test('onQuickDispatch and preset dispatch require confirm, Idempotency-Key, propose=false, and namedReason while stops stay 1-click', async () => {
  const mkNode = (tag = 'DIV') => {
    const el = {
      tagName: String(tag).toUpperCase(), dataset: {}, style: {}, attributes: {}, listeners: {}, children: [],
      hidden: false, value: '', textContent: '', className: '', open: false, selected: false,
      get firstElementChild() { return el.children[0] || null; },
      get childElementCount() { return el.children.length; },
      classList: {add() {}, remove() {}, toggle() {}, contains: () => false},
      append(...nodes) { for (const n of nodes) if (typeof n !== 'string') { n.parentNode = el; el.children.push(n); } },
      replaceChildren(...nodes) { el.children = []; el.append(...nodes); },
      addEventListener(type, cb) { (el.listeners[type] ??= []).push(cb); },
      setAttribute(k, v) { el.attributes[k] = String(v); },
      getAttribute(k) { return el.attributes[k] ?? null; },
      hasAttribute(k) { return k in el.attributes; },
      removeAttribute(k) { delete el.attributes[k]; },
      querySelector: () => null, querySelectorAll: () => [],
    };
    return el;
  };
  const prevDoc = globalThis.document;
  globalThis.document = {createElement: mkNode, hidden: false, querySelectorAll: () => []};
  try {
    const els = {};
    const posts = [];
    const confirms = [];
    let allowConfirm = false;
    let reason = '이름 있는 운영자 로그인이 필요합니다';
    const view = createChargeBaysView({
      scope: {capture: () => ({check() {}, signal: null}), listen() {}, onDispose() {}},
      el: id => (els[id] ??= mkNode('DIV')),
      auth: {locked: false},
      namedReason: () => reason,
      confirmedAction: {
        run: async ({message, opener, eligible, request}) => {
          confirms.push({message, opener, eligible: eligible()});
          if (allowConfirm && eligible()) await request();
        },
      },
      call: async (path, opts) => {
        if (opts?.method === 'POST') {
          posts.push({path, headers: opts.headers || {}, body: JSON.parse(opts.body)});
          return {ok: true, stop_confirmed: true, unconfirmed_pinky_stops: []};
        }
        return {
          ...plan,
          omx_cells: {
            cell_s: {gate: {phase: 'IDLE', robot_id: 'rosy_46'}},
            cell_ab: {gate: {phase: 'IDLE', robot_id: null}},
          },
        };
      },
    });
    const findButtons = (node, pred, out = []) => {
      for (const c of node.children || []) {
        if ((c.tagName === 'BUTTON' || c.tagName === 'UI-BUTTON') && pred(c)) out.push(c);
        findButtons(c, pred, out);
      }
      return out;
    };
    await view.refresh();
    const lockedRun = findButtons(els['omx-right-inspector'], b => b.textContent.includes('맞춤 실행'))[0];
    assert.equal(lockedRun.getAttribute('reason'), '이름 있는 운영자 로그인이 필요합니다');
    await lockedRun.listeners.click[0]();
    assert.equal(confirms.length, 0);
    assert.equal(posts.length, 0);

    // Emergency stops remain 1-click even while dispatch buttons are locked for unnamed operators
    const visionBtn = findButtons(els['omx-right-inspector'], b => b.textContent.includes('비전 안전 비상정지'))[0];
    await visionBtn.listeners.click[0]();
    assert.equal(posts.length, 1);
    assert.equal(posts[0].path, '/api/fleet/pipeline/vision-auto-check');

    reason = '';
    await view.refresh();
    const runBtn = findButtons(els['omx-right-inspector'], b => b.textContent.includes('맞춤 실행'))[0];
    const presetBtn = findButtons(els['omx-right-inspector'], b => b.textContent.includes('S3 셔틀 (Pinky→Belt)'))[0];
    assert.equal(runBtn.hasAttribute('disabled'), false);
    await runBtn.listeners.click[0]();
    await presetBtn.listeners.click[0]();
    assert.equal(confirms.length, 2);
    assert.equal(posts.length, 1, 'canceled confirms do not POST');

    allowConfirm = true;
    await runBtn.listeners.click[0]();
    await presetBtn.listeners.click[0]();
    assert.equal(posts.length, 3);
    assert.equal(posts[1].path, '/api/fleet/pipeline/cell-tasks');
    assert.equal(posts[1].body.propose, false);
    assert.ok(posts[1].headers['Idempotency-Key']);
    assert.equal(posts[2].path, '/api/fleet/pipeline/cell-tasks');
    assert.equal(posts[2].body.preset, 's3_shuttle');
    assert.equal(posts[2].body.propose, false);
    assert.ok(posts[2].headers['Idempotency-Key']);
  } finally {
    globalThis.document = prevDoc;
  }
});
