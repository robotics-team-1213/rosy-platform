'use strict';
// ---- config (all timings/sizes/limits in one place) -----------------------
const CFG = {
  poll_ms: 333, result_ms: 5000, map_recheck_ms: 120, stale_ms: 1500,
  teleop_period_ms: 100, cam_stale_ms: 3000,
  // clamps must match the /teleop handler in rosy_nodes/web_node.py
  lin_max: 0.2, ang_max: 1.0,
  lin_steps: [0.02, 0.05, 0.10, 0.20],
  ang_steps: [0.25, 0.50, 0.75, 1.00],
  fit_margin: 0.98, zoom_min: 1, zoom_max: 8, zoom_step: 1.15,
  click_slop_px: 4,
  // Fallbacks only. web_node publishes state.limits from config/robot.yaml —
  // the numbers that actually stop the robot. These keep the gauges honest
  // when the page is opened against a rig that runs no safety node.
  lim: { stop: 0.12, clear: 0.14, warn: 0.18, us_stop: 0.020,
         us_clear: 0.028, radius: 0.076, open_max: 0.40 },
};
// ---- canvas colours (read from the :root CSS custom properties) ----------
// Canvas colours: T.key names a CSS property, resolved at paint time through ui.js (cached, cleared on theme change).
const T_VARS = { unk: '--unk', grid: '--grid', ink: '--ink', route: '--route', alt: '--alt', goal: '--goal', hist: '--hist', crit: '--crit', warn: '--warn', pin: '--pin', inkQuiet: '--ink-quiet', ink2: '--ink-2',
  bodyFill: '--route-wash', bodyLine: '--route-line', wedge: '--ink-wash', space: '--route-wash', spaceLine: '--route-line', haltLine: '--crit-line', chassis: '--line-06', chassisLine: '--line-50' };
const T = new Proxy(T_VARS, { get: (vars, key) => window.RosyPalette ? window.RosyPalette.cssColor(vars[key]) : 'transparent' });
// ---- state ----------------------------------------------------------------
const S = {
  previewEnabled: true, pendingCommand: null,
  data: {},
  img: { gen: -1, im: null, t: 0 },
  cam: { gen: -1, t: 0 },
  view: { angle: 0, aligned: false, z: 1, A: { x: 0, y: 0 }, ok: false,
          k: 1, w: 0, h: 1, res: 0.05, ox: 0, oy: 0, wc: null },
  split: { key: '', bi: 0 },
  pin: null, lastOk: 0, raf: 0,
  tele: { lin: 1, ang: 1, x: 0, z: 0 },
  held: new Set(), kt: null,
  mappingBusy: false, mapEpoch: null,
  gaugeKey: '',
};
// ---- helpers + api ---------------------------------------------------------
const $ = id => document.getElementById(id);
const BACKEND_PORT = document.querySelector('meta[name=backend-port]').content;  // page handler fills __BACKEND_PORT__
const API = (location.port === BACKEND_PORT) ? '' :
  location.protocol + '//' + location.hostname + ':' + BACKEND_PORT;
