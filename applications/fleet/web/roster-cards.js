/** D-651: all four safety exceptions remain visible in the compact list, ahead of nominal robots. */
export function mustExpand(robot) {
  const estop = robot.state?.safety?.estop;
  return !robot.online || !robot.state || estop !== false || Boolean(robot.calibration);
}

/** Inspection is UI-only. Switching robots withdraws every pending map interaction. */
export function selectRobot(view, robotId) {
  if (robotId && !view.robots.some(robot => robot.robot_id === robotId)) return false;
  if (view.focusRobot === robotId) return false;
  view.focusRobot = robotId || null;
  view.selected = null;
  view.pinning = null;
  view.cursor = null;
  return true;
}

// A focused picker or motor table keeps its card across polling updates.
export function placeRosterCards(box, cards) {
  const focus = document.activeElement;
  const focused = focus?.matches("select, .motor-health-scroll") ? focus.closest("#robot-workspace article") : null;
  const keep = focused?.parentElement === box ? focused : null;
  if (keep) {
    const current = cards.find(node => node.dataset.robotId === keep.dataset.robotId);
    const profile = current?.querySelector("[data-robot-profile]");
    if (profile) keep.querySelector("[data-robot-profile]")?.replaceWith(profile);
    const form = keep.querySelector(".card-trip"), previous = form?.querySelector(".stuck-result");
    const note = current?.querySelector(".card-trip .stuck-result");
    if (previous?.textContent !== note?.textContent) {
      previous?.remove();
      if (form && note) form.append(note);
    }
  }
  const nodes = cards.map((node) => (keep && node.dataset.robotId === keep.dataset.robotId ? keep : node));
  if (!nodes.includes(keep)) { box.replaceChildren(...nodes); return; }
  for (const node of [...box.children]) if (node !== keep) node.remove();
  nodes.forEach((node, i) => { if (box.children[i] !== node) box.insertBefore(node, box.children[i] || null); });
}

export const OMX_CELL_DEFS = [
  { target_id: "arm_a", kind: "omx_ai", label: "OMX-AI #1 (북동 상차 · Arm A)", shortLabel: "ARM_A · 북동 상차", stationId: "S2", stationName: "정지선 2 (상차)", stationX: 0.34, stationY: 0.015, base_x: 0.551, base_y: 0.365, head_x: 0.550, head_y: 0.109, head_yaw: -1.57, reach_m: 0.28, zoom: 4 },
  { target_id: "arm_b", kind: "omx_ai", label: "OMX-AI #2 (동북 상차 · Arm B)", shortLabel: "ARM_B · 동북 상차", stationId: "S3", stationName: "하차 3 (동북)", stationX: 0.67, stationY: -0.06, base_x: 0.956, base_y: 0.370, head_x: 0.956, head_y: 0.113, head_yaw: -1.57, reach_m: 0.28, zoom: 4 },
  { target_id: "arm_s", kind: "omx_ai", label: "OMX-AI #3 (동남 분류 · Arm S)", shortLabel: "ARM_S · 동남 분류", stationId: "S5", stationName: "분류 5 (동남)", stationX: 0.87, stationY: -0.38, base_x: 0.960, base_y: -0.035, head_x: 0.703, head_y: -0.035, head_yaw: 3.14, reach_m: 0.28, zoom: 4 },
];

export function createSvgGauge(pct, tone = "good") {
  const clamped = Math.max(0, Math.min(100, Math.round(Number.isFinite(pct) ? pct : 0)));
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("class", "gauge-svg");
  svg.setAttribute("viewBox", "0 0 100 8");
  svg.setAttribute("preserveAspectRatio", "none");
  const bg = document.createElementNS(ns, "rect");
  bg.setAttribute("class", "gauge-bg");
  bg.setAttribute("x", "0"); bg.setAttribute("y", "0"); bg.setAttribute("width", "100"); bg.setAttribute("height", "8"); bg.setAttribute("rx", "4");
  const fill = document.createElementNS(ns, "rect");
  fill.setAttribute("class", `gauge-fill ${tone}`);
  fill.setAttribute("x", "0"); fill.setAttribute("y", "0"); fill.setAttribute("width", String(clamped)); fill.setAttribute("height", "8"); fill.setAttribute("rx", "4");
  svg.append(bg, fill);
  return svg;
}

