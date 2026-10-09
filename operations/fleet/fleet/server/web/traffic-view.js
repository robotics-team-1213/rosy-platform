// D-517 10 교통 층 그리기 (map-view.js 에서 분리). 폴링과 토글은 map-view.js 가 가진다.

import { signalLampText, trafficDrawing } from "/console/assets/site-map-model.js";

// D-517 10 교통 층 — 블록 띠(점유 채움·허가 테두리·불명 빗금), 구역 윤곽과 "점유 a/b · 대기 n",
// 로봇마다 통행권 끝 가로 표시. 미터 좌표를 toPoint 하나로 그려 화면 방향·위에서 본 보기를 그대로 따른다.
// 테두리는 굵은 선에서 가는 선을 지운 따로 그린 판이라 밑의 실영상을 덮지 않는다.
export function drawTraffic(ctx, toPoint, pxPerM, { view, el, css, colorOf, drawChip, on }) {
  const drawing = on ? trafficDrawing(view.traffic, view.activeSiteMap, view.trafficTrips) : null;
  el("legend-traffic").hidden = !drawing || !(drawing.bands.length || drawing.zones.length || drawing.signals.length);
  if (!drawing) return;
  const band = Math.max(6, Math.min(16, 0.09 * pxPerM));
  const trace = (target, points) => {
    target.beginPath();
    points.forEach(([x, y], i) => { const p = toPoint(x, y); if (i) target.lineTo(p.x, p.y); else target.moveTo(p.x, p.y); });
  };
  const outline = (lines, colour, width, edge, dash = []) => {
    const sheet = document.createElement("canvas");
    sheet.width = ctx.canvas.width; sheet.height = ctx.canvas.height;
    const o = sheet.getContext("2d");
    o.setTransform(ctx.getTransform());
    o.lineJoin = "round";
    o.strokeStyle = colour;
    o.lineWidth = width;
    o.setLineDash(dash);
    for (const line of lines) { trace(o, line); o.stroke(); }
    o.setLineDash([]);
    o.globalCompositeOperation = "destination-out";
    o.lineWidth = width - 2 * edge;
    o.lineCap = "round";
    for (const line of lines) { trace(o, line); o.stroke(); }
    ctx.save(); ctx.setTransform(1, 0, 0, 1, 0, 0); ctx.drawImage(sheet, 0, 0); ctx.restore();
  };
  for (const zone of drawing.zones) outline(zone.lines, css("--ink-quiet"), band + 10, 2);
  const hatch = document.createElement("canvas");
  hatch.width = hatch.height = 8;
  const h = hatch.getContext("2d");
  h.strokeStyle = css("--status-warn"); h.lineWidth = 2;
  h.beginPath(); h.moveTo(0, 8); h.lineTo(8, 0); h.moveTo(-2, 2); h.lineTo(2, -2); h.moveTo(6, 10); h.lineTo(10, 6); h.stroke();
  ctx.save();
  ctx.lineCap = "butt"; ctx.lineJoin = "round"; ctx.lineWidth = band;
  for (const item of drawing.bands) {
    if (item.state === "GRANTED") continue;
    trace(ctx, item.points);
    ctx.strokeStyle = item.state === "OCCUPIED" ? colorOf(item.robot) : ctx.createPattern(hatch, "repeat");
    ctx.globalAlpha = item.state === "OCCUPIED" ? 0.9 : 1;
    ctx.stroke();
  }
  ctx.restore();
  for (const item of drawing.bands.filter((b) => b.state === "GRANTED")) outline([item.points], colorOf(item.robot), band, 2);
  for (const item of drawing.bands.filter((b) => b.state === "UNKNOWN")) outline([item.points], css("--status-warn"), band, 1.5, [4, 3]);
  ctx.save();
  ctx.lineCap = "round";
  // 대열(M3): 앞 로봇에서 팔로워로 가는 가는 선 하나, 리더 색. 띠 위, 통행권 표시 아래.
  for (const line of drawing.convoys) {
    const a = toPoint(line.from.x, line.from.y), b = toPoint(line.to.x, line.to.y);
    ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y);
    ctx.strokeStyle = colorOf(line.leader); ctx.lineWidth = 2; ctx.stroke();
  }
  for (const tick of drawing.ticks) {
    const p = toPoint(tick.x, tick.y);
    const q = toPoint(tick.x + Math.cos(tick.angle) * 0.05, tick.y + Math.sin(tick.angle) * 0.05);
    const span = Math.hypot(q.x - p.x, q.y - p.y) || 1;
    const nx = -(q.y - p.y) / span * band * 0.9, ny = (q.x - p.x) / span * band * 0.9;
    for (const [colour, width] of [[css("--ground-deep"), 6], [colorOf(tick.robot), 3]]) {
      ctx.beginPath(); ctx.moveTo(p.x - nx, p.y - ny); ctx.lineTo(p.x + nx, p.y + ny);
      ctx.strokeStyle = colour; ctx.lineWidth = width; ctx.stroke();
    }
  }
  ctx.restore();
  // 통행권 끝에 로봇 이름 — 띠 색만으로는 어느 로봇의 블록인지 읽히지 않는다(같은 계열 색).
  for (const tick of drawing.ticks) {
    const p = toPoint(tick.x, tick.y);
    drawChip(ctx, null, p.x, p.y - band - 14, tick.robot, "");
  }
  // 구역 글은 차로망 안쪽(가운데 쪽)에 둔다 — 띠·통행권 표시와 바깥 사각형 치수 글을 덮지 않는다.
  const centre = toPoint(...drawing.centre);
  for (const zone of drawing.zones) {
    const p = toPoint(zone.anchor.x, zone.anchor.y);
    const q = toPoint(zone.anchor.x + Math.cos(zone.anchor.angle) * 0.05, zone.anchor.y + Math.sin(zone.anchor.angle) * 0.05);
    const span = Math.hypot(q.x - p.x, q.y - p.y) || 1;
    let nx = -(q.y - p.y) / span, ny = (q.x - p.x) / span;
    if (nx * (centre.x - p.x) + ny * (centre.y - p.y) < 0) { nx = -nx; ny = -ny; }
    const reach = band + 18 + Math.abs(nx) * 52;  // a sideways label needs room for its width
    drawChip(ctx, null, p.x + nx * reach, p.y + ny * reach, zone.label, "");
  }
  // D-525 8: 가상 신호 — 정지선 막대(접근로에 가로)와 그 바깥의 등 하나, 옆에 글자(색만으로 구별하지 않는다).
  const lampColour = { green: css("--status-good"), yellow: css("--status-warn"), red: css("--status-crit") };
  for (const stop of drawing.signals) {
    const p = toPoint(stop.x, stop.y);
    const q = toPoint(stop.x + Math.cos(stop.angle) * 0.05, stop.y + Math.sin(stop.angle) * 0.05);
    const span = Math.hypot(q.x - p.x, q.y - p.y) || 1;
    const nx = -(q.y - p.y) / span, ny = (q.x - p.x) / span, half = band * 0.9;
    ctx.save();
    ctx.lineCap = "butt";
    for (const [colour, width] of [[css("--ground-deep"), 7], [css("--ink"), 3]]) {
      ctx.beginPath(); ctx.moveTo(p.x - nx * half, p.y - ny * half); ctx.lineTo(p.x + nx * half, p.y + ny * half);
      ctx.strokeStyle = colour; ctx.lineWidth = width; ctx.stroke();
    }
    // D-525 rev 3: T-map 식 신호 알약 — 등 하나와 남은 초. 주황 점선 테두리와 "가상" 글자로 실제 신호기가
    // 아님을 말한다(색만으로 말하지 않는다). "≥7"은 구역이 비어야 켜지는 다음 녹색의 하한이다.
    const cx = p.x + nx * (half + 26), cy = p.y + ny * (half + 26);
    const label = stop.count ? `${signalLampText(stop.lamp)} ${stop.count}` : signalLampText(stop.lamp);
    ctx.font = `600 12px ${css("--font-mono") || "monospace"}`;
    const w = 30 + ctx.measureText(label).width, h = 22;
    ctx.beginPath(); ctx.roundRect(cx - w / 2, cy - h / 2, w, h, 11);
    ctx.fillStyle = css("--ground-deep"); ctx.fill();
    ctx.setLineDash([4, 3]); ctx.lineWidth = 2; ctx.strokeStyle = css("--status-warn"); ctx.stroke(); ctx.setLineDash([]);
    ctx.beginPath(); ctx.arc(cx - w / 2 + 12, cy, 6, 0, Math.PI * 2);
    ctx.fillStyle = lampColour[stop.lamp] || lampColour.red; ctx.fill();
    ctx.fillStyle = css("--ink"); ctx.textAlign = "left"; ctx.textBaseline = "middle";
    ctx.fillText(label, cx - w / 2 + 22, cy + 0.5);
    ctx.font = `600 10px ${css("--font-mono") || "monospace"}`; ctx.fillStyle = css("--status-warn"); ctx.textAlign = "center";
    ctx.fillText("가상", cx, cy - h / 2 - 7);
    ctx.restore();
  }
  window.__trafficLayer = { bands: drawing.bands.length, zones: drawing.zones.length, ticks: drawing.ticks.length,
    convoys: drawing.convoys.length, signals: drawing.signals.length };
}
