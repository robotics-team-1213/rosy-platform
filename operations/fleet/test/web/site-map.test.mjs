import {test} from 'node:test';
import assert from 'node:assert/strict';
import {arrowMarks, fitView, editViewTurn, viewTurnOf, planPolylines, segmentPoints, rectangularView, addApproach, removeApproach, mergeCrosswalks} from '../../../../applications/fleet/web/shared/site-map-model.js';
import {tripErrorText} from '../../../../applications/fleet/web/shared/trip-display.js';
import {
  editEdge, editPlace,
  createSurveyDraft, appendSurveyElement, reviewSurveyDraft,
  editSurveyElement, removeSurveyElement,
} from '../../../../applications/fleet/web/shared/site-map-edit.js';

const MAP = {
  places: [{id: 'A', name: 'A', x: 0, y: 0, kind: 'junction'}, {id: 'B', name: 'B', x: 2, y: 0, kind: 'park'}],
  edges: [{id: 'ab', from: 'A', to: 'B', polyline: [[0, 0], [1, 0], [2, 0]], direction: 'one_way',
           width_m: 0.2, speed_cap_mps: 0.2, drive_mode: 'lane'}],
};

test('a mapless survey starts empty at a usable metric view and rejects missing scale evidence', () => {
  const reference = {revision: 'survey-1', origin: [3, 4], heading_rad: 0, scale_source: 'odometry', description: 'Start mark'};
  const map = createSurveyDraft('new', reference);
  assert.deepEqual(map.places, []);
  assert.deepEqual(map.edges, []);
  assert.equal(map.survey.reviewed, false);
  const view = fitView(map, 800, 480);
  assert.ok(view.scale > 0 && view.scale < 1000);
  assert.deepEqual(view.toMap(...view.toPx(3, 4)), [3, 4]);
  assert.throws(() => createSurveyDraft('new', {...reference, scale_source: 'measured'}));
  assert.throws(() => createSurveyDraft('new', {...reference, origin: [NaN, 0]}));
});

test('elements grow only the draft, preserve geometry and require review after additions', () => {
  const reference = {revision: 'survey-1', origin: [0, 0], heading_rad: 0, scale_source: 'odometry', description: 'Start mark'};
  let map = createSurveyDraft('new', reference);
  const empty = structuredClone(map);
  map = appendSurveyElement(map, {id: 'a', kind: 'junction', name: 'Start', geometry: [[0, 0]]});
  map = appendSurveyElement(map, {id: 'b', kind: 'park', name: 'Destination', geometry: [[2, 0]]});
  map = appendSurveyElement(map, {id: 'ab', kind: 'road', name: 'Road', from: 'a', to: 'b',
    geometry: [[0, 0], [.8, .3], [2, 0]], width_m: .2, direction: 'two_way'});
  assert.deepEqual(empty.places, []);
  assert.deepEqual(map.edges[0].polyline, [[0, 0], [.8, .3], [2, 0]]);
  assert.equal(map.edges[0].evidence.status, 'observed');
  assert.throws(() => reviewSurveyDraft(map, ' '));
  map = reviewSurveyDraft(map, 'Origin, scale and lanes inspected');
  assert.equal(map.survey.reviewed, true);
  assert.equal(map.edges[0].evidence.status, 'reviewed');
  const next = appendSurveyElement(map, {id: 'sig', kind: 'traffic_signal', name: 'Light', geometry: [[1, .2]],
    signal_id: 's1', signal_kind: 'virtual', approaches: [{edge_id: 'ab', forward: true, stop_s_m: .8}]});
  assert.equal(next.survey.reviewed, false);
  assert.equal(map.survey.reviewed, true);
  assert.equal(next.facilities[0].approaches[0].edge_id, 'ab');
  assert.ok(fitView(next, 800, 480).toPx(1, .2).every(Number.isFinite));
  assert.throws(() => appendSurveyElement(map, {id: 'x', kind: 'road', name: 'X', from: 'a', to: 'missing', geometry: []}));
});

