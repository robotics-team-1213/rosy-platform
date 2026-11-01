'use strict';
// ---- inputs: teleop keys + pad (one held-set, one ticker) ------------------
const ACT = {   // action -> [linear, angular] components
  up: [1, 0], down: [-1, 0], left: [0, 1], right: [0, -1],
  ul: [1, 1], ur: [1, -1], dl: [-1, 1], dr: [-1, -1],
};
const KEYMAP = { u: ['ul'], i: ['up'], o: ['ur'], j: ['left'], k: ['stop'],
                 l: ['right'], m: ['dl'], n: ['down'], ',': ['down'],
                 '.': ['dr'], ArrowUp: ['up'], ArrowDown: ['down'],
                 ArrowLeft: ['left'], ArrowRight: ['right'] };
const lin = () => CFG.lin_steps[S.tele.lin];
const ang = () => CFG.ang_steps[S.tele.ang];
function showSpeed() {
  const cms = Math.round(lin() * 100);
  const dps = Math.round(ang() * 180 / Math.PI);
  setTxt('speed', (S.tele.lin + 1) + '/' + CFG.lin_steps.length + ' · ' +
    cms + ' cm/s, ' + dps + '°/s');
}
function showSending() {
  const x = S.tele.x, z = S.tele.z;
  setTxt('sending', (x || z) ?
    (x * 100).toFixed(0) + ' cm/s, ' +
    (z * 180 / Math.PI).toFixed(0) + '°/s' : '정지');
}
function ktick() {
  if (!calibrationReady(S.data)) { S.held.clear(); api.tw(0, 0); return; }
  let x = 0, z = 0;
  S.held.forEach(a => {
    const d = ACT[a];
    if (d) { x += d[0] * lin(); z += d[1] * ang(); }
  });
  S.tele.x = x; S.tele.z = z;
  showSending();
  api.tw(x, z);
}
function ksync() {
  if (S.held.has('stop')) S.held.clear();
  if (S.held.size === 0) {
    if (S.kt) { clearInterval(S.kt); S.kt = null; api.tw(0, 0); }
    S.tele.x = 0; S.tele.z = 0;
    showSending();
  } else if (!S.kt) {
    S.kt = setInterval(ktick, CFG.teleop_period_ms);
    ktick();
  }
  document.querySelectorAll('#keys span').forEach(el =>
    el.classList.toggle('on', S.held.has(el.dataset.a)));
}
function hold(a) {
  if (a === 'stop') { S.held.clear(); ksync(); return; }
  const comp = ACT[a];
  if (!comp) return;
  S.held.add(a);
  ksync();
}
function release(a) {
  const comp = ACT[a];
  if (!comp) return;
  S.held.delete(a);
  ksync();
}
window.addEventListener('keydown', e => {
  if (e.target instanceof HTMLInputElement) return;
  const k = e.key;
  if (k === '-' || k === '_') { stepSpeed(-1); return; }
  if (k === '+' || k === '=' || k === 'ArrowUp' && e.shiftKey) { stepSpeed(1); return; }
  if (k === 'f') { fitReset(); return; }
  const a = KEYMAP[k];
  if (!a || e.repeat) return;
  e.preventDefault();
  a.forEach(hold);
});
window.addEventListener('keyup', e => {
  const a = KEYMAP[e.key];
  if (a) a.forEach(release);
});
window.addEventListener('blur', () => { S.held.clear(); ksync(); });
function stepSpeed(d) {
  const cl = CFG.lin_steps.length - 1;
  S.tele.lin = Math.min(cl, Math.max(0, S.tele.lin + d));
  S.tele.ang = Math.min(cl, Math.max(0, S.tele.ang + d));
  showSpeed();
}
// ---- map interactions: wheel zoom, drag pan, click pin, hover coords -------
let drag = null;
cv.addEventListener('wheel', e => {
  e.preventDefault();
  const r = cv.getBoundingClientRect(), dpr = window.devicePixelRatio || 1;
  zoomAt((e.clientX - r.left) * dpr, (e.clientY - r.top) * dpr,
         e.deltaY < 0 ? CFG.zoom_step : 1 / CFG.zoom_step);
}, { passive: false });
cv.addEventListener('pointerdown', e => {
  drag = { x: e.clientX, y: e.clientY, moved: false };
  cv.setPointerCapture(e.pointerId);
});
cv.addEventListener('pointermove', e => {
  const r = cv.getBoundingClientRect(), dpr = window.devicePixelRatio || 1;
  const cx = (e.clientX - r.left) * dpr, cy = (e.clientY - r.top) * dpr;
  if (S.view.ok) {
    const w = c2w(cx, cy);
    setTxt('coords', w[0].toFixed(2) + ', ' + w[1].toFixed(2) + ' m');
  }
  if (!drag) return;
  const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
  if (!drag.moved && Math.hypot(dx, dy) > CFG.click_slop_px) drag.moved = true;
  if (drag.moved && S.view.ok && S.view.z > 1) {
    const delta = rotateVector(dx*dpr, dy*dpr, -S.view.angle);
    S.view.A.x += delta[0];
    S.view.A.y += delta[1];
    drag.x = e.clientX; drag.y = e.clientY;
    clampPan(); requestDraw();
    wrap.classList.add('grabbing');
  }
});
cv.addEventListener('pointerup', e => {
  if (drag && !drag.moved && S.view.ok) {
    const r = cv.getBoundingClientRect(), dpr = window.devicePixelRatio || 1;
    const w = c2w((e.clientX - r.left) * dpr, (e.clientY - r.top) * dpr);
    S.pin = { x: w[0], y: w[1] };
    updatePin();
  }
  drag = null;
  wrap.classList.remove('grabbing');
});
cv.addEventListener('pointerleave', () => setTxt('coords', ''));
function fitReset() {
  S.view.z = 1;
  if (S.data.map) fitView();
  clampPan(); showZoom(); requestDraw();
}
function showZoom() { setTxt('zoompct', Math.round(S.view.z * 100) + '%'); }
// ---- pin: click to pin, send relays to /goal/cmd ----------------------------
function updatePin() {
  const has = !!S.pin;
  $('pin').textContent = has ?
    '지점 ' + S.pin.x.toFixed(2) + ', ' + S.pin.y.toFixed(2) + ' m' : '';
  $('pinsend').hidden = !has;
  $('pinclear').hidden = !has;
  draw(S.data);
}
async function sendPin() {
  if (!S.pin) return;
  if (!calibrationReady(S.data) || S.data.estop !== false) {
    setTxt('calibrationerror', '보정 완료와 비상정지 해제 후 지점 이동을 시작할 수 있습니다.');
    return;
  }
  const b = $('pinsend');
  b.disabled = true;
  const ok = await api.goal(S.pin.x.toFixed(3) + ',' + S.pin.y.toFixed(3));
  b.textContent = ok ? '목표 전송됨' : '전송 실패';
  b.disabled = false;
  setTimeout(() => { b.textContent = '이 지점으로'; }, 1200);
}
function clearPin() { S.pin = null; updatePin(); }
// ---- poll: status + bind table ----------------------------------------------
const POSE_WHY = {
  stale_odom: '오도메트리 끊김', missing_map_tf: '지도 TF 없음',
  stale_map_tf: '지도 TF 지연', invalid_map_tf: '지도 TF 오류',
  mapping_paused: '매핑 일시정지',
};
const BIND = [
  ['mode', s => s.mode || '-'],
  ['wander', s => s.wander || '-'],
  ['estop', s => s.estop === true ? '걸림' : (s.estop === false ? '해제' : '-')],
  ['ok', s => (s.ok == null) ? '-' : (s.ok ? '정상' : '이상')],
  ['gstate', s => plannerStatus(s)],
  ['ttopic', s => s.teleop_topic || '-'],
  ['health', s => s.health || '-'],
  ['eta', s => (s.gstate || '').startsWith('planning blocked:') ? '-' : (s.eta != null && s.eta > 0) ? '계획 ' + s.eta.toFixed(0) + ' s' : '-'],
  ['vel', s => s.vel ?
    (s.vel[0] * 100).toFixed(1) + ' cm/s, ' +
    (s.vel[1] * 180 / Math.PI).toFixed(0) + '°/s' : '-'],
  ['pose', s => s.pose ?
    s.pose[0].toFixed(2) + ', ' + s.pose[1].toFixed(2) :
    (POSE_WHY[s.pose_reason] || '위치 없음')],
  ['msize', s => s.map ? s.map[0] + '×' + s.map[1] : '-'],
  ['pathm', s => (s.path_m != null) ? s.path_m.toFixed(1) + ' m' : '-'],
  ['rinfo', s => {
    const rp = s.route || [];
    if (rp.length < 2) return '-';
    let m = 0;
    for (let i = 1; i < rp.length; i++)
      m += Math.hypot(rp[i][0] - rp[i - 1][0], rp[i][1] - rp[i - 1][1]);
    return m.toFixed(2) + ' m';
  }],
];
async function poll() {
  const s = await getJson('/state.json');
  if (!s) { $('live').classList.remove('live'); renderMapping(null); renderNavigation(null); renderCalibration(null); renderOverview(null); return; }
  $('live').classList.add('live');
  S.lastOk = Date.now();
  S.data = s;
  if (S.runtimeId !== s.runtime_id || (s.map_control && S.mapEpoch !== s.map_control.epoch)) {
    if (S.mapEpoch !== null) S.view.aligned = false;
    S.runtimeId = s.runtime_id;
    S.mapEpoch = s.map_control ? s.map_control.epoch : null;
    S.img = {gen: -1, im: null, t: 0};
    S.pin = null;
    S.view.ok = false;
    updatePin();
  }
  renderMapping(s.map_control);
  renderNavigation(s);
  renderCalibration(s);
  renderOverview(s);
  BIND.forEach(([id, fn]) => setTxt(id, fn(s)));
  setCls('estopChip', 'crit', s.estop === true);
  setCls('modeChip', 'crit', s.mode === 'ESTOP');
  setCls('okChip', 'crit', s.ok === false);
  setCls('poseCell', 'warnval', !s.pose);
  if (s.map && s.map[5] !== S.img.gen && Date.now() - S.img.t > CFG.map_recheck_ms)
    loadMap(s.map[5]);
  if (s.cam != null && s.cam !== S.cam.gen) loadCam(s.cam);
  renderSensors(s);
  drawScan(s);
  draw(s);
}
// ---- result ------------------------------------------------------------------
const RES_KO = [['ok', '판정'], ['wall_recall', '벽 재현율'],
                ['corridor_purity', '통로 순도'], ['phantom_frac', '허상 비율'],
                ['interior_unknown', '내부 미지']];