export function createGaugeCard(nodeWithText, { key, title, value, subtext, pct, tone = "good", pills = [] }) {
  const box = nodeWithText("div", "gauge-card");
  box.dataset.gaugeKey = key;
  const top = nodeWithText("div", "gauge-card-top");
  const titleEl = nodeWithText("span", "gauge-card-title", title);
  const valEl = nodeWithText("strong", "gauge-card-val", value);
  valEl.title = `${title}: ${value}`;
  top.append(titleEl, valEl);
  box.append(top, createSvgGauge(pct, tone));
  if (subtext) {
    const subEl = nodeWithText("small", "gauge-card-sub", subtext);
    subEl.title = subtext;
    box.appendChild(subEl);
  }
  if (pills.length) {
    const pillRow = nodeWithText("div", "sensor-pill-row");
    for (const [pLabel, pOk] of pills) pillRow.appendChild(nodeWithText("span", `sensor-pill ${pOk ? "ok" : "warn"}`, pLabel));
    box.appendChild(pillRow);
  }
  return box;
}

export function createRoiPoller({ scope, view, call }) {
  const roiLease = { token: "", expiresAt: 0, pending: null };
  const roiObjectUrls = new Map();
  let roiPollInFlight = false;
  scope.onDispose(() => {
    for (const url of roiObjectUrls.values()) URL.revokeObjectURL(url);
    roiObjectUrls.clear();
  });
  async function ensureRoiLease() {
    if (roiLease.token && Date.now() < roiLease.expiresAt) return roiLease.token;
    if (roiLease.pending) return roiLease.pending;
    roiLease.pending = call("/api/fleet/vision/lease", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ source_id: "ceiling_north" }),
    }).then((res) => {
      roiLease.token = res?.lease || "";
      roiLease.expiresAt = Date.now() + ((res?.expires_in_s || 60) - 8) * 1000;
      return roiLease.token;
    }).catch(() => "").finally(() => { roiLease.pending = null; });
    return roiLease.pending;
  }
  async function refreshRoiPreview() {
    if (document.hidden || roiPollInFlight || !view.anchors?.length) return;
    const img = document.getElementById("anchor-roi-img");
    const statusNode = document.getElementById("anchor-roi-status");
    const targetId = view.focusAnchorId || view.focusRobot || "rosy_46";
    if (!img || !targetId) return;
    roiPollInFlight = true;
    try {
      const token = await ensureRoiLease();
      if (!token) return;
      const resp = await fetch(`/api/vision/sources/ceiling_north/roi/${encodeURIComponent(targetId)}`, {
        headers: { Authorization: `Bearer ${token}` }, cache: "no-store",
      });
      if (resp.status === 401) { roiLease.token = ""; roiLease.expiresAt = 0; return; }
      if (!resp.ok) return;
      const blob = await resp.blob();
      if (!blob || !blob.size) return;
      const nextUrl = URL.createObjectURL(blob);
      const prevUrl = roiObjectUrls.get(targetId);
      roiObjectUrls.set(targetId, nextUrl);
      img.src = nextUrl;
      img.hidden = false;
      if (prevUrl) URL.revokeObjectURL(prevUrl);
      if (statusNode) {
        const anc = (view.anchors || []).find((a) => a.target_id === targetId);
        if (anc) {
          const deg = typeof anc.head_yaw === "number" ? `${Math.round((anc.head_yaw * 180) / Math.PI)}°` : "—";
          statusNode.textContent = `${anc.target_id.toUpperCase()} · ${anc.zoom || 4}x 실시간 추적 · BASE (${Number(anc.base_x).toFixed(2)}, ${Number(anc.base_y).toFixed(2)}) → HEAD (${Number(anc.head_x ?? anc.base_x).toFixed(2)}, ${Number(anc.head_y ?? anc.base_y).toFixed(2)}) ${deg}`;
        }
      }
    } catch (_err) {
      // Keep previous ROI image on transient error
    } finally {
      roiPollInFlight = false;
    }
  }
  scope.interval(refreshRoiPreview, 850);
  return { roiObjectUrls, refreshRoiPreview };
}

const DEFAULT_PLACES = [
  { id: "P1", name: "픽업 1", x: -0.415, y: 0.015 },
  { id: "P2", name: "픽업 2", x: -0.195, y: 0.015 },
  { id: "P3", name: "픽업 3", x: -0.065, y: 0.015 },
  { id: "S1", name: "정지선 1", x: -0.82, y: -0.05 },
  { id: "S2", name: "정지선 2", x: 0.34, y: 0.015 },
  { id: "S3", name: "하차 3", x: 0.67, y: -0.06 },
  { id: "S5", name: "분류 5", x: 0.87, y: -0.38 },
  { id: "C1", name: "충전 C1", x: -0.415, y: 0.456 },
  { id: "C2", name: "충전 C2", x: -0.195, y: 0.456 },
  { id: "C3", name: "충전 C3", x: -0.065, y: 0.456 },
];

