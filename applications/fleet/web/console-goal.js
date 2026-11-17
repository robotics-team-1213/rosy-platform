import {randomUUID} from "/console/assets/uuid.js";
// 지도 위 목표 지정과 운영자 핀(D-201·D-224·D-593). 셸(console.js)이 그리기(render)와 지도 뷰를 건넨다(D-798 3.2).
import { capabilityReason, motionCommandReason } from "./motion-readiness.js";
import { pinPrefill, robotMapPose } from "./localization-badge.js";
import { stepQueuedStarts } from "./localization-view.js";
import { roadPolylineBetween } from "/console/assets/guide-layer.js";
import { valueText } from "/common/value-text.js";
import { planTrip, startTrip, tripPoseReason, tripRefusalText } from "/console/assets/site-map-model.js";

export function createConsoleGoal({ pageScope, el, view, auth, inbox, log, call, render, confirmedAction, namedReason,
  toWorld, refreshGuide, queuedReason, drawMap = () => {}, onSelectRobot = () => {} }) {
  function disarmGoal(reason) {
    view.selected = null; view.cursor = null; view.hoverWorld = null;
    const canvas = el("map-canvas");
    canvas.classList.add("idle"); canvas.tabIndex = -1;
    if (reason) log(reason, "bad", { silent: true });
  }

  // D-224 — 예외 문법의 키보드 어휘(§7.3 "keyboard-first" 의 실현).
  pageScope.listen(document, "keydown", (event) => {
    if (event.defaultPrevented || event.target.closest("input, select, textarea, button, ui-button, a, canvas, summary")) return;
    const cards = [...document.querySelectorAll("#roster .robot-row, #robot-panel-mount article")];
    if (!cards.length) return;
    const active = document.activeElement;
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault(); inbox.select("status");
      const idx = cards.indexOf(active);
      const next = idx < 0 ? cards[event.key === "ArrowDown" ? 0 : cards.length - 1]
        : cards[(idx + (event.key === "ArrowDown" ? 1 : -1) + cards.length) % cards.length];
      next.focus();
    } else if (event.key === "Enter" && cards.includes(active)) {
      const choose = active.querySelector("ui-button[data-select-robot-id]");
      if (choose && !choose.disabled) { event.preventDefault(); choose.click(); }
    } else if (event.key === "Escape" && view.selected) {
      const robotId = view.selected; disarmGoal("목표 지정 취소"); render(); focusGoalButton(robotId);
    }
  });

  const localizedRobotPose = (robot) => robotMapPose(robot)
    || (robot?.pose_state === "LOCALIZED" && robot?.pose?.frame_id === "map"
      && Number.isFinite(robot.pose.x) && Number.isFinite(robot.pose.y) ? robot.pose : null);

  async function commitWorldGoal(point, placeLabel = "", placeId = "", overrideRobotId = null) {
    const life = pageScope.capture(); life.check();
    if (!point || !Number.isFinite(point.x) || !Number.isFinite(point.y)) return;
    const robotId = overrideRobotId || view.selected;
    if (!robotId) return;
    const selectedRobot = view.robots.find((robot) => robot.robot_id === robotId);
    const guideRow = (view.guide?.robots || []).find((r) => r.robot_id === robotId);
    const curPose = guideRow?.pose || localizedRobotPose(selectedRobot) || null;
    const yaw = curPose && Number.isFinite(curPose.x) && Number.isFinite(curPose.y) ? Math.atan2(point.y - curPose.y, point.x - curPose.x) : 0;
    const where = placeLabel ? `${placeLabel} (${point.x.toFixed(2)}, ${point.y.toFixed(2)})` : `(${point.x.toFixed(2)}, ${point.y.toFixed(2)})`;
    const siteMapObj = view.activeSiteMap?.map, localRoad = curPose ? roadPolylineBetween(siteMapObj, curPose, point) : null;
    const initialPts = localRoad?.points?.length >= 2 ? localRoad.points : (curPose ? [[curPose.x, curPose.y], [point.x, point.y]] : [[point.x, point.y]]);
    const initialLen = typeof localRoad?.length_m === "number" ? localRoad.length_m : (curPose ? Math.hypot(point.x - curPose.x, point.y - curPose.y) : 0);
    view.selectedGoal = {
      robotId, x: point.x, y: point.y, yaw, placeId: placeId || null,
      label: placeLabel || `좌표 (${point.x.toFixed(2)}, ${point.y.toFixed(2)})`,
      where, points: initialPts, places: localRoad?.places || (placeId ? [placeId] : []),
      length_m: initialLen, eta_s: initialLen / 0.15, status: "SELECTED",
      statusText: "목표 핀 고정 · 도로 경로 확정", at: Date.now(),
    };
    view.lastDispatchedGoal = { robotId, x: point.x, y: point.y, yaw, label: where, at: Date.now() };
    const stationInspectMap = {
      S2: { targetId: "arm_a", camId: "arm_a_wrist" }, S3: { targetId: "arm_s", camId: "arm_s_wrist" },
      S5: { targetId: "arm_b", camId: "arm_b_wrist" }, S1: { targetId: robotId, camId: "side" },
      C1: { targetId: robotId, camId: "pinky" }, C2: { targetId: robotId, camId: "pinky" }, C3: { targetId: robotId, camId: "pinky" },
    };
    const linkedInspect = placeId ? stationInspectMap[String(placeId).toUpperCase()] : null;
    if (linkedInspect && typeof window !== "undefined" && typeof window.dispatchEvent === "function") {
      if (linkedInspect.targetId.startsWith("arm_")) view.focusAnchorId = linkedInspect.targetId;
      window.dispatchEvent(new CustomEvent("rosy:inspect-target", { detail: linkedInspect }));
    }
    drawMap(); render();

    // A robot on its own (SLAM) map takes a site goal only as a lane trip Fleet plans from its measured site pose;
    // say why before the confirm when that cannot start (2026-11-14: no raw site goal into a robot's own frame).
    const siteMapId = view.activeSiteMap?.map?.map_id;
    const viaTrip = !view.map && selectedRobot?.state?.map_id !== siteMapId;   // site view, robot not on this map
    const onFrame = () => !view.map && (view.robots.find(robot => robot.robot_id === robotId)?.state?.map_id !== siteMapId) === viaTrip
      && view.activeSiteMap?.map?.map_id === siteMapId;
    const canDispatch = !view.stateUnavailable && auth.role === "operator" && !namedReason()
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
          view.selectedGoal = {
            ...view.selectedGoal, points: planRes.waypoints_site.map((w) => [w.x, w.y]),
            places: planRes.places || view.selectedGoal.places, length_m: planRes.length_m ?? view.selectedGoal.length_m,
            eta_s: planRes.eta_s ?? view.selectedGoal.eta_s, status: "PREVIEW",
            statusText: auth.role !== "operator" ? "목표 핀 고정 (운영자 로그인 시 출발)" : "목표 핀 고정 (안전 확인 대기)", at: Date.now(),
          };
          view.activeRoadPlan = { robotId, ...planRes, at: Date.now() };
          drawMap(); render();
        }
      } catch (_planErr) { /* Keep local road pin visible */ }
      log(`${robotId} → ${where} 목표 핀 및 도로 경로(${view.selectedGoal.length_m.toFixed(2)}m)가 지도에 고정되었습니다.`, "good");
      return;
    }

    if (viaTrip) {
      const blocked = !siteMapId ? "현장 지도 활성화 필요: 활성 지도가 없어 보내지 않습니다"
        : !placeId ? "차로 위 아님: 지도의 장소를 찍으세요"
        : !view.guide ? "위치 확인 중: 잠시 뒤 다시 찍으세요"
        : tripPoseReason(view.guide, robotId, view.activeSiteMap);
      if (blocked) {
        view.selectedGoal = { ...view.selectedGoal, status: "BLOCKED", statusText: blocked, at: Date.now() };
        drawMap(); render();
        log(`${robotId} 출발 보류 · ${blocked}`, "bad");
        return;
      }
    }

    const mapSnapshot = JSON.stringify([view.map?.map_id, view.map?.width, view.map?.height, view.map?.resolution, view.map?.origin]);
    const siteFrame = !view.map; // the site map view: Fleet converts into the robot's own map frame (D-1003)
    await confirmedAction.run({
      message: viaTrip ? `${robotId}를 ${where}까지 차로로 보낼까요?` : `${robotId}에게 목표 (${point.x.toFixed(2)}, ${point.y.toFixed(2)}) m를 보낼까요?`,
      opener: overrideRobotId ? el("map-sel-send") : el("map-canvas"),
      eligible: () => !view.stateUnavailable && (overrideRobotId ? view.robotSelection?.get?.() === robotId : view.selected === robotId) && !namedReason()
        && (viaTrip || !capabilityReason(view.robots.find(robot => robot.robot_id === robotId)?.capabilities, 'navigation.goal_navigation'))
        && !motionCommandReason(view, robotId, viaTrip ? "trip" : "goal")
        && view.robots.some(robot => robot.robot_id === robotId && robot.online && robot.state?.safety?.estop === false)
        && mapSnapshot === JSON.stringify([view.map?.map_id, view.map?.width, view.map?.height, view.map?.resolution, view.map?.origin])
        && (Boolean(view.map) || onFrame()),   // site view: the robot did not change map under the open confirm
      request: async owner => {
    view.selected = null;
    view.cursor = null;
    const canvas = el("map-canvas");
    canvas.classList.add("idle");
    canvas.tabIndex = -1;
    render();
    focusGoalButton(robotId);
    try {
      if (viaTrip) {
        const plan = await planTrip(call, robotId, { to: placeId });
        owner.check();
        await startTrip(call, plan.plan_id);
        owner.check();
        log(`${robotId} → ${where} 차로 주행 시작 (Trip ${String(plan.plan_id).slice(0, 8)})`, "good");
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
  }

  view.dispatchBerthPark = async (targetRobotId, bayId = "", mode = "berth_park") => {
    const robotId = targetRobotId;
    const activeRobot = view.robotSelection ? view.robotSelection.get() : null;
    if (!robotId || view.selected !== robotId || activeRobot !== robotId) return;
    const defaultBay = robotId === "rosy_45" ? "C2" : robotId === "rosy_42" ? "C3" : "C1";
    const chosenBay = (bayId || defaultBay).toUpperCase();
    const bayCoords = { C1: { x: -0.418, y: 0.380 }, C2: { x: -0.190, y: 0.380 }, C3: { x: 0.038, y: 0.380 } };
    const pt = bayCoords[chosenBay];
    if (!pt || !["berth_park", "forward_and_berth_park"].includes(mode)) return;
    const eligible = () => {
      const robot = view.robots.find(row => row.robot_id === robotId);
      const currentRobot = view.robotSelection ? view.robotSelection.get() : null;
      return !view.stateUnavailable && auth.role === "operator" && !namedReason()
        && view.selected === robotId && currentRobot === robotId && robot?.online
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
        body: JSON.stringify({ bay_id: chosenBay, mode, forward_m: 0.20 }), signals: [owner.signal],
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
      log(`${robotId} ${modeTitle} 시작 (${res?.dock_id || chosenBay} · 레일 내부 ω=0 직진 후진)`, "good");
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
    [...document.querySelectorAll("#robot-panel-mount ui-button[data-goal-robot-id]")]
      .find(button => button.dataset.goalRobotId === robotId)?.focus({preventScroll: true});
  }

  const STATION_TO_ARM = { S2: "arm_a", S3: "arm_s", S5: "arm_b" };

  // D-593 운영자 핀: 누른 점 = 위치, 끈 방향 = 로봇 앞(3 px 미만이면 지금 지도 자세의 방향, 없으면 0).
  let pinStart = null;
  function canvasWorld(event) {
    const rect = el("map-canvas").getBoundingClientRect();
    if (!view.map) {
      const lx = event.clientX - rect.left, ly = event.clientY - rect.top;
      const world = view.siteToWorld?.(lx, ly);
      if (!world) return null;
      const w2 = view.siteToWorld?.(lx + 20, ly);
      const worldPerPx = w2 ? Math.hypot(w2.x - world.x, w2.y - world.y) / 20 : 0.008;
      return { ...world, px: event.clientX, py: event.clientY, worldPerPx };
    }
    const scale = Math.min(rect.width / view.map.width, rect.height / view.map.height);
    const offX = (rect.width - view.map.width * scale) / 2, offY = (rect.height - view.map.height * scale) / 2;
    const col = (event.clientX - rect.left - offX) / scale, rowFromTop = (event.clientY - rect.top - offY) / scale;
    if (col < 0 || rowFromTop < 0 || col >= view.map.width || rowFromTop >= view.map.height) return null;
    const row = view.map.height - rowFromTop;
    return { x: view.map.origin.x + col * view.map.resolution, y: view.map.origin.y + row * view.map.resolution,
      px: event.clientX, py: event.clientY, worldPerPx: scale > 0 ? view.map.resolution / scale : 0.01 };
  }
  function distToSegment(px, py, x0, y0, x1, y1) {
    const dx = x1 - x0, dy = y1 - y0, len2 = dx * dx + dy * dy;
    const t = len2 > 1e-12 ? Math.max(0, Math.min(1, ((px - x0) * dx + (py - y0) * dy) / len2)) : 0;
    return Math.hypot(px - (x0 + t * dx), py - (y0 + t * dy));
  }

  function hitTestMapEntity(world) {
    const px = world.worldPerPx || 0.01;
    const pinkyTol = Math.max(0.14, 22 * px);
    const omxTol = Math.max(0.16, 24 * px);
    const placeTol = Math.max(0.14, 20 * px);
    for (const r of view.guide?.robots || []) {
      if (r.pose && Math.hypot(r.pose.x - world.x, r.pose.y - world.y) <= pinkyTol) {
        return { kind: "pinky", id: r.robot_id, guideRow: r };
      }
    }
    for (const r of view.robots || []) {
      const p = localizedRobotPose(r);
      if (p && typeof p.x === "number" && typeof p.y === "number" && Math.hypot(p.x - world.x, p.y - world.y) <= pinkyTol) {
        return { kind: "pinky", id: r.robot_id, guideRow: { robot_id: r.robot_id, online: r.online, pose: p } };
      }
    }
    for (const row of view.cameraTracking?.robots || []) {
      const p = row?.camera || row?.pose;
      if (p && typeof p.x === "number" && typeof p.y === "number" && Math.hypot(p.x - world.x, p.y - world.y) <= pinkyTol) {
        return { kind: "pinky", id: row.robotId, guideRow: { robot_id: row.robotId, online: true, pose: p } };
      }
    }
    for (const s of view.sightings || []) {
      if (typeof s.x === "number" && typeof s.y === "number" && Math.hypot(s.x - world.x, s.y - world.y) <= pinkyTol) {
        return { kind: "pinky", id: s.robot_id, guideRow: { robot_id: s.robot_id, online: true, pose: { x: s.x, y: s.y, yaw: s.yaw } } };
      }
    }
    if (view.layers?.omx !== false) {
      const anchors = Array.isArray(view.anchors) ? view.anchors : Array.isArray(view.guide?.anchors) ? view.guide.anchors : [];
      for (const anc of anchors) {
        if (anc.kind === "omx_ai") {
          const hx = anc.head_x ?? anc.base_x, hy = anc.head_y ?? anc.base_y;
          if (distToSegment(world.x, world.y, anc.base_x, anc.base_y, hx, hy) <= omxTol) {
            return { kind: "omx_ai", id: anc.target_id, anchor: anc };
          }
        }
      }
    }
    const places = view.activeSiteMap?.map?.places || [];
    let bestPlace = null, bestDist = placeTol;
    for (const place of places) {
      const d = Math.hypot(place.x - world.x, place.y - world.y);
      if (d < bestDist) { bestDist = d; bestPlace = place; }
    }
    return bestPlace ? { kind: "place", id: bestPlace.id, place: bestPlace } : null;
  }

  function renderHoverCard(entity) {
    const card = el("map-hover-card");
    if (!card) return;
    if (!entity) { card.hidden = true; card.replaceChildren(); return; }
    // Hover card: a value that is not read is 정보 없음, never an invented default (D-280).
    const lines = [];
    let title = "", badge = "", badgeTone = "neutral", footer = "";
    const unknown = valueText(null).text;
    if (entity.kind === "pinky") {
      const r = entity.guideRow;
      const robotObj = (view.robots || []).find((item) => item.robot_id === r.robot_id);
      const host = view.robotNames?.[r.robot_id] || robotObj?.hostname || r.robot_id;
      const p = r.pose || {}, deg = typeof p.yaw === "number" ? `${((p.yaw * 180) / Math.PI).toFixed(1)}°` : unknown;
      const lane = r.lane, bat = robotObj?.state?.battery;
      const rawPct = typeof bat?.percent === "number" ? bat.percent
        : typeof bat?.percentage === "number" ? (bat.percentage <= 1 ? bat.percentage * 100 : bat.percentage)
        : typeof robotObj?.state?.battery_status?.shown_percent === "number" ? robotObj.state.battery_status.shown_percent
        : typeof robotObj?.power_health?.battery?.percent === "number" ? robotObj.power_health.battery.percent : null;
      const voltVal = bat?.voltage ?? robotObj?.state?.battery_status?.filtered_voltage ?? robotObj?.power_health?.battery?.filtered_voltage;
      const devices = robotObj?.state?.power?.devices || [];
      const sensors = devices.length ? `${devices.filter((d) => d.ready !== false).length}/${devices.length} 정상` : unknown;
      title = `${host} (${r.robot_id})`;
      badge = r.online !== false ? "온라인" : "오프라인";
      badgeTone = r.online !== false ? "neutral" : "warn";
      lines.push(["정밀 좌표 · 방위", typeof p.x === "number" && typeof p.y === "number"
        ? `(${p.x.toFixed(3)}, ${p.y.toFixed(3)}) m · HEAD ${deg}${typeof p.u_m === "number" ? ` (±${p.u_m.toFixed(2)}m)` : ""}` : unknown]);
      lines.push(["차로", lane?.edge_id || "자유구역"]);
      lines.push(["배터리", `${valueText(rawPct === null ? null : Math.round(rawPct), {unit: "%"}).text}${typeof voltVal === "number" ? ` · ${voltVal.toFixed(2)}V` : ""}`]);
      lines.push(["센서", sensors]);
      footer = "클릭하여 선택 · 아래 제어 막대에서 이동·조종 가능";
    } else if (entity.kind === "omx_ai") {
      const anc = entity.anchor, cell = view.omxCells?.[anc.target_id];
      const deg = typeof anc.head_yaw === "number" ? `${((anc.head_yaw * 180) / Math.PI).toFixed(1)}°` : unknown;
      const handoffMap = { arm_a: "S5 (적재 · S2 상차)", arm_s: "S3 (하차 셔틀)", arm_b: "S5 (적재 · 반출)" };
      title = anc.label || anc.target_id.toUpperCase();
      badge = anc.cell_status || (cell?.reachable === true ? "셀 연결" : unknown);
      badgeTone = "neutral";
      lines.push(["베이스 → 헤드", `(${anc.base_x.toFixed(2)}, ${anc.base_y.toFixed(2)}) → (${(anc.head_x ?? anc.base_x).toFixed(2)}, ${(anc.head_y ?? anc.base_y).toFixed(2)}) m · HEAD ${deg}`]);
      lines.push(["관절 · 연계역", `${valueText(anc.joints_summary).text} · Fleet 연계: ${handoffMap[anc.target_id] || unknown}`]);
      lines.push(["팔 뻗음", typeof anc.extension_m === "number" && anc.reach_m > 0 ? `${anc.extension_m.toFixed(2)}/${anc.reach_m.toFixed(2)}m` : unknown]);
      lines.push(["서보 버스", valueText(anc.motor_summary).text]);
      lines.push(["4x 추적", typeof anc.confidence === "number" ? `신뢰도 ${Math.round(anc.confidence * 100)}%` : unknown]);
      footer = "클릭하여 팔 선택 · 상세·연계 상태 확인";
    } else if (entity.kind === "place") {
      const pl = entity.place, siteMapObj = view.activeSiteMap?.map;
      const edges = (siteMapObj?.edges || []).filter((e) => e.from === pl.id || e.to === pl.id);
      const edgeDesc = edges.map((e) => `${e.id}(${e.direction === "two_way" ? "양방향" : "일방향"})`).join(", ") || "연결 차로";
      const activeId = view.selected || view.robotSelection?.get?.() || null;
      const guideRow = activeId ? (view.guide?.robots || []).find((r) => r.robot_id === activeId) : null;
      const road = guideRow?.pose ? roadPolylineBetween(siteMapObj, guideRow.pose, pl) : null;
      const isCharger = String(pl.id).startsWith("C");
      title = `${pl.id} · ${pl.name || pl.id}`;
      badge = isCharger ? "충전 스테이션" : (String(pl.id).startsWith("P") ? "대기·분기점" : "작업 정류장");
      lines.push(["지도 좌표 · 도로", `X ${pl.x.toFixed(3)} m, Y ${pl.y.toFixed(3)} m · ${edgeDesc}`]);
      if (road) {
        const via = road.places?.length ? road.places.join(" → ") : pl.id;
        lines.push([`${activeId} 도로 경로`, `거리 ${road.length_m.toFixed(2)} m · 경유: ${via}`]);
      }
      footer = view.selected
        ? `클릭 시 ${view.selected} 목표 확인창 열기`
        : `클릭하여 장소 선택${activeId ? ` · 아래에서 ${activeId} 이동 가능` : ""}`;
    }

    const headRow = document.createElement("div");
    headRow.className = "hover-card-head";
    const strong = document.createElement("strong"); strong.textContent = title;
    const tag = document.createElement("ui-tag");
    tag.setAttribute("status", badgeTone); tag.setAttribute("variant", "inline"); tag.textContent = badge;
    headRow.append(strong, tag);

    const dl = document.createElement("dl"); dl.className = "hover-card-grid";
    for (const [k, v] of lines) {
      const dt = document.createElement("dt"); dt.textContent = k;
      const dd = document.createElement("dd"); dd.textContent = v;
      dl.append(dt, dd);
    }

    const foot = document.createElement("p"); foot.className = "hover-card-foot"; foot.textContent = footer;
    card.replaceChildren(headRow, dl, foot);
    card.hidden = false;
  }

  pageScope.listen(el("map-canvas"), "pointermove", (event) => {
    if (!view.map && !view.siteMap) return;
    const world = canvasWorld(event);
    if (!world) {
      el("map-canvas").classList.remove("clickable-entity");
      if (view.hoverWorld || view.hoverEntity) {
        view.hoverWorld = null; view.hoverEntity = null; renderHoverCard(null); drawMap();
      }
      return;
    }
    const hoverEntity = hitTestMapEntity(world);
    const bestPlace = hoverEntity?.kind === "place" ? hoverEntity.place : null;
    view.hoverEntity = hoverEntity;
    view.hoverWorld = { x: bestPlace ? bestPlace.x : world.x, y: bestPlace ? bestPlace.y : world.y, place: bestPlace };
    el("map-canvas").classList.toggle("clickable-entity", Boolean(hoverEntity));
    renderHoverCard(hoverEntity);
    drawMap();
  });
  pageScope.listen(el("map-canvas"), "pointerleave", () => {
    el("map-canvas").classList.remove("clickable-entity");
    if (view.hoverWorld || view.hoverEntity) {
      view.hoverWorld = null; view.hoverEntity = null; renderHoverCard(null); drawMap();
    }
  });
  pageScope.listen(el("map-canvas"), "pointerdown", (event) => {
    if (!view.pinning || (!view.map && !view.siteMap)) return;
    pinStart = canvasWorld(event);
  });
  pageScope.listen(el("map-canvas"), "pointerup", async (event) => {
    const life = pageScope.capture();
    const start = pinStart, end = canvasWorld(event);
    pinStart = null;
    const robotId = view.pinning;
    if (!robotId || !start) return;
    const dragged = end && Math.hypot(end.px - start.px, end.py - start.py) >= 3;
    const guideRow = (view.guide?.robots || []).find((row) => row.robot_id === robotId);
    const current = guideRow?.pose;
    const yaw = dragged ? Math.atan2(end.y - start.y, end.x - start.x) : (typeof current?.yaw === "number" ? current.yaw : 0);
    view.pinning = null;
    el("map-canvas").classList.add("idle");
    render();
    let led = null;
    try {
      led = pinPrefill(await call("/api/fleet/tracking/identity", { signals: [life.signal] }), guideRow, robotId);
    } catch (error) {
      if (error.name === "AbortError") return;
    }
    if (!life.current()) return;
    const place = led || start;
    const deg = (yaw * 180 / Math.PI).toFixed(0);
    try {
      const pose = await call(`/api/fleet/robots/${encodeURIComponent(robotId)}/map-pin`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ x: place.x, y: place.y, yaw }), signals: [life.signal] });
      if (!life.current()) return;
      log(`${robotId} 운영자 핀 (${place.x.toFixed(2)}, ${place.y.toFixed(2)}) ${deg}° · ${{ LOCALIZED: "확정", DEGRADED: "추정" }[pose?.state] || "위치 모름"}`, "good");
      stepQueuedStarts({ view, pinnedRobotId: robotId, render });
      refreshGuide();
    } catch (err) {
      if (err.name !== "AbortError") log(`${robotId} 위치 찍기 거절 — ${err.message}`, "bad");
    }
  });

  function activateEntityFromMap(entity) {
    if (!entity) return false;
    if (entity.kind === "pinky") {
      view.mapSelection = null; onSelectRobot(entity.id); view.focusAnchorId = entity.id;
      log(`${entity.id} 선택됨 · 우측 패널에서 상태·카메라·명령을 확인합니다`, "good"); render(); return true;
    }
    if (entity.kind === "omx_ai") {
      view.mapSelection = null; view.focusAnchorId = entity.id; onSelectRobot(entity.id);
      if (typeof window !== "undefined" && typeof window.dispatchEvent === "function") {
        window.dispatchEvent(new CustomEvent("rosy:inspect-target", { detail: { targetId: entity.id } }));
      }
      log(`${entity.anchor?.label || entity.id} 선택됨 · 우측 셀 상세 패널 활성화`, "good"); render(); return true;
    }
    if (entity.kind === "place") {
      view.mapSelection = { kind: "place", id: String(entity.id), place: entity.place }; render(); return true;
    }
    return false;
  }

  function normalizeHoverEntity(entity) {
    if (!entity) return null;
    if (entity.kind === "pinky" && entity.id) {
      const guideRow = (view.guide?.robots || []).find((r) => r.robot_id === entity.id);
      if (guideRow) return { ...entity, guideRow };
      const robotObj = (view.robots || []).find((r) => r.robot_id === entity.id);
      const safePose = robotMapPose(robotObj)
        || (entity.guideRow?.pose && (!entity.guideRow.state || robotMapPose(entity.guideRow)) ? entity.guideRow.pose : null)
        || entity.pose || null;
      return { ...entity, guideRow: { robot_id: entity.id, online: robotObj?.online ?? entity.guideRow?.online, pose: safePose } };
    }
    if (entity.kind === "omx_ai" && !entity.anchor && entity.id) {
      const anchors = Array.isArray(view.anchors) ? view.anchors : Array.isArray(view.guide?.anchors) ? view.guide.anchors : [];
      const anchor = anchors.find((a) => a.target_id === entity.id);
      return anchor ? { ...entity, anchor } : null;
    }
    if (entity.kind === "place" && !entity.place && entity.id != null) {
      const place = (view.activeSiteMap?.map?.places || []).find((p) => String(p.id) === String(entity.id));
      return place ? { ...entity, place } : null;
    }
    return entity;
  }

  function handleHoverEntity(entity) {
    const normalized = normalizeHoverEntity(entity);
    view.hoverEntity = normalized;
    const bestPlace = normalized?.kind === "place" ? normalized.place : null;
    view.hoverWorld = bestPlace ? { x: bestPlace.x, y: bestPlace.y, place: bestPlace } : normalized?.world || null;
    renderHoverCard(normalized);
  }

  async function handlePointSelect(point, { toggleSelection = true } = {}) {
    if (!point || !Number.isFinite(point.x) || !Number.isFinite(point.y) || view.pinning) return;
    if (view.selected) { view.mapSelection = null; await commitWorldGoal({ x: point.x, y: point.y }); return; }
    if (toggleSelection) {
      const samePoint = view.mapSelection?.kind === "point" && Math.hypot(view.mapSelection.x - point.x, view.mapSelection.y - point.y) < 0.08;
      view.mapSelection = samePoint ? null : { kind: "point", x: point.x, y: point.y };
    }
    render();
  }

  pageScope.listen(el("map-canvas"), "click", async (event) => {
    const life = pageScope.capture(); life.check();
    if (view.pinning) return;
    const world = (view.map || view.siteMap) ? canvasWorld(event) : null;
    if (world && !view.selected) {
      const hit = hitTestMapEntity(world);
      if (activateEntityFromMap(hit)) return;
      await handlePointSelect(world); life.check(); return;
    }
    if (!view.map && view.siteMap) {
      if (!world) return;
      const hit = hitTestMapEntity(world);
      if (hit && hit.kind !== "place" && activateEntityFromMap(hit)) return;
      if (!view.selected) return;
      const bestPlace = hit?.kind === "place" ? hit.place : null;
      const targetPoint = bestPlace ? { x: bestPlace.x, y: bestPlace.y } : { x: world.x, y: world.y };
      await commitWorldGoal(targetPoint, bestPlace ? `${bestPlace.name || bestPlace.id} (${bestPlace.id})` : "", bestPlace ? String(bestPlace.id) : "");
      life.check(); return;
    }
    if (!view.selected || !view.map) return;
    if (world) {
      const hit = hitTestMapEntity(world);
      if (hit?.kind === "place") {
        await commitWorldGoal({ x: hit.place.x, y: hit.place.y }, `${hit.place.name || hit.place.id} (${hit.place.id})`, String(hit.place.id));
        life.check(); return;
      }
    }
    const canvas = el("map-canvas"), rect = canvas.getBoundingClientRect();
    const scale = Math.min(rect.width / view.map.width, rect.height / view.map.height);
    const drawnW = view.map.width * scale, drawnH = view.map.height * scale;
    const offX = (rect.width - drawnW) / 2, offY = (rect.height - drawnH) / 2;
    const col = ((event.clientX - rect.left - offX) / drawnW) * view.map.width;
    const rowFromTop = ((event.clientY - rect.top - offY) / drawnH) * view.map.height;
    if (col < 0 || rowFromTop < 0 || col >= view.map.width || rowFromTop >= view.map.height) return;
    view.cursor = { col: Math.floor(col), row: view.map.height - 1 - Math.floor(rowFromTop) };
    render(); await commitGoal(view.cursor.col, view.cursor.row); life.check();
  });

  pageScope.listen(el("map-canvas"), "keydown", async (event) => {
    const life = pageScope.capture(); life.check();
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
      event.preventDefault(); await commitGoal(view.cursor.col, view.cursor.row); life.check();
    } else if (event.key === "Escape") {
      event.preventDefault(); const robotId = view.selected; disarmGoal(); render(); focusGoalButton(robotId);
    }
  });

  return { disarmGoal, focusGoalButton, commitWorldGoal, handlePointSelect, handleHoverEntity, renderHoverCard, clearPinStart: () => { pinStart = null; } };
}