async function pollResult() {
  const s = await getJson('/result.json');
  if (!s) return;
  setTxt('pathm', (s.path_m != null) ? s.path_m.toFixed(1) + ' m' : '-');
  const m = s.metrics;
  const card = $('rescard');
  card.hidden = !m;
  if (!m) return;
  $('resrows').innerHTML = RES_KO.filter(([k]) => m[k] != null)
    .map(([k, ko]) => '<div class="srow"><span class="k">' + ko +
      '</span><span class="v">' + esc(m[k]) + '</span></div>').join('');
}
// ---- freshness veils ---------------------------------------------------------
setInterval(() => {
  const stale = S.lastOk && (Date.now() - S.lastOk > CFG.stale_ms);
  const el = $('stale');
  el.hidden = !stale;
  if (stale) setTxt('stale', '수신 끊김 ' +
    Math.round((Date.now() - S.lastOk) / 1000) + '초');
  const camOld = S.cam.t && (Date.now() - S.cam.t > CFG.cam_stale_ms);
  setCls('camimg', 'old', camOld);
  setTxt('camveil', camOld ? '정지된 프레임 ' +
    Math.round((Date.now() - S.cam.t) / 1000) + '초' : '');
}, 500);
// ---- boot: bindings replace the old inline handlers ---------------------------
document.querySelectorAll('[data-post]').forEach(b =>
  b.addEventListener('click', () => post(b.dataset.post, b.dataset.val)));
