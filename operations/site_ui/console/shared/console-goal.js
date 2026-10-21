// 지도 위 목표 지정과 운영자 핀(D-201·D-224·D-593). 캔버스 찍기·방향키 커서·확인 뒤 보내기를 가진다.
// 셸(console.js)이 그리기(render)와 지도 뷰를 건넨다(D-798 3.2).
import { motionCommandReason } from "./motion-readiness.js";
import { pinPrefill } from "./localization-badge.js";

export function createConsoleGoal({ pageScope, el, view, auth, inbox, log, call, render, confirmedAction, namedReason,
  toWorld, refreshGuide, queuedReason }) {
  function disarmGoal(reason) {
    view.selected = null;
    view.cursor = null;
    const canvas = el("map-canvas");
    canvas.classList.add("idle");
    canvas.tabIndex = -1;
    log(reason, "bad");
  }

  // D-224 — 예외 문법의 키보드 어휘(§7.3 "keyboard-first" 의 실현).
  // ↑/↓ 로 로스터를 순회하고, Enter 로 그 로봇의 작업 패널을 선택한다.
  // Escape 으로 선택을 해소한다. 입력 컨트롤에 있을 땐 간섭하지 않는다.
  // 포커스 링은 표면 전역 :focus-visible 규약이 그린다.
  pageScope.listen(document, "keydown", (event) => {
    if (event.defaultPrevented || event.target.closest("input, select, textarea, button, ui-button, a, canvas, summary")) return;
    const cards = [...document.querySelectorAll("#roster article")];
    if (!cards.length) return;
    const active = document.activeElement;
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      inbox.select("status");
      const idx = cards.indexOf(active);
      const next = idx < 0
        ? cards[event.key === "ArrowDown" ? 0 : cards.length - 1]
        : cards[(idx + (event.key === "ArrowDown" ? 1 : -1) + cards.length) % cards.length];
      next.focus();
    } else if (event.key === "Enter" && cards.includes(active)) {
      const choose = active.querySelector("ui-button[data-select-robot-id]");
      if (choose && !choose.disabled) {
        event.preventDefault();
        choose.click();
      }
    } else if (event.key === "Escape" && view.selected) {
      const robotId = view.selected;
      disarmGoal("목표 지정 취소");
      render();
      focusGoalButton(robotId);
    }
  });

  async function commitGoal(col, row) {
    const life = pageScope.capture();
    life.check();
    if (!view.selected || !view.map) return;
    const selectedRobot = view.robots.find((robot) => robot.robot_id === view.selected);
    if (view.stateUnavailable || auth.role !== "operator" || namedReason() || motionCommandReason(view, view.selected, 'goal') ||
        !selectedRobot?.online || selectedRobot.state?.safety?.estop !== false) {
      disarmGoal("안전·연결·권한 상태를 확인할 수 없어 목표 지정 취소");
      render();
      return;
    }
    const point = toWorld(view.map, col, row);
    const robotId = view.selected;
    const mapSnapshot = JSON.stringify([view.map.map_id, view.map.width, view.map.height, view.map.resolution, view.map.origin]);
    await confirmedAction.run({message: `${robotId}에게 목표 (${point.x.toFixed(2)}, ${point.y.toFixed(2)}) m를 보낼까요?`, opener: el("map-canvas"),
      eligible: () => !view.stateUnavailable && view.selected === robotId && view.robots.some(robot => robot.robot_id === robotId && robot.online && robot.state?.safety?.estop === false)
        && !motionCommandReason(view, robotId, 'goal')
        && mapSnapshot === JSON.stringify([view.map?.map_id, view.map?.width, view.map?.height, view.map?.resolution, view.map?.origin]),
      request: async owner => {
    view.selected = null;
    view.cursor = null;
    const canvas = el("map-canvas");
    canvas.classList.add("idle");
    canvas.tabIndex = -1;
    render();
    focusGoalButton(robotId);
      const result = await call(`/api/fleet/robots/${encodeURIComponent(robotId)}/goal`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "Idempotency-Key": crypto.randomUUID() },
        body: JSON.stringify({ x: point.x, y: point.y, yaw: 0 }),
        signals: [owner.signal],
      });
      if (!owner.current()) return;
      const task = result && result.task ? result.task : null;
      if (task && task.status === "QUEUED") {
        view.pendingTasks[robotId] = task;
        const why = task.reason || result.reason || "READY";
        const blockedBy = task.waiting_on?.length ? ` · ${task.waiting_on.join(", ")}` : "";
        const position = task.queue_position ? `#${task.queue_position}` : "순번 대기";
        log(`${robotId} task ${task.task_id} QUEUED · ${position} · ${why}${blockedBy} · 취소 가능`, "good");
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
      const where = `(${point.x.toFixed(2)}, ${point.y.toFixed(2)})`;
      if (receipt && receipt.queued) {
        log(`${robotId} → ${where} ${queuedReason(result)}`,
            receipt.reason === "NO_YIELD_SPACE" ? "bad" : "");
      } else {
        log(`${robotId} → ${where} 미션 하달`, "good");
      }
    }, onError: err => log(`${robotId} 미션 거절 — ${err.message}`, "bad")});
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
    // D-596 amendment (b): an LED-confirmed blob is the place; the press and drag only set the heading.
    let led = null;
    try {
      led = pinPrefill(await call("/api/fleet/tracking/identity", { signals: [life.signal] }), guideRow, robotId);
    } catch (error) {
      if (error.name === "AbortError") return;
    }
    if (!life.current()) return;
    const place = led || start;
    const deg = (yaw * 180 / Math.PI).toFixed(0);
    const where = led ? "LED로 확인된 자리" : "지도 위치";
    await confirmedAction.run({message: `${robotId}의 ${where}를 (${place.x.toFixed(2)}, ${place.y.toFixed(2)}) m, 방향 ${deg}°로 찍을까요? 로봇에는 아무것도 보내지 않습니다.`,
      opener: el("map-canvas"), eligible: () => !view.stateUnavailable && !namedReason(),
      request: async (owner) => {
        const pose = await call(`/api/fleet/robots/${encodeURIComponent(robotId)}/map-pin`, {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ x: place.x, y: place.y, yaw }), signals: [owner.signal] });
        if (!owner.current() || !life.current()) return;
        log(`${robotId} 운영자 핀 (${place.x.toFixed(2)}, ${place.y.toFixed(2)}) ${deg}° · ${{ LOCALIZED: "확정", DEGRADED: "추정" }[pose?.state] || "위치 모름"}`, "good");
        refreshGuide();
      }, onError: (err) => log(`${robotId} 위치 찍기 거절 — ${err.message}`, "bad")});
  });

  pageScope.listen(el("map-canvas"), "click", async (event) => {
    const life = pageScope.capture();
    life.check();
    if (!view.selected || !view.map) return;
    const canvas = el("map-canvas");
    const rect = canvas.getBoundingClientRect();
    // D-201 — 캔버스는 object-fit: contain 으로 그려진다. 레터박스(빈 여백)를
    // 제외한 그려진 영역 안에서만 셀 좌표가 성립한다.
    const scale = Math.min(rect.width / view.map.width, rect.height / view.map.height);
    const drawnW = view.map.width * scale;
    const drawnH = view.map.height * scale;
    const offX = (rect.width - drawnW) / 2;
    const offY = (rect.height - drawnH) / 2;
    const col = ((event.clientX - rect.left - offX) / drawnW) * view.map.width;
    const rowFromTop = ((event.clientY - rect.top - offY) / drawnH) * view.map.height;
    if (col < 0 || rowFromTop < 0 || col >= view.map.width || rowFromTop >= view.map.height) {
      return; // 여백을 찍은 것 — 목표가 아니다.
    }
    view.cursor = { col: Math.floor(col), row: view.map.height - 1 - Math.floor(rowFromTop) };
    render();
    await commitGoal(view.cursor.col, view.cursor.row);
    life.check();
  });

  pageScope.listen(el("map-canvas"), "keydown", async (event) => {
    const life = pageScope.capture();
    life.check();
    if (view.pinning && event.key === "Escape") {  // D-593: 위치 찍기 취소
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
      view.selected = null;
      view.cursor = null;
      const canvas = el("map-canvas");
      canvas.classList.add("idle");
      canvas.tabIndex = -1;
      render();
      focusGoalButton(robotId);
    }
  });

  return { disarmGoal, focusGoalButton, clearPinStart: () => { pinStart = null; } };
}