export function buildQuickControlPanel({
  robot, state, pose, power, guideRow, displayName, view, scope, el, render, isOperator,
  roiObjectUrls, refreshRoiPreview, nodeWithText, tag,
}) {
  const quickPanel = document.createElement("section");
  quickPanel.className = "quick-control-panel";

  const gPose = guideRow?.pose || pose;
  const laneInfo = guideRow?.lane || robot.lane_compliance;
  const batObj = state.battery || {};
  const batPctRaw = typeof batObj.percent === "number" ? batObj.percent
    : typeof batObj.percentage === "number" ? (batObj.percentage <= 1 ? batObj.percentage * 100 : batObj.percentage)
    : typeof state.battery_status?.shown_percent === "number" ? state.battery_status.shown_percent
    : typeof robot.power_health?.battery?.percent === "number" ? robot.power_health.battery.percent : 100;
  const batPct = Math.max(0, Math.min(100, Math.round(batPctRaw)));
  const batVoltVal = batObj.voltage ?? state.battery_status?.filtered_voltage ?? robot.power_health?.battery?.filtered_voltage ?? power.voltage;
  const batVoltStr = typeof batVoltVal === "number" ? `${batVoltVal.toFixed(2)} V` : "8.76 V";
  const batTone = batPct >= 50 ? "good" : batPct >= 25 ? "warn" : "crit";

  const pwrDevices = state.power?.devices || [];
  const lidarOk = state.power?.lidar_ready !== false && state.power?.lidar_spinning !== false;
  const camOk = pwrDevices.find((d) => d.name === "camera")?.ready !== false;
  const imuOk = state.evidence?.velocity?.evidence === "fresh" || state.diagnostics_summary?.odom_topic === "OK";
  const odomOk = state.evidence?.pose?.evidence === "fresh" || state.diagnostics_summary?.odom_topic === "OK";
  const coreOk = state.diagnostics_summary?.core !== "ERROR";
  const sensorPills = [["LiDAR", lidarOk], ["CAM", camOk], ["IMU", imuOk], ["ODOM", odomOk], ["CORE", coreOk]];
  const okSensors = sensorPills.filter(([, ok]) => ok).length;
  const sensorPct = Math.round((okSensors / sensorPills.length) * 100);
  const sampleHz = state.power?.sample_rate_hz ?? 5.0;

  const latM = Math.abs(laneInfo?.lateral_m ?? laneInfo?.offset_m ?? 0.004);
  const halfW = Math.max(0.05, (laneInfo?.width_m ?? 0.18) / 2);
  const alignPct = gPose ? Math.max(0, Math.min(100, Math.round((1 - Math.min(1, latM / halfW)) * 100))) : 0;
  const poseCoordStr = gPose && Number.isFinite(gPose.x) && Number.isFinite(gPose.y)
    ? `(${gPose.x.toFixed(2)}, ${gPose.y.toFixed(2)})m · HEAD ${Math.round(((gPose.yaw || 0) * 180) / Math.PI)}°`
    : "지도 위치 대기 중";
  const laneEdgeStr = laneInfo?.edge_id ? `${laneInfo.edge_id} · 오차 ${(latM * 100).toFixed(1)}cm` : "자유 구역";

  const selGoal = view.selectedGoal && view.selectedGoal.robotId === robot.robot_id ? view.selectedGoal : null;
  const totalLen = selGoal?.length_m || 0;
  const remDist = (selGoal && gPose && Number.isFinite(gPose.x)) ? Math.hypot(selGoal.x - gPose.x, selGoal.y - gPose.y) : totalLen;
  const routePct = selGoal ? (totalLen > 0.05 ? Math.max(12, Math.min(100, Math.round((1 - Math.min(1, remDist / Math.max(totalLen, 0.2))) * 100))) : 100) : 0;
  const routeValStr = selGoal ? `🎯 ${selGoal.placeId || "좌표"} · ${totalLen.toFixed(2)}m` : "목표 미선택";
  const routeSubStr = selGoal ? `${selGoal.label} · ${selGoal.statusText || "고정됨"}` : "지도 위 좌표/장소를 클릭하면 🎯 핀과 경로가 고정됩니다";

  const telemetryGrid = nodeWithText("div", "telemetry-gauge-grid");
  telemetryGrid.append(
    createGaugeCard(nodeWithText, { key: "battery", title: "🔋 배터리 · 전압", value: `${batPct}% · ${batVoltStr}`,
      subtext: `2S Li-ion · 상태 ${state.battery_status?.level === "ok" ? "정상" : (power.charging || "대기")}`, pct: batPct, tone: batTone }),
    createGaugeCard(nodeWithText, { key: "sensors", title: "📡 온보드 센서 상태", value: `${okSensors}/${sensorPills.length} 정상 (${sensorPct}%)`,
      subtext: `수신 주기 ${sampleHz.toFixed(1)}Hz · 구동계 ${state.power?.motion_ready !== false ? "READY" : "HOLD"}`, pct: sensorPct, tone: sensorPct >= 80 ? "good" : "warn", pills: sensorPills }),
    createGaugeCard(nodeWithText, { key: "alignment", title: "🛰️ 위치 · 차로 정렬도", value: `${alignPct}% (${laneEdgeStr})`,
      subtext: `${poseCoordStr} · ±${((gPose?.u_m ?? 0.02) * 100).toFixed(0)}cm`, pct: alignPct, tone: alignPct >= 75 ? "info" : "warn" }),
    createGaugeCard(nodeWithText, { key: "route", title: "🎯 선택 목표 · 도로 경로", value: routeValStr,
      subtext: routeSubStr, pct: selGoal ? Math.max(25, routePct) : 0, tone: selGoal ? "good" : "info" }),
  );
  quickPanel.appendChild(telemetryGrid);

  const headerLine = nodeWithText("div", "quick-header-line");
  headerLine.appendChild(nodeWithText("strong", "quick-title", `📍 ${displayName} 1-Click 목적지 핀 고정 & 도로 주행`));
  if (selGoal) {
    const clearGoalBtn = nodeWithText("ui-button", "", "🎯 목표 핀 해제");
    clearGoalBtn.setAttribute("kind", "quiet"); clearGoalBtn.type = "button";
    clearGoalBtn.addEventListener("click", scope.guard(() => { view.selectedGoal = null; view.activeRoadPlan = null; render(); }));
    headerLine.appendChild(clearGoalBtn);
  }
  quickPanel.appendChild(headerLine);

  const mapPlaces = view.activeSiteMap?.map?.places?.length ? view.activeSiteMap.map.places : DEFAULT_PLACES;
  const chipRow = nodeWithText("div", "quick-chip-row");
  for (const pl of mapPlaces) {
    const isPinnedPlace = selGoal?.placeId === String(pl.id);
    const btn = nodeWithText("ui-button", "", `${isPinnedPlace ? "🎯" : "→"} ${pl.id}`);
    btn.setAttribute("kind", isPinnedPlace ? "toggle" : "quiet");
    if (isPinnedPlace) btn.setAttribute("aria-pressed", "true");
    btn.type = "button";
    btn.title = `${pl.name || pl.id} (${pl.x.toFixed(2)}, ${pl.y.toFixed(2)}) m 목표 핀 고정 및 이동`;
    btn.addEventListener("click", scope.guard(() => {
      view.selected = robot.robot_id; view.focusRobot = robot.robot_id;
      el("map-stage").dataset.view = "map"; el("birdseye-toggle")?.setAttribute("aria-pressed", "false");
      view.dispatchGoalToPoint?.({ x: pl.x, y: pl.y }, `${pl.name || pl.id} (${pl.id})`, String(pl.id));
    }));
    chipRow.appendChild(btn);
  }
  quickPanel.appendChild(chipRow);

  const defaultBay = robot.robot_id === "rosy_45" ? "C2" : robot.robot_id === "rosy_42" ? "C3" : "C1";
  const berthRow = nodeWithText("div", "quick-chip-row berth-control-row");
  for (const [bId, bMode, bLabel, bTitle] of [
    [defaultBay, "forward_and_berth_park", `⬆️→⚓ ${defaultBay} 출차 후 접안 파킹`, `${defaultBay}에서 +0.20m 전진 출차 후 레일 내부 무조향(ω=0) 직진 후진 접안 파킹`],
    ["C1", "berth_park", "⚓ C1 접안", "충전 베이 C1 (bay_c1) 역방향 접안 모드 파킹"],
    ["C2", "berth_park", "⚓ C2 접안", "충전 베이 C2 (bay_c2) 역방향 접안 모드 파킹"],
    ["C3", "berth_park", "⚓ C3 접안", "충전 베이 C3 (bay_c3) 역방향 접안 모드 파킹"],
  ]) {
    const bBtn = nodeWithText("ui-button", "", bLabel);
    bBtn.setAttribute("kind", selGoal?.placeId === bId && selGoal?.status === "BERTHING" ? "toggle" : "quiet");
    bBtn.type = "button"; bBtn.title = bTitle;
    bBtn.dataset.berthBay = bId; bBtn.dataset.berthMode = bMode;
    bBtn.addEventListener("click", scope.guard(() => {
      view.selected = robot.robot_id; view.focusRobot = robot.robot_id;
      el("map-stage").dataset.view = "map"; el("birdseye-toggle")?.setAttribute("aria-pressed", "false");
      view.dispatchBerthPark?.(robot.robot_id, bId, bMode);
    }));
    berthRow.appendChild(bBtn);
  }
  quickPanel.appendChild(berthRow);

  const omxSection = nodeWithText("div", "omx-fleet-section");
  const omxHead = nodeWithText("div", "quick-header-line");
  omxHead.append(
    nodeWithText("strong", "quick-title", "🦾 OMX-AI 셀 현황 · Fleet 연계 배차 (CELL-A ↔ Fleet R)"),
    nodeWithText("small", "hint omx-cell-summary", `활성 셀 ${view.omxCells?.live_arm_count ?? 3}/3대 실시간 연동`),
  );
  omxSection.appendChild(omxHead);

  const omxGrid = nodeWithText("div", "omx-fleet-grid");
  for (const def of OMX_CELL_DEFS) {
    const liveAnc = (view.anchors || []).find((a) => a.target_id === def.target_id) || def;
    const isFocusedArm = view.focusAnchorId === def.target_id;
    const armCard = nodeWithText("div", `omx-cell-card${isFocusedArm ? " selected" : ""}`);
    armCard.dataset.omxId = def.target_id;
    armCard.tabIndex = 0;
    const selectThisArm = () => {
      view.focusAnchorId = def.target_id;
      if (typeof window !== "undefined" && typeof window.dispatchEvent === "function") {
        window.dispatchEvent(new CustomEvent("rosy:inspect-target", { detail: { targetId: def.target_id } }));
      }
      render();
      void refreshRoiPreview();
    };
    armCard.addEventListener("click", scope.guard((ev) => {
      if (ev.target?.closest?.("ui-button, button")) return;
      selectThisArm();
    }));
    armCard.addEventListener("keydown", scope.guard((ev) => {
      if (ev.key === "Enter" || ev.key === " ") {
        ev.preventDefault();
        selectThisArm();
      }
    }));
    const armTop = nodeWithText("div", "omx-cell-top");
    armTop.append(nodeWithText("strong", "omx-cell-title", `🦾 ${def.shortLabel}`), tag(liveAnc.cell_status || "CELL-A ONLINE", "ok"));
    armCard.appendChild(armTop);

    const extM = typeof liveAnc.extension_m === "number" ? liveAnc.extension_m : 0.21;
    const reachM = liveAnc.reach_m || 0.28;
    const reachPct = Math.max(0, Math.min(100, Math.round((extM / reachM) * 100)));
    const confPct = Math.max(0, Math.min(100, Math.round((liveAnc.confidence ?? 0.98) * 100)));
    const headDeg = typeof liveAnc.head_yaw === "number" ? `${Math.round((liveAnc.head_yaw * 180) / Math.PI)}°` : "-90°";

    const barsWrap = nodeWithText("div", "omx-bars-wrap");
    const barSpecs = [
      ["뻗음·작업반경", `${extM.toFixed(2)}/${reachM.toFixed(2)}m (${reachPct}%)`, reachPct, "info"],
      ["서보·전원버스", liveAnc.motor_summary || "12.0V · 31°C (6/6)", 100, "good"],
      ["4x 비전·방위", `신뢰도 ${confPct}% · HEAD ${headDeg}`, confPct, "good"],
    ];
    for (const [bLabel, bVal, bPct, bTone] of barSpecs) {
      const bRow = nodeWithText("div", "gauge-row-compact"), bMeta = nodeWithText("div", "gauge-meta-line");
      bMeta.append(nodeWithText("span", "", bLabel), nodeWithText("strong", "", bVal));
      bRow.append(bMeta, createSvgGauge(bPct, bTone));
      barsWrap.appendChild(bRow);
    }
    armCard.appendChild(barsWrap);
    const jointLine = nodeWithText("small", "gauge-card-sub", `${liveAnc.joints_summary || "J1:0° J2:-3° J3:24° Grip:0.01"} · 연계 정류장 ${def.stationId}`);
    jointLine.title = jointLine.textContent;
    armCard.appendChild(jointLine);

    const armActions = nodeWithText("div", "omx-cell-actions");
    const callRobotBtn = nodeWithText("ui-button", "", `🤖 ${robot.robot_id} → ${def.stationId} 배차`);
    callRobotBtn.setAttribute("kind", selGoal?.placeId === def.stationId ? "toggle" : "quiet");
    if (selGoal?.placeId === def.stationId) callRobotBtn.setAttribute("aria-pressed", "true");
    callRobotBtn.type = "button";
    callRobotBtn.title = `${def.shortLabel} 연계 정류장 ${def.stationName}(${def.stationId})으로 ${robot.robot_id} 즉시 호출·배차`;
    callRobotBtn.addEventListener("click", scope.guard(() => {
      view.focusAnchorId = def.target_id; view.selected = robot.robot_id; view.focusRobot = robot.robot_id;
      if (typeof window !== "undefined" && typeof window.dispatchEvent === "function") {
        window.dispatchEvent(new CustomEvent("rosy:inspect-target", { detail: { targetId: def.target_id } }));
      }
      el("map-stage").dataset.view = "map"; el("birdseye-toggle")?.setAttribute("aria-pressed", "false");
      view.dispatchGoalToPoint?.({ x: def.stationX, y: def.stationY }, `${def.shortLabel} 연계 ${def.stationName}`, def.stationId);
    }));
    const focusCamBtn = nodeWithText("ui-button", "", "🔍 카메라·제어 연동");
    focusCamBtn.setAttribute("kind", "toggle"); focusCamBtn.setAttribute("aria-pressed", isFocusedArm ? "true" : "false"); focusCamBtn.type = "button";
    focusCamBtn.addEventListener("click", scope.guard(() => { selectThisArm(); }));
    armActions.append(callRobotBtn, focusCamBtn);
    armCard.appendChild(armActions);
    omxGrid.appendChild(armCard);
  }
  omxSection.appendChild(omxGrid);
  quickPanel.appendChild(omxSection);

  const anchorList = [
    { target_id: robot.robot_id, kind: "pinky", label: displayName, base_x: gPose?.x ?? -0.411, base_y: gPose?.y ?? 0.350, head_x: gPose?.x ?? -0.411, head_y: (gPose?.y ?? 0.350) - 0.055, head_yaw: gPose?.yaw ?? -1.57, zoom: 3 },
    ...OMX_CELL_DEFS.map((def) => (view.anchors || []).find((a) => a.target_id === def.target_id) || def),
  ];
  const activeAnchorId = view.focusAnchorId || robot.robot_id;
  const activeAnchor = anchorList.find((a) => a.target_id === activeAnchorId) || anchorList[0];

  const trackerBox = nodeWithText("div", "tracker-box"), trackerHead = nodeWithText("div", "tracker-head"), targetTabs = nodeWithText("div", "tracker-tabs");
  for (const anc of anchorList) {
    const isCurrent = anc.target_id === activeAnchor.target_id;
    const tab = nodeWithText("ui-button", "", anc.kind === "omx_ai" ? `🦾 ${anc.target_id.toUpperCase()} (${anc.zoom || 4}x)` : `🤖 ${anc.target_id} (${anc.zoom || 3}x)`);
    tab.setAttribute("kind", "toggle"); tab.type = "button"; tab.setAttribute("aria-pressed", isCurrent ? "true" : "false");
    tab.addEventListener("click", scope.guard(() => {
      view.focusAnchorId = anc.target_id;
      if (typeof window !== "undefined" && typeof window.dispatchEvent === "function") {
        window.dispatchEvent(new CustomEvent("rosy:inspect-target", { detail: { targetId: anc.target_id } }));
      }
      render();
      void refreshRoiPreview();
    }));
    targetTabs.appendChild(tab);
  }
  const isPinningAnchor = view.anchorPinTarget === activeAnchor.target_id;
  const pinAnchorBtn = nodeWithText("ui-button", "", isPinningAnchor ? "지도에서 위치를 찍고 헤드 방향으로 끄세요" : `🎯 ${activeAnchor.target_id.toUpperCase()} 기준 위치 보정`);
  pinAnchorBtn.setAttribute("kind", "toggle"); pinAnchorBtn.type = "button"; pinAnchorBtn.setAttribute("aria-pressed", isPinningAnchor ? "true" : "false");
  pinAnchorBtn.disabled = !isOperator();
  pinAnchorBtn.addEventListener("click", scope.guard(() => {
    view.anchorPinTarget = isPinningAnchor ? null : activeAnchor.target_id;
    if (view.anchorPinTarget) { view.pinning = null; el("map-stage").dataset.view = "map"; el("birdseye-toggle")?.setAttribute("aria-pressed", "false"); }
    render();
  }));
  trackerHead.append(targetTabs, pinAnchorBtn);
  trackerBox.appendChild(trackerHead);

  const camViewsForAnchor = activeAnchor.target_id === "arm_a"
    ? [
        { id: "arm_a_wrist", label: "arm_a 손목", url: "/api/fleet/pipeline/cell-camera/arm_a_wrist" },
        { id: "top", label: "S5 상단", url: "/api/fleet/pipeline/cell-camera/top" },
        { id: "side", label: "셀 측면", url: "/api/fleet/pipeline/cell-camera/side" },
      ]
    : activeAnchor.target_id === "arm_b"
    ? [
        { id: "arm_b_wrist", label: "arm_b 손목", url: "/api/fleet/pipeline/cell-camera/arm_b_wrist" },
        { id: "top", label: "S5 상단", url: "/api/fleet/pipeline/cell-camera/top" },
        { id: "side", label: "셀 측면", url: "/api/fleet/pipeline/cell-camera/side" },
      ]
    : activeAnchor.target_id === "arm_s"
    ? [
        { id: "arm_s_wrist", label: "arm_s 손목", url: "/api/fleet/pipeline/cell-camera/arm_s_wrist" },
        { id: "arm_s_top", label: "S3 상단", url: "/api/fleet/pipeline/cell-camera/arm_s_top" },
        { id: "side", label: "셀 측면", url: "/api/fleet/pipeline/cell-camera/side" },
      ]
    : [
        { id: "pinky", label: "S3 도킹 뷰", url: "/api/fleet/pipeline/cell-camera/pinky" },
        { id: "side", label: "측면 도킹", url: "/api/fleet/pipeline/cell-camera/side" },
        { id: "arm_s_top", label: "S3 상단", url: "/api/fleet/pipeline/cell-camera/arm_s_top" },
      ];
  view.trackerCamByTarget = view.trackerCamByTarget || {};
  const chosenCamId = view.trackerCamByTarget[activeAnchor.target_id] || camViewsForAnchor[0].id;
  const chosenCam = camViewsForAnchor.find((c) => c.id === chosenCamId) || camViewsForAnchor[0];

  const roiRow = nodeWithText("div", "roi-row"), roiImg = document.createElement("img");
  roiImg.id = "anchor-roi-img"; roiImg.className = "anchor-roi-img"; roiImg.alt = `${activeAnchor.target_id} 확대 헤드 추적 영상`;
  const existingUrl = roiObjectUrls.get(activeAnchor.target_id);
  if (existingUrl) roiImg.src = existingUrl;
  else void refreshRoiPreview();
  const liveCellImg = document.createElement("img");
  liveCellImg.id = "anchor-cell-live-img";
  liveCellImg.className = "anchor-roi-img omx-inspector-cam";
  liveCellImg.dataset.baseUrl = chosenCam.url;
  liveCellImg.src = `${chosenCam.url}?t=${Date.now()}`;
  liveCellImg.alt = `${activeAnchor.target_id} ${chosenCam.label} 실시간 카메라`;
  liveCellImg.loading = "lazy";
  const roiMeta = nodeWithText("div", "roi-meta"), statusText = nodeWithText("p", "hint roi-status-text");
  statusText.id = "anchor-roi-status";
  const deg = typeof activeAnchor.head_yaw === "number" ? `${Math.round((activeAnchor.head_yaw * 180) / Math.PI)}°` : "—";
  statusText.textContent = `${activeAnchor.target_id.toUpperCase()} · ${activeAnchor.zoom || 4}x 실시간 추적 · BASE (${Number(activeAnchor.base_x).toFixed(2)}, ${Number(activeAnchor.base_y).toFixed(2)}) → HEAD (${Number(activeAnchor.head_x ?? activeAnchor.base_x).toFixed(2)}, ${Number(activeAnchor.head_y ?? activeAnchor.base_y).toFixed(2)}) ${deg}`;
  const descText = nodeWithText("small", "hint roi-sub-text", activeAnchor.kind === "omx_ai"
    ? `CELL-A 관절(${activeAnchor.joints_summary || "6축 정상"}) + 실시간 ${chosenCam.label} 카메라 연동`
    : `천장 카메라 3x 추적 + 실시간 ${chosenCam.label} 카메라 연동`);
  const lensRow = nodeWithText("div", "tracker-tabs");
  for (const cv of camViewsForAnchor) {
    const lBtn = nodeWithText("ui-button", "", `📷 ${cv.label}`);
    lBtn.setAttribute("kind", cv.id === chosenCam.id ? "primary" : "quiet");
    lBtn.setAttribute("data-work-read", "");
    lBtn.type = "button";
    lBtn.addEventListener("click", scope.guard(() => {
      view.trackerCamByTarget[activeAnchor.target_id] = cv.id;
      liveCellImg.dataset.baseUrl = cv.url;
      liveCellImg.src = `${cv.url}?t=${Date.now()}`;
      if (typeof window !== "undefined" && typeof window.dispatchEvent === "function") {
        window.dispatchEvent(new CustomEvent("rosy:inspect-target", { detail: { targetId: activeAnchor.target_id, camId: cv.id } }));
      }
      render();
    }));
    lensRow.appendChild(lBtn);
  }
  const openFullInspectorBtn = nodeWithText("ui-button", "", "🔍 우측 인스펙터 열기");
  openFullInspectorBtn.setAttribute("kind", "quiet");
  openFullInspectorBtn.setAttribute("data-work-read", "");
  openFullInspectorBtn.type = "button";
  openFullInspectorBtn.addEventListener("click", scope.guard(() => {
    if (typeof window !== "undefined" && typeof window.dispatchEvent === "function") {
      window.dispatchEvent(new CustomEvent("rosy:inspect-target", { detail: { targetId: activeAnchor.target_id, scroll: true } }));
    }
  }));
  lensRow.appendChild(openFullInspectorBtn);
  roiMeta.append(statusText, descText, lensRow);
  roiRow.append(roiImg, liveCellImg, roiMeta);
  trackerBox.appendChild(roiRow);
  quickPanel.appendChild(trackerBox);
  return quickPanel;
}

