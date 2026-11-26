// D-775: preview approval and current-session confirmation; no tracking/motion writes.
import { setOff } from "/common/cause-line.js";
import { isOperator, NAMED_OPERATOR_REASON } from "/console/assets/authorization.js";
export function isMeasuredFrame(headers, revision, session) {
  return headers.get('Content-Type')?.split(';')[0] === 'image/jpeg'
    && headers.get('X-Frame-Rectified') === 'measured-map'
    && headers.get('X-Frame-Calibration') === revision && headers.get('X-Frame-Session') === session;
}

const REASONS = {ok:'적용 중', not_approved:'승인 없음', not_reported:'적용 확인 대기',
  confirmation_required:'현재 촬영 조건 확인 필요', not_rendered:'미리보기 대기',
  config_stale:'설정 확인 만료', frame_stale:'새 영상 대기', geometry_changed:'촬영 조건 바뀜',
  map_changed:'지도 바뀜', invalid_config:'교정 기록 확인 필요', readback_stale:'적용 기록 만료'};

const READING_REASON = '상태 읽는 중';

function invert3x3(rows) {
  if (!Array.isArray(rows) || rows.length !== 3) return null;
  const m = rows.flat();
  if (m.length !== 9 || !m.every((v) => typeof v === 'number' && Number.isFinite(v))) return null;
  const [a, b, c, d, e, f, g, h, i] = m;
  const A = e * i - f * h, B = -(d * i - f * g), C = d * h - e * g;
  const det = a * A + b * B + c * C;
  if (!Number.isFinite(det) || Math.abs(det) < 1e-15) return null;
  return [A, -(b * i - c * h), b * f - c * e, B, a * i - c * g, -(a * f - c * d), C, -(a * h - b * g), a * e - b * d].map((v) => v / det);
}

