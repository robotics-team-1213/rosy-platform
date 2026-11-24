import { patchHidden, patchText, uiTag } from "/common/control-dom.js";
import { isOperator } from "/console/assets/authorization.js";
import {randomUUID} from "/console/assets/uuid.js";
// 지도 위 목표 지정과 운영자 핀(D-201·D-224·D-593). 셸(console.js)이 그리기(render)와 지도 뷰를 건넨다(D-798 3.2).
import { capabilityReason, motionCommandReason } from "./motion-readiness.js";
import { pinPrefill, robotMapPose } from "./localization-badge.js";
import { nearestLaneHeading, roadPolylineBetween } from "/console/assets/guide-layer.js";
import { planPolylines, planSummaryText, planTrip, startTrip, tripPoseReason, tripRefusalText, tripStartReason } from "/console/assets/site-map-model.js";
import { gridCellOf } from "./map-datum.js";

function flattenPlanPoints(map, plan) {
  if (!map?.edges || !Array.isArray(plan?.segments)) return null;
  const out = [];
  for (const poly of planPolylines(map, plan)) {
    for (const pt of poly) {
      const last = out[out.length - 1];
      if (!last || Math.hypot(pt[0] - last[0], pt[1] - last[1]) >= 1e-6) out.push(pt);
    }
  }
  return out.length >= 2 ? out : null;
}

const planMetrics = (plan) => ({
  ...(Array.isArray(plan.places) ? { places: plan.places } : {}),
  ...(Number.isFinite(plan.length_m) ? { length_m: plan.length_m } : {}),
  ...(Number.isFinite(plan.eta_s) ? { eta_s: plan.eta_s } : {}),
});
const mkEl = (tag, cls, txt) => {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (txt != null) n.textContent = txt;
  return n;
};

