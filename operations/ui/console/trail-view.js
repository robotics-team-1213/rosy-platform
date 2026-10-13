// 지도 위 로봇 경로(지나온 길)와 D-512 테더 원(D-526 감시 정지면 위험 색). 표시 전용 — 목표·교통정리에 쓰지 않는다.
// D-594: 경로는 Fleet 이 1 s 마다 기록한 지도 좌표다(GET /api/fleet/robots/{id}/path). 범위를 고르면 그 범위를
// 한 번 받고, 그 뒤로는 PATH_POLL_MS 마다 마지막 점 뒤만 받는다. 새로 고쳐도 남는다. 선 모양이 상태다:
// LOCALIZED 실선, DEGRADED 파선, CAMERA_ONLY(천장 카메라 추적만) 점선. 위치 미보고(모터 모드)·odom pose 는
// Fleet 이 기록하지 않으므로 지도에 그려지지 않는다. 테더 밖 판정도 LOCALIZED·map 보고만 쓴다(D-526 감시와 같다).
// map-view 가 자기 toPx(격자 칸 또는 D-513 7 로 돌린 미터 뷰)를 넘기므로 지도와 같이 돈다.
export const PATH_POLL_MS = 2000, TRIPS_POLL_MS = 10000, TETHER_POLL_MS = 5000, WATCH_STALE_S = 2, MAX_POINTS = 20000;

const watching = (view) => view.watchAge != null && view.watchAge <= WATCH_STALE_S; // null: no tick yet

/** The robot's pose only when it reports LOCALIZED in the map frame; `localization: null` may be odom. */
export const mapPose = (robot) => {
  const loc = robot?.state?.localization;
  return loc?.state === "LOCALIZED" && loc?.pose_frame === "map" ? robot.state.pose : null;
};

/** "120" / "600" (seconds) or "trip": the robot's open trip, else its most recent one. */
export function pathQuery(range, tripId, entry, key) {
  const base = range === "trip" ? `trip_id=${encodeURIComponent(tripId)}` : null;
  const last = entry?.key === key ? entry.points[entry.points.length - 1] : null;
  if (last) return [base, `since=${last.t}`].filter(Boolean).join("&");
  return base || `last_s=${Number(range)}`;
}

/** A first page replaces the path, a later page of the same key appends after its last point;
 *  a time range drops points older than the range by the server clock (`body.now`). */
export function mergePath(entry, key, body, rangeS) {
  const points = entry?.key === key ? entry.points : [];
  const lastT = points.length ? points[points.length - 1].t : -Infinity;
  for (const point of body.points || []) if (point.t > lastT) points.push(point);
  const from = rangeS == null ? -Infinity : body.now - rangeS;
  let drop = Math.max(0, points.length - MAX_POINTS);
  while (drop < points.length && points[drop].t < from) drop += 1;
  return { key, now: body.now, points: drop ? points.slice(drop) : points };
}

export function tripFor(trips, robotId) {
  const mine = (list) => (list || []).filter((t) => t.robot_id === robotId)
    .sort((a, b) => String(b.created_at).localeCompare(String(a.created_at)))[0];
  return (mine(trips?.open) || mine(trips?.trips))?.trip_id || null;
}

function pollPaths(view, call, now) {
  if (!call || now - (view.pathAt || 0) < PATH_POLL_MS) return;
  view.pathAt = now;
  view.paths ||= new Map();
  const range = view.trailRange || "120";
  if (range === "trip" && now - (view.tripsAt || 0) > TRIPS_POLL_MS) {
    view.tripsAt = now;
    call("/api/fleet/trips").then((r) => { view.trailTrips = r; view.pathAt = 0; }, () => {});
  }
  for (const robot of view.robots || []) {
    const id = robot.robot_id, entry = view.paths.get(id);
    const tripId = range === "trip" ? tripFor(view.trailTrips, id) : null;
    if (view.trailHidden?.has(id) || entry?.busy || (range === "trip" && !tripId)) {
      if (range === "trip" && !tripId) view.paths.delete(id);
      continue;
    }
    const key = `${range}:${tripId || ""}`;
    if (entry) entry.busy = true;
    call(`/api/fleet/robots/${encodeURIComponent(id)}/path?${pathQuery(range, tripId, entry, key)}`).then(
      (body) => {
        if ((view.trailRange || "120") !== range) return; // 범위를 바꾼 뒤 늦게 온 답
        view.paths.set(id, mergePath(view.paths.get(id), key, body, range === "trip" ? null : Number(range)));
      },
      () => {}).finally(() => { const e = view.paths.get(id); if (e) e.busy = false; }); // 실패하면 직전 경로를 둔다
  }
}