test('survey corrections preserve lane endpoints and refuse deleting referenced elements', () => {
  let map = createSurveyDraft('new', {revision: 'r1', origin: [0, 0], heading_rad: 0,
    scale_source: 'odometry', description: 'Start'});
  map = appendSurveyElement(map, {id: 'a', kind: 'junction', name: 'A', geometry: [[0, 0]]});
  map = appendSurveyElement(map, {id: 'b', kind: 'park', name: 'B', geometry: [[2, 0]]});
  map = appendSurveyElement(map, {id: 'ab', kind: 'road', name: 'ab', geometry: [[0, 0], [2, 0]],
    from: 'a', to: 'b', width_m: .2, direction: 'two_way'});
  assert.throws(() => removeSurveyElement(map, 'a'));
  const corrected = editSurveyElement(map, {id: 'b', kind: 'park', name: 'B', geometry: [[2, .1]]});
  assert.deepEqual(corrected.edges[0].polyline.at(-1), [2, .1]);
  assert.deepEqual(map.edges[0].polyline.at(-1), [2, 0]);
  assert.equal(corrected.survey.reviewed, false);
  const removed = removeSurveyElement(removeSurveyElement(corrected, 'ab'), 'b');
  assert.equal(removed.places.length, 1);
});

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
  const {actionRows, planIsCurrent, siteMapErrorText} = await import('../../../../applications/fleet/web/shared/site-map-model.js');
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
  const {siteMapErrorText} = await import('../../../../applications/fleet/web/shared/site-map-model.js');
  const text = siteMapErrorText({code: 'SITE_MAP_INVALID',
    detail: {errors: [{loc: ['map', 'edges', '0', 'width_m'], msg: 'Input should be greater than 0'}]}});
  assert.match(text, /맞지 않는 값.*map\.edges\.0\.width_m: Input should be greater than 0/);
});

test('D-494 trip panel text and button reasons', async () => {
  const {tripStartReason} = await import('../../../../applications/fleet/web/shared/site-map-model.js');
  const {tripStatusText} = await import('../../../../applications/fleet/web/shared/trip-display.js');
  assert.equal(tripStatusText(null, MAP), '진행 중인 운행 없음');
  const trip = {state: 'running', robot_id: 'r1', current_edge: 'ab', next_place: 'B', next_action: 'stop',
    pose: {state: 'LOCALIZED', source: 'bridged'}, hold: null, reason: null};
  assert.equal(tripStatusText(trip, MAP), '운행 중 · r1 · 차로 ab · 다음 B 정지 · 자세 위치 확정 · odom 다리');
  for (const [state, label] of [['DEGRADED', '위치 정확도 저하'], ['UNKNOWN', '위치 확인 불가'], ['future', 'future']]) {
    assert.ok(tripStatusText({...trip, pose: {...trip.pose, state}}, MAP).includes(`자세 ${label} ·`));
  }
  assert.match(tripStatusText({...trip, state: 'stopped', reason: 'restart'}, MAP), /자동으로 다시 출발하지 않습니다/);
  // D-763 8: the wait shows on an open trip only; a canceled trip keeps its last stored wait
  const waiting = {...trip, wait: {reason: 'signal', waiting: true, over_bound: false}};
  assert.match(tripStatusText(waiting, MAP), / · 대기 · 신호$/);
  assert.doesNotMatch(tripStatusText({...waiting, state: 'canceled'}, MAP), /대기/);
  // D-517 3 (2026-10-09 "다음 지점까지 가서 섬"): the moved destination is shown
  assert.match(tripStatusText({...trip, stop_moved: {from: 'A', to: 'B'}}, MAP), /목적지 .+ → .+ · 교차로 안에 서지 않도록 다음 지점에서 섭니다/);
  assert.match(tripStatusText({...trip, stop_moved: {from: null, to: 'B'}}, MAP), /목적지 좌표 → /);
  const plan = {map_version: 1, expires_at: 100};
  const active = {version: 1};
  assert.equal(tripStartReason({role: 'operator', plan, active, running: null, now: 99}), '');
  assert.match(tripStartReason({role: 'operator', plan, active, running: null, now: 101}), /30초/);
  assert.match(tripStartReason({role: 'operator', plan, active, running: trip, now: 99}), /이 로봇은 이미 운행 중/);
  assert.match(tripStartReason({role: 'operator', plan, active: {version: 2}, running: null, now: 99}), /지도가 바뀌었습니다/);
  assert.match(tripStartReason({role: 'viewer', plan, active, running: null, now: 99}), /운영자/);
  assert.match(tripStartReason({role: 'operator', plan: null, active, running: null}), /경로를 계산/);
});

