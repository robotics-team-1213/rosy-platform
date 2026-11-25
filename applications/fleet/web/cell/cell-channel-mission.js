import {setOffBy} from '/common/cause-line.js';
import {confirmIrreversible} from '/common/ui.js';
import {isOperator, namedOperatorReason, OPERATOR_REASON} from '/console/assets/authorization.js';
import {owns, relays} from '/console/assets/unit-scope.js';

export function createChannelMission({$, scope, api, post, action, channelPath, state, setReview, jobStatusLabel}) {
  const checkResult = '결과 미확인 · 페이지를 새로고침해 요청 상태를 확인하세요.';
  let needsReadback = false;

  function lockReason() {
    if (needsReadback) return checkResult;
    const {role, principal} = state();
    return !owns('arms') ? '팔을 맡은 셀 관제에서 준비하세요.'
      : !isOperator(role) ? OPERATOR_REASON : namedOperatorReason(role, principal);
  }

  async function submit(path, body, life) {
    try {
      const result = await post(channelPath + path, body, [life.signal]);
      life.check(); setReview(result);
    } catch (error) {
      if (!life.current() || [401, 403].includes(error.status)) throw error;
      needsReadback = true;
      throw new Error(checkResult);
    }
  }

  function paint() {
    const {review, busy} = state();
    const linked = review?.state === 'LINKED', mission = review?.work_kind === 'mission';
    const picker = $('cell-channel-mission'), status = $('cell-channel-mission-state');
    const reason = busy ? '요청 처리 중' : lockReason();
    $('cell-channel-mission-candidate').hidden = !review || linked;
    $('cell-channel-mission-approval').hidden = !mission || review.work_status !== 'PROPOSED';
    status.hidden = !mission;
    status.textContent = mission ? `팔 작업 ${review.work_id} · ${jobStatusLabel(review.work_status)}` : '';
    setOffBy(picker, reason);
    setOffBy($('cell-channel-mission-prepare'), reason || (picker.options.length < 2 ? '준비할 팔 작업 후보가 없습니다' : ''));
    setOffBy($('cell-channel-mission-admit'), reason);
  }

  $('cell-channel-mission-prepare').addEventListener('click', () => action(async () => {
    const snapshot = state().review, sourceId = $('cell-channel-mission').value, reason = $('cell-channel-reason').value.trim();
    if (!snapshot || snapshot.state === 'LINKED' || lockReason()) return;
    if (!sourceId || !reason) throw new Error('내 팔 작업 후보와 검토 사유를 확인하세요.');
    const life = scope.capture(), signals = [life.signal];
    const source = await api(`/api/fleet/proposals/${encodeURIComponent(sourceId)}`, {signals});
    life.check();
    if (!source.mission || state().review !== snapshot || lockReason()) throw new Error('현재 팔 작업 후보를 다시 확인하세요.');
    await submit('/prepare', {kind: 'mission', source_proposal_id: sourceId,
      workcell_id: source.mission.workcell_id, instance_id: source.mission.instance_id, reason,
      expected_hash: snapshot.content_hash, expected_revision: snapshot.revision}, life);
    $('notice').textContent = '팔 작업을 준비했습니다. 내용을 확인한 뒤 실행을 승인하세요.';
  }));

  $('cell-channel-mission-admit').addEventListener('click', () => action(async () => {
    const snapshot = state().review, epoch = state().epoch;
    if (snapshot?.work_kind !== 'mission' || snapshot.work_status !== 'PROPOSED' || lockReason() || relays()) return;
    const life = scope.capture(), signals = [life.signal];
    const control = await api('/api/fleet/dispatch-control', {signals});
    life.check();
    if (control.dispatch_enabled !== true) throw new Error('사이트 정지 상태와 현재 작업을 확인하세요.');
    const allowed = await confirmIrreversible({message: `팔 작업 ${snapshot.work_id}의 실행을 승인할까요?`,
      action: '실행 승인', opener: $('cell-channel-mission-admit'), signal: life.signal});
    if (!allowed || !life.current() || state().epoch !== epoch || state().review !== snapshot || lockReason() || relays()) {
      $('notice').textContent = '현재 팔 작업의 승인 상태를 확인하세요.';
      return;
    }
    await submit('/admit', {expected_hash: snapshot.content_hash, expected_revision: snapshot.revision,
      expected_generation: control.generation}, life);
    $('notice').textContent = '팔 작업 승인 결과를 받았습니다.';
  }));

  async function loadCandidates() {
    needsReadback = false;
    const picker = $('cell-channel-mission');
    picker.replaceChildren(new Option('후보 선택', ''));
    if (state().review?.state === 'LINKED') return;
    try {
      const {rows} = await api('/api/fleet/work');
      for (const row of rows.filter(row => row.source === 'mission' && row.status === 'PROPOSED')) {
        picker.append(new Option(`${row.source_id} · ${row.workcell_id}`, row.source_id));
      }
    } catch (error) {
      if (error.status !== 404) throw error;
    }
  }
  return {loadCandidates, paint, get needsReadback() { return needsReadback; }};
}
