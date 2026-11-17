import { actionIcon } from "/common/ui.js";
import { statusTag } from "/common/status-tag.js";
import { valueText } from "/common/value-text.js";
import { createRobotRow } from "/common/robot-row.js";
import { skillState } from "/common/skill-state.js";
import { isSample, sampleTag } from "/common/sample-data.js";
import { renderRefusalSlot, renderLocalizationSlot } from "/console/assets/localization-view.js";
import { armCameraSpecs } from "./robot-panel-adapters.js";
export { createDetail3dController, appendDetailCamera } from "./roster-presentation.js";

/** D-651: all four safety exceptions remain visible in the compact list, ahead of nominal robots. */
export function mustExpand(robot) {
  const estop = robot.state?.safety?.estop;
  return !robot.online || !robot.state || estop !== false || Boolean(robot.calibration);
}

// 카메라·트윈 보기에서 지도로 되돌리는 길은 이 한 곳이다(r-C §3.1 3곳 중복 통합).
// 목표·위치 고정은 지도를 봐야 하므로 트윈도 나가고, 로봇 선택은 카메라만 닫는다.
function backToMap(view, el) {
  if (typeof view.setDisplayMode === "function") view.setDisplayMode("coordinates");
  else { const stage = el("map-stage"); if (stage) stage.dataset.view = "map"; }
  el("birdseye-toggle")?.setAttribute("aria-pressed", "false");
}
const inStageView = (view, el, modes) =>
  modes.includes(view.displayMode) || modes.includes(el("map-stage")?.dataset?.view);

export function leaveTwinOrCameraView(view, el) {
  if (inStageView(view, el, ["camera", "twin3d"])) backToMap(view, el);
}

export function leaveCameraView(view, el) {
  if (inStageView(view, el, ["camera"])) backToMap(view, el);
}

/** Inspection is UI-only. Switching robots withdraws every pending map interaction. */
export function selectRobot(view, robotId) {
  const nextId = robotId || null;
  if (nextId && !view.robots.some(robot => robot.robot_id === nextId)) return false;
  const currentId = view.robotSelection?.get() ?? null;
  if (currentId === nextId) return false;
  view.selected = null;
  view.pinning = null;
  view.cursor = null;
  view.focusAnchorId = nextId;
  view.robotSelection?.set(nextId, { source: "selectRobot" });
  return true;
}

// A focused picker or motor table keeps its card across polling updates.
export function placeRosterCards(box, cards) {
  const focus = document.activeElement;
  const focused = focus?.matches("select, .motor-health-scroll") ? focus.closest("#robot-panel-mount article") : null;
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
  { target_id: "arm_a", kind: "omx_ai", label: "OMX-AI #1 (Cell A · S5 1·3단 적재)", shortLabel: "Cell A · arm_a (S5 1·3단)", stationId: "S2", stationName: "정지선 2 (상차)", stationX: 0.34, stationY: 0.015, base_x: 0.551, base_y: 0.365, head_x: 0.550, head_y: 0.109, head_yaw: -1.57, reach_m: 0.28, zoom: 4 },
  { target_id: "arm_b", kind: "omx_ai", label: "OMX-AI #2 (Cell B · S5 2단 적재·반출)", shortLabel: "Cell B · arm_b (S5 2단)", stationId: "S5", stationName: "분류 5 (동남)", stationX: 0.87, stationY: -0.38, base_x: 0.956, base_y: 0.370, head_x: 0.956, head_y: 0.113, head_yaw: -1.57, reach_m: 0.28, zoom: 4 },
  { target_id: "arm_s", kind: "omx_ai", label: "OMX-AI #3 (Cell S · S3 공급 셔틀)", shortLabel: "Cell S · arm_s (S3 공급)", stationId: "S3", stationName: "하차 3 (동북)", stationX: 0.67, stationY: -0.06, base_x: 0.960, base_y: -0.035, head_x: 0.703, head_y: -0.035, head_yaw: 3.14, reach_m: 0.28, zoom: 4 },
];

export const STATION_INSPECT_LINKS = Object.freeze({
  S2: { targetId: "arm_a", camId: "arm_a_wrist", label: "S2 상차 · arm_a" },
  S3: { targetId: "arm_s", camId: "arm_s_wrist", label: "S3 하역 셔틀 · arm_s" },
  S5: { targetId: "arm_b", camId: "arm_b_wrist", label: "S5 적재·반출 · arm_b" },
  S1: { targetId: "rosy_46", camId: "side", label: "S1 반출대 · Pinky" },
  C1: { targetId: "rosy_46", camId: "pinky", label: "C1 충전소 · rosy_46" },
  C2: { targetId: "rosy_45", camId: "pinky", label: "C2 임시칸 · rosy_45" },
  C3: { targetId: "rosy_42", camId: "pinky", label: "C3 충전소 · rosy_42" },
});

