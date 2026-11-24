import { patchHidden, uiTag } from "/common/control-dom.js";
import { iconSvg } from "/common/ui.js";
import { batteryMeterState } from "/console/assets/cockpit-telemetry.js";
import { roadPolylineBetween } from "/console/assets/guide-layer.js";
import { gridCellOf } from "./map-datum.js";

const fmtCoord = (v) => (Math.abs(v) < 0.005 ? 0 : v).toFixed(2);
const mkEl = (tag, cls, txt) => {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (txt != null) n.textContent = txt;
  return n;
};
const iconLabel = (name, text) => {
  const wrap = mkEl("span", ""), svg = name ? iconSvg(name) : null;
  if (svg) wrap.append(svg);
  wrap.append(text);
  return wrap;
};
function makeBattMeter(props) {
  const st = batteryMeterState(props), wrap = mkEl("span", "batt-meter"), fill = mkEl("span", "batt-fill");
  wrap.setAttribute("aria-hidden", "true"); wrap.setAttribute("data-tone", st.tone);
  wrap.setAttribute("data-charging", String(st.charging)); fill.setAttribute("data-meter", st.meter);
  wrap.append(fill); return wrap;
}
function makeGaugeBar(pct, tone = "good") {
  const clamped = Math.max(0, Math.min(100, Math.round(Number.isFinite(pct) ? pct : 0)));
  const bar = mkEl("span", "gauge-bar"), fill = mkEl("span", "gauge-bar-fill");
  fill.setAttribute("data-tone", tone === "info" ? "good" : tone); fill.setAttribute("data-meter", `${clamped}%`);
  bar.append(fill); return bar;
}

const lastSigs = new WeakMap();

