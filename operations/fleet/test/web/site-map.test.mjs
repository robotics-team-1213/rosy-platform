import {test} from 'node:test';
import assert from 'node:assert/strict';
import {
  arrowMarks, editEdge, editPlace, fitView, editViewTurn, viewTurnOf, planPolylines, segmentPoints, tripErrorText, rectangularView,
} from '../../fleet/server/web/shared/site-map-model.js';

const MAP = {
  places: [{id: 'A', name: 'A', x: 0, y: 0, kind: 'junction'}, {id: 'B', name: 'B', x: 2, y: 0, kind: 'park'}],
  edges: [{id: 'ab', from: 'A', to: 'B', polyline: [[0, 0], [1, 0], [2, 0]], direction: 'one_way',
           width_m: 0.2, speed_cap_mps: 0.2, drive_mode: 'lane'}],
};

test('rectangular camera view preserves metric aspect and rejects mismatched or singular calibration', () => {
  const record = {map_id: 'camera', map_to_image: [100, 0, 200, 0, -100, 100, 0, 0, 1],
    track_bounds_m: {min_x: -1.405, max_x: 1.405, min_y: -0.63, max_y: 0.63}};
  const {view, field} = rectangularView(record, 'camera', 800, 480);
  assert.ok(Math.abs(field.width / field.height - 2.81 / 1.26) < 1e-12);
  assert.deepEqual(view.toMap(field.x, field.y), [-1.405, 0.63]);
  assert.deepEqual(view.toMap(...view.toPx(0, 0)), [0, 0]);
  assert.throws(() => rectangularView(record, 'other', 800, 480));
  assert.throws(() => rectangularView({...record, map_to_image: Array(9).fill(0)}, 'camera', 800, 480));
  assert.throws(() => rectangularView({...record, map_to_image: [100, 0, 200, 0, -100, 100, 1, 0, 0]}, 'camera', 800, 480));
});

test('fitView flips y and round-trips map metres', () => {
  const view = fitView(MAP, 200, 100, 10);
  const [px, py] = view.toPx(2, 0);
  assert.deepEqual(view.toMap(px, py).map(v => Math.round(v * 1e6) / 1e6), [2, 0]);
  assert.ok(view.toPx(0, 1)[1] < view.toPx(0, 0)[1]);
});

test('one-way edges get one arrow, two-way edges two opposite ones', () => {
  assert.equal(arrowMarks(MAP.edges[0]).length, 1);
  assert.equal(arrowMarks(MAP.edges[0])[0].angle, 0);
  const both = arrowMarks({...MAP.edges[0], direction: 'two_way'});
  assert.equal(both.length, 2);
  assert.equal(Math.abs(both[1].angle), Math.PI);
});

test('segments slice the edge in driving order', () => {
  assert.deepEqual(segmentPoints(MAP.edges[0], true, 0.5, 1.5), [[0.5, 0], [1, 0], [1.5, 0]]);
  assert.deepEqual(segmentPoints(MAP.edges[0], false, 0, 0.5), [[2, 0], [1.5, 0]]);
  const plan = {segments: [{edge_id: 'ab', forward: true, s_from: 0, s_to: 2}, {edge_id: 'gone', forward: true}]};
  assert.equal(planPolylines(MAP, plan).length, 1);
});

test('edits copy the map and refuse bad values', () => {
  const named = editPlace(MAP, 'B', {name: ' 주차-1 ', kind: 'charge'});
  assert.equal(named.places[1].name, '주차-1');
  assert.equal(MAP.places[1].name, 'B');
  const edge = editEdge(MAP, 'ab', {direction: 'two_way', drive_mode: 'free', speed_cap_mps: '0.3'});
  assert.deepEqual([edge.edges[0].direction, edge.edges[0].drive_mode, edge.edges[0].speed_cap_mps],
    ['two_way', 'free', 0.3]);
  assert.throws(() => editEdge(MAP, 'ab', {speed_cap_mps: 0}));
  assert.throws(() => editPlace(MAP, 'A', {kind: 'garage'}));
  assert.throws(() => editPlace(MAP, 'A', {kind: 'start'}), /방향이 필요/);
  const faced = {...MAP, places: [{...MAP.places[0], yaw: 0}, MAP.places[1]]};
  assert.equal(editPlace(faced, 'A', {kind: 'start'}).places[0].kind, 'start');
});

test('trip errors read in Korean with the leg and the unblock hint', () => {
  assert.match(tripErrorText('TRIP_NO_ROUTE', {segment: 1, unblock_would_help: true}), /2번째 구간.*막은 차로/);
  assert.match(tripErrorText('NEW_CODE'), /NEW_CODE/);
});