test('D-541 7 trip lease: held shown, a lost lease names the CORE reason and who', async () => {
  const {tripStatusText, tripErrorText} = await import('../../../../applications/fleet/web/shared/trip-display.js');
  const trip = {state: 'running', robot_id: 'r1', reason: null, detail: {}, lease: {state: 'held'}};
  assert.match(tripStatusText(trip, MAP), /CORE 점유 중/);
  const lost = {...trip, state: 'stopped', reason: 'lease_lost', lease: {state: 'lost'},
    detail: {lease_reason: 'taken_over', lease_by: 'kim-tablet'}};
  assert.match(tripStatusText(lost, MAP), /운행 끝 · 다시 몰려면 새 운행을 시작하세요 · 로봇 화면·Pilot에서 넘겨받음\(kim-tablet\)/);
  assert.doesNotMatch(tripStatusText(lost, MAP), /CORE 점유 중/);
  assert.match(tripStatusText({...lost, detail: {lease_reason: 'core_restarted'}}, MAP), /CORE가 다시 시작됨$/);
  assert.match(tripErrorText('TRIP_ROBOT_MANUAL'), /멈춤\(IDLE\)/);
});

test('D-494 trip stop reasons name the configured stall time and loop errors', async () => {
  const {PLACE_KIND_LABEL} = await import('../../../../applications/fleet/web/shared/site-map-model.js');
  const {tripStatusText} = await import('../../../../applications/fleet/web/shared/trip-display.js');
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
  assert.match(tripStatusText({...trip, reason: 'junction_corner_hold', detail: {line_reason: 'junction_corner_hold'}}, MAP),
    /차선 모서리로 돌지 않게 멈췄습니다/);  // lap SIM A
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
  const {teachStatusText} = await import('../../../../applications/fleet/web/shared/site-map-model.js');
  assert.equal(teachStatusText({recording: null, pending: []}), '기록 없음');
  assert.equal(teachStatusText({recording: {robot_id: 'r1', points: [[0, 0], [1, 0]], started_by: 'bob'}, pending: []}),
    '기록 중 · r1 · 2점 · bob');
  assert.match(teachStatusText({recording: null, pending: [{}]}), /확정 대기 1건/);
});

test('survey teach start requires a saved explicit basis and a checked physical origin', async () => {
  const {teachStartBody} = await import('../../../../applications/fleet/web/shared/site-map-edit.js');
  const draft = {revision: 'd1', map: {map_id: 'yard', survey: {revision: 'r1'}}};
  assert.deepEqual(teachStartBody({robotId: 'r1', mode: 'map'}), {robot_id: 'r1'});
  assert.throws(() => teachStartBody({robotId: 'r1', mode: 'survey', draft, confirmed: false}), /시작점/);
  assert.throws(() => teachStartBody({robotId: 'r1', mode: 'survey', confirmed: true}), /저장/);
  assert.deepEqual(teachStartBody({robotId: 'r1', mode: 'survey', draft, confirmed: true}),
    {robot_id: 'r1', mode: 'survey', map_id: 'yard', reference_revision: 'r1', expected_revision: 'd1'});
});

