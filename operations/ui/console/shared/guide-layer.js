// D-536 로봇 상황 층 — GET /api/fleet/guide 의 지도 자세를 몸체 원·방향·불확실성 고리로, 안내 목표를 점선과
// 화살표로 그린다. 미터 좌표를 toPoint 하나로 그려 화면 방향(D-513 7)과 위에서 본 보기(D-515)를 그대로 따른다.
// 색은 역할 토큰만 쓴다(D-359). 상태는 색만이 아니라 선 모양(점선 = 추정, 빈 원 = 연결 끊김)과 글로도 말한다.

const SEVERITY_TOKEN = { crit: "--status-crit", warn: "--status-warn", info: "--ink-quiet" };

/** Findings a robot has, worst first (crit, warn, info). */
export function guideFindings(guide, robotId) {
  const row = (guide?.robots || []).find((r) => r.robot_id === robotId);
  const order = { crit: 0, warn: 1, info: 2 };
  return [...(row?.findings || [])].sort((a, b) => order[a.severity] - order[b.severity]);
}

/** Exception-queue rows (D-493 one rule) for one robot; info rows are not queued. */
export function guideAttention(guide, robotId) {
  return guideFindings(guide, robotId).filter((f) => f.severity !== "info")
    .map((f) => ({ severity: f.severity, text: `: ${f.text}`, code: f.code, target: f.target || null }));
}

/** "rosy_26 · LOCALIZED · ±0.12 m" for the chip next to the body circle. */
export function poseLabel(row) {
  if (!row.pose) return `${row.robot_id} · 위치 모름`;
  const pin = row.pose.anchor_source === "operator_pin"   // D-593: 운영자 핀과 그 나이
    ? ` · 운영자 핀${typeof row.pose.anchor_age_s === "number" ? ` ${Math.round(row.pose.anchor_age_s)} s` : ""}` : "";
  return `${row.robot_id} · ±${row.pose.u_m.toFixed(2)} m${row.pose.state === "DEGRADED" ? " · 추정" : ""}${pin}`;
}

/** D-540 4: screen geometry of each placed robot, so the 관제 canvas and the site-map SVG draw the same marks.
 *  ``index`` is the row's place in ``guide.robots`` (the snapshot order the robot colours follow). */
export function guideMarks(guide, toPoint) {
  const scaleAt = (x, y, m) => {
    const a = toPoint(x, y), b = toPoint(x + m, y);
    return Math.hypot(b.x - a.x, b.y - a.y);
  };
  const ahead = (x, y, yaw, m) => toPoint(x + Math.cos(yaw) * m, y + Math.sin(yaw) * m);
  return (guide?.robots || []).flatMap((row, index) => {
    if (!row.pose) return [];
    const { x, y, yaw, u_m: u } = row.pose;
    const target = (row.findings || []).find((f) => f.target)?.target;  // the worst guide's target pose
    return [{ row, index, p: toPoint(x, y), r: Math.max(4, scaleAt(x, y, row.body_radius_m)),
      ring: scaleAt(x, y, row.body_radius_m + u), alert: row.worst && row.worst !== "info" ? row.worst : "",
      tip: typeof yaw === "number" ? ahead(x, y, yaw, row.body_radius_m * 1.6) : null,  // 반경의 1.6배 앞
      target: target ? { q: toPoint(target.x, target.y), tip: ahead(target.x, target.y, target.yaw, 0.08) } : null }];
  });
}

export function drawGuide(ctx, toPoint, { guide, css, colorOf, drawChip, on }) {
  if (!on || !guide?.robots?.length) return;
  const marks = guideMarks(guide, toPoint);
  for (const { row, p, r, ring, alert: worst, tip, target } of marks) {
    const colour = colorOf(row.robot_id);
    const alert = worst ? css(SEVERITY_TOKEN[worst]) : null;
    ctx.save();
    ctx.globalAlpha = row.online ? 1 : 0.4;
    // 불확실성 고리: 몸체 + u. 실제 몸은 이 안 어딘가에 있다.
    ctx.beginPath(); ctx.arc(p.x, p.y, ring, 0, Math.PI * 2);
    ctx.setLineDash([3, 4]); ctx.lineWidth = 1.5; ctx.strokeStyle = colour; ctx.stroke(); ctx.setLineDash([]);
    // 몸체 원(회전 반경). 추정(DEGRADED)은 점선 테두리.
    ctx.beginPath(); ctx.arc(p.x, p.y, r, 0, Math.PI * 2);
    ctx.fillStyle = colour; ctx.globalAlpha *= row.pose.state === "LOCALIZED" ? 0.35 : 0.18; ctx.fill();
    ctx.globalAlpha = row.online ? 1 : 0.4;
    if (row.pose.state !== "LOCALIZED") ctx.setLineDash([4, 3]);
    ctx.lineWidth = alert ? 3 : 2; ctx.strokeStyle = alert || colour; ctx.stroke(); ctx.setLineDash([]);
    if (tip) {  // 방향
      ctx.beginPath(); ctx.moveTo(p.x, p.y); ctx.lineTo(tip.x, tip.y);
      ctx.lineWidth = 3; ctx.strokeStyle = colour; ctx.lineCap = "round"; ctx.stroke();
      const back = Math.atan2(p.y - tip.y, p.x - tip.x);
      ctx.beginPath();
      for (const turn of [-0.5, 0.5]) {
        ctx.moveTo(tip.x, tip.y);
        ctx.lineTo(tip.x + Math.cos(back + turn) * 8, tip.y + Math.sin(back + turn) * 8);
      }
      ctx.stroke();
    }
    // 안내 목표: 가장 나쁜 안내의 목표 자세까지 점선, 목표에 방향 화살표.
    if (target) {
      const { q } = target;
      ctx.beginPath(); ctx.moveTo(p.x, p.y); ctx.lineTo(q.x, q.y);
      ctx.setLineDash([6, 4]); ctx.lineWidth = 2; ctx.strokeStyle = alert || colour; ctx.stroke(); ctx.setLineDash([]);
      ctx.beginPath(); ctx.moveTo(q.x, q.y); ctx.lineTo(target.tip.x, target.tip.y); ctx.lineWidth = 3; ctx.stroke();
      ctx.beginPath(); ctx.arc(q.x, q.y, 4, 0, Math.PI * 2); ctx.fillStyle = alert || colour; ctx.fill();
    }
    ctx.restore();
    drawChip(ctx, null, p.x, p.y - ring - 12, poseLabel(row), worst);
  }
  window.__guideLayer = { robots: marks.length, findings: guide.robots.reduce((n, r) => n + (r.findings || []).length, 0) };
}