test('actions read the address names and stale plans are refused', async () => {
  const {actionRows, planIsCurrent, siteMapErrorText} = await import('../../fleet/server/web/shared/site-map-model.js');
  const map = {places: [{id: 'B', name: '충전'}]};
  const plan = {map_version: 2, actions: [{place_id: 'B', action: 'left'}, {place_id: null, action: 'stop'}]};
  assert.deepEqual(actionRows(plan, map), ['충전 · 좌회전', '찍은 좌표 · 정지']);
  assert.equal(planIsCurrent(plan, {version: 2}), true);
  assert.equal(planIsCurrent(plan, {version: 3}), false);
  assert.match(siteMapErrorText({code: 'SITE_MAP_ROUTE_ACTIVE'}), /진행 중/);
  assert.match(siteMapErrorText({status: 401}), /토큰을 확인하고 다시 접속/);
  assert.match(siteMapErrorText({status: 503, code: 'SITE_MAP_UNAVAILABLE'}), /잠시 뒤 다시 접속/);
  assert.match(siteMapErrorText(new TypeError('Failed to fetch')), /연결이 끊겼습니다/);
});

test('invalid draft errors list the fields', async () => {
  const {siteMapErrorText} = await import('../../fleet/server/web/shared/site-map-model.js');
  const text = siteMapErrorText({code: 'SITE_MAP_INVALID',
    detail: {errors: [{loc: ['map', 'edges', '0', 'width_m'], msg: 'Input should be greater than 0'}]}});
  assert.match(text, /맞지 않는 값.*map\.edges\.0\.width_m: Input should be greater than 0/);
});

test('D-494 trip panel text and button reasons', async () => {
  const {tripStatusText, tripStartReason, tripCancelReason} = await import('../../fleet/server/web/shared/site-map-model.js');
  assert.equal(tripStatusText(null, MAP), '진행 중인 운행 없음');
  const trip = {state: 'running', robot_id: 'r1', current_edge: 'ab', next_place: 'B', next_action: 'stop',
    pose: {state: 'LOCALIZED', source: 'bridged'}, hold: null, reason: null};
  assert.equal(tripStatusText(trip, MAP), '운행 중 · r1 · 차로 ab · 다음 B 정지 · 자세 위치 확정 · odom 다리');
  for (const [state, label] of [['DEGRADED', '위치 정확도 저하'], ['UNKNOWN', '위치 확인 불가'], ['future', 'future']]) {
    assert.ok(tripStatusText({...trip, pose: {...trip.pose, state}}, MAP).includes(`자세 ${label} ·`));
  }
  assert.match(tripStatusText({...trip, state: 'stopped', reason: 'restart'}, MAP), /자동으로 다시 출발하지 않습니다/);
  const plan = {map_version: 1, expires_at: 100};
  const active = {version: 1};
  assert.equal(tripStartReason({role: 'operator', plan, active, running: null, now: 99}), '');
  assert.match(tripStartReason({role: 'operator', plan, active, running: null, now: 101}), /30초/);
  assert.match(tripStartReason({role: 'operator', plan, active, running: trip, now: 99}), /이 로봇은 이미 운행 중/);
  assert.match(tripStartReason({role: 'operator', plan, active: {version: 2}, running: null, now: 99}), /지도가 바뀌었습니다/);
  assert.match(tripStartReason({role: 'viewer', plan, active, running: null, now: 99}), /운영자/);
  assert.match(tripStartReason({role: 'operator', plan: null, active, running: null}), /경로를 계산/);
  assert.equal(tripCancelReason({role: 'operator', running: trip}), '');
  assert.match(tripCancelReason({role: 'operator', running: null}), /없습니다/);
});

test('D-494 trip stop reasons name the configured stall time and loop errors', async () => {
  const {tripStatusText, PLACE_KIND_LABEL} = await import('../../fleet/server/web/shared/site-map-model.js');
  const trip = {state: 'stopped', robot_id: 'r1', reason: 'stall', detail: {stall_s: 35}};
  assert.match(tripStatusText(trip, MAP), /35초 넘게 경로를 따라 나아가지 않아/);
  assert.match(tripStatusText({...trip, reason: 'TRIP_LOOP_ERROR', detail: {}}, MAP), /관제 운행 처리에 오류/);
  assert.match(tripStatusText({...trip, reason: 'junction', detail: {}}, MAP), /차선 주행을 껐습니다/);
  const unexpected = tripStatusText({...trip, reason: 'junction_unexpected', pose: {state: 'LOCALIZED', source: 'sighting', x: 1.234, y: -0.5},
    detail: {junction_state: 'waiting', junction_reason: null, line_reason: 'junction_waiting'}}, MAP);
  assert.match(unexpected, /지도에 없는 자리에서 교차로를 봐 멈췄습니다/);
  assert.match(unexpected, /지도 자세 \(1\.23, -0\.50\) · 사유 junction_waiting/);
  assert.match(tripStatusText({...trip, state: 'running', reason: null, detail: {junction_retry: 'JUNCTION_ODOM_STALE', junction_fields_dropped: 'map_version'}}, MAP),
    /odom이 낡아 교차로 지시를 다음 주기에 다시 보냅니다 · 활성 지도가 바뀌어/);
  assert.match(tripStatusText({...trip, reason: 'junction_no_window', detail: {junction_action: 'left', junction_place: 'SW'}}, MAP),
    /기대 창이 없어 좌·우 회전 지시를 보내지 않고 멈췄습니다/);  // D-507 2, 2026-10-08
  assert.equal(PLACE_KIND_LABEL.stall, undefined);
  // D-520 2
  assert.match(tripStatusText({...trip, reason: 'lane_arc', detail: {arc_reason: 'lane_arc_edge'}}, MAP),
    /회전교차로 호를 달리던 로봇이 멈췄습니다 .* · 사유 lane_arc_edge/);
  assert.match(tripStatusText({...trip, reason: 'junction', detail: {junction_reason: 'arc_mismatch'}}, MAP),
    /다른 장소의 지시라 로봇이 버렸습니다/);
  assert.match(tripStatusText({...trip, state: 'running', reason: null, detail: {arc_end_unarmed: {end_place_id: 'SE'}}}, MAP),
    /호 끝에 다음 지시가 없어/);
});