async function getJson(path) {
  try { const r = await fetch(API + path); return await r.json(); }
  catch (e) { return null; }
}
async function post(path, body) {
  if (path === '/wander' && body !== 'stop' && !calibrationReady(S.data)) return;
  try {
    if (path === '/wander' || path === '/estop') {
      S.pendingCommand = {path, body, until:Date.now()+5000, sequence:S.data[path === '/estop' ? 'estop_sequence' : 'wander_sequence'] || 0};
      setTxt('commandstatus', '명령 전송 중 · 로봇 응답 확인');
    }
    const response = await fetch(API + path, { method: 'POST', body: body });
    if (!response.ok) {
      const result = await response.json();
      setTxt('calibrationerror', result.error || '명령을 실행할 수 없습니다.');
      S.pendingCommand = null;
      setTxt('commandstatus', '명령 실패 · ' + (result.error || '로봇이 요청을 거부했습니다'));
      return false;
    }
    return true;
  } catch (e) {
    S.pendingCommand = null;
    setTxt('commandstatus', '명령 실패 · 로봇 연결을 확인해 주세요');
    setTxt('calibrationerror', '로봇 연결을 확인해 주세요.');
  }
  return false;
}
function calibrationReady(s) {
  return !!s && s.calibration_ready === true && !!s.calibration && s.calibration.ready === true;
}
function existingSettings(s) {
  return !!(s && s.calibration && s.calibration.mode === 'existing_settings');
}
function limitedSensors(s) {
  return !!(s && s.calibration && s.calibration.mode === 'limited_sensors');
}
function renderOverview(s) {
  const battery = s && s.battery;
  const live = battery && battery.available === true;
  setTxt('batteryvalue', live && Number.isFinite(battery.percent) ? Math.round(battery.percent) + '%' : '정보 없음');
  const batteryStates = {charging:'충전 중',discharging:'사용 중',not_charging:'충전 안 함',full:'충전 완료',unknown:'충전 상태 미확인'};
  const missing = {missing:'배터리 측정 대기',stale:'배터리 수신 지연',not_present:'배터리 연결 미확인',invalid:'유효한 측정값 없음'};
  setTxt('batterydetail', live ? (Number.isFinite(battery.voltage) ? battery.voltage.toFixed(2)+' V · ' : '') + batteryStates[battery.status] : missing[battery && battery.reason] || '배터리 측정 대기');
  $('batteryfill').style.width = live && Number.isFinite(battery.percent) ? Math.max(0,Math.min(100,battery.percent))+'%' : '0%';
  setTxt('overviewcal', calibrationReady(s) ? '적용 완료' : s && s.calibration && (s.calibration.phase === 'sensor_hold' || s.calibration.runtime_state === 'sensor_hold') ? '센서 재확인' : '준비 필요');
  setTxt('overviewcaldetail', calibrationReady(s) ? '보정값 적용 확인됨' : '상세 원인은 조작 영역에서 확인');
  if (existingSettings(s)) {
    setTxt('overviewcal', '기존 설정값 · 미보정');
    setTxt('overviewcaldetail', calibrationReady(s) ? '실시간 안전 조건 확인됨 · 주행은 직접 선택' : '실시간 안전 조건 대기 · 주행 불가');
  }
  if (limitedSensors(s)) {
    setTxt('overviewcal', '보정 완료(일부 센서 모드)');
    setTxt('overviewcaldetail', '수동 완료 · IMU 제외 · 저속 제한 · ' + (calibrationReady(s) ? '주행은 직접 선택' : '안전 조건 대기'));
  }
  setTxt('overviewpose', s && s.pose_available ? '위치 확인됨' : '위치 확인 대기');
  const stopped = !s || !s.wander || s.wander.startsWith('stop') || s.wander === 'wait';
  setTxt('overviewmotion', !s ? '연결 끊김' : s.estop ? '비상정지' : stopped ? '대기 중' : '주행 중');
  setTxt('overviewreason', !s ? '로봇 연결을 확인하세요' : s.estop ? '해제 후 주행 모드를 선택하세요' : stopped ? '자동으로 출발하지 않습니다' : s.wander);
  const pending = S.pendingCommand;
  if (pending) {
    const state = s && s.wander || '';
    const fresh = s && s[pending.path === '/estop' ? 'estop_sequence' : 'wander_sequence'] > pending.sequence;
    const applied = fresh && (pending.path === '/estop' ? s.estop === (pending.body === 'stop') :
      pending.body === 'stop' ? state.startsWith('stop') :
      pending.body === 'start' ? state === 'forward' || state === 'look' : state.startsWith('route_'+pending.body+':'));
    if (applied) { S.pendingCommand = null; setTxt('commandstatus', '로봇 상태 반영 확인 · ' + (pending.path === '/estop' ? '비상정지 ' + (s.estop ? '설정' : '해제') : pending.body === 'stop' ? '주행 정지' : '주행 시작')); }
    else if (Date.now() > pending.until) { S.pendingCommand = null; setTxt('commandstatus', '적용 확인 시간 초과 · 현재 로봇 상태를 확인하세요'); }
  }
  setTxt('previewstatus', !S.previewEnabled ? '영상 표시 꺼짐 · 영상 요청 중지됨' : S.cam.t && Date.now()-S.cam.t < CFG.cam_stale_ms ? '영상 수신 중' : '영상 수신 대기');
}
function togglePreview() {
  S.previewEnabled = $('cameratoggle').checked;
  try { localStorage.setItem('pinky.preview', S.previewEnabled ? 'on' : 'off'); } catch (_) {}
  $('camcard').hidden = !S.previewEnabled;
  if (!S.previewEnabled) { $('camimg').removeAttribute('src'); S.cam.t = 0; }
  S.cam.gen = -1;
  renderOverview(S.data);
}
function renderCalibration(s) {
  cameraGroundCalibration(s && s.camera_calibration);
  const calibration = s && s.calibration;
  const phase = calibration && calibration.phase;
  const limited = limitedSensors(s);
  const partial = phase === 'sensing_only' || !!(calibration && calibration.partial && !limited);
  const existing = existingSettings(s);
  $('calibrationexistingstatus').hidden = !existing;
  setTxt('calibrationexistingstatus', '기존 설정값 모드 · 미보정 · 이동·회전 보정 검증 생략. ' +
    (calibrationReady(s) ? '실시간 안전 조건 확인됨 · 주행은 직접 선택합니다.' : '실시간 안전 조건 대기 · 주행 불가.') +
    (existing && Array.isArray(calibration.waiting_reasons) && calibration.waiting_reasons.length ? ' · ' + calibration.waiting_reasons.map(reason => reason === 'estop' ? '비상정지 해제 대기' : reason).join(' · ') : ''));
  $('calibrationpartial').hidden = !partial;
  setTxt('calibrationpartial', '부분 센싱 · IMU 제외 · 미교정 · 주행 불가. 정지 상태에서 나머지 센서만 확인합니다.');
  $('calibrationlimitedstatus').hidden = !limited;
  if (limited) {
    const excluded = Array.isArray(calibration.excluded_sensors) ? calibration.excluded_sensors.map(name => String(name).toUpperCase()).join(', ') : 'IMU';
    const caps = calibration.speed_limits;
    const speed = caps && Number.isFinite(caps.linear_mps) && Number.isFinite(caps.angular_rad_s)
      ? ' · 최대 ' + (caps.linear_mps * 100).toFixed(1) + 'cm/s · ' + caps.angular_rad_s + 'rad/s' : '';
    const waiting = Array.isArray(calibration.waiting_reasons) ? calibration.waiting_reasons.map(reason => reason === 'estop' ? '비상정지 해제 대기' : reason).join(' · ') : '';
    setTxt('calibrationlimitedstatus', '보정 완료(일부 센서 모드) · 수동 완료 · ' + excluded + ' 제외 · 저속 제한' + speed + ' · ' +
      (calibrationReady(s) ? '나머지 안전 조건 확인됨 · 주행은 직접 선택합니다.' : '나머지 안전 조건 대기 · 주행 불가.') + (waiting ? ' · ' + waiting : ''));
  }
  const names = {lidar:'LiDAR', odom:'이동 거리', ir:'바닥 IR', imu:'자세 IMU', us:'초음파', camera:'카메라', tf:'센서 위치', map:'지도', map_tf:'지도 내 위치'};
  const states = {collecting:'수집 중', ok:'정상', stale:'수신 지연', unstable:'불안정', invalid:'확인 필요'};
  const phases = {collecting:'정지 센서 확인 중', waiting_motion:'정지 확인 완료 · 이동 검증 대기', validating_motion:'저속 이동 검증 중', ready:'교정 완료 · 주행 가능', sensor_hold:'보정 유지 · 센서 재확인 중', failed:'교정 실패', aborted:'교정 중단'};
  const sensors = calibration && calibration.sensors || {};
  phases.sensing_only = '부분 센싱 · IMU 제외 · 미교정 · 주행 불가';
  phases.existing_settings = '기존 설정값 모드 · 미보정 · ' + (calibrationReady(s) ? '운행 조건 확인됨' : '안전 조건 대기');
  phases.limited_sensors = '보정 완료(일부 센서 모드) · ' + (calibrationReady(s) ? '운행 조건 확인됨' : '안전 조건 대기');
  phases.validating_rotation = '좌우 회전 반복 검증 중';
  phases.relocating_calibration = '교정 공간 확보 중 · 제한 직선 이동';
  phases.returning_calibration = '보정 측정 완료 · 원위치 복귀 중';
  phases.waiting_space = '교정 공간 부족 · 안전 정지';
  phases.return_blocked = '보정 측정 완료 · 복귀 불가로 정지';
  if (phase === 'ready' && !calibrationReady(s)) phases.ready = calibration.recalibration_required === true
    ? '보정 대상 변경 · 재보정 필요' : calibration.runtime_state === 'sensor_hold'
    ? '보정 완료 유지 · 실시간 안전 조건 대기' : '안전 노드 적용 확인 대기';
  let count = 0;
  const lines = Object.keys(names).map(key => {
    const sensor = sensors[key];
    if (sensor && sensor.excluded === true) return names[key] + ': 제외 · 정상 판정 및 교정에 사용하지 않음';
    if (sensor && sensor.ok === true) count++;
    return names[key] + ': ' + (sensor ? (states[sensor.status] || sensor.status) +
      ' · ' + (sensor.samples || 0) + '개 · ' + (sensor.detail || '') : '데이터 대기');
  });
  $('calibrationprogress').value = count;
  const clearance = calibration && calibration.motion_clearance;
  if (clearance) {
    const cm = value => Number.isFinite(value) ? (value * 100).toFixed(1) + 'cm' : '미수신';
    if (clearance.translation_mode) {
      lines.push('차체 외곽·정지 여유 제외 후 이동 가능: 전방 ' + cm(clearance.available_travel_m) + ' / 필요 ' + cm(clearance.required_travel_m) + ' · 후방 ' + cm(clearance.reverse_travel_m) + ' / 필요 ' + cm(clearance.required_reverse_travel_m));
      lines.push('직선 저속 보정 · 차체 밖 1cm 정지 여유 · 회전은 별도 검사');
    } else {
      lines.push('왕복 공간 확인 (LiDAR 기준): 전방 ' + cm(clearance.available_front_m) + ' / 필요 ' + cm(clearance.required_front_m) + ' · 후방 ' + cm(clearance.available_rear_m) + ' / 필요 ' + cm(clearance.required_rear_m));
    }
    lines.push('이번 보정 이동 목표 ' + cm(clearance.target_m) + ' · 정지 기준: 전방 ' + cm(clearance.front_stop_m) + ' / 후방 ' + cm(clearance.rear_stop_m));
    if (clearance.reason) lines.push('공간 확인: ' + clearance.reason);
  }
  const env = calibration && calibration.navigation_profile;
  setTxt('calibrationenvironment', env ? '환경 보정 ' + (phase === 'ready' ? '적용' : '측정') + ' · 통로 ' + (env.corridor_width_m*100).toFixed(1) + 'cm · 몸체 바깥 최소 여유 ' + (env.uncertainty_margin_m*100).toFixed(1) + 'cm' + (env.map_lidar_mismatch ? ' · 지도/센서 거리 차이 확인 필요' : '') : '환경 여유 측정 대기 · 미측정 시 기본 여유 적용');
  if (env) {
    lines.push('환경 보정: 통로 ' + (env.corridor_width_m*100).toFixed(1) + 'cm · 거리 흔들림 ' + (env.range_noise_m*1000).toFixed(1) + 'mm');
    lines.push('로봇 반경 ' + (env.body_radius_m*100).toFixed(1) + 'cm · 최소 중심 여유 ' + (env.minimum_clearance_m*100).toFixed(1) + 'cm · 선호 여유 ' + (env.preferred_clearance_m*100).toFixed(1) + 'cm');
    if (env.map_lidar_mismatch) lines.push('지도와 LiDAR 벽 거리 차이 있음 · 환경 여유를 줄여 차이를 보상하지 않습니다');
  }
  setTxt('calibrationsummary', '센서 검사 ' + count + '/9 · ' + (calibration && calibration.recalibration_required === true ? '\uBCF4\uC815 \uB300\uC0C1 \uBCC0\uACBD \u00b7 \uC7AC\uBCF4\uC815 \uD544\uC694' : phase === 'sensor_hold' || calibration && calibration.runtime_state === 'sensor_hold' ? '저장된 보정 유지 · 해당 센서 정상 수신 후 자동 복구' : phase === 'ready' ? '왕복 검증 및 저장 완료' : phase === 'validating_motion' ? '왕복 검증 중 — 앞뒤 공간을 비워 주세요' : phase === 'waiting_motion' ? '비상정지 해제 및 안전 조건 대기' : phase === 'failed' || phase === 'aborted' ? '정지됨 · 원인 확인 후 재시작하세요' : '검사 중'));
  if (partial) setTxt('calibrationsummary', '부분 센싱 · IMU 제외 · ' + (calibration.partial_baseline_ready ? '나머지 센서 기준값 수집 완료' : '나머지 센서 기준값 수집 중') + ' · 전체 교정 미완료');
  if (existing) setTxt('calibrationsummary', '기존 설정값 사용 · 미보정 · 실시간 센서 검사 ' + count + '/9 · 비상정지와 센서 안전 조건 유지');
  if (limited) setTxt('calibrationsummary', '수동 완료 · IMU 제외 · 저속 제한 · 나머지 센서와 비상정지 안전 조건 유지');
  if (calibration && calibration.motion && calibration.motion.stage) {
    const m = calibration.motion;
    lines.push('왕복 ' + m.cycle + '/2 · 목표 ' + (m.target_m * 100).toFixed(1) + 'cm · ' + ({outbound:'전진 중',settle_out:'전진 거리 확인',returning:'출발점으로 복귀 중',settle_home:m.done ? '복귀 확인 완료' : '복귀 오차 확인'}[m.stage] || m.stage));
    lines.push('속도 보정: 전진 ×' + m.forward_scale.toFixed(3) + ' / 후진 ×' + m.reverse_scale.toFixed(3));
    if (m.legs && m.legs.length) {
      const last = m.legs[m.legs.length - 1];
      lines.push('최근 이동 ' + (last.measured_m * 100).toFixed(2) + 'cm · 원점 차이 ' + (last.home_error_m * 100).toFixed(2) + 'cm');
    }
  }
  const rotation = calibration && calibration.rotation;
  if (calibration && calibration.after_relocation)
    lines.push('보정 후 위치: ' + (calibration.after_relocation === 'return_origin' ? '원위치 복귀' : '확보한 위치 유지'));
  if (calibration && calibration.relocation) {
    const relocation = calibration.relocation;
    lines.push('공간 확보 이동 ' + (relocation.travel_m*100).toFixed(1) + 'cm · ' +
      (relocation.error || (relocation.done ? '확보 완료' : '진행 중')));
  }
  if (calibration && calibration.return_motion)
    lines.push('원위치 복귀: ' + (calibration.return_motion.error || (calibration.return_motion.done ? '완료' : '진행 중')));
  if (rotation) lines.push('회전 검증 ' + (rotation.legs || []).length + '/8 · ' + (rotation.done ? '완료' : '진행 중'));
  const activeMotion = s && s.motion_limits_fresh && s.motion_limits;
  const envelope = activeMotion && activeMotion.rotation_estimate || rotation && rotation.envelope;
  const cm = value => (value*100).toFixed(1);
  if (envelope && envelope.valid && Array.isArray(envelope.center_m) &&
      envelope.center_m.length === 2 && [...envelope.center_m, envelope.pivot_radius_m,
        envelope.center_uncertainty_m].every(Number.isFinite)) {
    lines.push('센서 회전 추정 · 중심 x ' + cm(envelope.center_m[0]) + ' / y ' + cm(envelope.center_m[1]) + 'cm');
    lines.push('중심 기준 회전 반경 ' + cm(envelope.pivot_radius_m) + 'cm · 중심 불확실성 ' + cm(envelope.center_uncertainty_m) + 'cm');
  }
  if (activeMotion && Number.isFinite(activeMotion.body_radius_m))
    lines.push('설정 형상 기준 차체 반경 ' + cm(activeMotion.body_radius_m) + 'cm');
  lines.push('현재 회전 · ' + (activeMotion
    ? (activeMotion.can_rotate === true ? '허용' : '보류') + ' · 전방위 스캔 ' +
      (activeMotion.rotation_scan_observed === true ? '관측 완료' : '관측 대기')
    : '보류 · 최신 안전 정보 대기'));
  const effective = s && s.safety_profile && s.safety_profile.valid && s.safety_profile.effective;
  if (effective) lines.push('현재 안전 기준 · 정지 ' + (effective.stop*100).toFixed(1) + 'cm · 반경 ' + (effective.radius*100).toFixed(1) + 'cm');
  if (s && s.safety_decision && s.safety_decision.reason) lines.push('안전 판단: ' + s.safety_decision.reason);
  setTxt('calibrationsensors', lines.join('\n'));
  setTxt('calibrationstatus', (phases[phase] || '교정 노드 연결 대기') +
    (calibration && calibration.message ? ' · ' + calibration.message : ''));
  if (s && s.estop === true) {
    const pending = phase === 'collecting' ? '센서 검사도 진행 중입니다' : '해제 전에는 이동하지 않습니다';
    setTxt('calibrationstatus', $('calibrationstatus').textContent + ' · 비상정지 걸림: ' + pending);
  }
  $('calibrationmotion').hidden = !!(calibration && calibration.auto_motion);
  $('calibrationmotion').disabled = !!(calibration && calibration.auto_motion) || phase !== 'waiting_motion' || !s || s.estop !== false ||
    !s.map_control || s.map_control.paused !== false;
  const busy = phase === 'validating_motion' || phase === 'validating_rotation';
  $('calibrationretry').disabled = busy;
  setTxt('calibrationretry', '전체 보정');
  // The node owns the verdict; the page only renders which route it left open.
  const option = calibration && calibration.partial_option || {available: false, reason: 'unknown'};
  const blocking = Array.isArray(option.blocking_sensors) ? option.blocking_sensors : [];
  const dropped = Array.isArray(option.excluded_sensors) ? option.excluded_sensors : [];
  const label = list => list.map(name => names[name] || String(name).toUpperCase()).join(', ');
  $('calibrationpartialaction').disabled = !option.available || busy;
  const partialReasons = {
    required_sensor_failed: label(blocking) + ' 실패 — 제외 불가(주행 필수). 전체 보정 재시도 또는 중단.',
    no_failed_sensor: '제외할 실패 센서 없음 — 전체 보정을 사용하세요',
    rotation_unavailable: label(dropped) + ' 제외 가능 — 회전 검증 없이 기존 설정값 · 저속 제한 주행',
    calibration_continues: label(dropped) + ' 제외 가능 — 나머지 센서로 보정을 완주합니다',
  };
  $('calibrationpartialreason').hidden = !partialReasons[option.reason];
  setTxt('calibrationpartialreason', partialReasons[option.reason] || '');
  $('wanderstart').disabled = !calibrationReady(s) || s.estop !== false;
  document.querySelectorAll('[data-hold]').forEach(button => {
    button.disabled = button.dataset.hold !== 'stop' && (!calibrationReady(s) || s.estop !== false);
  });
  if (!calibrationReady(s) && S.held.size) { S.held.clear(); ksync(); }
}
function cameraGroundCalibration(calibration) {
  const value = calibration || {eligible:false, active:false, reason:'waiting_for_camera_node', checks:{}};
  const checks = value.checks || {};
  const toggle = $('camera_ground_toggle');
  toggle.disabled = value.mode !== 'homography' || value.eligible !== true;
  toggle.checked = value.active === true;
  const labels = {
    waiting_for_camera_node:'카메라 노드 연결 대기', profile_missing:'보정 프로필 없음',
    validation_failed:'후보 로드됨 · 검증 미통과', disabled:'검증 통과 · 사용 안 함',
    active:'검증 통과 · 거리 보정 사용 중', mode_pinhole:'기존 핀홀 모델 선택',
    mode_off:'카메라 거리 보정 꺼짐', unsupported_mode:'지원하지 않는 모드'
  };
  setTxt('camera_ground_status', labels[value.reason] || value.reason || '상태 미확인');
  ['profile_loaded', 'image_contract', 'intrinsic_calibration', 'reference_fit', 'independent_validation',
   'physical_validation'].forEach(name => {
    const input = $('camera_ground_check_' + name);
    input.checked = !!(checks[name] && checks[name].passed === true);
  });
  const metric = value.metrics || {};
  const threshold = value.thresholds || {};
  const range = Array.isArray(value.validated_range_m) && value.validated_range_m.length === 2
    ? (value.validated_range_m[0] * 100).toFixed(1) + '–' + (value.validated_range_m[1] * 100).toFixed(1) + 'cm' : '미검증';
  const number = (v, unit) => Number.isFinite(v) ? v.toFixed(3) + unit : '없음';
  setTxt('camera_ground_detail',
    '모드: ' + (value.mode || '미수신') + '\n' +
    '프로필: ' + (value.source || '없음') + '\n' +
    '상태: ' + (value.profile_status || '없음') + '\n' +
    '참조 RMSE: ' + number(metric.fit_rmse_cm, 'cm') + ' / 기준 ' + number(threshold.max_fit_rmse_cm, 'cm') + '\n' +
    '독립 RMSE: ' + number(metric.validation_rmse_cm, 'cm') + ' / 기준 ' + number(threshold.max_validation_rmse_cm, 'cm') + '\n' +
    '독립 최대 오차: ' + number(metric.validation_max_error_cm, 'cm') + ' / 기준 ' + number(threshold.max_validation_error_cm, 'cm') + '\n' +
    '독립 사진/점: ' + (metric.validation_frames || 0) + '/' + (metric.validation_points || 0) +
      ' / 기준 ' + (threshold.min_validation_frames || '-') + '/' + (threshold.min_validation_points || '-') + '\n' +
    '검증 거리 폭: ' + number(metric.validation_span_cm, 'cm') + ' / 기준 ' + number(threshold.min_validation_span_cm, 'cm') + '\n' +
    '검증 거리: ' + range + '\n' +
    '좌우 거리: ' + (value.lateral_available ? 'robot frame 사용 가능' : '사용 안 함') + '\n' +
    '적용: 세션 전용');
}
async function calibrationAction(action) {
  if (action === 'validate_motion' && $('calibrationmotion').disabled) return;
  setTxt('calibrationerror', '');
  if (action === 'retry') action += ':' + ($('calibrationafter').value || 'stay') + ':' + ($('calibrationscope').value || 'full');
  await post('/calibration', action);
}
const api = {
  cmd: v => post('/cmd', v),
  wander: v => post('/wander', v),
  estop: v => post('/estop', v),
  goal: xy => post('/goal', xy),
  tw: (x, z) => post('/teleop', JSON.stringify({ x: x, z: z })),
};
function setTxt(id, t) {
  const el = $(id);
  if (el && el.textContent !== t) el.textContent = t;
}
function setCls(id, cls, on) {
  const el = $(id);
  if (el) el.classList.toggle(cls, !!on);
}
const esc = t => String(t).replace(/&/g, '&amp;').replace(/</g, '&lt;');
// Limits the robot is actually running on; CFG.lim is the offline fallback.
const LIM = () => {
  const limits = Object.assign({}, CFG.lim, S.data.limits || {});
  const active = S.data.motion_limits;
  if (S.data.motion_limits_fresh && active) {
    const keys = {front_stop_m:'stop',front_clear_m:'clear',rear_stop_m:'rear_stop',rear_clear_m:'rear_clear',us_stop_m:'us_stop',body_radius_m:'radius'};
    Object.entries(keys).forEach(([source,key]) => { if (Number.isFinite(active[source])) limits[key]=active[source]; });
    limits.live = true;
    limits.translation = active.translation_mode === true;
    limits.bounded = active.bounded_motion_enabled === true;
    limits.halfWidth = active.footprint_half_width_m;
  }
  return limits;
};

