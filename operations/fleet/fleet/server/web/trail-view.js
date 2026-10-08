// 지도 위 로봇 궤적(지나온 길)과 D-512 테더 원. 표시 전용 — 목표·교통정리에 쓰지 않는다.
// 궤적은 브라우저가 1 s 상태 폴링의 robot.state.pose(map 프레임)로 모은다: 최근 TRAIL_S 초,
// 최대 TRAIL_MAX 점, TRAIL_STEP_M 이상 움직였을 때만 새 점. 새로 고치면 처음부터 다시 모은다.
// odom 자세(localization.pose_frame)는 지도 좌표가 아니므로 궤적·테더 판정에 쓰지 않는다.
// map-view 가 자기 toPx(격자 칸 또는 D-513 7 로 돌린 미터 뷰)를 넘기므로 지도와 같이 돈다.
export const TRAIL_S = 120, TRAIL_MAX = 600, TRAIL_STEP_M = 0.01, TETHER_POLL_MS = 5000;

const mapPose = (robot) => (robot?.state?.localization?.pose_frame === "odom" ? null : robot?.state?.pose);

export function recordTrails(trails, robots, now) {
  const ids = new Set();
  for (const robot of robots || []) {
    ids.add(robot.robot_id);
    const pose = mapPose(robot);
    const points = trails.get(robot.robot_id) || [];
    const last = points[points.length - 1];
    if (pose && Number.isFinite(pose.x) && Number.isFinite(pose.y)
      && (!last || Math.hypot(pose.x - last.x, pose.y - last.y) >= TRAIL_STEP_M)) {
      points.push({ x: pose.x, y: pose.y, t: now });
    }
    while (points.length && (points.length > TRAIL_MAX || now - points[0].t > TRAIL_S * 1000)) points.shift();
    trails.set(robot.robot_id, points);
  }
  for (const id of trails.keys()) if (!ids.has(id)) trails.delete(id);
  return trails;
}

let tetherAt = 0;
export function drawTrails(ctx, view, toPx, lineWidth, call) {
  const now = Date.now();
  view.trails = recordTrails(view.trails || new Map(), view.robots, now);
  if (call && now - tetherAt > TETHER_POLL_MS) {
    tetherAt = now;
    call("/api/fleet/tethers").then((r) => { view.tethers = r.tethers || []; }, () => {}); // 실패하면 직전 목록을 둔다
  }
  let drawn = 0;
  ctx.save();
  ctx.lineWidth = lineWidth;
  ctx.lineCap = "round";
  view.robots.forEach((robot, index) => {
    const points = view.layers?.poses === false ? [] : view.trails.get(robot.robot_id) || [];
    ctx.strokeStyle = view.colors[index % view.colors.length];
    for (let i = 1; i < points.length; i += 1) {
      const a = toPx(points[i - 1].x, points[i - 1].y), b = toPx(points[i].x, points[i].y);
      ctx.globalAlpha = 0.8 * Math.max(0.1, 1 - (now - points[i].t) / (TRAIL_S * 1000)); // 오래될수록 흐리게
      ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke();
      drawn += 1;
    }
  });
  ctx.globalAlpha = 1;
  ctx.setLineDash([lineWidth * 3, lineWidth * 2]);
  for (const tether of view.tethers || []) {
    const [ax, ay] = tether.anchor_xy, r = tether.radius_m;
    const pose = mapPose(view.robots.find((robot) => robot.robot_id === tether.robot_id));
    // 로봇이 원 밖일 때만 주의 색 — 테더 자체는 경계선일 뿐 경고가 아니다.
    const outside = pose && Math.hypot(pose.x - ax, pose.y - ay) > r;
    ctx.strokeStyle = ctx.fillStyle = window.RosyPalette.cssColor(outside ? "--status-warn" : "--ink-quiet");
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
  window.__trailOverlay = { segments: drawn, tethers: (view.tethers || []).length };
}