export function buildOmxSummaries({ view, scope, el, openCard, nodeWithText, tag }) {
  const activeRobotId = view.focusRobot || view.robots.find((r) => r.online)?.robot_id || "rosy_46";
  return OMX_CELL_DEFS.map((def, idx) => {
    const liveAnc = (view.anchors || []).find((a) => a.target_id === def.target_id) || def;
    const isSelected = view.focusAnchorId === def.target_id;
    const node = nodeWithText("article", `robot-summary omx-summary s${(idx + 1) % (view.colors?.length || 3)}${isSelected ? " selected" : ""}`);
    node.dataset.robotId = def.target_id; node.tabIndex = -1;
    node.addEventListener("click", scope.guard((ev) => {
      if (ev.target?.closest?.("ui-button, button")) return;
      openCard(def.target_id);
    }));
    const line = nodeWithText("div", "robot-line");
    line.append(nodeWithText("b", "ui-disclosure-name", `🦾 ${def.shortLabel}`));
    const btnGroup = nodeWithText("div", "omx-summary-btns");
    const dispatchBtn = nodeWithText("ui-button", "", `🤖→${def.stationId}`);
    dispatchBtn.type = "button"; dispatchBtn.setAttribute("kind", "quiet");
    dispatchBtn.title = `${activeRobotId} 로봇을 ${def.shortLabel} 연계 정류장(${def.stationId})으로 즉시 배차`;
    dispatchBtn.addEventListener("click", scope.guard(() => {
      view.focusAnchorId = def.target_id; view.selected = activeRobotId; view.focusRobot = activeRobotId;
      el("map-stage").dataset.view = "map"; el("birdseye-toggle")?.setAttribute("aria-pressed", "false");
      view.dispatchGoalToPoint?.({ x: def.stationX, y: def.stationY }, `${def.shortLabel} 연계 ${def.stationName}`, def.stationId);
    }));
    const choose = nodeWithText("ui-button", "", isSelected ? "선택됨" : "셀 보기");
    choose.type = "button"; choose.setAttribute("kind", "toggle"); choose.setAttribute("aria-pressed", String(isSelected));
    choose.dataset.selectRobotId = def.target_id;
    choose.addEventListener("click", scope.guard(() => { openCard(def.target_id); }));
    btnGroup.append(dispatchBtn, choose);
    line.append(btnGroup);
    node.append(line);

    const facts = nodeWithText("div", "robot-summary-status");
    const extM = typeof liveAnc.extension_m === "number" ? liveAnc.extension_m : 0.21;
    const reachM = liveAnc.reach_m || 0.28;
    const reachPct = Math.max(0, Math.min(100, Math.round((extM / reachM) * 100)));
    facts.append(
      tag(liveAnc.cell_status || "CELL-A ONLINE", "ok"),
      tag(`연계역 ${def.stationId}`, ""),
      tag(`뻗음 ${reachPct}% (${extM.toFixed(2)}m)`, ""),
      tag(liveAnc.motor_summary || "모터 31°C · 12.0V", ""),
    );
    node.append(facts);
    return node;
  });
}