test('survey records are shown only against their original coordinate reference', async () => {
  const {surveyTeachMatches} = await import('../../../../applications/fleet/web/shared/site-map-edit.js');
  const reference = {revision: 'r1', origin: [1, 2], heading_rad: 0, description: 'mark'};
  const record = {mode: 'survey', map_id: 'yard', survey_reference: reference};
  const map = {map_id: 'yard', survey: {...reference, reviewed: true, review_note: 'checked'}};
  assert.equal(surveyTeachMatches(record, map), true);
  assert.equal(surveyTeachMatches(record, {...map, map_id: 'other'}), false);
  assert.equal(surveyTeachMatches(record, {...map, survey: {...reference, origin: [9, 2]}}), false);
  assert.equal(surveyTeachMatches(record, null), false);
});

test('teach confirm body: a place id, or a new address name; speed is bounded', async () => {
  const {teachConfirmBody} = await import('../../../../applications/fleet/web/shared/site-map-model.js');
  const args = {teachId: 't1', from: 'A', fromName: '', to: '', toName: ' 새 곳 ', direction: 'two_way',
    driveMode: 'lane', speed: '0.2', revision: undefined};
  assert.deepEqual(teachConfirmBody(args), {teach_id: 't1', from: 'A', to: {name: '새 곳', kind: 'junction'},
    direction: 'two_way', drive_mode: 'lane', speed_cap_mps: 0.2, expected_revision: null});
  assert.throws(() => teachConfirmBody({...args, toName: ''}), /끝 새 주소 이름/);
  assert.throws(() => teachConfirmBody({...args, speed: '0'}), /속도 상한/);
  assert.equal(teachConfirmBody({...args, revision: 'r9'}).expected_revision, 'r9');
});