function renderMapping(control) {
  const ready = !!control && control.available;
  const busy = S.mappingBusy || !!(control && control.busy);
  $('mapreset').disabled = !ready || busy;
  $('mapsave').disabled = !ready || busy || !S.data.map || !S.img.im || S.img.gen !== S.data.map[5];
  $('mapresume').disabled = !ready || busy || control.paused !== true;
  $('mappingtoggle').checked = !!control && control.paused === false;
  $('mappingtoggle').disabled = !ready || busy || typeof control.paused !== 'boolean';
  setTxt('mappingstatus', busy ? '처리 중…' : !ready ? 'SLAM 연결 대기' :
    control.paused === true ? '지도 수집 일시정지' :
    control.paused === false ? '지도 수집 중' : '매핑 상태 확인 중…');
}
function plannerStatus(s) {
  const raw = s && s.gstate || '';
  if (raw.startsWith('planning blocked:')) return '지도 경로 계산 대기 · ' + raw.split(/\s+eta=/)[0].replace('planning blocked:', '').trim();
  return raw ? '경로 계획: ' + raw.replace(/\beta=/g, '계획 ETA=').replace(/\bv=/g, '계획 속도=') : '-';
}
function renderNavigation(s) {
  renderNavigationSession(s);
  renderNavigationMotion(s);
  const planningBlocked = s && (s.gstate || '').startsWith('planning blocked:');
  const reason = !s ? '로봇 연결 대기' : s.estop !== false ? '비상정지 상태' :
    !s.map || !s.map_control || s.map_control.paused !== false ? '매핑을 재개해 주세요' :
    !s.pose_available ? '지도 내 로봇 위치 확인 대기' : s.planner_fresh !== true ? '경로 계획 노드 연결 대기 · 매핑 기능을 다시 시작해 주세요' : '';
  $('navexplore').disabled = !!reason || !calibrationReady(s);
  $('navcoverage').disabled = !!reason || !calibrationReady(s);
  const recovery = s && s.wander || '';
  const executionStates = {
    gate_rotation_blocked:'회전 조건 미충족 · 대체 경로 탐색',
    execution_escape_reverse:'관측된 후방 공간으로 이동 · 회전 여유 재확인',
    execution_escape_forward:'관측된 전방 공간으로 이동 · 회전 여유 재확인',
    execution_escape_complete:'공간 확보 이동 완료 · 재탐색',
    execution_escape_stopped:'공간 확보 이동 중단',
  };
  const executionState = Object.keys(executionStates).find(key => recovery.includes(key));
  if (!reason && calibrationReady(s) && executionState) {
    setTxt('navready', executionStates[executionState]);
    return;
  }
  if (!reason && calibrationReady(s) && recovery.includes('stalled_restart_required')) {
    setTxt('navready', '이동 정체 감지 · 자동 재계획 전 대기 중 · 실제 출력과 안전 판단을 확인하세요');
    return;
  }
  if (!reason && calibrationReady(s) && /replanning_|recovery_|alternative_accepted/.test(recovery)) {
    setTxt('navready', recovery.includes('exhausted') ? '자동 복구 중단 · 실행 상태와 정지 사유를 확인하세요' :
      recovery.includes('alternative_accepted') ? '대체 경로 확인 · 주행 재개' : '정체 감지 · 실패한 목표를 제외하고 다른 경로를 찾는 중');
    return;
  }
  if (!reason && calibrationReady(s) && planningBlocked) {
    const startClearance = /robot inside obstacle clearance|map start clearance/.test(s.gstate || '');
    setTxt('navready', '지도 경로 계산 대기 · ' + (startClearance ? '지도 격자의 시작 위치 여유가 부족합니다. ' : '') + '실제 센서 차단 여부는 안전 상태에서 확인하세요');
    return;
  }
  if (!reason && calibrationReady(s) && /^(escape:|verified start connection:)/.test(s.gstate || '')) {
    setTxt('navready', '지도 시작 연결 경로 선택 · 실제 이동 여부와 차단은 모터 출력 및 안전 상태에서 확인하세요');
    return;
  }
  if (!reason && calibrationReady(s) && (s.gstate || '').startsWith('narrow passage:')) {
    setTxt('navready', '좁은 통로 경로 선택 · 계획 ETA와 속도는 실제 이동이 아닙니다. 아래 안전 판단과 최종 출력을 확인하세요');
    return;
  }
  const calibrationWait = limitedSensors(s) ? '보정 완료(일부 센서 모드) · 안전 조건 대기' + (s.calibration.message ? ' · ' + s.calibration.message : '') : existingSettings(s) ? '기존 설정값 · 미보정 · 실시간 안전 조건 대기' + (s.calibration.message ? ' · ' + s.calibration.message : '') : s && s.calibration && s.calibration.calibration_verified === true
    ? '보정 유지 · 센서 재확인 중' + (s.calibration.message ? ' · ' + s.calibration.message : '')
    : '자동 보정을 완료해 주세요';
  setTxt('navready', reason || (!calibrationReady(s) ? calibrationWait : '') || '준비됨 · 모드를 고르면 주행합니다');
}
function renderNavigationMotion(s) {
  const decision = s && s.safety_decision;
  const speed = (v, w) => Number.isFinite(v) && Number.isFinite(w)
    ? (v*100).toFixed(1) + 'cm/s · ' + w.toFixed(3) + 'rad/s' : '수신 대기';
  const lines = [];
  if (decision) {
    lines.push('주행 요청 ' + speed(decision.requested_v, decision.requested_omega));
    lines.push('안전 게이트 최종 출력 ' + speed(decision.safe_v, decision.safe_omega));
    const reasons = {allow:'허용', command_stale:'주행 명령 수신 지연', trajectory_changed:'안전 제한으로 요청 궤적 변경',
      bounded_sweep_unavailable:'이동 궤적 관측 부족', bounded_sweep_blocked:'이동 궤적 여유 부족',
      localization_unavailable:'위치 정보 대기', pickup:'들림 감지'};
    lines.push('안전 판단 ' + ({stop:'정지',limit:'제한',allow:'허용'}[decision.action] || '확인 중') +
      ' · ' + (reasons[decision.reason] || decision.reason || '사유 수신 대기'));
  } else lines.push('최신 안전 판단 수신 대기 · 출력과 정지 사유 확인 불가');
  const limits = s && s.motion_limits_fresh && s.motion_limits;
  if (!limits) lines.push('회전 판단: 최신 안전 정보 대기');
  else if (limits.can_rotate === false) lines.push('회전 보류 · ' +
    (limits.rotation_scan_observed !== true ? '전방위 스캔 관측 미완료' : '관측 완료 · 회전 여유 또는 다른 안전 조건 미충족') +
    (Number.isFinite(limits.rotation_pivot_clearance_m) ? ' · 측정 여유 ' + (limits.rotation_pivot_clearance_m*100).toFixed(1) + 'cm' : ''));
  else if (limits.can_rotate === true) lines.push('회전 조건 허용 · 실제 회전 여부는 최종 출력으로 확인');
  const escape = limits && limits.execution_escape;
  if (escape && Array.isArray(escape.candidates)) {
    const candidates = escape.candidates.filter(item => item && (item.direction === 1 || item.direction === -1) &&
      Number.isFinite(item.target_m) && item.target_m > 0);
    if (candidates.length) lines.push('형상 기반 필요 이동 추정 (이동한 거리 아님): ' + candidates.map(item =>
      (item.direction === 1 ? '전방 ' : '후방 ') + (item.target_m*100).toFixed(1) + 'cm · ' +
      (item.objective === 'restore_rotation' ? '회전 여유 확보 후보' : '여유 개선 후보')).join(' / '));
    else lines.push('형상 기반 이동 후보 없음' + (escape.reason ? ' · ' + escape.reason : ''));
  }
  if (s && s.wander) lines.push('제어 상태 ' + s.wander);
  const execution = s && s.navigation_session_fresh && s.navigation_session && s.navigation_session.execution_escape;
  if (execution && execution.reason) {
    const why = {motion:'공간 확보 이동 요청 중',safety_hold:'실시간 안전 조건 재확인',
      waiting_for_route:'경로 상태 대기',waiting_for_candidate:'최신 이동 후보 대기',
      rotation_restored:'회전 조건 회복',pose_or_geometry_changed:'위치 또는 형상 변경으로 중단',
      budget:'이동 또는 시간 한도 도달',no_progress:'이동 진전 없음',idle:'대기'};
    lines.push('공간 확보 판단: ' + (why[execution.reason] || execution.reason));
    if (Number.isFinite(execution.episode_elapsed_s)) lines.push('현재 복구 경과 ' + execution.episode_elapsed_s.toFixed(1) + '초');
    if (Number.isFinite(execution.remaining_s)) lines.push('복구에 사용 가능한 남은 시간 ' + Math.max(0,execution.remaining_s).toFixed(1) + '초');
    if (Number.isFinite(execution.target_remaining_m)) lines.push('현재 후보 잔여 이동 추정 ' + (execution.target_remaining_m*100).toFixed(1) + 'cm');
  }
  setTxt('navmotion', lines.join(' / '));
}
function renderNavigationSession(s) {
  const session = s && s.navigation_session;
  const fresh = !!(s && s.navigation_session_fresh && session);
  const active = fresh && session.active;
  if (active) setTxt('navsessionerror', '');
  $('navsessionstart').disabled = !fresh || s.planner_fresh !== true || active || !calibrationReady(s) ||
    s.estop !== false || !String(s.wander || '').startsWith('stop') ||
    !s.pose_available || !s.map || !s.map_control || s.map_control.paused !== false;
  ['navstrategy', 'navduration', 'navstall'].forEach(id => { $(id).disabled = !!active; });
  if (!fresh) { setTxt('navsessionstatus', '실행 상태 수신 불가 · 로봇 노드 연결 확인'); return; }
  if (s.planner_fresh !== true) { setTxt('navsessionstatus', '경로 계획 노드 연결 대기 · 지도 수집과 경로 계획 상태를 확인해 주세요'); return; }
  const labels = {gain:'정보량 우선', nearest:'가까운 곳 우선', coverage:'영역 순회'};
  const reasons = {idle:'대기', running:'실행 중', stopped:'사용자 또는 제어 정지',
    interrupted:'안전 조건 변경으로 중단', time_limit:'전체 시간 제한으로 정지',
    no_translation:'이동 정체 제한으로 정지', clock_invalid:'시간 정보 오류로 정지'};
  const options = session.options;
  setTxt('navsessionstatus', (reasons[session.reason] || session.reason) + (options ?
    ` · 적용: ${labels[options.strategy]} · 경과 ${Math.floor(session.elapsed_s)}초 / ${options.duration_s}초 · 남은 ${Math.ceil(session.remaining_s)}초` : ''));
}
async function startNavigationSession() {
  if ($('navsessionstart').disabled) return;
  const options = {strategy:$('navstrategy').value,
    duration_s:Number($('navduration').value), stall_s:Number($('navstall').value)};
  if (!Number.isFinite(options.duration_s) || options.duration_s < 10 || options.duration_s > 3600 ||
      !Number.isFinite(options.stall_s) || options.stall_s < 10 || options.stall_s > 600 || options.stall_s > options.duration_s) {
    setTxt('navsessionerror', '시간 범위를 확인하세요. 정체 제한은 전체 제한 이하여야 합니다.'); return;
  }
  $('navsessionstart').disabled = true;
  setTxt('navsessionerror', '시작 요청 전송 중 · 적용 상태를 확인합니다.');
  try {
    const response = await fetch(API + '/navigation/start', {method:'POST', body:JSON.stringify(options)});
    if (!response.ok) { const result = await response.json(); throw new Error(result.error || '시작 요청 실패'); }
    setTxt('navsessionerror', '요청 전송됨 · 아래 실행 상태가 바뀌는지 확인하세요.');
    await poll();
  } catch (error) { setTxt('navsessionerror', error.message); }
}
async function mappingAction(action) {
  if (S.mappingBusy || $(action === 'reset' ? 'mapreset' : action === 'pause' ? 'mappingtoggle' : 'mapresume').disabled) return;
  // The shared confirmation dialog (focus, Esc, live E-stop above it), not the browser's own prompt.
  if (action === 'reset' && !await (await import('/common/ui.js')).confirmIrreversible({message: '현재 지도를 초기화하고 주행을 정지합니다. 계속할까요?', action: '지도 초기화', opener: $('mapreset')})) return;
  S.mappingBusy = true;
  if (action === 'reset') { S.held.clear(); ksync(); }
  setTxt('mappingerror', '');
  renderMapping(S.data.map_control);
  try {
    const r = await fetch(API + '/map/' + action, { method: 'POST' });
    const result = await r.json();
    if (!r.ok || result.ok === false) throw new Error(result.message || '매핑 요청에 실패했습니다.');
    if (action === 'reset') {
      S.pin = null;
      S.img.gen = -1;
      S.view.ok = false;
      updatePin();
    }
    await poll();
  } catch (e) {
    setTxt('mappingerror', e.message || '로봇과 연결할 수 없습니다.');
  } finally {
    S.mappingBusy = false;
    renderMapping(S.data.map_control);
  }
}
async function saveMapImage() {
  if ($('mapsave').disabled || S.mappingBusy) return;
  const epoch = S.mapEpoch, gen = S.data.map[5], session = S.runtimeId;
  const current = () => !S.mappingBusy && S.runtimeId === session && S.mapEpoch === epoch && S.data.map && S.data.map[5] === gen;
  setTxt('mappingerror', '');
  try {
    // Download the native occupancy raster, not the zoomed canvas (which
    // contains overlays and may be tainted by the separate backend port).
    const response = await fetch(API + '/map.png?g=' + gen + (session ? '&session=' + session : ''), {cache:'no-store'});
    if (!response.ok) throw new Error('지도 PNG를 가져오지 못했습니다.');
    const blob = await response.blob();
    if (!current()) throw new Error('지도가 변경되었습니다. 새 지도에서 다시 저장해 주세요.');
    if (blob.type !== 'image/png' || !blob.size) throw new Error('유효한 지도 PNG가 없습니다.');
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = 'pinky-map-' + new Date().toISOString().replace(/[:.]/g, '-') + '.png';
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  } catch (error) { setTxt('mappingerror', error.message || '지도 저장에 실패했습니다.'); }
}
