// Map vs where robots actually drove (D-594 path history): report only, and one draft correction.
import {confirmIrreversible} from '/common/ui.js';

const VERDICT = {
  match: '지도가 운행 경로와 맞습니다',
  partial: '일부 차로만 운행 기록과 맞습니다',
  offset: '지도 전체가 운행 경로에서 벗어나 있습니다',
  unmapped: '운행 기록과 지도가 다른 차로입니다',
  mismatch: '로봇이 금지 구역을 지나갔습니다',
  no_evidence: '이 구간에 운행 기록이 없습니다',
};
const LANE_STATE = {matched: '맞음', offset: '벗어남', uncovered: '운행 없음'};
const ZONE_STATE = {clear: '들어가지 않음', entered: '지나감', used: '지나감'};

export function createRealityPanel(host) {
  const $ = id => document.getElementById(id);
  let report = null, roster = '';
  function fillRobots() {
    const rows = host.robots();
    const key = rows.map(robot => robot.robot_id).join(',');
    if (key === roster) return;
    roster = key;
    const keep = $('reality-robot').value;
    $('reality-robot').replaceChildren(new Option('모든 로봇', ''),
      ...rows.map(robot => new Option(robot.robot_id, robot.robot_id)));
    if ([...$('reality-robot').options].some(option => option.value === keep)) $('reality-robot').value = keep;
  }
  function item(text) {
    const row = document.createElement('li');
    row.textContent = text;
    return row;
  }
  function lines(list, rows) {
    list.replaceChildren(...(rows.length ? rows.map(item) : [item('해당 없음')]));
  }
  function describe() {
    if (!report) return '아직 대조하지 않았습니다';
    const lanes = report.lanes || [], zones = report.zones || [], fit = report.fit;
    const counts = state => lanes.filter(lane => lane.state === state).length;
    const parts = [`차로 ${lanes.length}개 중 맞음 ${counts('matched')} · 벗어남 ${counts('offset')} · 운행 없음 ${counts('uncovered')}`];
    if (report.off_lane) parts.push(`차로 밖 운행 ${report.off_lane.points}점`);
    if (fit?.before_median_m != null) parts.push(`차로까지 중앙값 ${fit.before_median_m} m`);
    if (fit?.accepted) parts.push(`보정하면 ${fit.after_median_m} m · ${fit.yaw_deg}° 이동`);
    parts.push(...(report.notes || []));
    lines($('reality-lanes'), lanes.map(lane =>
      `${lane.name} · ${LANE_STATE[lane.state] || lane.state} · 치우침 ${lane.median_offset_m ?? '-'} m · 운행이 덮은 비율 ${Math.round(lane.coverage * 100)}%`));
    lines($('reality-zones'), zones.map(zone =>
      `${zone.name} · ${zone.kind} · ${ZONE_STATE[zone.state] || zone.state} · ${zone.points}점`));
    return parts.join(' · ');
  }
  function sync() {
    fillRobots();
    const reason = host.reason();
    host.gate('reality-check', reason);
    host.gate('reality-apply', reason || (host.dirty() ? '수정한 초안을 먼저 저장하세요' : '')
      || (!host.draft()?.revision ? '초안을 먼저 저장하세요' : '')
      || (!report ? '먼저 대조하세요' : !report.fit?.accepted ? '적용할 보정이 없습니다' : ''));
    host.status('reality-verdict', describe(),
      report ? (report.verdict === 'match' ? 'ready' : 'pending') : 'empty');
  }
  function query() {
    const robot = $('reality-robot').value;
    return `last_s=${encodeURIComponent($('reality-window').value)}${robot ? `&robot_id=${encodeURIComponent(robot)}` : ''}`;
  }
  $('reality-check').addEventListener('click', () => host.guarded(async () => {
    if (host.reason()) return;
    const path = '/api/fleet/site-map/reality-check';  // the feature matrix pins this literal
    report = await host.request(query() ? `${path}?${query()}` : path);
    sync();
    host.notice(report.verdict === 'match' ? '지도와 운행 경로가 맞습니다.'
      : report.fit?.accepted ? '지도가 운행 경로에서 벗어났습니다 · 초안 보정을 적용할 수 있습니다.'
      : `보정할 수 없습니다 · ${report.fit?.reason || report.notes.join(' · ') || VERDICT[report.verdict]}`);
  }));
  $('reality-apply').addEventListener('click', () => host.guarded(async () => {
    const draft = host.draft();
    if (host.reason() || host.dirty() || !draft?.revision || !report?.fit?.accepted) return;
    if (!await confirmIrreversible({message: '초안의 모든 장소·도로·구역을 운행 경로에 맞춰 옮길까요? 활성 지도는 바뀌지 않습니다.',
      action: '초안 보정', opener: $('reality-apply')})) return;
    const robot = $('reality-robot').value;
    await host.request('/api/fleet/site-map/reality-check/apply', {method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({expected_revision: draft.revision, last_s: Number($('reality-window').value),
        ...(robot ? {robot_id: robot} : {})})});
    report = null;
    await host.reload();
    host.notice('초안을 운행 경로에 맞춰 옮겼습니다. 차로·구역을 다시 대조하고 검토한 뒤 활성화하세요.');
  }));
  $('reality-robot').addEventListener('change', sync);
  return {sync};
}