export function createConsoleGoal({ pageScope, el, view, auth, inbox, log, call, render, confirmedAction, namedReason,
  toWorld, refreshGuide, queuedReason, drawMap = () => {}, scheduleDraw = drawMap, onSelectRobot = () => {},
  selection = null, onGoalFinished = () => {} }) {
  let goalPlanSeq = 0;
  let suppressClickUntil = 0;

  function applyPinnedPose(robotId, pose) {
    if (!pose || !Number.isFinite(pose.x) || !Number.isFinite(pose.y)) return;
    const rows = [...(view.guide?.robots || [])], idx = rows.findIndex((row) => row.robot_id === robotId);
    const patchedPose = { ...(idx >= 0 ? rows[idx].pose : null), ...pose };
    if (idx >= 0) rows[idx] = { ...rows[idx], pose: patchedPose };
    else rows.push({ robot_id: robotId, online: true, pose: patchedPose, lane: null, findings: [] });
    view.guide = { ...view.guide, map_version: view.activeSiteMap?.version ?? view.guide?.map_version ?? null, robots: rows };
    drawMap(); render();
  }

  const setGoal = (patch) => { view.selectedGoal = { ...view.selectedGoal, ...patch, at: Date.now() }; drawMap(); render(); };
  function disarmGoal(reason) {
    goalPlanSeq += 1; view.selected = null; view.cursor = null; view.hoverWorld = null;
    const canvas = el("map-canvas");
    canvas.classList.add("idle"); canvas.tabIndex = -1;
    if (reason) log(reason, "bad");
  }

  // D-224 — 예외 문법의 키보드 어휘(§7.3 "keyboard-first" 의 실현).
  pageScope.listen(document, "keydown", (event) => {
    if (event.defaultPrevented || event.target.closest("input, select, textarea, button, ui-button, a, canvas, summary")) return;
    const cards = [...document.querySelectorAll("#roster article")], active = document.activeElement;
    if (!cards.length) return;
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault(); inbox.select("status");
      const idx = cards.indexOf(active), step = event.key === "ArrowDown" ? 1 : -1;
      cards[idx < 0 ? (event.key === "ArrowDown" ? 0 : cards.length - 1) : (idx + step + cards.length) % cards.length].focus();
    } else if (event.key === "Enter" && cards.includes(active)) {
      const id = active.dataset.robotId;
      if (id) {
        event.preventDefault();
        selection?.set?.(id, { source: "roster" });
        if (document.getElementById("robot-panel")?.hidden) {
          document.querySelector(`#robot-dock .robot-dock-btn[data-robot-id="${id}"]`)?.focus({ preventScroll: true });
        }
      }
    } else if (event.key === "Escape" && view.selected) {
      const robotId = view.selected; disarmGoal("목표 지정 취소"); render(); focusGoalButton(robotId);
    }
  });

  function makeSvgBar(pct, tone = "good") {
    const clamped = Math.max(0, Math.min(100, Math.round(Number.isFinite(pct) ? pct : 0))), ns = "http://www.w3.org/2000/svg";
    const svg = document.createElementNS(ns, "svg"), bg = document.createElementNS(ns, "rect"), fill = document.createElementNS(ns, "rect");
    svg.setAttribute("class", "gauge-svg"); svg.setAttribute("viewBox", "0 0 100 7"); svg.setAttribute("preserveAspectRatio", "none");
    bg.setAttribute("class", "gauge-bg"); bg.setAttribute("x", "0"); bg.setAttribute("y", "0"); bg.setAttribute("width", "100"); bg.setAttribute("height", "7"); bg.setAttribute("rx", "3.5");
    fill.setAttribute("class", `gauge-fill ${tone}`); fill.setAttribute("x", "0"); bg.setAttribute("y", "0"); fill.setAttribute("width", String(clamped)); fill.setAttribute("height", "7"); fill.setAttribute("rx", "3.5");
    svg.append(bg, fill); return svg;
  }

  async function commitWorldGoal(point, placeLabel = "", placeId = "") {
    const life = pageScope.capture(); life.check();
    if (!point || !Number.isFinite(point.x) || !Number.isFinite(point.y)) return;
    const robotId = view.selected;
    if (!robotId) return;
    const seq = ++goalPlanSeq, selectedRobot = view.robots.find((robot) => robot.robot_id === robotId);
    const guideRow = (view.guide?.robots || []).find((r) => r.robot_id === robotId), curPose = guideRow?.pose || selectedRobot?.state?.pose || null;
    const yaw = curPose && Number.isFinite(curPose.x) && Number.isFinite(curPose.y) ? Math.atan2(point.y - curPose.y, point.x - curPose.x) : 0;
    const where = placeLabel ? `${placeLabel} (${point.x.toFixed(2)}, ${point.y.toFixed(2)})` : `(${point.x.toFixed(2)}, ${point.y.toFixed(2)})`;
    const siteMapObj = view.activeSiteMap?.map, localRoad = curPose ? roadPolylineBetween(siteMapObj, curPose, point) : null;
    const initialPts = localRoad?.points?.length >= 2 ? localRoad.points : (curPose ? [[curPose.x, curPose.y], [point.x, point.y]] : [[point.x, point.y]]);
    const initialLen = typeof localRoad?.length_m === "number" ? localRoad.length_m : (curPose ? Math.hypot(point.x - curPose.x, point.y - curPose.y) : 0);
    view.selectedGoal = {
      robotId, x: point.x, y: point.y, yaw, placeId: placeId || null, where, points: initialPts,
      label: placeLabel || `좌표 (${point.x.toFixed(2)}, ${point.y.toFixed(2)})`,
      places: localRoad?.places || (placeId ? [placeId] : []), length_m: initialLen, eta_s: initialLen / 0.15,
      status: "SELECTED", statusText: "목표 핀 고정 · 도로 경로 확정", at: Date.now(),
    };
    view.lastDispatchedGoal = { robotId, x: point.x, y: point.y, yaw, label: where, at: Date.now() };
    const stationArmMap = { S2: "arm_a", S3: "arm_s", S5: "arm_b" };
    const linkedArm = placeId ? stationArmMap[String(placeId).toUpperCase()] : null;
    if (linkedArm) view.focusAnchorId = linkedArm;
    drawMap(); render();

    // A robot on its own (SLAM) map takes a site goal only as a lane trip Fleet plans from its measured site pose;
    // say why before the confirm when that cannot start (2026-11-14: no raw site goal into a robot's own frame).
    const siteMapId = view.activeSiteMap?.map?.map_id;
    const viaTrip = !view.map && selectedRobot?.state?.map_id !== siteMapId;   // site view, robot not on this map
    const onFrame = () => !view.map && (view.robots.find(robot => robot.robot_id === robotId)?.state?.map_id !== siteMapId) === viaTrip
      && view.activeSiteMap?.map?.map_id === siteMapId;
    const canDispatch = !view.stateUnavailable && isOperator(auth.role) && !namedReason()
      && (viaTrip || !capabilityReason(selectedRobot?.capabilities, 'navigation.goal_navigation'))
      && !motionCommandReason(view, robotId, viaTrip ? "trip" : "goal") && selectedRobot?.online && selectedRobot.state?.safety?.estop === false;
    if (!canDispatch) {
      try {
        const qs = new URLSearchParams({
          x: String(Number(point.x.toFixed(4))), y: String(Number(point.y.toFixed(4))), yaw: String(Number(yaw.toFixed(4))),
          ...(placeId ? { place_id: placeId } : {}), ...(placeLabel ? { label: placeLabel } : {}),
        });
        const planRes = await call(`/api/fleet/robots/${encodeURIComponent(robotId)}/road-nav2/plan?${qs}`, { signals: [life.signal] });
        life.check();
        if (planRes?.waypoints_site?.length >= 2) {
          view.activeRoadPlan = { robotId, ...planRes, at: Date.now() };
          setGoal({
            points: planRes.waypoints_site.map((w) => [w.x, w.y]), ...planMetrics(planRes), status: "PREVIEW",
            statusText: !isOperator(auth.role) ? "목표 핀 고정 (운영자 로그인 시 출발)" : "목표 핀 고정 (안전 확인 대기)",
          });
        }
      } catch (_planErr) { /* Keep local road pin visible */ }
      log(`${robotId} → ${where} 목표 핀 및 도로 경로(${view.selectedGoal.length_m.toFixed(2)}m)가 지도에 고정되었습니다.`, "good");
      return;
    }

    let prePlanned = null;
    if (viaTrip) {
      const corePose = robotMapPose(selectedRobot);
      const blocked = !siteMapId ? "현장 지도 활성화 필요: 활성 지도가 없어 보내지 않습니다"
        : !view.guide ? "위치 확인 중: 잠시 뒤 다시 찍으세요"
        : tripPoseReason(view.guide, robotId, view.activeSiteMap, corePose);
      if (blocked) { setGoal({ status: "BLOCKED", statusText: blocked }); log(`${robotId} 출발 보류 · ${blocked}`, "bad"); return; }
      setGoal({ status: "PLANNING", statusText: "서버 경로 계산 중…" });
      const tripTarget = placeId || { x: Number(point.x.toFixed(4)), y: Number(point.y.toFixed(4)) };
      const canNav2 = (selectedRobot?.capabilities?.controls?.items || []).some(
        (item) => item?.kind === "base_velocity" && Array.isArray(item.drive_modes) && item.drive_modes.includes("free"));
      try {
        try { prePlanned = await planTrip(call, robotId, { to: tripTarget }); } catch (err) {
          if (canNav2 && (err?.code === "TRIP_LANE_CAMERA_UNAVAILABLE" || err?.code === "TRIP_MODE_UNSUPPORTED")) {
            prePlanned = await planTrip(call, robotId, { to: tripTarget, drive_mode: "nav2" });
          } else throw err;
        }
        life.check();
      } catch (err) {
        if (err?.name === "AbortError" || seq !== goalPlanSeq) return;
        const refusal = tripRefusalText(err);
        setGoal({ status: "BLOCKED", statusText: refusal });
        log(`${robotId} 차로 주행 거절 — ${refusal}`, "bad");
        return;
      }
      if (seq !== goalPlanSeq || view.selected !== robotId || !onFrame()) return;
      const serverPoints = flattenPlanPoints(siteMapObj, prePlanned) || view.selectedGoal.points;
      const running = (view.trafficTrips || []).some((row) => row.robot_id === robotId);
      const startBlocked = tripStartReason({ role: isOperator(auth.role) ? "operator" : "viewer", plan: prePlanned, active: view.activeSiteMap, running });
      if (startBlocked) {
        setGoal({ points: serverPoints, ...planMetrics(prePlanned), status: "BLOCKED", statusText: startBlocked });
        log(`${robotId} 출발 보류 · ${startBlocked}`, "bad");
        return;
      }
      const hasSummary = Array.isArray(prePlanned.segments) && Number.isFinite(prePlanned.length_m);
      setGoal({ points: serverPoints, ...planMetrics(prePlanned), planId: prePlanned.plan_id, status: "PREVIEW",
        statusText: hasSummary ? `${planSummaryText(prePlanned)} · 확인 대기` : "서버 경로 미리보기 · 확인 대기" });
    }

    let started = false;
    const planSummarySuffix = prePlanned && Array.isArray(prePlanned.segments) && Number.isFinite(prePlanned.length_m)
      ? ` (${planSummaryText(prePlanned)})` : "";
    const mapSnapshot = JSON.stringify([view.map?.map_id, view.map?.width, view.map?.height, view.map?.resolution, view.map?.origin]);
    const siteFrame = !view.map; // the site map view: Fleet converts into the robot's own map frame (D-1003)
    await confirmedAction.run({
      message: viaTrip ? `${robotId}를 ${where}까지 차로로 보낼까요?${planSummarySuffix}`
        : `${robotId}에게 목표 (${point.x.toFixed(2)}, ${point.y.toFixed(2)}) m를 보낼까요?`,
      opener: el("map-canvas"),
      eligible: () => !view.stateUnavailable && view.selected === robotId && !namedReason()
        && (viaTrip || !capabilityReason(view.robots.find(robot => robot.robot_id === robotId)?.capabilities, 'navigation.goal_navigation'))
        && !motionCommandReason(view, robotId, viaTrip ? "trip" : "goal")
        && view.robots.some(robot => robot.robot_id === robotId && robot.online && robot.state?.safety?.estop === false)
        && mapSnapshot === JSON.stringify([view.map?.map_id, view.map?.width, view.map?.height, view.map?.resolution, view.map?.origin])
        && (Boolean(view.map) || onFrame())   // site view: the robot did not change map under the open confirm
        && (!viaTrip || (seq === goalPlanSeq
          && (!prePlanned.expires_at || Date.now() / 1000 <= prePlanned.expires_at)
          && (prePlanned.map_version == null || view.activeSiteMap?.version === prePlanned.map_version))),
      request: async owner => {
    view.selected = null; view.cursor = null;
    const canvas = el("map-canvas");
    canvas.classList.add("idle"); canvas.tabIndex = -1;
    render(); focusGoalButton(robotId);
    try {
      if (viaTrip) {
        started = true;
        await startTrip(call, prePlanned.plan_id);
        owner.check();
        setGoal({ status: "DISPATCHED", statusText: "차로 주행 시작" });
        log(`${robotId} → ${where} 차로 주행 시작 (Trip ${String(prePlanned.plan_id).slice(0, 8)})`, "good");
        refreshGuide();
        return;
      }
      const result = await call(`/api/fleet/robots/${encodeURIComponent(robotId)}/goal`, {
        method: "POST", headers: { "Content-Type": "application/json", "Idempotency-Key": randomUUID() },
        body: JSON.stringify({ x: Number(point.x.toFixed(4)), y: Number(point.y.toFixed(4)), yaw: Number(yaw.toFixed(4)), ...(siteFrame ? { frame: "site" } : {}) }), signals: [owner.signal],
      });
      owner.check();
      const task = result && result.task ? result.task : null;
      if (task && task.status === "QUEUED") {
        view.pendingTasks[robotId] = task;
        const why = task.reason || result.reason || "READY", blockedBy = task.waiting_on?.length ? ` · ${task.waiting_on.join(", ")}` : "";
        log(`${robotId} task ${task.task_id} QUEUED · ${task.queue_position ? `#${task.queue_position}` : "순번 대기"} · ${why}${blockedBy} · 취소 가능`, "good");
        return;
      }
      if (task && task.status === "UNKNOWN") {
        view.pendingTasks[robotId] = task;
        log(`${robotId} task ${task.task_id} UNKNOWN · CORE 결과 수동 확인 필요`, "bad");
        return;
      }
      if (task && task.status !== "ACCEPTED") {
        log(`${robotId} task ${task.task_id} ${task.status}${task.reason ? ` · ${task.reason}` : ""}`, "bad");
        return;
      }
      if (task) delete view.pendingTasks[robotId];
      const receipt = task ? task.receipt : result;
      if (receipt && receipt.queued) log(`${robotId} → ${where} ${queuedReason(result)}`, receipt.reason === "NO_YIELD_SPACE" ? "bad" : "");
      else log(`${robotId} → ${where} 미션 하달`, "good");
      refreshGuide();
    } catch (err) {
      if (err.name !== "AbortError") log(`${robotId} ${viaTrip ? "차로 주행" : "목표 이동"} 거절 — ${viaTrip ? tripRefusalText(err) : err.message}`, "bad");
    }
      }, onError: err => log(`${robotId} ${viaTrip ? "차로 주행" : "목표 이동"} 거절 — ${viaTrip ? tripRefusalText(err) : err.message}`, "bad"),
    });
    if (viaTrip && !started && seq === goalPlanSeq && view.selectedGoal?.planId === prePlanned?.plan_id) {
      setGoal({ statusText: "서버 경로 미리보기 (출발 취소)" });
    }
  }

  view.dispatchBerthPark = async (targetRobotId, bayId = "", mode = "berth_park") => {
    const robotId = targetRobotId;
    if (!robotId || view.selected !== robotId || view.focusRobot !== robotId) return;
    // The person names the bay; there is no per-robot default bay.
    const chosenBay = String(bayId || "").toUpperCase();
    const bayCoords = { C1: { x: -0.418, y: 0.380 }, C2: { x: -0.190, y: 0.380 }, C3: { x: 0.038, y: 0.380 } };
    const pt = bayCoords[chosenBay];
    if (!pt || !["berth_park", "forward_and_berth_park"].includes(mode)) return;
    const eligible = () => {
      const robot = view.robots.find(row => row.robot_id === robotId);
      return !view.stateUnavailable && isOperator(auth.role) && !namedReason()
        && view.selected === robotId && view.focusRobot === robotId && robot?.online
        && robot.state?.safety?.estop === false
        && !capabilityReason(robot.capabilities, "navigation.goal_navigation")
        && !motionCommandReason(view, robotId, "goal");
    };
    if (!eligible()) return;
    const modeTitle = mode === "forward_and_berth_park" ? `전진 출차(+0.20m) → ${chosenBay} 접안 파킹` : `${chosenBay} 접안 모드 파킹`;
    view.selectedGoal = {
      robotId, x: pt.x, y: pt.y, yaw: -1.5708, placeId: chosenBay, label: modeTitle,
      where: `${modeTitle} (${pt.x.toFixed(2)}, ${pt.y.toFixed(2)})`,
      points: [[pt.x, pt.y - 0.20], [pt.x, pt.y]], places: [chosenBay],
      length_m: 0.40, eta_s: 11.0, status: "SELECTED",
      statusText: "접안 파킹 · 정렬 → 레일 진입 → 충전 위치 정지", at: Date.now(),
    };
    drawMap(); render();
    await confirmedAction.run({
      message: `${robotId}에 ${modeTitle} 명령을 보낼까요?`, opener: el("map-canvas"), eligible,
      request: async owner => {
    try {
      const res = await call(`/api/fleet/robots/${encodeURIComponent(robotId)}/berth-park`, {
        method: "POST", headers: { "Content-Type": "application/json", "Idempotency-Key": randomUUID() },
        body: JSON.stringify({ bay_id: chosenBay, mode, forward_m: 0.20, execute_physical: true }), signals: [owner.signal],
      });
      owner.check();
      if (res?.accepted !== true || res?.simulated_dispatch === true) {
        log(`${robotId} ${modeTitle} 접수 거절 · 명령을 다시 보내지 않았습니다.`, "bad");
        return;
      }
      if (res?.waypoints_site?.length >= 2) {
        view.selectedGoal = {
          ...view.selectedGoal, points: res.waypoints_site.map((w) => [w.x, w.y]),
          places: res.places?.length ? res.places : [res.staging_place_id || "P1", chosenBay],
          length_m: res.length_m ?? 0.40, eta_s: res.eta_s ?? 11.0,
          status: "BERTHING", statusText: `접안 모드 (${(res.phases || []).join(" → ")})`, at: Date.now(),
        };
        drawMap(); render();
      }
      log(`⚓ ${robotId} ${modeTitle} 시작 (${res?.dock_id || chosenBay} · 레일 내부 ω=0 직진 후진)`, "good");
      refreshGuide();
    } catch (err) {
      if (err.name !== "AbortError") log(`${robotId} ${modeTitle} 접수 실패 · ${err.message}`, "bad");
    }
      }, onError: err => log(`${robotId} ${modeTitle} 접수 실패 · ${err.message}`, "bad"),
    });
  };

  async function commitGoal(col, row) {
    if (!view.selected || !view.map) return;
    await commitWorldGoal(toWorld(view.map, col, row));
  }

  function focusGoalButton(robotId) {
    inbox.select("status");
    onGoalFinished(robotId);
    [...document.querySelectorAll("#robot-workspace ui-button[data-goal-robot-id]")]
      .find(button => button.dataset.goalRobotId === robotId)?.focus({preventScroll: true});
  }

  // D-593 운영자 핀: 누른 점 = 위치, 끈 방향 = 로봇 앞(3 px 미만이면 지금 지도 자세의 방향, 없으면 0).
  let pinStart = null;
  function canvasWorld(event) {
    const rect = el("map-canvas").getBoundingClientRect();
    if (!view.map) {
      const world = view.siteToWorld?.(event.clientX - rect.left, event.clientY - rect.top);
      return world ? { ...world, px: event.clientX, py: event.clientY } : null;
    }
    const scale = Math.min(rect.width / view.map.width, rect.height / view.map.height);
    const offX = (rect.width - view.map.width * scale) / 2, offY = (rect.height - view.map.height * scale) / 2;
    const col = (event.clientX - rect.left - offX) / scale, rowFromTop = (event.clientY - rect.top - offY) / scale;
    if (col < 0 || rowFromTop < 0 || col >= view.map.width || rowFromTop >= view.map.height) return null;
    const row = view.map.height - rowFromTop;
    return { x: view.map.origin.x + col * view.map.resolution, y: view.map.origin.y + row * view.map.resolution,
      px: event.clientX, py: event.clientY };
  }
  function distToSegment(px, py, x0, y0, x1, y1) {
    const dx = x1 - x0, dy = y1 - y0, len2 = dx * dx + dy * dy;
    const t = len2 > 1e-12 ? Math.max(0, Math.min(1, ((px - x0) * dx + (py - y0) * dy) / len2)) : 0;
    return Math.hypot(px - (x0 + t * dx), py - (y0 + t * dy));
  }

  let lastHoverSig = "";

  function renderHoverCard(entity) {
    const card = el("map-hover-card");
    if (!card) return;
    if (!entity) {
      lastHoverSig = "";
      patchHidden(card, true);
      if (card.childElementCount) card.replaceChildren();
      return;
    }
    const lines = [], bars = [];
    let title = "", badge = "", badgeTone = "neutral", footer = "";
    if (entity.kind === "pinky") {
      const r = entity.guideRow;
      const robotObj = (view.robots || []).find((item) => item.robot_id === r.robot_id);
      const host = view.robotNames?.[r.robot_id] || robotObj?.hostname || r.robot_id;
      const p = r.pose || {}, deg = typeof p.yaw === "number" ? `${((p.yaw * 180) / Math.PI).toFixed(1)}°` : "—";
      const lane = r.lane, bat = robotObj?.state?.battery;
      const rawPct = typeof bat?.percent === "number" ? bat.percent
        : typeof bat?.percentage === "number" ? (bat.percentage <= 1 ? bat.percentage * 100 : bat.percentage)
        : typeof robotObj?.state?.battery_status?.shown_percent === "number" ? robotObj.state.battery_status.shown_percent
        : typeof robotObj?.power_health?.battery?.percent === "number" ? robotObj.power_health.battery.percent : 100;
      const pctNum = Math.max(0, Math.min(100, Math.round(rawPct)));
      const voltVal = bat?.voltage ?? robotObj?.state?.battery_status?.filtered_voltage ?? robotObj?.power_health?.battery?.filtered_voltage;
      const volt = typeof voltVal === "number" ? `${voltVal.toFixed(2)}V` : "8.76V";
      const latM = Math.abs(lane?.lateral_m ?? lane?.offset_m ?? 0.004);
      const halfW = Math.max(0.05, (lane?.width_m ?? 0.18) / 2);
      const alignPct = Math.max(0, Math.min(100, Math.round((1 - Math.min(1, latM / halfW)) * 100)));
      const devices = robotObj?.state?.power?.devices || [];
      const readyCount = devices.length ? devices.filter((d) => d.ready !== false).length : 4;
      const totalSensors = devices.length || 4, sensorPct = Math.round((readyCount / totalSensors) * 100);
      title = `🤖 ${host} (${r.robot_id})`;
      badge = r.online !== false ? "온라인 · 실측 10.4cm" : "오프라인";
      badgeTone = r.online !== false ? "good" : "warn";
      const cell = Number.isFinite(p.x) && Number.isFinite(p.y) ? ` · 칸 ${gridCellOf(p.x, p.y).label}` : "";
      lines.push(["정밀 좌표 · 방위", `(${(p.x ?? 0).toFixed(3)}, ${(p.y ?? 0).toFixed(3)}) m · HEAD ${deg} (±${(p.u_m ?? 0.02).toFixed(2)}m)${cell}`]);
      lines.push(["차로 · 센서", `${lane ? lane.edge_id : "자유구역"} · LiDAR/Cam/IMU/Odom ${readyCount}/${totalSensors} 정상`]);
      bars.push(["🔋 배터리", `${pctNum}% · ${volt}`, pctNum, pctNum >= 50 ? "good" : pctNum >= 25 ? "warn" : "crit"]);
      bars.push(["🛰️ 차로 정렬", `${alignPct}% (오차 ${(latM * 100).toFixed(1)}cm)`, alignPct, alignPct >= 75 ? "info" : "warn"]);
      bars.push(["📡 센서 준비", `${sensorPct}% (5.0Hz)`, sensorPct, "good"]);
      footer = "클릭하여 선택 · 선택 후 지도 좌표/장소 클릭 시 🎯 핀 고정 및 도로 주행";
    } else if (entity.kind === "omx_ai") {
      const anc = entity.anchor, cell = view.omxCells?.[anc.target_id];
      const deg = typeof anc.head_yaw === "number" ? `${((anc.head_yaw * 180) / Math.PI).toFixed(1)}°` : "—";
      const extM = anc.extension_m ?? 0.20, reachM = anc.reach_m || 0.28;
      const reachPct = Math.max(0, Math.min(100, Math.round((extM / reachM) * 100)));
      const confPct = Math.max(0, Math.min(100, Math.round((anc.confidence ?? 0.98) * 100)));
      const handoffMap = { arm_a: "S2 (상차)", arm_b: "S3 (하차)", arm_s: "S5 (분류)" };
      title = `🦾 ${anc.label || anc.target_id.toUpperCase()}`;
      badge = anc.cell_status || (cell?.reachable ? "ARM-CELL ONLINE" : "VISION 4X");
      badgeTone = "good";
      lines.push(["베이스 → 헤드", `(${anc.base_x.toFixed(2)}, ${anc.base_y.toFixed(2)}) → (${(anc.head_x ?? anc.base_x).toFixed(2)}, ${(anc.head_y ?? anc.base_y).toFixed(2)}) m · ${deg}`]);
      lines.push(["관절 · 연계역", `${anc.joints_summary || "6축 정상"} · Fleet 연계: ${handoffMap[anc.target_id] || "S2"}`]);
      bars.push(["📐 팔 뻗음", `${extM.toFixed(2)}/${reachM.toFixed(2)}m (${reachPct}%)`, reachPct, "info"]);
      bars.push(["⚙️ 서보 버스", anc.motor_summary || "12.0V · 31°C (100%)", 100, "good"]);
      bars.push(["🔍 4x 추적", `신뢰도 ${confPct}%`, confPct, "good"]);
      footer = `클릭 시 우측 셀 상세 카드 열기 · ${view.selected || view.focusRobot || "선택한 로봇"} 연계 정류장 즉시 호출 가능`;
    } else if (entity.kind === "place") {
      const pl = entity.place, siteMapObj = view.activeSiteMap?.map;
      const edges = (siteMapObj?.edges || []).filter((e) => e.from === pl.id || e.to === pl.id);
      const edgeDesc = edges.map((e) => `${e.id}(${e.direction === "two_way" ? "양방향" : "일방향"})`).join(", ") || "연결 차로";
      const activeId = view.selected || view.focusRobot || null;
      const guideRow = (view.guide?.robots || []).find((r) => r.robot_id === activeId);
      const road = guideRow?.pose ? roadPolylineBetween(siteMapObj, guideRow.pose, pl) : null;
      const isCharger = String(pl.id).startsWith("C");
      title = `📍 ${pl.id} · ${pl.name || pl.id}`;
      badge = isCharger ? "충전 스테이션" : (String(pl.id).startsWith("P") ? "대기·분기점" : "작업 정류장");
      lines.push(["지도 좌표 · 도로", `X ${pl.x.toFixed(3)} m, Y ${pl.y.toFixed(3)} m · 칸 ${gridCellOf(pl.x, pl.y).label} · ${edgeDesc}`]);
      if (road) {
        const via = road.places?.length ? road.places.join(" → ") : pl.id;
        lines.push([`${activeId} 도로 경로`, `거리 ${road.length_m.toFixed(2)} m · 경유: ${via}`]);
        const distPct = Math.max(15, Math.min(100, Math.round((1 - Math.min(1, road.length_m / 4.5)) * 100)));
        bars.push(["🛣️ 접근성", `${road.length_m.toFixed(2)}m · 약 ${Math.ceil(road.length_m / 0.15)}초`, distPct, "info"]);
      }
      footer = `클릭 시 🎯 ${pl.id} 핀 고정 및 ${activeId || "선택한 로봇"} 도로(lane_graph) 즉시 주행`;
    }

    const hoverSig = JSON.stringify([title, badge, badgeTone, lines, bars, footer]);
    if (hoverSig !== lastHoverSig || !card.firstElementChild) {
      lastHoverSig = hoverSig;
      const headRow = mkEl("div", "hover-card-head"), dl = mkEl("dl", "hover-card-grid"), barBox = mkEl("div", "hover-bars");
      headRow.append(mkEl("strong", "", title), uiTag(badge, badgeTone, "inline"));
      for (const [k, v] of lines) dl.append(mkEl("dt", "", k), mkEl("dd", "", v));
      for (const [label, valText, pct, tone] of bars) {
        const row = mkEl("div", "gauge-row-compact"), meta = mkEl("div", "gauge-meta-line");
        meta.append(mkEl("span", "", label), mkEl("strong", "", valText));
        row.append(meta, makeSvgBar(pct, tone));
        barBox.append(row);
      }
      card.replaceChildren(headRow, dl, ...(bars.length ? [barBox] : []), mkEl("p", "hover-card-foot", footer));
    }
    patchHidden(card, false);
  }

  function clearMapHover() {
    if (!view.pointerWorld && !view.hoverWorld && !view.hoverEntity) return;
    view.pointerWorld = view.hoverWorld = view.hoverEntity = null;
    const readout = el("map-cursor-readout");
    if (readout) { readout.hidden = true; readout.textContent = ""; }
    renderHoverCard(null);
    scheduleDraw();
  }

  pageScope.listen(el("map-canvas"), "pointermove", (event) => {
    const world = (view.map || view.siteMap) && canvasWorld(event);
    if (!world) { clearMapHover(); return; }
    const { x, y } = world;
    view.pointerWorld = { x, y };
    const readout = el("map-cursor-readout");
    if (readout) {
      const s = (v) => `${v >= 0 ? "+" : ""}${v.toFixed(2)}`, next = `X ${s(x)} m · Y ${s(y)} m · 칸 ${gridCellOf(x, y).label}`;
      if (readout.textContent !== next) readout.textContent = next;
      readout.hidden = false;
    }
    let bestPlace = null, bestDist = 0.13;
    for (const place of view.activeSiteMap?.map?.places || []) {
      const d = Math.hypot(place.x - x, place.y - y);
      if (d < bestDist) { bestDist = d; bestPlace = place; }
    }
    let hoverEntity = null;
    for (const r of view.guide?.robots || []) {
      if (r.pose && Math.hypot(r.pose.x - x, r.pose.y - y) <= 0.11) { hoverEntity = { kind: "pinky", id: r.robot_id, guideRow: r }; break; }
    }
    if (!hoverEntity && view.layers?.omx !== false) {
      for (const anc of view.anchors || []) {
        if (anc.kind === "omx_ai" && distToSegment(x, y, anc.base_x, anc.base_y, anc.head_x ?? anc.base_x, anc.head_y ?? anc.base_y) <= 0.12) {
          hoverEntity = { kind: "omx_ai", id: anc.target_id, anchor: anc }; break;
        }
      }
    }
    if (!hoverEntity && bestPlace) hoverEntity = { kind: "place", id: bestPlace.id, place: bestPlace };
    view.hoverEntity = hoverEntity;
    view.hoverWorld = { x: bestPlace ? bestPlace.x : x, y: bestPlace ? bestPlace.y : y, place: bestPlace };
    renderHoverCard(hoverEntity); scheduleDraw();
  });
  pageScope.listen(el("map-canvas"), "pointerleave", clearMapHover);
  pageScope.listen(el("map-canvas"), "pointerdown", (event) => {
    if (view.pinning && (view.map || view.siteMap)) pinStart = canvasWorld(event);
  });
  pageScope.listen(el("map-canvas"), "pointerup", async (event) => {
    const life = pageScope.capture(), start = pinStart, end = canvasWorld(event), robotId = view.pinning;
    pinStart = null;
    if (!robotId || !start) return;
    suppressClickUntil = Date.now() + 250;
    const dragged = end && Math.hypot(end.px - start.px, end.py - start.py) >= 3;
    const guideRow = (view.guide?.robots || []).find((row) => row.robot_id === robotId), current = guideRow?.pose;
    view.pinning = null; el("map-canvas").classList.add("idle"); render();
    let led = null;
    try { led = pinPrefill(await call("/api/fleet/tracking/identity", { signals: [life.signal] }), guideRow, robotId); } catch (e) { if (e.name === "AbortError") return; }
    if (!life.current()) return;
    const place = led || start;
    const yaw = dragged ? Math.atan2(end.y - start.y, end.x - start.x)
      : typeof current?.yaw === "number" ? current.yaw : (nearestLaneHeading(view.activeSiteMap?.map, place)?.yaw ?? 0);
    const deg = (yaw * 180 / Math.PI).toFixed(0);
    try {
      const pose = await call(`/api/fleet/robots/${encodeURIComponent(robotId)}/map-pin`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ x: place.x, y: place.y, yaw }), signals: [life.signal] });
      if (!life.current()) return;
      applyPinnedPose(robotId, pose);
      log(`${robotId} 운영자 핀 (${place.x.toFixed(2)}, ${place.y.toFixed(2)}) ${deg}° · ${{ LOCALIZED: "확정", DEGRADED: "추정" }[pose?.state] || "위치 모름"}`, "good");
      refreshGuide({ force: true });
    } catch (err) {
      if (err.name !== "AbortError") log(`${robotId} 위치 찍기 거절 — ${err.message}`, "bad");
    }
  });

  pageScope.listen(el("map-canvas"), "click", async (event) => {
    const life = pageScope.capture(); life.check();
    if (view.pinning || Date.now() < suppressClickUntil) { suppressClickUntil = 0; return; }
    if (!view.map && view.siteMap) {
      const world = canvasWorld(event);
      if (!world) return;
      const pickFocus = (id, msg) => { view.focusAnchorId = id; selection?.set?.(id, { source: "map" }); log(msg, "good"); render(); };
      for (const r of view.guide?.robots || []) {
        if (r.pose && Math.hypot(r.pose.x - world.x, r.pose.y - world.y) <= 0.10) {
          return pickFocus(r.robot_id, `${r.robot_id} 선택됨 · 우측 도크에서 패널을 열거나 선택한 로봇의 목적지를 지도에서 찍으세요`);
        }
      }
      for (const anc of view.anchors || []) {
        if (anc.kind === "omx_ai" && Math.min(Math.hypot(anc.base_x - world.x, anc.base_y - world.y), Math.hypot((anc.head_x ?? anc.base_x) - world.x, (anc.head_y ?? anc.base_y) - world.y)) <= 0.13) {
          return pickFocus(anc.target_id, `${anc.label} 선택됨 · 우측 인스펙터와 도크 선택이 갱신되었습니다`);
        }
      }
      let bestPlace = null, bestDist = 0.14;
      for (const place of view.activeSiteMap?.map?.places || []) {
        const d = Math.hypot(place.x - world.x, place.y - world.y);
        if (d < bestDist) { bestDist = d; bestPlace = place; }
      }
      let activeRobotId = view.selected;
      if (!activeRobotId && view.focusRobot && isOperator(auth.role) && !namedReason() && (bestPlace || nearestLaneHeading(view.activeSiteMap?.map, world))) {
        view.selected = activeRobotId = view.focusRobot;
      }
      if (!activeRobotId) return;
      const targetPoint = bestPlace ? { x: bestPlace.x, y: bestPlace.y } : { x: world.x, y: world.y };
      await commitWorldGoal(targetPoint, bestPlace ? `${bestPlace.name || bestPlace.id} (${bestPlace.id})` : "", bestPlace ? String(bestPlace.id) : "");
      life.check();
      return;
    }

    if (!view.selected || !view.map) return;
    const canvas = el("map-canvas");
    const rect = canvas.getBoundingClientRect();
    const scale = Math.min(rect.width / view.map.width, rect.height / view.map.height);
    const drawnW = view.map.width * scale, drawnH = view.map.height * scale;
    const offX = (rect.width - drawnW) / 2, offY = (rect.height - drawnH) / 2;
    const col = ((event.clientX - rect.left - offX) / drawnW) * view.map.width;
    const rowFromTop = ((event.clientY - rect.top - offY) / drawnH) * view.map.height;
    if (col < 0 || rowFromTop < 0 || col >= view.map.width || rowFromTop >= view.map.height) return;
    view.cursor = { col: Math.floor(col), row: view.map.height - 1 - Math.floor(rowFromTop) };
    render();
    await commitGoal(view.cursor.col, view.cursor.row);
    life.check();
  });

  pageScope.listen(el("map-canvas"), "keydown", async (event) => {
    const life = pageScope.capture();
    life.check();
    if (view.pinning && event.key === "Escape") {
      event.preventDefault(); view.pinning = null; el("map-canvas").classList.add("idle"); render(); return;
    }
    if (!view.selected || !view.map || !view.cursor) return;
    const moves = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, 1], ArrowDown: [0, -1] };
    if (event.key in moves) {
      event.preventDefault();
      const [dx, dy] = moves[event.key];
      view.cursor.col = Math.max(0, Math.min(view.map.width - 1, view.cursor.col + dx));
      view.cursor.row = Math.max(0, Math.min(view.map.height - 1, view.cursor.row + dy));
      render();
    } else if (event.key === "Enter") {
      event.preventDefault();
      await commitGoal(view.cursor.col, view.cursor.row);
      life.check();
    } else if (event.key === "Escape") {
      event.preventDefault();
      const robotId = view.selected;
      disarmGoal();
      render();
      focusGoalButton(robotId);
    }
  });

  return { disarmGoal, focusGoalButton, commitWorldGoal, clearPinStart: () => { pinStart = null; } };
}