test('teach status reads the recording, then what waits for confirm', async () => {
  const {teachStatusText} = await import('../../fleet/server/web/shared/site-map-model.js');
  assert.equal(teachStatusText({recording: null, pending: []}), '기록 없음');
  assert.equal(teachStatusText({recording: {robot_id: 'r1', points: [[0, 0], [1, 0]], started_by: 'bob'}, pending: []}),
    '기록 중 · r1 · 2점 · bob');
  assert.match(teachStatusText({recording: null, pending: [{}]}), /확정 대기 1건/);
});

test('teach confirm body: a place id, or a new address name; speed is bounded', async () => {
  const {teachConfirmBody} = await import('../../fleet/server/web/shared/site-map-model.js');
  const args = {teachId: 't1', from: 'A', fromName: '', to: '', toName: ' 새 곳 ', direction: 'two_way',
    driveMode: 'lane', speed: '0.2', revision: undefined};
  assert.deepEqual(teachConfirmBody(args), {teach_id: 't1', from: 'A', to: {name: '새 곳', kind: 'junction'},
    direction: 'two_way', drive_mode: 'lane', speed_cap_mps: 0.2, expected_revision: null});
  assert.throws(() => teachConfirmBody({...args, toName: ''}), /끝 새 주소 이름/);
  assert.throws(() => teachConfirmBody({...args, speed: '0'}), /속도 상한/);
  assert.equal(teachConfirmBody({...args, revision: 'r9'}).expected_revision, 'r9');
});

test('the confirm form acts on the newest stopped recording, whatever the list order', async () => {
  const {newestPending} = await import('../../fleet/server/web/shared/site-map-model.js');
  const old = {teach_id: 'old', expires_at: 100}, fresh = {teach_id: 'new', expires_at: 200};
  assert.equal(newestPending({pending: [old, fresh]}).teach_id, 'new');
  assert.equal(newestPending({pending: [fresh, old]}).teach_id, 'new');
  assert.equal(newestPending({pending: []}), null);
  assert.equal(newestPending(null), null);
});

test('D-513 7: a turned view keeps metres round-tripping and turns directions on screen', () => {
  const view = fitView(MAP, 200, 300, 10, 90);
  for (const [x, y] of [[0, 0], [2, 0], [1, 0.3]]) {
    const back = view.toMap(...view.toPx(x, y));
    assert.ok(Math.abs(back[0] - x) < 1e-9 && Math.abs(back[1] - y) < 1e-9);
  }
  const [ax, ay] = view.toPx(0, 0), [bx, by] = view.toPx(2, 0);
  assert.ok(Math.abs(ax - bx) < 1e-9 && by > ay); // map +x points down after a 90° turn
  assert.equal(view.rotateDeg(0), 90);
  const record = {map_id: 'camera', map_to_image: [100, 0, 200, 0, -100, 100, 0, 0, 1],
    track_bounds_m: {min_x: -1.405, max_x: 1.405, min_y: -0.63, max_y: 0.63}};
  const {field} = rectangularView(record, 'camera', 480, 800, 90);
  assert.match(field.transform, /^rotate\(90 /);
  assert.ok(Math.abs(field.width / field.height - 2.81 / 1.26) < 1e-12);
});

test('D-513 7: the map keeps one view turn and refuses other angles', () => {
  const turned = editViewTurn(MAP, '90');
  assert.equal(turned.view_turn_deg, 90);
  assert.equal(viewTurnOf(MAP), 0);
  assert.equal(viewTurnOf(turned), 90);
  assert.equal(MAP.view_turn_deg, undefined);
  assert.throws(() => editViewTurn(MAP, 45), /0·90·180·270/);
});