function formatRoiStatus(anc) {
  const deg = typeof anc.head_yaw === "number" ? `${Math.round((anc.head_yaw * 180) / Math.PI)}°` : "—";
  return `${anc.target_id} · ${anc.zoom || 4}x 실시간 추적 · 기준 (${Number(anc.base_x).toFixed(2)}, ${Number(anc.base_y).toFixed(2)}) → 방향 (${Number(anc.head_x ?? anc.base_x).toFixed(2)}, ${Number(anc.head_y ?? anc.base_y).toFixed(2)}) ${deg}`;
}

export function createRoiPoller({ scope, view, call, render = () => {} }) {
  const roiLease = { token: "", expiresAt: 0, pending: null };
  const roiObjectUrls = new Map();
  let roiPollInFlight = false;
  scope.onDispose(() => {
    roiPollInFlight = false;
    roiLease.token = "";
    roiLease.expiresAt = 0;
    roiLease.pending = null;
    for (const url of roiObjectUrls.values()) URL.revokeObjectURL(url);
    roiObjectUrls.clear();
  });
  async function ensureRoiLease(signal) {
    if (roiLease.token && Date.now() < roiLease.expiresAt) return roiLease.token;
    if (roiLease.pending) return roiLease.pending;
    roiLease.pending = call("/api/fleet/vision/lease", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ source_id: "ceiling_north" }),
      ...(signal ? { signals: [signal] } : {}),
    }).then((res) => {
      roiLease.token = res?.lease || "";
      roiLease.expiresAt = Date.now() + ((res?.expires_in_s || 60) - 8) * 1000;
      return roiLease.token;
    }).catch(() => "").finally(() => { roiLease.pending = null; });
    return roiLease.pending;
  }
  async function refreshRoiPreview() {
    const life = scope.capture();
    if (!life.current() || document.hidden || roiPollInFlight || !view.anchors?.length) return;
    const img = document.getElementById("anchor-roi-img");
    const statusNode = document.getElementById("anchor-roi-status");
    const targetId = view.focusAnchorId || view.robotSelection?.get() || null;
    if (!img || !targetId || (typeof img.closest === "function" && !img.closest(".quick-cell-link")?.open)) return;
    roiPollInFlight = true;
    try {
      const token = await ensureRoiLease(life.signal);
      if (!life.current() || !token) return;
      const resp = await fetch(`/api/vision/sources/ceiling_north/roi/${encodeURIComponent(targetId)}`, {
        headers: { Authorization: `Bearer ${token}` }, cache: "no-store", signal: life.signal,
      });
      if (!life.current()) return;
      if (resp.status === 401) { roiLease.token = ""; roiLease.expiresAt = 0; return; }
      if (!resp.ok) return;
      const blob = await resp.blob();
      if (!life.current() || !blob || !blob.size) return;
      const nextUrl = URL.createObjectURL(blob);
      const prevUrl = roiObjectUrls.get(targetId);
      roiObjectUrls.set(targetId, nextUrl);
      img.src = nextUrl;
      img.hidden = false;
      if (prevUrl) URL.revokeObjectURL(prevUrl);
      if (statusNode) {
        const anc = (view.anchors || []).find((a) => a.target_id === targetId);
        if (anc) statusNode.textContent = formatRoiStatus(anc);
      }
    } catch (err) {
      if (err?.name === "AbortError") return;
      // Keep previous ROI image on transient error
    } finally {
      if (life.current()) roiPollInFlight = false;
    }
  }
  scope.interval(() => {
    if (typeof document !== "undefined" && document.querySelector?.(".quick-cell-link")?.open) void refreshRoiPreview();
  }, 850);
  // A map anchor click focuses its card; an arm anchor also refreshes its ROI preview.
  if (typeof window !== "undefined" && typeof window.addEventListener === "function") {
    scope.listen(window, "rosy:focus-anchor", (ev) => {
      const targetId = ev?.detail?.targetId;
      if (!targetId) return;
      if (targetId.startsWith("arm_")) {
        view.focusAnchorId = targetId;
        render();
        void refreshRoiPreview();
      } else if (targetId.startsWith("rosy_")) {
        view.focusAnchorId = targetId;
        render();
      }
    });
  }
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
  roiObjectUrls, refreshRoiPreview, nodeWithText, tag, cellFrames = null,
}) {
  const quickPanel = document.createElement("section");
  quickPanel.className = "quick-control-panel";

  const gPose = guideRow?.pose || pose;
  const selGoal = view.selectedGoal && view.selectedGoal.robotId === robot.robot_id ? view.selectedGoal : null;
  // The strip and the evidence line above carry battery, pose and age; this panel only holds destinations.
  const headerLine = nodeWithText("div", "quick-header-line");
  headerLine.appendChild(nodeWithText("strong", "quick-title", "빠른 목적지"));
  if (selGoal) {
    const totalLen = selGoal.length_m || 0;
    headerLine.appendChild(nodeWithText("small", "hint", `${selGoal.placeId || "좌표"} · ${totalLen.toFixed(2)} m · ${selGoal.statusText || "고정됨"}`));
    const clearGoalBtn = nodeWithText("ui-button", "", "목표 핀 해제");
    clearGoalBtn.setAttribute("kind", "quiet"); clearGoalBtn.type = "button";
    actionIcon(clearGoalBtn, "close");
    clearGoalBtn.addEventListener("click", scope.guard(() => { view.selectedGoal = null; view.activeRoadPlan = null; render(); }));
    headerLine.appendChild(clearGoalBtn);
  }
  quickPanel.appendChild(headerLine);

  const mapPlaces = view.activeSiteMap?.map?.places?.length ? view.activeSiteMap.map.places : DEFAULT_PLACES;
  const placeGroups = [
    { key: "P", label: "픽업 P1–P3", items: [] },
    { key: "S", label: "작업대 S1–S5", items: [] },
    { key: "C", label: "충전 C1–C3", items: [] },
    { key: "OTHER", label: "기타 위치", items: [] },
  ];
  for (const pl of mapPlaces) {
    const pid = String(pl.id).toUpperCase();
    const bucket = placeGroups.find((g) => g.key !== "OTHER" && pid.startsWith(g.key)) || placeGroups[3];
    bucket.items.push(pl);
  }
  for (const group of placeGroups) {
    if (!group.items.length) continue;
    const chipRow = nodeWithText("div", "quick-chip-row");
    chipRow.setAttribute("role", "group");
    chipRow.setAttribute("aria-label", group.label);
    chipRow.appendChild(nodeWithText("span", "quick-group-label", group.label));
    for (const pl of group.items) {
      const pid = String(pl.id);
      const isPinnedPlace = selGoal?.placeId === pid;
      const btn = nodeWithText("ui-button", "", pid);
      btn.dataset.quickGoal = pid;
      btn.setAttribute("kind", isPinnedPlace ? "toggle" : "quiet");
      if (isPinnedPlace) btn.setAttribute("aria-pressed", "true");
      btn.type = "button";
      btn.setAttribute("data-ui-tooltip", `${pl.name || pl.id} (${pl.x.toFixed(2)}, ${pl.y.toFixed(2)}) m 목표 핀 고정 및 이동`);
      btn.addEventListener("click", scope.guard(() => {
        selectRobot(view, robot.robot_id);
        view.selected = robot.robot_id;
        const stationLink = STATION_INSPECT_LINKS[pid.toUpperCase()];
        if (stationLink) {
          if (stationLink.targetId.startsWith("arm_")) view.focusAnchorId = stationLink.targetId;
          if (typeof window !== "undefined" && typeof window.dispatchEvent === "function") {
            window.dispatchEvent(new CustomEvent("rosy:inspect-target", {
              detail: { targetId: stationLink.targetId.startsWith("arm_") ? stationLink.targetId : robot.robot_id, camId: stationLink.camId },
            }));
          }
        }
        leaveTwinOrCameraView(view, el);
        view.dispatchGoalToPoint?.({ x: pl.x, y: pl.y }, `${pl.name || pl.id} (${pl.id})`, pid);
      }));
      chipRow.appendChild(btn);
    }
    quickPanel.appendChild(chipRow);
  }

  // Berth parking is not built yet (D-1013): one locked line instead of four disabled buttons that each repeat the reason.
  const berthLine = nodeWithText("p", "robot-evidence");
  berthLine.append(statusTag("locked", "접안 정렬 잠김"), nodeWithText("span", "", "자동 정렬 구현·안전 검증 대기"));
  quickPanel.appendChild(berthLine);

  // Cell and camera links are L4 for a robot card: one fold, kept open across the 1 s redraw by view.openFolds.
  const cells = document.createElement("details");
  cells.className = "quick-cell-link";
  const cellsSummary = nodeWithText("summary", "ui-disclosure-row", "셀 연계 · 카메라");
  actionIcon(cellsSummary, "arm");
  cells.appendChild(cellsSummary);
  view.openFolds = view.openFolds || new Set();
  const foldKey = `cells:${robot.robot_id}`;
  cells.open = view.openFolds.has(foldKey);
  cells.addEventListener("toggle", () => {
    if (cells.open) {
      view.openFolds.add(foldKey);
      void refreshRoiPreview();
    } else {
      view.openFolds.delete(foldKey);
    }
  });
  const omxSection = nodeWithText("div", "omx-fleet-section");
  const visibleOmx = OMX_CELL_DEFS.filter(def => (view.anchors || []).some(a => a.target_id === def.target_id));
  const omxHead = nodeWithText("div", "quick-header-line");
  omxHead.append(
    nodeWithText("strong", "quick-title", "OMX-AI 셀 · 연계 배차"),
    nodeWithText("small", "hint omx-cell-summary", `관측된 셀 ${visibleOmx.length}/3`),
  );
  omxSection.appendChild(omxHead);

  const omxGrid = nodeWithText("div", "omx-fleet-grid");
  for (const def of visibleOmx) {
    const liveAnc = view.anchors.find((a) => a.target_id === def.target_id);
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
    armTop.append(nodeWithText("strong", "omx-cell-title", def.shortLabel), tag(liveAnc.cell_status || valueText(null).text, ""));
    armCard.appendChild(armTop);

    const extM = typeof liveAnc.extension_m === "number" ? liveAnc.extension_m : null;
    const reachM = typeof liveAnc.reach_m === "number" ? liveAnc.reach_m : null;
    const confPct = typeof liveAnc.confidence === "number" ? Math.max(0, Math.min(100, Math.round(liveAnc.confidence * 100))) : null;
    const headDeg = typeof liveAnc.head_yaw === "number" ? `${Math.round((liveAnc.head_yaw * 180) / Math.PI)}°` : null;
    const barsWrap = nodeWithText("dl", "omx-bars-wrap");
    const rows = [
      ["뻗음·작업반경", extM !== null && reachM > 0 ? `${extM.toFixed(2)}/${reachM.toFixed(2)} m` : null],
      ["서보·전원버스", liveAnc.motor_summary],
      ["비전·방위", confPct === null ? null : `신뢰도 ${confPct}%${headDeg ? ` · 방향 ${headDeg}` : ""}`],
    ];
    for (const [label, value] of rows) {
      const row = nodeWithText("div", "omx-bars-row");
      row.append(nodeWithText("dt", "", label), nodeWithText("dd", "", valueText(value).text));
      barsWrap.appendChild(row);
    }
    armCard.appendChild(barsWrap);
    const jointLine = nodeWithText("small", "omx-cell-joints", `${liveAnc.joints_summary || `관절 ${valueText(null).text}`} · 연계 정류장 ${def.stationId}`);
    jointLine.title = jointLine.textContent;
    armCard.appendChild(jointLine);

    const armActions = nodeWithText("div", "omx-cell-actions");
    const callRobotBtn = nodeWithText("ui-button", "", `${robot.robot_id} → ${def.stationId} 배차`);
    callRobotBtn.setAttribute("kind", selGoal?.placeId === def.stationId ? "toggle" : "quiet");
    if (selGoal?.placeId === def.stationId) callRobotBtn.setAttribute("aria-pressed", "true");
    callRobotBtn.type = "button";
    callRobotBtn.title = `${def.shortLabel} 연계 정류장 ${def.stationName}(${def.stationId})으로 ${robot.robot_id} 즉시 호출·배차`;
    callRobotBtn.addEventListener("click", scope.guard(() => {
      view.focusAnchorId = def.target_id; selectRobot(view, robot.robot_id); view.selected = robot.robot_id;
      if (typeof window !== "undefined" && typeof window.dispatchEvent === "function") {
        window.dispatchEvent(new CustomEvent("rosy:inspect-target", { detail: { targetId: def.target_id } }));
      }
      leaveTwinOrCameraView(view, el);
      view.dispatchGoalToPoint?.({ x: def.stationX, y: def.stationY }, `${def.shortLabel} 연계 ${def.stationName}`, def.stationId);
    }));
    const focusCamBtn = nodeWithText("ui-button", "", "카메라·제어 연동");
    actionIcon(focusCamBtn, "camera");
    focusCamBtn.setAttribute("kind", "toggle"); focusCamBtn.setAttribute("aria-pressed", isFocusedArm ? "true" : "false"); focusCamBtn.type = "button";
    focusCamBtn.addEventListener("click", scope.guard(() => { selectThisArm(); }));
    armActions.append(callRobotBtn, focusCamBtn);
    armCard.appendChild(armActions);
    omxGrid.appendChild(armCard);
  }
  omxSection.appendChild(omxGrid);
  if (visibleOmx.length) cells.appendChild(omxSection);

  const anchorList = [
    // No observed pose, no pinky tracker: nothing is invented (D-280).
    ...(Number.isFinite(gPose?.x) && Number.isFinite(gPose?.y) ? [
    { target_id: robot.robot_id, kind: "pinky", label: displayName, base_x: gPose.x, base_y: gPose.y, head_x: gPose.x, head_y: gPose.y - 0.055, head_yaw: gPose.yaw, zoom: 3 }] : []),
    ...OMX_CELL_DEFS.flatMap((def) => {
      const observed = (view.anchors || []).find((a) => a.target_id === def.target_id);
      return observed ? [observed] : [];
    }),
  ];
  if (!anchorList.length) { quickPanel.appendChild(cells); return quickPanel; }
  const activeAnchorId = view.focusAnchorId || robot.robot_id;
  const activeAnchor = anchorList.find((a) => a.target_id === activeAnchorId) || anchorList[0];

  const trackerBox = nodeWithText("div", "tracker-box"), trackerHead = nodeWithText("div", "tracker-head"), targetTabs = nodeWithText("div", "tracker-tabs");
  for (const anc of anchorList) {
    const isCurrent = anc.target_id === activeAnchor.target_id;
    const tab = nodeWithText("ui-button", "", `${anc.target_id} (${anc.zoom || (anc.kind === "omx_ai" ? 4 : 3)}x)`);
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
  // No Fleet anchor route exists, so there is no pin button (it could only fail).
  trackerHead.append(targetTabs);
  trackerBox.appendChild(trackerHead);

  // 셀 카메라 뷰는 Vision 소스만 가리킨다(D-136). cell S(arm_s·S3)에는 측면 카메라가 없고,
  // Pinky 도킹은 천장 Cam ROI 확대로 위에서 본다. 팔 카메라 목록은 armCameraSpecs 한 곳이 정본이다.
  const camViewsForAnchor = activeAnchor.target_id.startsWith("arm_")
    ? armCameraSpecs(activeAnchor.target_id)
    : [
        { id: "pinky_dock", label: "도킹 확대 (천장 Cam)", roiTarget: activeAnchor.target_id },
        { id: "arm_s_top", label: "S3 상단", source: "arm_s_top" },
      ];
  view.trackerCamByTarget = view.trackerCamByTarget || {};
  const chosenCamId = view.trackerCamByTarget[activeAnchor.target_id] || camViewsForAnchor[0].id;
  const chosenCam = camViewsForAnchor.find((c) => c.id === chosenCamId) || camViewsForAnchor[0];

  const roiRow = nodeWithText("div", "roi-row"), roiImg = document.createElement("img");
  roiImg.id = "anchor-roi-img"; roiImg.className = "anchor-roi-img"; roiImg.alt = `${activeAnchor.target_id} 확대 헤드 추적 영상`;
  const existingUrl = roiObjectUrls.get(activeAnchor.target_id);
  if (existingUrl) roiImg.src = existingUrl;
  else {
    roiImg.hidden = true;
    if (cells.open) void refreshRoiPreview();
  }
  const liveCellImg = document.createElement("img");
  liveCellImg.id = "anchor-cell-live-img";
  liveCellImg.className = "anchor-roi-img omx-inspector-cam";
  liveCellImg.alt = `${activeAnchor.target_id} ${chosenCam.label} 실시간 카메라`;
  liveCellImg.loading = "lazy";
  // No Vision lease until the person picks a camera for this target (selecting a robot only inspects).
  if (view.trackerCamByTarget[activeAnchor.target_id]) cellFrames?.bind(liveCellImg, chosenCam);
  else liveCellImg.hidden = true;
  const roiMeta = nodeWithText("div", "roi-meta"), statusText = nodeWithText("p", "hint roi-status-text");
  statusText.id = "anchor-roi-status";
  statusText.textContent = formatRoiStatus(activeAnchor);
  const cellLabel = activeAnchor.target_id === "arm_s" ? "Cell S" : activeAnchor.target_id === "arm_b" ? "Cell B" : "Cell A";
  const descText = nodeWithText("small", "hint roi-sub-text", activeAnchor.kind === "omx_ai"
    ? `${cellLabel} 관절(${valueText(activeAnchor.joints_summary).text}) + 실시간 ${chosenCam.label} 카메라 연동`
    : `천장 카메라 3x 추적 + 실시간 ${chosenCam.label} 카메라 연동`);
  const lensRow = nodeWithText("div", "tracker-tabs");
  for (const cv of camViewsForAnchor) {
    const lBtn = nodeWithText("ui-button", "", cv.label);
    lBtn.setAttribute("kind", cv.id === chosenCam.id ? "primary" : "quiet");
    lBtn.setAttribute("data-work-read", "");
    lBtn.type = "button";
    lBtn.addEventListener("click", scope.guard(() => {
      view.trackerCamByTarget[activeAnchor.target_id] = cv.id;
      cellFrames?.bind(liveCellImg, cv);
      if (typeof window !== "undefined" && typeof window.dispatchEvent === "function") {
        window.dispatchEvent(new CustomEvent("rosy:inspect-target", { detail: { targetId: activeAnchor.target_id, camId: cv.id } }));
      }
      render();
    }));
    lensRow.appendChild(lBtn);
  }
  const openFullInspectorBtn = nodeWithText("ui-button", "", "우측 인스펙터 열기");
  actionIcon(openFullInspectorBtn, "search");
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
  cells.appendChild(trackerBox);
  quickPanel.appendChild(cells);
  return quickPanel;
}

export function appendDetailSlots({ mainCol, profile, robot, view, scope, openCard, render, nodeWithText, call, isOperator, log, onPin, onStop, split = false }) {
  if (!split) {
    const detailRowList = nodeWithText("ul", "robot-rows robot-detail-row");
    detailRowList.append(createRobotRow(profile, {
      selected: view.robotSelection?.get() === robot.robot_id,
      onSelect: scope.guard(() => {
        if (view.robotSelection) view.robotSelection.set(null, { source: "detail" });
        else { openCard(null); render(); }
      }),
    }));
    mainCol.appendChild(detailRowList);
  }
  const refusalSlot = nodeWithText("div", "detail-refusal");
  refusalSlot.id = "detail-refusal";
  renderRefusalSlot({ slot: refusalSlot, robot, view, call, scope, isOperator, render, log, onPin, onStop });
  mainCol.appendChild(refusalSlot);
  const nowSlot = nodeWithText("section", "detail-now");
  nowSlot.id = "detail-now";
  nowSlot.setAttribute("aria-label", "지금 상태");
  const locSlot = document.createElement("div");
  locSlot.id = "detail-localization";
  renderLocalizationSlot({ slot: locSlot, robot, view, call, scope, isOperator, render, log, onPin, onStop });
  const skillSlot = document.createElement("div");
  skillSlot.id = "detail-skill";
  // B3 (계획 6.2 R4): 이 로봇의 실행 중 스킬 한 줄 + readout 띠. 행 글자와 같은 C20 표를 쓰고,
  // 정상 진행은 조용하다(태그 없음). 샘플 상태면 sampleTag()가 이름을 밝힌다(C22).
  const armSkill = !view.stateUnavailable && robot.state?.arm_skill ? robot.state.arm_skill : null;
  if (armSkill) {
    const skill = skillState(armSkill);
    const line = nodeWithText("p", "detail-skill-line");
    line.append(nodeWithText("strong", "", "스킬"), ` ${skill.text}`);
    if (skill.tag) line.append(statusTag(skill.tag.state, undefined, {icon: skill.tag.icon}));
    if (isSample(armSkill)) line.append(sampleTag());
    skillSlot.append(line);
    if (skill.readout.length) {
      const strip = nodeWithText("dl", "ui-readout detail-skill-readout");
      strip.dataset.form = "strip";
      for (const row of skill.readout) {
        const cell = nodeWithText("div", "detail-skill-cell");
        cell.append(nodeWithText("dt", "", row.label), nodeWithText("dd", "", row.value));
        strip.append(cell);
      }
      skillSlot.append(strip);
    }
  }
  nowSlot.append(locSlot, skillSlot);
  if (!split) mainCol.appendChild(nowSlot);
  return nowSlot;
}
