// D-775: preview approval and current-session confirmation; no tracking/motion writes.
export function isMeasuredFrame(headers, revision, session) {
  return headers.get('Content-Type')?.split(';')[0] === 'image/jpeg'
    && headers.get('X-Frame-Rectified') === 'measured-map'
    && headers.get('X-Frame-Calibration') === revision && headers.get('X-Frame-Session') === session;
}

const REASONS = {ok:'적용 중', not_approved:'승인 없음', not_reported:'적용 확인 대기',
  confirmation_required:'현재 촬영 조건 확인 필요', not_rendered:'미리보기 대기',
  config_stale:'설정 확인 만료', frame_stale:'새 영상 대기', geometry_changed:'촬영 조건 바뀜',
  map_changed:'지도 바뀜', invalid_config:'교정 기록 확인 필요', readback_stale:'적용 기록 만료'};

export function createMeasuredCalibrationView({scope, root, call, visionView, auth}) {
  const el = id => root.querySelector(`#measured-${id}`);
  const file = el('bundle'), p95 = el('p95'), maximum = el('max'), conditions = el('conditions');
  const message = el('state'), summary = el('summary'), image = el('image');
  const buttons = Object.fromEntries(['approve','revoke','confirm','read','refresh'].map(id => [id,el(id)]));
  let source = '', generation = 0, candidate = null, record = null, status = null;
  let busy = false, reading = false, imageURL = null, cancelImageExpiry = null;
  let sourceLifetime = new AbortController();
  const identity = () => `${auth.token}\n${auth.role}\n${auth.principal}`;
  const operator = () => auth.role === 'operator' && !!auth.principal && !auth.locked;
  const visible = () => !root.closest('#camera-calibration').hidden;

  function clearImage() {
    cancelImageExpiry?.(); cancelImageExpiry = null;
    if (imageURL) URL.revokeObjectURL(imageURL);
    imageURL = null; image.removeAttribute('src'); image.hidden = true;
  }
  function reset() {
    sourceLifetime.abort(); sourceLifetime = new AbortController(); generation++;
    candidate = record = status = null; busy = reading = false; conditions.checked = false;
    p95.value = maximum.value = file.value = ''; clearImage();
    message.textContent = '저장 기록 확인 중'; summary.textContent = '';
  }
  function pause() {
    sourceLifetime.abort(); sourceLifetime = new AbortController(); generation++;
    status = null; busy = reading = false; conditions.checked = false; clearImage(); render();
    message.textContent = '적용 상태 확인 대기';
  }
  function syncSource() {
    const current = visionView.currentSource();
    if (current !== source) { reset(); source = current; }
  }
  function ticket() {
    syncSource();
    const life = scope.capture(), held = generation, who = identity(), camera = source;
    return {signal: AbortSignal.any([life.signal,sourceLifetime.signal]), source:camera,
      current: () => life.current() && held === generation && camera === visionView.currentSource() && who === identity(),
      check() { life.check(); if (!this.current()) throw new DOMException('Camera context changed','AbortError'); }};
  }
  function limits() {
    const a = p95.valueAsNumber, b = maximum.valueAsNumber;
    return Number.isFinite(a) && Number.isFinite(b) && a > 0 && b >= a ? {p95_m:a,max_m:b} : null;
  }
  function setEnabled(control, enabled, reason) {
    control.disabled = !enabled;
    control.setAttribute('reason', enabled ? '' : reason);
    control.setAttribute('title', enabled ? '' : reason);
    control.setAttribute('aria-description', enabled ? '' : reason);
  }
  function render() {
    const pending = busy || reading;
    const pendingReason = reading ? '적용 상태를 확인 중입니다.' : '요청을 처리 중입니다.';
    const editable = operator() && !busy;
    const operable = editable && !reading;
    const editReason = pending ? pendingReason : '이름 있는 운영자 권한이 필요합니다.';
    for (const input of [file,p95,maximum]) setEnabled(input,editable,editReason);
    setEnabled(conditions,editable && !!record,!editable ? editReason : '먼저 실측 교정을 승인 저장하세요.');
    setEnabled(buttons.approve,operable && !!candidate && candidate.evidence_kind === 'measured'
      && !!limits() && candidate.source_id === source,
      !operable ? editReason : '선택한 카메라의 실측 묶음과 양수 p95·최대 오차 한도를 입력하세요.');
    setEnabled(buttons.revoke,operable && !!record,!operable ? editReason : '철회할 승인 기록이 없습니다.');
    const current = record && status?.calibration_revision === record.calibration_revision && status.state !== 'invalid';
    setEnabled(buttons.confirm,operable && !!current && conditions.checked,
      !operable ? editReason : '적용 상태를 읽고 현재 촬영 조건 확인란을 선택하세요.');
    setEnabled(buttons.read,!pending && !!current && !auth.locked,
      auth.locked ? '먼저 로그인하세요.' : pending ? pendingReason : '현재 교정·촬영 상태를 먼저 확인하세요.');
    setEnabled(buttons.refresh,!pending && !!source && !auth.locked,
      auth.locked ? '먼저 로그인하세요.' : pending ? pendingReason : '카메라를 먼저 선택하세요.');
    const b = candidate || record?.bundle;
    summary.textContent = b ? `${b.source_id} · 지도 ${b.map_id} · 독립 검증 p95 ${b.floor.validation.p95_m} m / 최대 ${b.floor.validation.max_m} m · ${b.evidence_kind === 'measured' ? '실측 근거' : '합성 자료 — 승인 불가'}` : '이 카메라의 교정 묶음을 가져오세요.';
  }
  async function request(path, body, t, method='POST') {
    const result = await call(path, {method, signals:[t.signal], headers:{'Content-Type':'application/json'},
      ...(body === undefined ? {} : {body:JSON.stringify(body)})});
    t.check(); return result;
  }
  async function grant(t, measured=null) {
    const body = {source_id:t.source, ...(measured ? {measured} : {})};
    const lease = await request('/api/fleet/vision/lease',body,t);
    const url = new URL(lease.frame_path,location.origin);
    if (url.origin !== location.origin || url.pathname !== `/api/vision/sources/${t.source}/frame`
      || url.search || url.hash || url.username || url.password) throw new Error('영상 주소를 확인하세요.');
    return {...lease,url};
  }
  async function readState(t) {
    const body = await call('/api/fleet/calibrations?purpose=preview',{signals:[t.signal]}); t.check();
    if (body.use !== 'preview-only') throw new Error('이 서버는 실측 교정 미리보기를 지원하지 않습니다.');
    const next = body.calibrations?.find(row => row.source_id === t.source) || null;
    if (next?.calibration_revision !== record?.calibration_revision) { clearImage(); conditions.checked = false; }
    const previousSession = status?.session_id;
    record = next; status = null;
    if (record) {
      const lease = await grant(t);
      const response = await fetch(lease.url.href.replace(/\/frame$/,'/measured-status'), {
        signal:t.signal,credentials:'omit',redirect:'error',cache:'no-store',headers:{Authorization:`Bearer ${lease.lease}`}});
      if (!response.ok) throw new Error('실측 교정 적용 상태를 읽지 못했습니다.');
      const result = await response.json(); t.check();
      if (result.source_id !== t.source) throw new Error('카메라 상태의 출처가 다릅니다.');
      status = result;
      if (status.session_id !== previousSession || status.state === 'invalid'
        || status.calibration_revision !== record.calibration_revision) {
        clearImage(); conditions.checked = false;
      }
    } else { clearImage(); conditions.checked = false; }
    message.textContent = record ? `저장됨${record.persistent ? '' : ' (메모리 전용)'} · Vision ${REASONS[status?.reason] || '적용 확인 대기'}` : '승인 없음';
    render();
  }
  async function showFrame(t, confirm) {
    if (!record || !status?.session_id) throw new Error('현재 촬영 상태를 먼저 확인하세요.');
    const revision = record.calibration_revision, session = status.session_id;
    const measured = {calibration_revision:revision,session_id:session,
      capture_signature:record.bundle.capture.signature,confirm_conditions:confirm};
    const started = performance.now(), lease = await grant(t,measured);
    const response = await fetch(lease.url,{signal:t.signal,credentials:'omit',redirect:'error',cache:'no-store',
      headers:{Authorization:`Bearer ${lease.lease}`}});
    if (!response.ok || !isMeasuredFrame(response.headers,revision,session)) {
      throw new Error(REASONS[response.headers.get('X-Measured-Reason')] || '현재 조건에 맞는 실측 영상을 읽지 못했습니다.');
    }
    const blob = await response.blob(); t.check();
    const remaining = 5000-(performance.now()-started);
    if (remaining <= 0) throw new Error('영상 응답이 만료되었습니다. 다시 확인하세요.');
    clearImage(); imageURL = URL.createObjectURL(blob); image.src = imageURL; image.hidden = false;
    cancelImageExpiry = scope.timeout(clearImage,remaining);
    status = {...status,state:'applied',reason:'ok'};
    message.textContent = '저장됨 · Vision 적용 중 · 지도 미리보기'; render();
  }
  function failure(error,t) {
    if (error.name === 'AbortError' || !t.current()) return;
    clearImage(); message.textContent = `실측 교정 확인 실패: ${error.message}`;
  }
  async function action(fn) {
    if (busy || reading) return;
    const t = ticket(); busy = true; render();
    try { await fn(t); } catch(error) { failure(error,t); }
    finally { if (t.current()) { busy = false; render(); } }
  }
  async function refresh() {
    syncSource();
    if (!source || busy || reading || auth.locked || !visible()) return;
    const t = ticket(); reading = true; render();
    try {
      const wasVisible = !!imageURL; await readState(t);
      if (wasVisible && imageURL) await showFrame(t,false);
    } catch(error) { failure(error,t); }
    finally { if (t.current()) { reading = false; render(); } }
  }
  scope.listen(file,'change',async () => {
    const selected = file.files[0], t = ticket();
    if (!selected) return;
    try {
      if (selected.size > 200000) throw new Error('교정 묶음은 200 KB 이하여야 합니다.');
      const value = JSON.parse(await selected.text()); t.check();
      const keys = ['schema','source_id','map_id','map_revision','lens','floor','training_digests',
        'validation_digests','survey_digest','capture','bounds_m','evidence_kind','digest'];
      if (value.schema !== 'rosy.measured-calibration/1' || value.source_id !== t.source
        || !value.floor?.validation || !value.capture?.signature || Object.keys(value).some(k=>!keys.includes(k))) {
        throw new Error('선택한 카메라의 교정 묶음이 필요합니다.');
      }
      candidate = value; conditions.checked = false; clearImage(); render();
    } catch(error) { if (t.current()) { candidate = null; failure(error,t); render(); } }
  });
  for (const field of [p95,maximum,conditions]) scope.listen(field,'input',render);
  scope.listen(buttons.approve,'click',() => action(async t => {
    if (!operator() || !candidate || !limits()) return;
    record = await request('/api/fleet/calibrations',{purpose:'preview',kind:'measured',bundle:candidate,
      expected_revision:record?.calibration_revision || null,limits:limits()},t);
    candidate = null; conditions.checked = false; clearImage(); await readState(t);
  }));
  scope.listen(buttons.revoke,'click',() => action(async t => {
    if (!operator() || !record) return;
    await request(`/api/fleet/calibrations/${encodeURIComponent(t.source)}?purpose=preview&expected_revision=${encodeURIComponent(record.calibration_revision)}`,undefined,t,'DELETE');
    record = null; clearImage(); conditions.checked = false; await readState(t);
  }));
  scope.listen(buttons.confirm,'click',() => action(async t => {
    if (operator() && conditions.checked) await showFrame(t,true);
  }));
  scope.listen(buttons.read,'click',() => action(t => showFrame(t,false)));
  scope.listen(buttons.refresh,'click',refresh);
  scope.listen(document.getElementById('vision-source'),'change',() => {syncSource(); render(); return refresh();});
  scope.interval(refresh,2000); scope.onResume(refresh); scope.onDispose(reset);
  syncSource(); render();
  return {refresh, updateAuthorization:render, pause};
}
