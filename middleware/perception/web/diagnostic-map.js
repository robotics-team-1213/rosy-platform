'use strict';
// ---- map view --------------------------------------------------------------
// world metres -> cells: u = (x-ox)/res, v = h-(y-oy)/res (row 0 = top)
// cells -> device px:    X = A.x + u*S, S = k*z (k = base fit, z = user zoom)
// A is the screen position of cell (0,0); pan/zoom move A, meta changes are
// absorbed by re-anchoring the world point at the canvas center.
const cv = $('map'), c = cv.getContext('2d'), wrap = $('mapwrap');
const Sc = () => S.view.k * S.view.z;
function rotateVector(x, y, angle) {
  const co = Math.cos(angle), si = Math.sin(angle);
  return [co*x-si*y, si*x+co*y];
}
function screenPoint(x, y, inverse = false) {
  const q = rotateVector(x-cv.width/2, y-cv.height/2,
                        (inverse ? -1 : 1) * S.view.angle);
  return [q[0]+cv.width/2, q[1]+cv.height/2];
}
function setViewAngle(angle) {
  if (!Number.isFinite(angle)) return;
  S.view.angle = Math.atan2(Math.sin(angle), Math.cos(angle));
  S.view.aligned = true;
  setTxt('viewangle', (S.view.angle*180/Math.PI).toFixed(1) + '°');
  fitReset();
}
function fitView() {
  const W = cv.width, H = cv.height;
  if (!W || !H || !S.data.map) return;
  const m = S.data.map;
  S.view.w = m[0]; S.view.h = m[1]; S.view.res = m[2];
  S.view.ox = m[3]; S.view.oy = m[4];
  const co = Math.abs(Math.cos(S.view.angle)), si = Math.abs(Math.sin(S.view.angle));
  S.view.k = Math.min(W / (S.view.w*co + S.view.h*si),
                     H / (S.view.w*si + S.view.h*co)) * CFG.fit_margin;
  S.view.A.x = (W - S.view.w * Sc()) / 2;
  S.view.A.y = (H - S.view.h * Sc()) / 2;
  S.view.ok = true;
}
function clampPan() {
  const V = S.view, W = cv.width, H = cv.height, s = Sc();
  const fix = (ext, C, a) =>
    (ext * s >= C) ? Math.min(0, Math.max(C - ext * s, a)) : (C - ext * s) / 2;
  V.A.x = fix(V.w, W, V.A.x);
  V.A.y = fix(V.h, H, V.A.y);
}
function zoomAt(cx, cy, f) {
  if (!S.view.ok) return;
  [cx, cy] = screenPoint(cx, cy, true);
  const V = S.view, s = Sc();
  const u0 = (cx - V.A.x) / s, v0 = (cy - V.A.y) / s;
  V.z = Math.min(CFG.zoom_max, Math.max(CFG.zoom_min, V.z * f));
  const s2 = Sc();
  V.A.x = cx - u0 * s2; V.A.y = cy - v0 * s2;
  clampPan(); showZoom(); requestDraw();
}
function viewMetaChanged(m) {
  return !S.view.ok || S.view.w !== m[0] || S.view.h !== m[1] ||
         S.view.res !== m[2] || S.view.ox !== m[3] || S.view.oy !== m[4];
}
function syncView() {
  const m = S.data.map, W = cv.width, H = cv.height;
  if (!m || !W || !H) { S.view.ok = false; return; }
  if (viewMetaChanged(m)) {
    const world = S.view.ok && S.view.z > 1 && S.view.wc ?
      S.view.wc : null;                    // keep the center world point
    const z = S.view.z;
    S.view.ok = false;                     // force fresh base fit
    fitView();
    S.view.z = z;
    if (world && z > 1) {                  // re-anchor the center point
      const u = (world[0] - S.view.ox) / S.view.res;
      const v = S.view.h - (world[1] - S.view.oy) / S.view.res;
      S.view.A.x = W / 2 - u * Sc();
      S.view.A.y = H / 2 - v * Sc();
    }
    clampPan();
  }
  const V = S.view;
  V.wc = [ V.ox + (W / 2 - V.A.x) / Sc() * V.res,
           V.oy + (V.h - (H / 2 - V.A.y) / Sc()) * V.res ];
}
function w2c(x, y) {
  const V = S.view;
  return [ V.A.x + ((x - V.ox) / V.res) * Sc(),
           V.A.y + (V.h - (y - V.oy) / V.res) * Sc() ];
}
function c2w(X, Y) {
  [X, Y] = screenPoint(X, Y, true);
  const V = S.view;
  return [ V.ox + ((X - V.A.x) / Sc()) * V.res,
           V.oy + (V.h - (Y - V.A.y) / Sc()) * V.res ];
}
function requestDraw() {
  if (!S.raf) S.raf = requestAnimationFrame(() => { S.raf = 0; draw(S.data); });
}
// ---- draw: raster + overlays ----------------------------------------------
function draw(s) {
  const W = cv.width, H = cv.height;
  if (!W || !H) return;
  const dpr = window.devicePixelRatio || 1;
  c.fillStyle = T.unk;
  c.fillRect(0, 0, W, H);
  if (!s.map) {
    S.view.ok = false;
    $('mapnote').hidden = false;
    return;
  }
  $('mapnote').hidden = true;
  // Lock the first valid heading; subsequent robot turns never spin the map.
  // Map orientation changes only through explicit operator controls.
  syncView();
  c.save();
  c.translate(W/2, H/2); c.rotate(S.view.angle); c.translate(-W/2, -H/2);
  if (S.img.im && S.img.meta && S.img.meta.slice(0, 5).every((v, i) => v === s.map[i])) {
    // stale-while-revalidate: the previous raster stays until the next one
    // has decoded — a fresh gen must never blank the map (the blink).
    c.imageSmoothingEnabled = false;
    const V = S.view;
    c.drawImage(S.img.im, V.A.x, V.A.y, V.w * Sc(), V.h * Sc());
  }
  const W2C = w2c;
  function line(pts, color, width) {
    if (!pts || pts.length < 2) return;
    c.strokeStyle = color; c.lineWidth = width;
    c.lineJoin = 'round'; c.lineCap = 'round';
    c.beginPath();
    pts.forEach((p, i) => {
      const q = W2C(p[0], p[1]);
      if (i === 0) c.moveTo(q[0], q[1]); else c.lineTo(q[0], q[1]);
    });
    c.stroke();
  }
  line(s.trail, T.hist, 1.5 * dpr);
  const haveRoute = s.route && s.route.length > 1;
  (s.options || []).forEach((o, i) => {
    if (i === 0 && haveRoute) return;   // chosen option == the route
    line(o, T.alt, (i === 0 ? 3 : 1.5) * dpr);
  });
  if (haveRoute && s.pose) {
    let bi = 0, bd = Infinity;
    s.route.forEach((p, i) => {
      const d = (p[0] - s.pose[0]) ** 2 + (p[1] - s.pose[1]) ** 2;
      if (d < bd) { bd = d; bi = i; }
    });
    const rkey = s.route.length + '@' + s.route[0][0].toFixed(2) + ',' +
      s.route[0][1].toFixed(2) + '-' + s.route[s.route.length - 1][0].toFixed(2) +
      ',' + s.route[s.route.length - 1][1].toFixed(2);
    if (S.split.key !== rkey) S.split = { key: rkey, bi: bi };
    else {
      const po = s.pose, ps = s.route[S.split.bi];
      const dOld = (ps[0] - po[0]) ** 2 + (ps[1] - po[1]) ** 2;
      if (bd * 2.5 < dOld) S.split.bi = bi;
    }
    bi = S.split.bi;    line(s.route.slice(0, bi + 1), T.hist, 1.5 * dpr);  // traveled
    line(s.route.slice(bi), T.route, 2 * dpr);          // to-go
    const step = s.route.length > 40 ? 3 : 1;
    for (let i = bi + 1; i < s.route.length; i += step) {
      const q = w2c(s.route[i][0], s.route[i][1]);
      c.fillStyle = T.route;
      c.beginPath(); c.arc(q[0], q[1], 2.5 * dpr, 0, 7); c.fill();
      c.strokeStyle = T.unk; c.lineWidth = 2;           // surface ring
      c.beginPath(); c.arc(q[0], q[1], 2.5 * dpr + 2, 0, 7); c.stroke();
    }
  } else {
    line(s.route, T.route, 2 * dpr);
  }
  if (s.goal_pt) {
    const g = w2c(s.goal_pt[0], s.goal_pt[1]);
    const a = 5 * dpr;
    c.strokeStyle = T.goal; c.lineWidth = 2.5 * dpr; c.lineCap = 'round';
    c.beginPath();
    c.moveTo(g[0] - a, g[1] - a); c.lineTo(g[0] + a, g[1] + a);
    c.moveTo(g[0] + a, g[1] - a); c.lineTo(g[0] - a, g[1] + a);
    c.stroke();
  }
  if (s.pose) {
    const p = w2c(s.pose[0], s.pose[1]);
    const yaw = s.pose[2] || 0;
    // True-scale body circle: at desk scale the 7.6 cm chassis is the unit
    // the operator judges gaps in, so draw the body, not a generic marker.
    const rpx = (LIM().radius / S.view.res) * Sc();
    if (rpx > 3) {
      c.fillStyle = T.bodyFill;
      c.strokeStyle = T.bodyLine; c.lineWidth = 1 * dpr;
      c.beginPath(); c.arc(p[0], p[1], rpx, 0, 7); c.fill(); c.stroke();
    }
    const arm = Math.max(14 * dpr, rpx + 4 * dpr);
    c.strokeStyle = T.route; c.lineWidth = 2 * dpr;
    c.beginPath(); c.moveTo(p[0], p[1]);
    c.lineTo(p[0] + arm * Math.cos(yaw), p[1] - arm * Math.sin(yaw));
    c.stroke();
    c.fillStyle = T.route;
    c.beginPath(); c.arc(p[0], p[1], 5 * dpr, 0, 7); c.fill();
    c.strokeStyle = T.unk; c.lineWidth = 2 * dpr;
    c.beginPath(); c.arc(p[0], p[1], 5 * dpr + 2 * dpr, 0, 7); c.stroke();
  }
  if (S.pin) {
    const q = w2c(S.pin.x, S.pin.y);
    c.strokeStyle = T.pin; c.lineWidth = 2 * dpr;
    c.beginPath(); c.arc(q[0], q[1], 6 * dpr, 0, 7); c.stroke();
    c.fillStyle = T.pin;
    c.beginPath(); c.arc(q[0], q[1], 2 * dpr, 0, 7); c.fill();
  }
  c.restore();
}
// ---- lidar dial ------------------------------------------------------------
// Nose up. Rings every 10 cm, safety's stop distance drawn as a no-go annulus,
// and the chassis drawn at true scale inside it — so the picture and the
// gauges below are visibly the same measurement.
function wrapPi(a) { return Math.atan2(Math.sin(a), Math.cos(a)); }
// The nose bearing comes from the base<-scan TF that web_node resolves, the
// same one safety uses. Without it the scan frame is unknown, so refuse to
// guess a mount angle: every bearing would be wrong by the same amount.
function noseYaw(sc) {
  const n = sc && sc.nose_yaw;
  return (typeof n === 'number' && isFinite(n)) ? n : null;
}
function bucket(sc, lo, hi) {
  const nose = noseYaw(sc);
  if (nose == null) return null;
  let m = null;
  for (let i = 0; i < sc.rs.length; i++) {
    const deg = wrapPi(sc.amin + i * sc.inc - nose) * 180 / Math.PI;
    if (deg < lo || deg > hi) continue;
    const r = sc.rs[i];
    if (r > sc.rmin && r < sc.rmax && (m == null || r < m)) m = r;
  }
  return m;
}
const dialCv = $('scan'), scv = dialCv.getContext('2d');
// [from deg, to deg] in robot frame (nose = 0, left = +): the beams that feed
// the 정면 / 왼쪽 / 오른쪽 gauge rows.
const WEDGES = [[-10, 10], [45, 135], [-135, -45]];
function drawScan(s) {
  const W = dialCv.width, H = dialCv.height;
  if (!W || !H) return;
  const sc = s.scan;
  const nose = noseYaw(sc);
  const cx = W / 2, cy = H / 2, R = W / 2 - 14;
  const lim = LIM();
  const view = Math.max(0.25, Math.min(sc ? sc.rmax : lim.open_max,
                                       lim.open_max));
  const k = R / view;
  scv.clearRect(0, 0, W, H);
  scv.fillStyle = T.wedge;
  WEDGES.forEach(([lo, hi]) => {
    scv.beginPath(); scv.moveTo(cx, cy);
    for (let d = lo; d <= hi; d += 2) {
      const th = d * Math.PI / 180;
      scv.lineTo(cx - view * k * Math.sin(th), cy - view * k * Math.cos(th));
    }
    scv.closePath(); scv.fill();
  });
  scv.strokeStyle = T.grid; scv.lineWidth = 1;
  for (let d = 0.1; d < view - 0.001; d += 0.1) {
    scv.beginPath(); scv.arc(cx, cy, d * k, 0, 7); scv.stroke();
  }
  if (nose != null && sc.rs && sc.rs.length) {
    // One closed silhouette of the space the robot is standing in, then the
    // hits on top. A fan of per-beam rays just fills the middle with haze.
    const pts = [];
    for (let i = 0; i < sc.rs.length; i++) {
      const r = sc.rs[i];
      const ok = r > sc.rmin && r < sc.rmax;
      const th = wrapPi(sc.amin + i * sc.inc - nose);
      const d = ok ? Math.min(r, view) : view;   // no return = open, not near
      pts.push([cx - d * k * Math.sin(th), cy - d * k * Math.cos(th), ok, r]);
    }
    scv.beginPath();
    pts.forEach((p, i) => i ? scv.lineTo(p[0], p[1]) : scv.moveTo(p[0], p[1]));
    scv.closePath();
    scv.fillStyle = T.space;
    scv.strokeStyle = T.spaceLine; scv.lineWidth = 1;
    scv.fill(); scv.stroke();
    pts.forEach(([px, py, ok, r]) => {
      if (!ok) return;
      scv.fillStyle = lim.translation || lim.bounded ? T.route : r < lim.stop ? T.crit : (r < lim.clear ? T.warn : T.route);
      scv.beginPath(); scv.arc(px, py, 2.6, 0, 7); scv.fill();
    });
  }
  // the line safety halts at — a boundary, so a ring rather than a disc
  scv.strokeStyle = T.haltLine; scv.lineWidth = 1.2;
  scv.setLineDash([4, 4]);
  scv.beginPath();
  if (lim.translation && Number.isFinite(lim.halfWidth)) {
    const half = (lim.halfWidth + .010) * k;
    scv.rect(cx-half, cy-lim.stop*k, 2*half, (lim.stop+lim.rear_stop)*k);
  } else scv.arc(cx, cy, lim.stop * k, 0, 7);
  if (!lim.bounded) scv.stroke();
  scv.setLineDash([]);
  // chassis at true scale, nose marker on its rim
  const body = lim.radius * k;
  scv.fillStyle = T.chassis;
  scv.strokeStyle = T.chassisLine; scv.lineWidth = 1.2;
  scv.beginPath(); scv.arc(cx, cy, body, 0, 7);
  scv.fill(); scv.stroke();
  scv.fillStyle = T.ink;
  scv.beginPath();
  scv.moveTo(cx, cy - body - 9);
  scv.lineTo(cx - 5.5, cy - body + 2);
  scv.lineTo(cx + 5.5, cy - body + 2);
  scv.closePath(); scv.fill();
  scv.fillStyle = T.inkQuiet; scv.font = '11px system-ui, sans-serif';
  scv.textAlign = 'right';
  scv.fillText(Math.round(view * 100) + ' cm', W - 4, cy - 5);
  setTxt('dialnote',
    s.scan_reason === 'missing_mount_tf' ? '라이다 장착 TF 없음 — 방향 계산 불가' :
    (nose != null && sc.rs && sc.rs.length) ?
      (lim.bounded ? '정면 위 · 차체 크기 표시 · 이동 궤적 별도 검사' : lim.translation ? '정면 위 · 점선은 차체 외곽과 정지 여유' : '정면 위 · 참고 정면 거리 ' + Math.round(lim.stop * 100) + ' cm') :
      '라이다 대기');
}
// ---- 감지: clearance gauges -------------------------------------------------
// Every channel is a distance the robot is about to run out of, so each gets
// the same shape: a bar, a fixed threshold tick, a value in centimetres.
// more:true = bigger is better, so no threshold and no alarm colour.
const CH = [
  { k: 'F',        ko: '정면',        topic: '/safety/min_range', lead: true },
  { k: 'L',        ko: '왼쪽',        topic: '/safety/left_range' },
  { k: 'R',        ko: '오른쪽',      topic: '/safety/right_range' },
  { k: 'US',       ko: '초음파',      topic: '/safety/us_range',  us: true },
  { k: 'rear',     ko: '뒤',          topic: '/safety/rear_range' },
  { k: 'rear L',   ko: '뒤 왼쪽',     topic: '/safety/rear_left',  opt: true },
  { k: 'rear R',   ko: '뒤 오른쪽',   topic: '/safety/rear_right', opt: true },
  { k: 'open',     ko: '최대 개방',   topic: '/safety/open_range', more: true },
  { k: 'corridor', ko: '통로 폭',     topic: '/safety/corridor',   corridor: true },
  { k: 'cam side', ko: '카메라 측면', topic: '/camera/side', more: true, opt: true },
];
const gid = k => 'g' + k.replace(/[^A-Za-z]/g, '');
function chLimits(ch) {
  const L = LIM();
  if (ch.us) return { scale: 0.10, stop: L.us_stop, clear: L.us_clear };
  if (L.bounded) return {scale:ch.corridor ? .80 : L.open_max,stop:null,clear:null};
  // below two body widths the robot cannot turn around in the corridor
  if (ch.corridor) return { scale: 0.80, stop: 2 * L.radius,
                            clear: 2 * L.radius + 0.04 };
  if (ch.more) return { scale: L.open_max, stop: null, clear: null };
  if (ch.k === 'rear' && L.live) return {scale:L.open_max,stop:L.rear_stop,clear:L.rear_clear};
  if (L.live && ch.k !== 'F') return {scale:L.open_max,stop:L.radius+.010,clear:L.radius+.020};
  return { scale: L.open_max, stop: L.stop, clear: L.clear };
}
function buildGauges(shown) {
  const key = shown.join('|') + '#' + JSON.stringify(LIM());
  if (S.gaugeKey === key) return;
  S.gaugeKey = key;
  $('gauges').innerHTML = CH.filter(ch => shown.indexOf(ch.k) >= 0).map(ch => {
    const L = chLimits(ch);
    const tick = L.stop == null ? '' :
      '<i class="g-x" style="left:' +
      (100 * Math.min(1, L.stop / L.scale)).toFixed(1) + '%"></i>';
    return '<div class="gauge' + (ch.lead ? ' lead' : '') + '" id="' +
      gid(ch.k) + '" title="' + ch.topic + '">' +
      '<span class="g-k">' + ch.ko + '</span>' +
      '<span class="g-t"><i class="g-f" id="' + gid(ch.k) + 'f"></i>' + tick +
      '</span><span class="g-v" id="' + gid(ch.k) + 'v">-</span></div>';
  }).join('');
}
function paintGauge(ch, v) {
  const L = chLimits(ch), row = $(gid(ch.k));
  const fill = $(gid(ch.k) + 'f'), val = $(gid(ch.k) + 'v');
  if (!row || !fill || !val) return;
  const has = v != null && isFinite(v);
  row.classList.toggle('miss', !has);
  fill.style.width = has ?
    (100 * Math.min(1, Math.max(0, v / L.scale))).toFixed(1) + '%' : '0%';
  const lvl = (!has || L.stop == null) ? '' :
    (v < L.stop ? 'crit' : (v < L.clear ? 'warn' : ''));
  fill.classList.toggle('crit', lvl === 'crit');
  fill.classList.toggle('warn', lvl === 'warn');
  val.classList.toggle('crit', lvl === 'crit');
  val.classList.toggle('warn', lvl === 'warn');
  val.textContent = has ? (v * 100).toFixed(v < 0.1 ? 1 : 0) + ' cm' : '—';
}
// ---- 감지: safety flags -----------------------------------------------------
// Polarity matters: 'rear clear' true is good, 'cliff' true is bad. Off-states
// stay on screen so "no cliff" is visible rather than merely absent.
const FLAGS = [
  { k: 'blocked',     ko: '전방 차단',       topic: '/safety/blocked',   bad: true },
  { k: 'cliff',       ko: '낭떠러지',        topic: '/safety/cliff',     bad: true },
  { k: 'tilt',        ko: '기울어짐',        topic: '/safety/tilt',      bad: true },
  { k: 'pickup',      ko: '들림',            topic: '/safety/pickup',    bad: true },
  { k: 'cam blocked', ko: '영상 물체 후보', topic: '/camera/blocked', observation: true },
  { k: 'cam cliff',   ko: '영상 바닥 변화', topic: '/camera/cliff', observation: true },
  { k: 'rear clear',  ko: '후방 여유',       topic: '/safety/rear_clear' },
  { k: 'can reverse', ko: '후진 가능',       topic: '/safety/can_reverse' },
];
function flagHtml(f, v) {
  const cls = f.observation ? 'flag' : f.bad ? (v ? 'flag hit' : 'flag ok')
                    : (v ? 'flag ok' : 'flag lost');
  return '<span class="' + cls + '" title="' + f.topic + '">' +
         (f.bad && v ? '감지 · ' : '') + f.ko + '</span>';
}
function renderEvidenceScope(s) {
  const el = $('evidencescope');
  if (!el) return;
  const scope = s && s.evidence_scope;
  if (!scope) {
    el.textContent = '로봇이 재는 값';
    return;
  }
  const bits = ['시뮬 증거', 'safety 융합값'];
  if (scope.ir === 'synthetic') bits.push('IR 가상');
  if (scope.us === 'lidar_derived') bits.push('US 라이다 복제');
  if (scope.imu === 'gt_pose') bits.push('IMU GT');
  if (scope.camera === 'synthetic') bits.push('카메라 가상');
  if (scope.camera === 'rendered_pixels') bits.push('카메라 렌더');
  el.textContent = bits.join(' · ');
}
function renderSensors(s) {
  renderEvidenceScope(s);
  const v = Object.assign({}, s.sensors || {});
  const shown = CH.filter(ch => !ch.opt || v[ch.k] != null).map(ch => ch.k);
  buildGauges(shown);
  CH.forEach(ch => { if (shown.indexOf(ch.k) >= 0) paintGauge(ch, v[ch.k]); });
  const lim = LIM();
  const travel = s.motion_limits && s.motion_limits.bounded_translation_limits_m;
  const travelText = Array.isArray(travel) && travel.length === 2 && travel.every(x => Number.isFinite(x) && x >= 0) ?
    '확인된 직진 구간: 전진 ' + (travel[0]*100).toFixed(1) + 'cm / 후진 ' + (travel[1]*100).toFixed(1) + 'cm' : '이동 여유 확인 불가';
  setTxt('clearhint', !lim.live ? '설정 기준 표시 · 실시간 안전 기준 수신 대기' :
    (v.blocked ? '실제 전방 차단 · ' : '실제 전방 차단 없음 · ') +
    (lim.bounded ? '이동 궤적 기준 · ' + travelText + ' · 제자리 회전 별도 판정' :
    (lim.translation ? '차체 외곽 기준 · ' : '회전/일반 기준 · ') +
    '정면 기준 ' + (lim.stop*100).toFixed(1) + 'cm · 후방 기준 ' + (lim.rear_stop*100).toFixed(1) + 'cm'));
  const have = FLAGS.filter(f => v[f.k] != null);
  $('bools').innerHTML = have.length ?
    have.map(f => flagHtml(f, v[f.k])).join('') :
    '<span class="flag">safety 노드 대기</span>';
  renderCamVerdicts(v);
}
// ---- camera -----------------------------------------------------------------
function loadCam(gen) {
  if (!S.previewEnabled) return;
  S.cam.gen = gen;
  const im = $('camimg');
  im.onload = () => {
    if (!S.previewEnabled) return;
    S.cam.t = Date.now();
    im.hidden = false;
    $('camnone').hidden = true;
    $('camcard').hidden = false;
  };
  im.onerror = () => {
    im.hidden = true;
    $('camnone').hidden = false;
  };
  im.src = API + '/camera.jpg?g=' + gen;
}
function renderCamVerdicts(v) {
  const chips = FLAGS.filter(f => f.k.indexOf('cam') === 0 && v[f.k] != null);
  $('camverdict').innerHTML = chips.map(f => flagHtml(f, v[f.k])).join('');
  setTxt('camcap', v['cam dbg'] ? String(v['cam dbg']) : '');
}