test('the confirm form acts on the newest stopped recording, whatever the list order', async () => {
  const {newestPending} = await import('../../../../applications/fleet/web/shared/site-map-model.js');
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

test('the existing place and lane editors invalidate survey review after a change', () => {
  const map = {...MAP, survey: {revision: 'survey-1', reviewed: true, review_note: 'measured'},
    edges: MAP.edges.map(edge => ({...edge, evidence: {source: 'odometry', status: 'reviewed',
      reference_revision: 'survey-1', note: 'measured'}}))};
  const lane = editEdge(map, 'ab', {direction: 'two_way'});
  assert.equal(lane.survey.reviewed, false);
  assert.equal(lane.survey.review_note, '');
  assert.equal(lane.edges[0].evidence.source, 'operator');
  assert.equal(lane.edges[0].evidence.status, 'observed');
  assert.equal(editPlace(map, 'B', {kind: 'charge'}).survey.reviewed, false);
  assert.equal(map.survey.reviewed, true);
  assert.equal(map.edges[0].evidence.status, 'reviewed');
});

test('D-573 waiting bands are added mm-rounded, capped at four, removed by index and kept across a lane_graph merge', () => {
  const map = {...MAP, crosswalks: [{id: 'cw1', polygon: [[0.9, -0.1], [1.1, -0.1], [1.1, 0.1]], approach: [], lanes: ['ab'], revision: 'r1'}]};
  const band = [[0.9, 0.1], [1.1, 0.1], [1.10049, 0.3]];
  const one = addApproach(map, 'cw1', band);
  assert.deepEqual(one.crosswalks[0].approach, [[[0.9, 0.1], [1.1, 0.1], [1.1, 0.3]]]);
  assert.deepEqual(map.crosswalks[0].approach, []);  // pure
  assert.throws(() => addApproach(map, 'cw1', band.slice(0, 2)));
  assert.throws(() => addApproach(map, 'nope', band));
  let full = one;
  for (let i = 0; i < 3; i += 1) full = addApproach(full, 'cw1', band);
  assert.throws(() => addApproach(full, 'cw1', band));
  assert.deepEqual(removeApproach(one, 'cw1', 0).crosswalks[0].approach, []);
  assert.throws(() => removeApproach(map, 'cw1', 0));
  const merged = mergeCrosswalks(one, [{id: 'cw1', polygon: [[0, 0], [1, 0], [1, 1]], approach: [], lanes: [], revision: 'r2'},
    {id: 'cw2', polygon: [[2, 0], [3, 0], [3, 1]], approach: [], lanes: [], revision: 'r2'}]);
  assert.deepEqual(merged.crosswalks.map(c => [c.id, c.revision, c.approach.length]), [['cw1', 'r2', 1], ['cw2', 'r2', 0]]);
});
test("soccer profile template uses measured metres and never creates driving lanes", async () => {
  const { soccerProfileMap } = await import("../../../../applications/fleet/web/shared/site-map-model.js");
  const map = soccerProfileMap({length_m: 2, width_m: 1.4, goal_width_m: 0.35}, "pitch");
  assert.equal(map.map_id, "pitch");
  assert.deepEqual(map.places.map(p => [p.x, p.y]), [[-1, -0.7], [1, -0.7], [1, 0.7], [-1, 0.7]]);
  assert.deepEqual(map.edges, []);
  assert.throws(() => soccerProfileMap({length_m: 2, width_m: 1, goal_width_m: 2}, "pitch"));
});


test('survey edits preserve legal IDs shared across categories', async () => {
  const {editSurveyElement, removeSurveyElement} = await import('../../../../applications/fleet/web/shared/site-map-edit.js');
  const map = {schema: 'rosy.site_map/1', places: [{id: 'a', name: 'Place', kind: 'park', x: 0, y: 0}], edges: [],
    facilities: [{id: 'a', name: 'Marker', kind: 'landmark', geometry: [[1, 1]], approaches: []}],
    survey: {revision: 's1', reviewed: true}};
  const edited = editSurveyElement(map, {id: 'a', name: 'Moved', kind: 'park', geometry: [[2, 2]]});
  assert.deepEqual(edited.facilities, map.facilities);
  const deleted = removeSurveyElement(map, 'a', 'facilities');
  assert.deepEqual(deleted.places, map.places);
  assert.deepEqual(deleted.facilities, []);
  assert.throws(() => removeSurveyElement(map, 'a'), /category/);
  assert.equal(map.survey.reviewed, true);
});



test('normal teach previews follow their captured frame and cannot overlay another profile', async () => {
  const {teachFrameMatches} = await import('../../../../applications/fleet/web/shared/site-map-edit.js');
  const record = {mode: 'map', map_id: 'site'};
  assert.equal(teachFrameMatches(record, MAP), true);
  assert.equal(teachFrameMatches(record, {...MAP, map_id: 'other'}), false);
  assert.equal(teachFrameMatches(record, {...MAP, survey: {revision: 'new'}}), false);
  assert.equal(teachFrameMatches({}, MAP), false);
  const reference = {revision: 's1', origin: [1, 2]};
  const observed = {...record, survey_reference: reference};
  assert.equal(teachFrameMatches(observed, {...MAP, survey: {...reference, reviewed: true}}), true);
  assert.equal(teachFrameMatches(observed, {...MAP, survey: {...reference, origin: [3, 4]}}), false);
});


test('camera observations accumulate in the same survey without invented joins or duplicate roads', async () => {
  const {mergeCameraMap} = await import('../../../../applications/fleet/web/shared/site-map-edit.js');
  const reference = {revision: 's1', origin: [0, 0], heading_rad: 0, scale_source: 'measured',
    measured_distance_m: 2, description: 'Measured frame'};
  const base = {...MAP, map_id: 'yard', survey: {...reference, reviewed: true, review_note: 'Checked'},
    facilities: [{id: 'light', kind: 'landmark', name: 'Mark', geometry: [[0, 1]], approaches: []}]};
  const observation = {schema: 'rosy.site_map/1', map_id: 'yard', survey: {...reference, reviewed: false, review_note: ''},
    places: [{id: 'A', name: 'Camera A', kind: 'junction', x: 3, y: 0},
      {id: 'B', name: 'Camera B', kind: 'junction', x: 4, y: 0}],
    edges: [{...MAP.edges[0], from: 'A', to: 'B', polyline: [[3, 0], [4, 0]],
      evidence: {source: 'camera', status: 'observed', reference_revision: 's1', note: 'Frame abc'}}]};
  const merged = mergeCameraMap(base, observation);
  assert.equal(merged.edges.length, 2);
  assert.equal(merged.places.length, 4);
  assert.equal(new Set(merged.places.map(p => p.id)).size, 4);
  assert.deepEqual(merged.facilities, base.facilities);
  assert.equal(merged.edges[1].evidence.note, 'Frame abc');
  assert.equal(merged.survey.reviewed, false);
  assert.equal(base.survey.reviewed, true);
  assert.deepEqual(mergeCameraMap(merged, observation), merged);
  assert.throws(() => mergeCameraMap(base, {...observation, map_id: 'other'}));
  assert.throws(() => mergeCameraMap(base, {...observation, survey: {...reference, origin: [1, 0]}}));
  assert.throws(() => mergeCameraMap(base, {...observation, places: observation.places.map(p => ({...p, x: p.x - 3}))}));
  assert.throws(() => mergeCameraMap(base, {...observation, edges: observation.edges.map(e => ({...e, evidence: undefined}))}));
  assert.throws(() => mergeCameraMap(base, {...observation, survey: {}}));
  const reviewed = reviewSurveyDraft(merged, 'Measured lanes');
  assert.ok(reviewed.edges[1].evidence.note.includes('Frame abc'));
  assert.ok(reviewed.edges[1].evidence.note.includes('Measured lanes'));
  const repeated = {...observation, edges: observation.edges.map(e => ({...e, evidence: {...e.evidence, note: 'Frame xyz'}}))};
  const accumulated = mergeCameraMap(reviewed, repeated);
  assert.equal(accumulated.edges.length, 2);
  assert.ok(accumulated.edges[1].evidence.note.includes('Frame abc'));
  assert.ok(accumulated.edges[1].evidence.note.includes('Frame xyz'));
  assert.equal(accumulated.edges[1].evidence.status, 'observed');
  assert.equal(accumulated.survey.reviewed, false);
  assert.deepEqual(mergeCameraMap(accumulated, repeated), accumulated);
  assert.throws(() => mergeCameraMap(accumulated, {...repeated, edges: repeated.edges.map(e => ({...e,
    evidence: {...e.evidence, note: 'x'.repeat(1000)}}))}), /1000/);
  const corrected = editSurveyElement(reviewed, {id: reviewed.edges[1].id, kind: 'road', name: 'Observed road',
    from: reviewed.edges[1].from, to: reviewed.edges[1].to, geometry: [[3, 0], [3.5, .1], [4, 0]], width_m: .2, direction: 'one_way'});
  assert.ok(corrected.edges[1].evidence.note.includes('Frame abc'));
  const place = reviewed.places[2];
  assert.ok(editSurveyElement(reviewed, {id: place.id, name: place.name, kind: place.kind,
    geometry: [[3, .1]]}).edges[1].evidence.note.includes('Frame abc'));
});

test('camera maps without a survey can be reviewed and edits require re-review', () => {
  const map = {...MAP, edges: MAP.edges.map(e => ({...e, evidence: {source: 'camera', status: 'observed',
    reference_revision: 'cal_123', note: 'frame sha256 abc'}}))};
  const reviewed = reviewSurveyDraft(map, 'Checked metric calibration and lane direction');
  assert.equal(reviewed.survey, undefined);
  assert.equal(reviewed.edges[0].evidence.status, 'reviewed');
  assert.equal(reviewed.edges[0].evidence.reference_revision, 'cal_123');
  assert.ok(reviewed.edges[0].evidence.note.includes('frame sha256 abc'));
  assert.equal(editEdge(reviewed, 'ab', {direction: 'two_way'}).edges[0].evidence.status, 'observed');
});

test('camera endpoint connections need explicit same-frame review and remain inferred until approved', async () => {
  const {cameraConnectionCandidates, mergeCameraMap} = await import('../../../../applications/fleet/web/shared/site-map-edit.js');
  const survey = {revision: 's1', origin: [0, 0], heading_rad: 0, scale_source: 'odometry', description: 'Marked origin'};
  const base = {...MAP, map_id: 'yard', survey};
  const observation = {schema: 'rosy.site_map/1', map_id: 'yard', survey,
    places: [{id: 'near', name: 'Observed endpoint', kind: 'junction', x: 2.02, y: 0},
      {id: 'far', name: 'Branch end', kind: 'junction', x: 3, y: 1}],
    edges: [{id: 'branch', from: 'near', to: 'far', polyline: [[2.02, 0], [2.5, .5], [3, 1]],
      direction: 'two_way', drive_mode: 'lane', width_m: .2, speed_cap_mps: .03,
      evidence: {source: 'camera', status: 'observed', reference_revision: 's1', note: 'frame sha256 abc'}}]};
  const candidates = cameraConnectionCandidates(base, observation);
  assert.equal(candidates.length, 1);
  assert.equal(candidates[0].observation_id, 'near');
  assert.equal(candidates[0].candidates[0].id, 'B');
  assert.ok(Math.abs(candidates[0].candidates[0].distance_m - .02) < 1e-9);
  assert.throws(() => mergeCameraMap(base, observation));
  assert.throws(() => mergeCameraMap(base, observation, {near: 'A'}));
  assert.throws(() => mergeCameraMap(base, observation, {typo: 'B'}));
  const joined = mergeCameraMap(base, observation, {near: 'B'});
  assert.equal(joined.places.length, 3);
  assert.equal(joined.edges[1].from, 'B');
  assert.deepEqual(joined.edges[1].polyline, [[2, 0], [2.5, .5], [3, 1]]);
  assert.equal(joined.edges[1].evidence.status, 'inferred');
  assert.ok(joined.edges[1].evidence.note.includes('frame sha256 abc'));
  assert.ok(joined.edges[1].evidence.note.includes('near -> B'));
  assert.deepEqual(base.places, MAP.places);
  assert.equal(reviewSurveyDraft(joined, 'Endpoint connection checked').edges[1].evidence.status, 'reviewed');
  assert.deepEqual(mergeCameraMap(joined, observation, {near: 'B'}), joined);
  const alternate = {...joined, places: [...joined.places, {...joined.places[1], id: 'C'}]};
  const connections = {near: 'C', far: joined.places[2].id};
  const differentTarget = mergeCameraMap(alternate, observation, connections);
  assert.equal(differentTarget.edges.length, 3);
  assert.equal(differentTarget.edges[2].from, 'C');
  assert.ok(differentTarget.edges[2].evidence.note.includes('near -> C'));
  assert.deepEqual(mergeCameraMap(differentTarget, observation, connections), differentTarget);
  const unrestricted = mergeCameraMap({...joined, edges: joined.edges.map(e => ({...e, robot_kinds: ['pinky']}))},
    observation, {...connections, near: 'B'});
  assert.equal(unrestricted.edges.length, 3);
  assert.equal(unrestricted.edges[1].robot_kinds[0], 'pinky');
  assert.equal(unrestricted.edges[2].robot_kinds, undefined);
  assert.throws(() => cameraConnectionCandidates(base, {...observation, map_id: 'other'}));
});