$('navsessionstart').addEventListener('click', startNavigationSession);
document.querySelectorAll('[data-calibration]').forEach(button =>
  button.addEventListener('click', () => calibrationAction(button.dataset.calibration)));
document.querySelectorAll('[data-hold]').forEach(b => {
  const a = b.dataset.hold;
  b.addEventListener('pointerdown', () => hold(a));
  b.addEventListener('pointerup', () => release(a));
  b.addEventListener('pointerleave', () => release(a));
});
document.querySelectorAll('[data-view]').forEach(b =>
  b.addEventListener('click', () => {
    if (b.dataset.view === 'in') zoomAt(cv.width / 2, cv.height / 2, CFG.zoom_step);
    if (b.dataset.view === 'out') zoomAt(cv.width / 2, cv.height / 2, 1 / CFG.zoom_step);
    if (b.dataset.view === 'fit') fitReset();
    if (b.dataset.view === 'align' && S.data.pose) setViewAngle(S.data.pose[2]);
    if (b.dataset.view === 'left') setViewAngle(S.view.angle - Math.PI/36);
    if (b.dataset.view === 'right') setViewAngle(S.view.angle + Math.PI/36);
    if (b.dataset.view === 'north') setViewAngle(0);
  }));
$('pinsend').addEventListener('click', sendPin);
$('pinclear').addEventListener('click', clearPin);
$('mapreset').addEventListener('click', () => mappingAction('reset'));
$('mapsave').addEventListener('click', saveMapImage);
$('mapresume').addEventListener('click', () => mappingAction('resume'));
$('mappingtoggle').addEventListener('change', () => mappingAction($('mappingtoggle').checked ? 'resume' : 'pause'));
$('cameratoggle').addEventListener('change', togglePreview);
$('camera_ground_toggle').addEventListener('change', async () => {
  const toggle = $('camera_ground_toggle');
  const requested = toggle.checked;
  toggle.disabled = true;
  const ok = await post('/camera/calibration', requested ? 'enable' : 'disable');
  if (!ok) toggle.checked = !requested;
});
try { S.previewEnabled = localStorage.getItem('pinky.preview') !== 'off'; } catch (_) {}
$('cameratoggle').checked = S.previewEnabled;
$('camcard').hidden = !S.previewEnabled;
function fit() {
  const dpr = window.devicePixelRatio || 1;
  const r = wrap.getBoundingClientRect();
  if (r.width < 2 || r.height < 2) return;
  cv.width = Math.round(r.width * dpr);
  cv.height = Math.round(r.height * dpr);
  draw(S.data);
}
new ResizeObserver(fit).observe(wrap);
function loadMap(gen) {
  const epoch = S.mapEpoch;
  const session = S.runtimeId;
  const meta = S.data.map && S.data.map.slice();
  S.img.t = Date.now();
  const image = new Image();
  image.onload = () => {
    if (session !== S.runtimeId || epoch !== S.mapEpoch || !S.data.map || S.data.map[5] !== gen) return;
    S.img.gen = gen; S.img.im = image; S.img.meta = meta; draw(S.data); renderMapping(S.data.map_control);
  };
  image.src = API + '/map.png?g=' + gen + (session ? '&session=' + session : '');
}
setInterval(poll, CFG.poll_ms);
poll();
pollResult();
setInterval(pollResult, CFG.result_ms);
fit();
showZoom();
showSpeed();
showSending();