export function renderHoverCard(entity, { el, view }) {
  const card = el("map-hover-card");
  if (!card) return;
  if (!entity) {
    lastSigs.delete(card);
    patchHidden(card, true);
    if (card.childElementCount) card.replaceChildren();
    return;
  }
  const clampPct = (v) => Math.max(0, Math.min(100, Math.round(v)));
  const lines = [], bars = [];
  let titleIcon = "robot", title = "", badge = "", badgeTone = "neutral", footer = "";
  if (entity.kind === "pinky") {
    const r = entity.guideRow, robotObj = (view.robots || []).find((item) => item.robot_id === r.robot_id);
    const host = view.robotNames?.[r.robot_id] || robotObj?.hostname || r.robot_id;
    const p = r.pose || {}, deg = typeof p.yaw === "number" ? `${((p.yaw * 180) / Math.PI).toFixed(1)}°` : "—";
    const lane = r.lane, bat = robotObj?.state?.battery, bs = robotObj?.state?.battery_status, ph = robotObj?.power_health?.battery;
    const rawPct = typeof bat?.percent === "number" ? bat.percent : typeof bat?.percentage === "number" ? (bat.percentage <= 1 ? bat.percentage * 100 : bat.percentage) : typeof bs?.shown_percent === "number" ? bs.shown_percent : typeof ph?.percent === "number" ? ph.percent : null;
    const pctNum = typeof rawPct === "number" && Number.isFinite(rawPct) ? clampPct(rawPct) : null;
    const voltVal = bat?.voltage ?? bs?.filtered_voltage ?? ph?.filtered_voltage;
    const volt = typeof voltVal === "number" ? `${voltVal.toFixed(2)}V` : null;
    const charging = Boolean(bat?.charging ?? bs?.charging ?? ph?.charging);
    const rawLat = lane ? (lane.lateral_m ?? lane.offset_m) : null;
    const latM = typeof rawLat === "number" && Number.isFinite(rawLat) ? Math.abs(rawLat) : null;
    const alignPct = latM !== null ? clampPct((1 - Math.min(1, latM / Math.max(0.05, (lane?.width_m ?? 0.18) / 2))) * 100) : null;
    const devices = robotObj?.state?.power?.devices || [], readyCount = devices.filter((d) => d.ready !== false).length;
    const sensorPct = devices.length ? Math.round((readyCount / devices.length) * 100) : null;
    titleIcon = "robot";
    title = `${host} (${r.robot_id})`;
    badge = r.online !== false ? (p.state || "온라인") : "오프라인";
    badgeTone = r.online !== false ? "good" : "warn";
    const hasXY = Number.isFinite(p.x) && Number.isFinite(p.y), cell = hasXY ? ` · 칸 ${gridCellOf(p.x, p.y).label}` : "";
    const unc = typeof p.u_m === "number" ? ` (±${p.u_m.toFixed(2)}m)` : "";
    lines.push(["정밀 좌표 · 방위", `${hasXY ? `(${fmtCoord(p.x)}, ${fmtCoord(p.y)}) m` : "위치 모름"} · HEAD ${deg}${unc}${cell}`]);
    lines.push(["차로 · 센서", `${lane ? lane.edge_id : "자유구역"} · ${devices.length ? `장치 ${readyCount}/${devices.length} 정상` : "장치 미수신"}`]);
    if (pctNum !== null) bars.push(["battery", "배터리", `${pctNum}%${volt ? ` · ${volt}` : ""}`, null, null, { percent: pctNum, charging, online: r.online !== false }]);
    else if (volt) lines.push(["배터리", volt]);
    if (alignPct !== null) bars.push(["pose", "차로 정렬", `${alignPct}% (오차 ${(latM * 100).toFixed(1)}cm)`, alignPct, alignPct >= 75 ? "info" : "warn", null]);
    if (sensorPct !== null) bars.push(["notification", "센서 준비", `${sensorPct}% (${readyCount}/${devices.length})`, sensorPct, "good", null]);
    footer = "클릭하여 선택 · 선택 후 지도 좌표/장소 클릭 시 핀 고정 및 도로 주행";
  } else if (entity.kind === "omx_ai") {
    const anc = entity.anchor, cell = view.omxCells?.[anc.target_id];
    const obsArm = (view.workcellObs?.arms || []).find((o) => o.id === anc.target_id) || null;
    const deg = typeof anc.head_yaw === "number" ? `${((anc.head_yaw * 180) / Math.PI).toFixed(1)}°` : "—";
    const hasHead = anc.live === true && Number.isFinite(anc.head_x) && Number.isFinite(anc.head_y);
    const extM = typeof anc.extension_m === "number" ? anc.extension_m : hasHead ? Math.hypot(anc.head_x - anc.base_x, anc.head_y - anc.base_y) : null;
    const reachM = anc.reach_m || 0.28, reachPct = extM !== null ? clampPct((extM / reachM) * 100) : null;
    const confPct = typeof anc.confidence === "number" ? clampPct(anc.confidence * 100) : null;
    const handoffMap = { arm_a: "S5 (1·3층 적재)", arm_b: "S5 (2층 적재)", arm_s: "S3 (하역 셔틀)" };
    titleIcon = "arm";
    title = anc.label || anc.target_id.toUpperCase();
    badge = anc.cell_status || (cell?.reachable ? "ARM-CELL ONLINE" : anc.live ? "VISION 4X" : "대기");
    badgeTone = anc.live || anc.cell_status ? "good" : "neutral";
    lines.push(["베이스 → 헤드", `(${fmtCoord(anc.base_x)}, ${fmtCoord(anc.base_y)}) → ${hasHead ? `(${fmtCoord(anc.head_x)}, ${fmtCoord(anc.head_y)}) m` : "미수신"} · ${deg}`]);
    lines.push(["관절 · 연계역", `${anc.joints_summary || (anc.live ? "관절 위치 수신" : "위치 미수신")} · Fleet 연계: ${handoffMap[anc.target_id] || "미배정"}`]);
    if (reachPct !== null) bars.push(["expand", "팔 뻗음", `${extM.toFixed(2)}/${reachM.toFixed(2)}m (${reachPct}%)`, reachPct, "info", null]);
    const mParts = [typeof obsArm?.maxCurrentMa === "number" && `${obsArm.maxCurrentMa} mA`, typeof obsArm?.maxTempC === "number" && `${obsArm.maxTempC} °C`].filter(Boolean);
    if (anc.motor_summary) bars.push(["settings", "서보 버스", anc.motor_summary, 100, "good", null]);
    else if (mParts.length) lines.push(["서보 버스", mParts.join(" · ")]);
    if (confPct !== null) bars.push(["image", "4x 추적", `신뢰도 ${confPct}%`, confPct, "good", null]);
    footer = `클릭 시 우측 셀 상세 카드 열기 · ${view.selected || view.focusRobot || "선택한 로봇"} 연계 정류장 즉시 호출 가능`;
  } else if (entity.kind === "place") {
    const pl = entity.place, siteMapObj = view.activeSiteMap?.map;
    const edges = (siteMapObj?.edges || []).filter((e) => e.from === pl.id || e.to === pl.id);
    const edgeDesc = edges.map((e) => `${e.id}(${e.direction === "two_way" ? "양방향" : "일방향"})`).join(", ") || "연결 차로";
    const activeId = view.selected || view.focusRobot || null;
    const guideRow = (view.guide?.robots || []).find((r) => r.robot_id === activeId);
    const road = guideRow?.pose ? roadPolylineBetween(siteMapObj, guideRow.pose, pl) : null;
    const isCharger = String(pl.id).startsWith("C");
    titleIcon = "map";
    title = `${pl.id} · ${pl.name || pl.id}`;
    badge = isCharger ? "충전 스테이션" : (String(pl.id).startsWith("P") ? "대기·분기점" : "작업 정류장");
    lines.push(["지도 좌표 · 도로", `X ${pl.x.toFixed(3)} m, Y ${pl.y.toFixed(3)} m · 칸 ${gridCellOf(pl.x, pl.y).label} · ${edgeDesc}`]);
    if (road) {
      const via = road.places?.length ? road.places.join(" → ") : pl.id;
      lines.push([`${activeId} 도로 경로`, `거리 ${road.length_m.toFixed(2)} m · 경유: ${via}`]);
      const distPct = Math.max(15, Math.min(100, Math.round((1 - Math.min(1, road.length_m / 4.5)) * 100)));
      bars.push(["next", "접근성", `${road.length_m.toFixed(2)}m · 약 ${Math.ceil(road.length_m / 0.15)}초`, distPct, "info", null]);
    }
    footer = `클릭 시 ${pl.id} 핀 고정 및 ${activeId || "선택한 로봇"} 도로(lane_graph) 즉시 주행`;
  }

  const hoverSig = JSON.stringify([titleIcon, title, badge, badgeTone, lines, bars, footer]);
  if (hoverSig !== lastSigs.get(card) || !card.childElementCount) {
    lastSigs.set(card, hoverSig);
    const headRow = mkEl("div", "hover-card-head"), dl = mkEl("dl", "hover-card-grid"), barBox = mkEl("div", "hover-bars");
    const headTitle = mkEl("strong", ""), titleSvg = iconSvg(titleIcon);
    if (titleSvg) headTitle.append(titleSvg);
    headTitle.append(title);
    headRow.append(headTitle, uiTag(badge, badgeTone, "inline"));
    for (const [k, v] of lines) dl.append(mkEl("dt", "", k), mkEl("dd", "", v));
    for (const [icon, label, valText, pct, tone, battery] of bars) {
      const row = mkEl("div", "gauge-row-compact"), meta = mkEl("div", "gauge-meta-line");
      meta.append(iconLabel(icon, label), mkEl("strong", "", valText));
      row.append(meta, battery ? makeBattMeter(battery) : makeGaugeBar(pct, tone));
      barBox.append(row);
    }
    card.replaceChildren(headRow, dl, ...(bars.length ? [barBox] : []), mkEl("p", "hover-card-foot", footer));
  }
  patchHidden(card, false);
}
