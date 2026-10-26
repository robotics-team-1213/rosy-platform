const node = (tag, text = '') => {
  const value = document.createElement(tag); value.textContent = text; return value;
};

export function analysisText(analysis, elapsedS = 0) {
  if (!analysis) return '최근 하중 분석 없음';
  const age = analysis.age_s + elapsedS;
  const bindingUnknown = analysis.source_binding_status && analysis.source_binding_status !== 'matched';
  const fresh = !bindingUnknown && analysis.fresh && analysis.evidence_age_s + elapsedS <= analysis.max_age_s;
  const state = analysis.status === 'hold_for_owner_review' ? '담당자 점검 필요' : '관측 중';
  const unknown = bindingUnknown ? '관측원 연결 미확인 · 현재 상태 미확인' : '근거 만료·누락 · 현재 상태 미확인';
  return `${fresh ? state : unknown} · ${Math.floor(age)}초 전 분석`
    + (analysis.reasons.length ? ` · ${analysis.reasons.join(', ')}` : '');
}

export function profileBindingMismatch(profile, expected) {
  if (!profile || !expected) return null;
  const previous = profile.source_binding;
  if (!previous || !expected.owner_id || !expected.sha256) return 'unverified_link';
  if (previous.owner_id !== expected.owner_id) return 'owner_changed';
  return previous.sha256 === expected.sha256 ? null : 'registration_changed';
}

export function paintProfile(root, profile, {elapsedS = 0, unavailable = false, historyOpen = false,
  bindingStatus = null, editDeviceId = null} = {}) {
  root.replaceChildren(node('h4', '로봇 프로필 · 주의사항'));
  const changed = ['owner_changed', 'registration_changed', 'source_unregistered', 'unverified_link']
    .includes(bindingStatus || profile?.source_binding_status);
  if (changed) root.append(node('p', '관측원 등록이 달라졌거나 연결 근거가 없습니다. 프로필 연결을 다시 확인하세요.'));
  if (unavailable) root.append(node('p', '프로필을 읽지 못했습니다. 현재 상태는 실시간 관측에서 확인하세요.'));
  if (!profile) {
    if (!unavailable && !changed) root.append(node('p', '연결된 프로필이 없습니다. 장치 정보에서 연결하세요.'));
  } else {
    root.append(node('p', `${profile.display_name} · ${profile.model || '모델 미입력'}`),
      node('p', profile.caution || '저장된 주의사항 없음 · 고장 없음의 증거가 아닙니다.'));
    const diagnosis = node('p', analysisText(profile.latest_analysis, elapsedS));
    diagnosis.dataset.profileDiagnosis = '';
    root.append(diagnosis);
    const characteristic = profile.characteristics_summary;
    const traits = node('p', characteristic
      ? `특성 ${characteristic.revision} · ${characteristic.status === 'measured' ? '측정 기록 · 운용 수용 미확인' : '미측정 초안'} · 관절 ${characteristic.joint_count}개 · 측정 구간 ${characteristic.envelope_count}개`
      : '특성 JSON 미등록');
    traits.dataset.profileCharacteristics = '';
    root.append(traits, node('p', '분석은 점검 권고입니다. 명령 연결과 실제 정지·복구는 확인되지 않았습니다.'));
    if (profile.events.length || profile.source_id || profile.latest_analysis) {
      const history = node('details'), list = node('ul');
      history.open = historyOpen;
      history.append(node('summary', `최근 기록 ${profile.events.length}건 · 연결·분석 출처`));
      const origin = node('dl'); origin.className = 'ui-readout'; origin.dataset.profileOrigin = '';
      const analysis = profile.latest_analysis;
      const rows = [['프로필', profile.device_id],
        ['설정된 관측원', profile.source_id ? `${profile.source_kind}/${profile.source_id}` : '연결 안 함'],
        ['연결 당시 owner', profile.source_binding?.owner_id || '미확인'],
        ['현재 등록 owner', profile.registered_owner_id || '미확인']];
      if (analysis) rows.push(
        ['분석 owner / 모터 그룹', `${analysis.context?.owner_id || '미확인'} / ${analysis.context?.motor_group || '미확인'}`],
        ['분석 시각', new Date(analysis.assessed_at * 1000).toLocaleString()],
        ['모터 관측 시각', analysis.captured_at ? new Date(analysis.captured_at * 1000).toLocaleString() : '근거 없음'],
        ['특성 SHA-256', analysis.characteristics_sha256],
        ['관측 세션', analysis.session_id], ['명령 (대조 미확인)', analysis.command_id]);
      for (const [label, value] of rows) origin.append(node('dt', label), node('dd', value || '미확인'));
      history.append(origin);
      for (const event of profile.events) {
        const label = {fault: '고장 관찰', caution: '주의', maintenance: '정비', analysis: '분석 주의'}[event.kind];
        list.append(node('li', `${label} · ${event.text} · ${new Date(event.created_at * 1000).toLocaleString()} · ${event.actor}`));
      }
      if (profile.events.length) history.append(list);
      root.append(history);
    }
  }
  const link = node('a', '프로필·주의사항 편집');
  const deviceId = profile?.device_id || editDeviceId;
  link.href = `/console/install${deviceId ? '?profile=' + encodeURIComponent(deviceId) : ''}#device-profiles`;
  root.append(link);
}

export function createRobotProfiles({call, scope, render = () => {}}) {
  const cache = new Map();
  let disposed = false;
  scope.onDispose(() => { disposed = true; cache.clear(); });
  function detail(kind, source, expectedBinding = null) {
    const root = node('section'); root.dataset.robotProfile = source;
    const key = `${kind}/${encodeURIComponent(source)}`;
    let entry = cache.get(key);
    if (!entry) { entry = {next: 0, received: performance.now(), profile: null}; cache.set(key, entry); }
    if (!disposed && !entry.pending && performance.now() >= entry.next) {
      entry.pending = true; entry.next = performance.now() + 1000;
      const started = performance.now();
      void call(`/api/fleet/device-profile-sources/${key}`).then(({profile, source_binding_status, device_id}) => {
        if (disposed) return;
        entry.profile = profile; entry.received = started; entry.unavailable = false;
        entry.bindingStatus = source_binding_status; entry.editDeviceId = device_id;
      }).catch(() => {
        entry.profile = null; entry.bindingStatus = null; entry.unavailable = true;
        entry.next = performance.now() + 5000;
      })
        .finally(() => { entry.pending = false; if (!disposed) render(); });
    }
    const mismatch = profileBindingMismatch(entry.profile, expectedBinding);
    paintProfile(root, mismatch ? null : entry.profile, {elapsedS: (performance.now() - entry.received) / 1000,
      unavailable: entry.unavailable, historyOpen: entry.historyOpen, bindingStatus: mismatch || entry.bindingStatus,
      editDeviceId: entry.profile?.device_id || entry.editDeviceId});
    const history = root.querySelector('details');
    history?.addEventListener('toggle', () => { entry.historyOpen = history.open; });
    return root;
  }
  return {detail};
}