export function createMeasuredCalibrationView({scope, root, call, visionView, auth, onPromoted = () => {}}) {
  const el = id => root.querySelector(`#measured-${id}`);
  const file = el('bundle'), p95 = el('p95'), maximum = el('max'), conditions = el('conditions');
  const message = el('state'), summary = el('summary'), image = el('image');
  const buttons = Object.fromEntries(['approve','revoke','confirm','read','refresh','promote'].map(id => [id,el(id)]));
  let source = '', generation = 0, candidate = null, record = null, status = null;
  let pendingFile = null;
  let busy = false, reading = false, imageURL = null, cancelImageExpiry = null;
  let sourceLifetime = new AbortController();
  const identity = () => `${auth.token}\n${auth.role}\n${auth.principal}`;
  const operator = () => isOperator(auth.role) && !!auth.principal && !auth.locked;
  const visible = () => !root.closest('#camera-calibration').hidden;

  function clearImage() {
    cancelImageExpiry?.(); cancelImageExpiry = null;
    if (imageURL) URL.revokeObjectURL(imageURL);
    imageURL = null; image.removeAttribute('src'); image.hidden = true;
  }
  function reset() {
    sourceLifetime.abort(); sourceLifetime = new AbortController(); generation++;
    candidate = record = status = pendingFile = null; busy = reading = false; conditions.checked = false;
    p95.value = maximum.value = file.value = ''; clearImage();
    message.textContent = '저장 기록 확인 중'; summary.textContent = '';
  }
  function pause() {
    sourceLifetime.abort(); sourceLifetime = new AbortController(); generation++;
    status = pendingFile = null; busy = reading = false; conditions.checked = false; clearImage(); render();
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
  // Write only what changed: the 2 s refresh must not touch a control whose state did not change.
  function setEnabled(control, enabled, reason) {
    const value = enabled ? '' : reason;
    const targetReason = enabled ? null : reason;
    if (control.disabled === enabled || control.getAttribute('reason') !== targetReason) setOff(control, !enabled, value);
    if (control.hasAttribute('data-reading-reason') !== (value === READING_REASON)) control.toggleAttribute('data-reading-reason');
    for (const name of ['title','aria-description']) if (control.getAttribute(name) !== value) control.setAttribute(name, value);
  }
  function promotableBundle() {
    const bundle = record?.bundle;
    const readback = record?.readback;
    if (file.files.length || status?.state === 'invalid'
      || (readback?.state === 'invalid' && readback.reason !== 'readback_stale')) return null;
    return bundle?.evidence_kind === 'measured' && bundle.source_id === source ? bundle : null;
  }
  function render() {
    // A read's reason is title/aria only (measured-calibration.css hides its line): a visible line would resize the
    // layout above the checkbox between mousedown and mouseup on a slow device.
    const busyReason = '요청을 처리 중입니다.', readingReason = READING_REASON;
    const editable = operator() && !busy;
    const operable = editable && !reading;
    const editReason = busy ? busyReason : `${NAMED_OPERATOR_REASON}.`;
    const setOperable = (control, ok, why) => setEnabled(control, operable && ok, !editable ? editReason : ok ? (reading ? readingReason : '') : why);
    for (const input of [file,p95,maximum]) setEnabled(input,editable,editReason);
    setEnabled(conditions,editable && !!record,!editable ? editReason : '먼저 보정을 승인 저장하세요.');
    setOperable(buttons.approve,!!candidate && candidate.evidence_kind === 'measured' && !!limits() && candidate.source_id === source,
      '선택한 카메라의 실측 묶음과 양수 p95·최대 오차 한도를 입력하세요.');
    setOperable(buttons.revoke,!!record,'철회할 승인 기록이 없습니다.');
    const current = record && status?.calibration_revision === record.calibration_revision && status.state !== 'invalid';
    setOperable(buttons.confirm,!!current && conditions.checked,'적용 상태를 읽고 현재 촬영 조건 확인란을 선택하세요.');
    const watch = (control, ok, why) => setEnabled(control, !busy && !reading && ok && !auth.locked,
      auth.locked ? '먼저 로그인하세요.' : busy ? busyReason : ok ? (reading ? readingReason : '') : why);
    watch(buttons.read,!!current,'현재 교정·촬영 상태를 먼저 확인하세요.');
    watch(buttons.refresh,!!source,'카메라를 먼저 선택하세요.');
    const activeBundle = candidate || record?.bundle;
    if (buttons.promote) {
      setOperable(buttons.promote, !!promotableBundle(),
        candidate || pendingFile ? '가져온 교정 묶음을 먼저 승인 저장하세요.' : '현재 유효한 보정 승인 기록이 필요합니다.');
    }
    const b = activeBundle;
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
  async function readStored(t) {
    try {
      const body = await call('/api/fleet/calibrations?purpose=preview',{signals:[t.signal]}); t.check();
      if (body.use !== 'preview-only') throw new Error('이 서버는 보정 미리보기를 지원하지 않습니다.');
      return body.calibrations?.find(row => row.source_id === t.source) || null;
    } catch (error) {
      if (t.current()) { record = status = null; conditions.checked = false; }
      throw error;
    }
  }
  async function readState(t) {
    const next = await readStored(t);
    if (next?.calibration_revision !== record?.calibration_revision) { clearImage(); conditions.checked = false; }
    const previousSession = status?.session_id;
    record = next; status = null;
    if (record) {
      const lease = await grant(t);
      const response = await fetch(lease.url.href.replace(/\/frame$/,'/measured-status'), {
        signal:t.signal,credentials:'omit',redirect:'error',cache:'no-store',headers:{Authorization:`Bearer ${lease.lease}`}});
      if (!response.ok) throw new Error('보정 적용 상태를 읽지 못했습니다.');
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
    clearImage(); message.textContent = `보정 확인 실패: ${error.message}`;
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
    pendingFile = selected || null; candidate = null; render();
    if (!selected) return;
    try {
      if (selected.size > 200000) throw new Error('교정 묶음은 200 KB 이하여야 합니다.');
      const value = JSON.parse(await selected.text()); t.check();
      if (pendingFile !== selected) return;
      const keys = ['schema','source_id','map_id','map_revision','lens','floor','training_digests',
        'validation_digests','survey_digest','capture','bounds_m','evidence_kind','digest'];
      if (value.schema !== 'rosy.measured-calibration/1' || value.source_id !== t.source
        || !value.floor?.validation || !value.capture?.signature || Object.keys(value).some(k=>!keys.includes(k))) {
        throw new Error('선택한 카메라의 교정 묶음이 필요합니다.');
      }
      candidate = value; conditions.checked = false; clearImage();
    } catch(error) {
      if (t.current() && pendingFile === selected) failure(error,t);
    } finally {
      if (t.current() && pendingFile === selected) { pendingFile = null; render(); }
    }
  });
  for (const field of [p95,maximum,conditions]) scope.listen(field,'input',render);
  scope.listen(buttons.approve,'click',() => action(async t => {
    if (!operator() || !candidate || !limits()) return;
    record = await request('/api/fleet/calibrations',{purpose:'preview',kind:'measured',bundle:candidate,
      expected_revision:record?.calibration_revision || null,limits:limits()},t);
    candidate = null; file.value = '';
    file.dispatchEvent(new Event('change', {bubbles:true}));
    conditions.checked = false; clearImage(); await readState(t);
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
  if (buttons.promote) {
    scope.listen(buttons.promote,'click',() => action(async t => {
      const expected = record?.calibration_revision;
      if (!operator() || !expected || !promotableBundle()) return;
      record = await readStored(t);
      if (record?.calibration_revision !== expected) {
        status = null; conditions.checked = false;
        throw new Error('승인 기록이 바뀌었습니다. 현재 보정을 다시 확인하세요.');
      }
      const bundle = promotableBundle();
      if (!bundle) throw new Error('현재 유효한 보정 승인 기록이 필요합니다.');
      const mapToImage = invert3x3(bundle.floor.undistorted_to_map);
      if (!mapToImage) throw new Error('실측 평면 행렬을 뒤집을 수 없습니다.');
      const [bx0, by0, bx1, by1] = bundle.bounds_m;
      const [w, h] = bundle.lens.image_size;
      const lensProfile = {
        model: bundle.lens.model, K: bundle.lens.K, D: bundle.lens.D, image_size: [w, h],
        source: 'measured', revision: bundle.lens.revision, reproj_p95_px: bundle.lens.validation?.p95_px,
      };
      const promoted = await request('/api/fleet/calibrations', {
        source_id: bundle.source_id, map_id: bundle.map_id, map_to_image: mapToImage,
        image: {width: w, height: h},
        track_bounds_m: {min_x: bx0, min_y: by0, max_x: bx1, max_y: by1},
        fit_score: Math.max(0, Math.min(1, Number((1 - bundle.floor.validation.p95_m * 5).toFixed(3)))),
        lens: bundle.capture.lens,
        lens_profile: lensProfile, method: 'measured',
        metrics: {p95_m: bundle.floor.validation.p95_m, max_m: bundle.floor.validation.max_m},
      }, t);
      message.textContent = `추적 보정 저장 완료 (${promoted.calibration_revision})`;
      onPromoted(promoted);
    }));
  }
  scope.listen(document.getElementById('vision-source'),'change',() => {syncSource(); render(); return refresh();});
  scope.interval(refresh,2000); scope.onResume(refresh); scope.onDispose(reset);
  syncSource(); render();
  return {refresh, updateAuthorization:render, pause};
}