// 범위 선택과 로봇별 켜고 끄기(index.html #trail-control). 표시 선호라 권한과 무관하다.
function bindControls(view) {
  const range = document.getElementById("trail-range"), box = document.getElementById("trail-robots");
  if (!range || !box) return { sync() {} };
  view.trailHidden ||= new Set();
  range.addEventListener("change", () => { view.trailRange = range.value; view.paths?.clear(); view.pathAt = 0; });
  let ids = "";
  return {
    sync() {
      const now = (view.robots || []).map((r) => r.robot_id);
      if (now.join("\n") === ids) return;
      ids = now.join("\n");
      box.replaceChildren(...now.map((id) => {
        const label = document.createElement("label"), input = document.createElement("input");
        label.className = "ui-check";
        input.className = "ui-field";
        input.type = "checkbox";
        input.checked = !view.trailHidden.has(id);
        input.addEventListener("change", () => {
          if (input.checked) view.trailHidden.delete(id); else view.trailHidden.add(id);
          view.paths?.delete(id); view.pathAt = 0;
        });
        label.append(input, ` ${id}`);
        return label;
      }));
    },
  };
}

const DASH = { LOCALIZED: [], DEGRADED: [4, 3], CAMERA_ONLY: [1, 2.5] }; // × lineWidth

let tetherAt = 0;
export function drawTrails(ctx, view, toPx, lineWidth, call) {
  const now = Date.now();
  if (typeof document !== "undefined") (view.trailUi ||= bindControls(view)).sync();
  pollPaths(view, call, now);
  if (call && now - tetherAt > TETHER_POLL_MS) {
    tetherAt = now;
    call("/api/fleet/tethers").then((r) => { view.tethers = r.tethers || []; view.watchAge = r.watch_age_s; }, () => {}); // 실패하면 직전 목록을 둔다
  }
  const rangeS = (view.trailRange || "120") === "trip" ? null : Number(view.trailRange || "120");
  let drawn = 0;
  ctx.save();
  ctx.lineWidth = lineWidth;
  ctx.lineCap = "round";
  view.robots.forEach((robot, index) => {
    const entry = view.layers?.poses === false || view.trailHidden?.has(robot.robot_id) ? null : view.paths?.get(robot.robot_id);
    const points = entry?.points || [];
    ctx.strokeStyle = view.colors[index % view.colors.length];
    for (let i = 1; i < points.length; i += 1) {
      const p = points[i - 1], q = points[i];
      if (p.seg !== q.seg) continue; // 기록이 끊긴 곳은 잇지 않는다
      const a = toPx(p.x, p.y), b = toPx(q.x, q.y);
      ctx.setLineDash((DASH[q.state] || DASH.CAMERA_ONLY).map((d) => d * lineWidth));
      ctx.globalAlpha = rangeS == null ? 0.8 : 0.8 * Math.max(0.15, 1 - (entry.now - q.t) / rangeS); // 오래될수록 흐리게
      ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke();
      drawn += 1;
    }
  });
  ctx.globalAlpha = 1;
  ctx.setLineDash([lineWidth * 3, lineWidth * 2]);
  for (const tether of view.tethers || []) {
    const [ax, ay] = tether.anchor_xy, r = tether.radius_m;
    const pose = mapPose(view.robots.find((robot) => robot.robot_id === tether.robot_id));
    // 로봇이 원 밖이면 주의 색, D-526 감시가 정지를 내렸으면 위험 색 — 테더 자체는 경계선일 뿐 경고가 아니다.
    const outside = pose && Math.hypot(pose.x - ax, pose.y - ay) > r;
    // 감시 루프가 멈췄거나(마지막 틱이 2 s 넘게 전, 또는 틱 없음) 죽었으면 정지 못 하니 트립과 같은 위험 색.
    const tripped = tether.watch?.state === "tripped" || !watching(view);
    ctx.strokeStyle = ctx.fillStyle = window.RosyPalette.cssColor(
      tripped ? "--status-crit" : outside ? "--status-warn" : "--ink-quiet");
    ctx.beginPath(); // 원도 toPx 로 점을 찍는다 — 격자 y 뒤집기와 화면 회전을 그대로 따른다.
    for (let k = 0; k <= 48; k += 1) {
      const p = toPx(ax + r * Math.cos(k * Math.PI / 24), ay + r * Math.sin(k * Math.PI / 24));
      if (k === 0) ctx.moveTo(p.x, p.y); else ctx.lineTo(p.x, p.y);
    }
    ctx.stroke();
    const c = toPx(ax, ay);
    ctx.beginPath(); ctx.arc(c.x, c.y, lineWidth * 2.5, 0, Math.PI * 2); ctx.fill();
  }
  ctx.restore();
  window.__trailOverlay = { segments: drawn, tethers: (view.tethers || []).length,
    tripped: (view.tethers || []).filter((t) => t.watch?.state === "tripped").map((t) => t.robot_id),
    watchRunning: watching(view) };
}
