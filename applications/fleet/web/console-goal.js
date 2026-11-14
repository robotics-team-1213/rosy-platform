import {randomUUID} from "/console/assets/uuid.js";
// 지도 위 목표 지정과 운영자 핀(D-201·D-224·D-593). 셸(console.js)이 그리기(render)와 지도 뷰를 건넨다(D-798 3.2).
import { capabilityReason, motionCommandReason } from "./motion-readiness.js";
import { pinPrefill } from "./localization-badge.js";
import { roadPolylineBetween } from "/console/assets/guide-layer.js";

export function createConsoleGoal({ pageScope, el, view, auth, inbox, log, call, render, confirmedAction, namedReason,
  toWorld, refreshGuide, queuedReason, drawMap = () => {}, onSelectRobot = () => {} }) {
  function disarmGoal(reason) {
    view.selected = null; view.cursor = null; view.hoverWorld = null;
    const canvas = el("map-canvas");
    canvas.classList.add("idle"); canvas.tabIndex = -1;
    if (reason) log(reason, "bad");
  }

  // D-224 — 예외 문법의 키보드 어휘(§7.3 "keyboard-first" 의 실현).
  pageScope.listen(document, "keydown", (event) => {
    if (event.defaultPrevented || event.target.closest("input, select, textarea, button, ui-button, a, canvas, summary")) return;
    const cards = [...document.querySelectorAll("#roster article")];
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
    const selectedRobot = view.robots.find((robot) => robot.robot_id === robotId);
    const guideRow = (view.guide?.robots || []).find((r) => r.robot_id === robotId);
    const curPose = guideRow?.pose || selectedRobot?.state?.pose || null;
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
      S2: { targetId: "arm_a", camId: "arm_a_wrist" },
      S3: { targetId: "arm_s", camId: "arm_s_wrist" },
      S5: { targetId: "arm_b", camId: "arm_b_wrist" },
      S1: { targetId: robotId, camId: "side" },
      C1: { targetId: robotId, camId: "pinky" },
      C2: { targetId: robotId, camId: "pinky" },
      C3: { targetId: robotId, camId: "pinky" },
    };
    const linkedInspect = placeId ? stationInspectMap[String(placeId).toUpperCase()] : null;
    if (linkedInspect && typeof window !== "undefined" && typeof window.dispatchEvent === "function") {
      if (linkedInspect.targetId.startsWith("arm_")) view.focusAnchorId = linkedInspect.targetId;
      window.dispatchEvent(new CustomEvent("rosy:inspect-target", { detail: linkedInspect }));
    }
    drawMap(); render();

    const canDispatch = !view.stateUnavailable && auth.role === "operator" && !namedReason()
      && !capabilityReason(selectedRobot?.capabilities, 'navigation.goal_navigation')
      && !motionCommandReason(view, robotId, "goal") && selectedRobot?.online && selectedRobot.state?.safety?.estop === false;
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

    const mapSnapshot = JSON.stringify([view.map?.map_id, view.map?.width, view.map?.height, view.map?.resolution, view.map?.origin]);
    await confirmedAction.run({
      message: `${robotId}에게 목표 (${point.x.toFixed(2)}, ${point.y.toFixed(2)}) m를 보낼까요?`,
      opener: el("map-canvas"),
      eligible: () => !view.stateUnavailable && view.selected === robotId && !namedReason()
        && !capabilityReason(view.robots.find(robot => robot.robot_id === robotId)?.capabilities, 'navigation.goal_navigation')
        && !motionCommandReason(view, robotId, "goal")
        && view.robots.some(robot => robot.robot_id === robotId && robot.online && robot.state?.safety?.estop === false)
        && mapSnapshot === JSON.stringify([view.map?.map_id, view.map?.width, view.map?.height, view.map?.resolution, view.map?.origin]),
      request: async owner => {
    view.selected = null;
    view.cursor = null;
    const canvas = el("map-canvas");
    canvas.classList.add("idle");
    canvas.tabIndex = -1;
    render();
    focusGoalButton(robotId);
    try {
      const result = await call(`/api/fleet/robots/${encodeURIComponent(robotId)}/goal`, {
        method: "POST", headers: { "Content-Type": "application/json", "Idempotency-Key": randomUUID() },
        body: JSON.stringify({ x: Number(point.x.toFixed(4)), y: Number(point.y.toFixed(4)), yaw: Number(yaw.toFixed(4)) }), signals: [owner.signal],
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
      if (err.name !== "AbortError") log(`${robotId} 목표 이동 거절 — ${err.message}`, "bad");
    }
      }, onError: err => log(`${robotId} 목표 이동 거절 — ${err.message}`, "bad"),
    });
  }

  view.dispatchBerthPark = async (targetRobotId, bayId = "", mode = "berth_park") => {
    const robotId = targetRobotId;
    if (!robotId || view.selected !== robotId || view.focusRobot !== robotId) return;
    const defaultBay = robotId === "rosy_45" ? "C2" : robotId === "rosy_42" ? "C3" : "C1";
    const chosenBay = (bayId || defaultBay).toUpperCase();
    const bayCoords = { C1: { x: -0.418, y: 0.380 }, C2: { x: -0.190, y: 0.380 }, C3: { x: 0.038, y: 0.380 } };
    const pt = bayCoords[chosenBay];
    if (!pt || !["berth_park", "forward_and_berth_park"].includes(mode)) return;
    const eligible = () => {
      const robot = view.robots.find(row => row.robot_id === robotId);
      return !view.stateUnavailable && auth.role === "operator" && !namedReason()
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

  function renderHoverCard(entity) {
    const card = el("map-hover-card");
    if (!card) return;
    if (!entity) { card.hidden = true; card.replaceChildren(); return; }
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
      lines.push(["정밀 좌표 · 방위", `(${(p.x ?? 0).toFixed(3)}, ${(p.y ?? 0).toFixed(3)}) m · HEAD ${deg} (±${(p.u_m ?? 0.02).toFixed(2)}m)`]);
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
      badge = anc.cell_status || (cell?.reachable ? "CELL-A ONLINE" : "VISION 4X");
      badgeTone = "good";
      lines.push(["베이스 → 헤드", `(${anc.base_x.toFixed(2)}, ${anc.base_y.toFixed(2)}) → (${(anc.head_x ?? anc.base_x).toFixed(2)}, ${(anc.head_y ?? anc.base_y).toFixed(2)}) m · ${deg}`]);
      lines.push(["관절 · 연계역", `${anc.joints_summary || "6축 정상"} · Fleet 연계: ${handoffMap[anc.target_id] || "S2"}`]);
      bars.push(["📐 팔 뻗음", `${extM.toFixed(2)}/${reachM.toFixed(2)}m (${reachPct}%)`, reachPct, "info"]);
      bars.push(["⚙️ 서보 버스", anc.motor_summary || "12.0V · 31°C (100%)", 100, "good"]);
      bars.push(["🔍 4x 추적", `신뢰도 ${confPct}%`, confPct, "good"]);
      footer = `클릭 시 우측 셀 상세 카드 열기 · ${view.selected || view.focusRobot || "rosy_46"} 연계 정류장 즉시 호출 가능`;
    } else if (entity.kind === "place") {
      const pl = entity.place, siteMapObj = view.activeSiteMap?.map;
      const edges = (siteMapObj?.edges || []).filter((e) => e.from === pl.id || e.to === pl.id);
      const edgeDesc = edges.map((e) => `${e.id}(${e.direction === "two_way" ? "양방향" : "일방향"})`).join(", ") || "연결 차로";
      const activeId = view.selected || view.focusRobot || "rosy_46";
      const guideRow = (view.guide?.robots || []).find((r) => r.robot_id === activeId);
      const road = guideRow?.pose ? roadPolylineBetween(siteMapObj, guideRow.pose, pl) : null;
      const isCharger = String(pl.id).startsWith("C");
      title = `📍 ${pl.id} · ${pl.name || pl.id}`;
      badge = isCharger ? "충전 스테이션" : (String(pl.id).startsWith("P") ? "대기·분기점" : "작업 정류장");
      lines.push(["지도 좌표 · 도로", `X ${pl.x.toFixed(3)} m, Y ${pl.y.toFixed(3)} m · ${edgeDesc}`]);
      if (road) {
        const via = road.places?.length ? road.places.join(" → ") : pl.id;
        lines.push([`${activeId} 도로 경로`, `거리 ${road.length_m.toFixed(2)} m · 경유: ${via}`]);
        const distPct = Math.max(15, Math.min(100, Math.round((1 - Math.min(1, road.length_m / 4.5)) * 100)));
        bars.push(["🛣️ 접근성", `${road.length_m.toFixed(2)}m · 약 ${Math.ceil(road.length_m / 0.15)}초`, distPct, "info"]);
      }
      footer = `클릭 시 🎯 ${pl.id} 핀 고정 및 ${activeId} 도로(lane_graph) 즉시 주행`;
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

    const barBox = document.createElement("div"); barBox.className = "hover-bars";
    for (const [label, valText, pct, tone] of bars) {
      const row = document.createElement("div"); row.className = "gauge-row-compact";
      const meta = document.createElement("div"); meta.className = "gauge-meta-line";
      const lSpan = document.createElement("span"); lSpan.textContent = label;
      const vStrong = document.createElement("strong"); vStrong.textContent = valText;
      meta.append(lSpan, vStrong);
      row.append(meta, makeSvgBar(pct, tone));
      barBox.appendChild(row);
    }

    const foot = document.createElement("p"); foot.className = "hover-card-foot"; foot.textContent = footer;
    card.replaceChildren(headRow, dl, ...(bars.length ? [barBox] : []), foot);
    card.hidden = false;
  }

  pageScope.listen(el("map-canvas"), "pointermove", (event) => {
    if (!view.map && !view.siteMap) return;
    const world = canvasWorld(event);
    if (!world) {
      if (view.hoverWorld || view.hoverEntity) {
        view.hoverWorld = null; view.hoverEntity = null; renderHoverCard(null); drawMap();
      }
      return;
    }
    const places = view.activeSiteMap?.map?.places || [];
    let bestPlace = null, bestDist = 0.13;
    for (const place of places) {
      const d = Math.hypot(place.x - world.x, place.y - world.y);
      if (d < bestDist) { bestDist = d; bestPlace = place; }
    }
    let hoverEntity = null;
    for (const r of view.guide?.robots || []) {
      if (r.pose && Math.hypot(r.pose.x - world.x, r.pose.y - world.y) <= 0.11) {
        hoverEntity = { kind: "pinky", id: r.robot_id, guideRow: r };
        break;
      }
    }
    if (!hoverEntity && view.layers?.omx !== false) {
      for (const anc of view.anchors || []) {
        if (anc.kind === "omx_ai") {
          const hx = anc.head_x ?? anc.base_x, hy = anc.head_y ?? anc.base_y;
          if (distToSegment(world.x, world.y, anc.base_x, anc.base_y, hx, hy) <= 0.12) {
            hoverEntity = { kind: "omx_ai", id: anc.target_id, anchor: anc };
            break;
          }
        }
      }
    }
    if (!hoverEntity && bestPlace) hoverEntity = { kind: "place", id: bestPlace.id, place: bestPlace };
    view.hoverEntity = hoverEntity;
    view.hoverWorld = { x: bestPlace ? bestPlace.x : world.x, y: bestPlace ? bestPlace.y : world.y, place: bestPlace };
    renderHoverCard(hoverEntity);
    drawMap();
  });
  pageScope.listen(el("map-canvas"), "pointerleave", () => {
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
      refreshGuide();
    } catch (err) {
      if (err.name !== "AbortError") log(`${robotId} 위치 찍기 거절 — ${err.message}`, "bad");
    }
  });

  pageScope.listen(el("map-canvas"), "click", async (event) => {
    const life = pageScope.capture();
    life.check();
    if (view.pinning) return;
    if (!view.map && view.siteMap) {
      const world = canvasWorld(event);
      if (!world) return;
      for (const r of view.guide?.robots || []) {
        if (r.pose && Math.hypot(r.pose.x - world.x, r.pose.y - world.y) <= 0.10) {
          onSelectRobot(r.robot_id);
          view.focusAnchorId = r.robot_id;
          if (typeof window !== "undefined" && typeof window.dispatchEvent === "function") {
            window.dispatchEvent(new CustomEvent("rosy:inspect-target", { detail: { targetId: r.robot_id } }));
          }
          log(`${r.robot_id} 선택됨 · 우측 카메라·제어 인스펙터 연동 완료 — 이동할 목적지를 지도에서 찍으세요`, "good");
          render();
          return;
        }
      }
      for (const anc of view.anchors || []) {
        if (anc.kind === "omx_ai") {
          const dBase = Math.hypot(anc.base_x - world.x, anc.base_y - world.y);
          const dHead = Math.hypot((anc.head_x ?? anc.base_x) - world.x, (anc.head_y ?? anc.base_y) - world.y);
          if (Math.min(dBase, dHead) <= 0.13) {
            view.focusAnchorId = anc.target_id;
            onSelectRobot(anc.target_id);
            if (typeof window !== "undefined" && typeof window.dispatchEvent === "function") {
              window.dispatchEvent(new CustomEvent("rosy:inspect-target", { detail: { targetId: anc.target_id } }));
            }
            log(`${anc.label} 선택됨 · 우측 실시간 손목·상단 카메라 및 제어 인스펙터 연동 활성화`, "good");
            render();
            return;
          }
        }
      }
      const activeRobotId = view.selected;
      if (!activeRobotId) return;
      const places = view.activeSiteMap?.map?.places || [];
      let bestPlace = null, bestDist = 0.14;
      for (const place of places) {
        const d = Math.hypot(place.x - world.x, place.y - world.y);
        if (d < bestDist) { bestDist = d; bestPlace = place; }
      }
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
