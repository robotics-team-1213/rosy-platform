// 명렬 카드 + 큐 채우기 (Fleet 분해 3). 로봇 한 대의 상태·증거·조작과
// 주의/개입 큐를 그린다. formation/signals 팩토리와 같은 모양이다.

export function createRoster({ el, view, log, call, render, streamEvidence }) {
  function needsAttention(robot) {
    const state = robot.state;
    const evidence = streamEvidence(view.formation, robot.robot_id);
    return view.stateUnavailable || !robot.online || !state || state.safety?.estop !== false
      || state.hitl_requested === true || Boolean(state.capabilities_degraded?.length)
      || state.navigation === "FAILED" || Boolean(robot.queued) || Boolean(robot.yielding)
      || (evidence !== null && evidence.cls !== "");
  }
  function navTag(state) {
    const nav = state && state.navigation;
    if (!nav) return { text: "—", cls: "" };
    if (nav === "NAVIGATING") return { text: nav, cls: "nav" };
    if (nav === "ARRIVED") return { text: nav, cls: "ok" };
    if (nav === "FAILED") return { text: nav, cls: "crit" };
    return { text: nav, cls: "" };
  }

  // 대기에는 세 가지 이유가 있고, 운영자가 할 일이 저마다 다르다. "대기 중" 한 마디로
  // 뭉뜽그리면, 손대야 풀리는 상황에서도 사람이 저절로 풀리기를 기다린다.
  function queuedReason(queued) {
    const who = queued.blocked_by;
    if (queued.reason === "NO_YIELD_SPACE") {
      return `${who} 가 길을 막았는데 비켜설 자리가 없습니다 — 맵이 좁습니다. `
        + `${who} 를 직접 다른 곳으로 보내 주세요`;
    }
    if (queued.reason === "YIELDING") {
      return `${who} 가 비켜서기를 기다리는 중 — 물러나면 자동 출발합니다`;
    }
    if (queued.reason === "YIELDED") {
      return `${who} 가 지나가기를 기다리는 중 — 지나가면 제 미션으로 돌아갑니다`;
    }
    return `${who} 경로와 겹쳐 대기 중 — 앞이 비면 자동 출발합니다`;
  }

  function card(robot, index) {
    const node = document.createElement("article");
    node.className = `robot s${index % view.colors.length}`;
    node.dataset.robotId = robot.robot_id;
    if (!view.stateUnavailable && !robot.online) node.classList.add("offline");
    if (view.selected === robot.robot_id) node.classList.add("selected");
    // D-224 — ↑/↓ 순회의 착지점. tabindex -1 은 프로그램 포커스만 허용한다
    // (탭 순서를 더럽히지 않는다).
    node.tabIndex = -1;

    const state = view.stateUnavailable ? {} : (robot.state || {});
    const pose = state.pose;
    const nav = navTag(state);
    const estop = state.safety?.estop;
    const safetyLabel = !robot.online ? "—" : view.stateUnavailable ? "정보 없음" : estop === true ? "E-STOP"
      : estop === false ? "OK" : "정보 없음";
    const goalSafetyReason = view.stateUnavailable
      ? "Fleet 상태를 확인할 수 없어 목표를 보낼 수 없습니다."
      : estop === true
      ? "비상정지가 활성화되어 목표를 보낼 수 없습니다."
      : estop !== false && robot.online
        ? "안전 상태를 확인할 수 없어 목표를 보낼 수 없습니다." : "";

    const head = document.createElement("div");
    head.className = "robot-head";
    const robotName = document.createElement("b");
    robotName.textContent = robot.robot_id;
    const spacer = document.createElement("span");
    spacer.className = "spacer";
    head.append(robotName, spacer);
    const mode = document.createElement("span");
    mode.className = "tag";
    mode.textContent = view.stateUnavailable ? "상태 확인 불가" : robot.online ? (state.mode || "—") : "OFFLINE";
    if (view.stateUnavailable || !robot.online) mode.classList.add("crit");
    head.appendChild(mode);
    const navEl = document.createElement("span");
    const blocked = !view.stateUnavailable && robot.queued && robot.queued.reason === "NO_YIELD_SPACE";
    navEl.className = `tag ${blocked ? "crit" : robot.queued ? "warn" : nav.cls}`;
    // 비켜서는 중인 로봇은 "주행 중"이 맞다 — 다만 제 미션을 가는 것이 아니라서 따로 적는다.
    navEl.textContent = view.stateUnavailable ? "—" : robot.yielding ? "비켜서는 중" : robot.queued ? "대기" : nav.text;
    head.appendChild(navEl);
    const evidence = view.stateUnavailable ? null : streamEvidence(view.formation, robot.robot_id);
    if (evidence) {
      // 릴레이 건강은 증거다(D-72). fresh 는 아무것도 붙지 않는다 — 붙는 것은 문제뿐이다.
      const evEl = document.createElement("span");
      evEl.className = `tag ${evidence.cls}`;
      evEl.textContent = evidence.text;
      head.appendChild(evEl);
    }
    node.appendChild(head);

    const facts = document.createElement("div");
    facts.className = "facts";
    const battery = state.battery && typeof state.battery.percent === "number"
      ? `${Math.round(state.battery.percent)}%` : "—";
    const rows = [
      ["POSE", pose ? `${pose.x.toFixed(2)}, ${pose.y.toFixed(2)}` : "—"],
      ["YAW", pose ? `${(pose.yaw * 180 / Math.PI).toFixed(0)}°` : "—"],
      ["BATTERY", battery],
      ["SAFETY", safetyLabel],
    ];
    rows.forEach(([label, value]) => {
      const cellEl = document.createElement("div");
      const labelEl = document.createElement("span");
      labelEl.textContent = label;
      const valueEl = document.createElement("strong");
      valueEl.textContent = value;
      cellEl.append(labelEl, valueEl);
      facts.appendChild(cellEl);
    });
    node.appendChild(facts);

    if (!view.stateUnavailable && robot.yielding) {
      // 운영자가 보내지 않은 좌표로 로봇이 움직인다. 이유를 적지 않으면 오작동으로 읽힌다.
      const why = document.createElement("p");
      why.className = "hint";
      why.textContent = `${robot.yielding.for} 가 지나가도록 비켜서는 중 — `
        + `(${robot.yielding.bay.x.toFixed(2)}, ${robot.yielding.bay.y.toFixed(2)}) 로 물러납니다`;
      node.appendChild(why);
    }

    if (!view.stateUnavailable && robot.queued) {
      // 왜 안 가는지 화면이 말하지 않으면 운영자는 미션이 사라졌다고 읽는다.
      const why = document.createElement("p");
      why.className = "hint";
      why.textContent = queuedReason(robot.queued);
      node.appendChild(why);
    }

    if (!view.stateUnavailable && !robot.online && robot.error) {
      const why = document.createElement("p");
      why.className = "hint";
      why.textContent = robot.error.reachable
        ? `로봇이 거절: ${robot.error.code}` : `닿지 않음: ${robot.error.code}`;
      node.appendChild(why);
    }

    const actions = document.createElement("div");
    actions.className = "robot-actions";
    const aim = document.createElement("ui-button");
    aim.setAttribute("kind", "quiet");
    aim.type = "button";
    aim.dataset.goalRobotId = robot.robot_id;
    aim.textContent = view.selected === robot.robot_id ? "지도를 찍으세요" : "목표 지정";
    if (view.selected === robot.robot_id) aim.classList.add("arming");
    aim.disabled = view.stateUnavailable || !robot.online || !view.map || estop !== false;
    aim.addEventListener("click", () => {
      view.selected = view.selected === robot.robot_id ? null : robot.robot_id;
      view.cursor = view.selected && view.map
        ? { col: Math.floor(view.map.width / 2), row: Math.floor(view.map.height / 2) }
        : null;
      const canvas = el("map-canvas");
      canvas.classList.toggle("idle", view.selected === null);
      canvas.tabIndex = view.selected ? 0 : -1;
      render();
      if (view.selected) canvas.focus({preventScroll: true});
      else [...document.querySelectorAll("#roster ui-button[data-goal-robot-id]")]
        .find(button => button.dataset.goalRobotId === robot.robot_id)?.focus({preventScroll: true});
    });
    const cancel = document.createElement("ui-button");
    cancel.setAttribute("kind", "quiet");
    cancel.type = "button";
    cancel.textContent = "취소";
    cancel.disabled = view.stateUnavailable || !robot.online;
    cancel.addEventListener("click", async () => {
      try {
        const pending = view.pendingTasks[robot.robot_id];
        if (pending) {
          const readback = await call(`/api/fleet/tasks/${encodeURIComponent(pending.task_id)}`);
          if (readback.task?.status === "QUEUED") {
            await call(`/api/fleet/tasks/${encodeURIComponent(pending.task_id)}/cancel`, { method: "POST" });
            delete view.pendingTasks[robot.robot_id];
            render();
            log(`${robot.robot_id} task ${pending.task_id} QUEUED 취소`, "good");
            return;
          }
          delete view.pendingTasks[robot.robot_id];
        }
        await call(`/api/fleet/robots/${encodeURIComponent(robot.robot_id)}/cancel`, { method: "POST" });
        log(`${robot.robot_id} 항법 취소`, "good");
      } catch (err) {
        log(`${robot.robot_id} 취소 실패 — ${err.message}`, "bad");
      }
    });
    actions.append(aim, cancel);
    node.appendChild(actions);
    if (goalSafetyReason) {
      const why = document.createElement("p");
      why.className = "hint";
      why.textContent = goalSafetyReason;
      node.appendChild(why);
    }
    return node;
  }

  // D-252: 큐 머리는 ui-triage. <b>는 범주+개수, <small>은 이름들이다. 행은 그대로 둔다.
  function setTriageHead(id, label, list) {
    const head = el(id);
    if (!head) return;
    const names = [...list.querySelectorAll("li b")].map((b) => b.textContent);
    head.querySelector("b").textContent = `${label} ${names.length}`;
    head.querySelector("small").textContent = names.join(" · ");
  }

  function fillQueues() {
    // ADR-1000: Populate Queues
    const warnList = el("warning-list");
    const critList = el("critical-list");
    warnList.innerHTML = "";
    critList.innerHTML = "";

    let warningCount = 0;
    let criticalCount = 0;

    for (const r of view.stateUnavailable ? [] : view.robots) {
      if (!r.state) continue;
      if (r.state.hitl_requested) {
        // 개입 요청은 이름으로 알린다(Law 0). 원격 조종은 이 서버에 없는
        // 능력이다 — 못 하는 조작을 모의 버튼으로 걸어 두면 경보가 거짓말을
        // 한다(D-218, F-20). 진짜 개입은 그 로봇의 대시보드에서 일어난다.
        const li = document.createElement("li");
        const name = document.createElement("b");
        name.textContent = r.robot_id;
        li.append(name, document.createTextNode(": 개입 필요 — 로봇 화면에서 확인"));
        critList.appendChild(li);
        criticalCount++;
      } else if (r.state.capabilities_degraded && r.state.capabilities_degraded.length > 0) {
        const li = document.createElement("li");
        const name = document.createElement("b");
        name.textContent = r.robot_id;
        li.append(name, document.createTextNode(`: 성능 저하 [${r.state.capabilities_degraded.join(", ")}]`));
        warnList.appendChild(li);
        warningCount++;
      }
    }
    setTriageHead("warning-head", "주의 요망", warnList);
    setTriageHead("critical-head", "최우선 개입 요망", critList);

    // ADR-1000 & UX Law 1: Hide empty queues to prevent alarm colors in normal state.
    // CSP `style-src 'self'` 는 style 속성을 막으므로 hidden 속성으로 토글한다
    // (D-201 회차 계측에서 style.display 토글이 실서버에서는 무시됨을 확인).
    warnList.parentElement.hidden = warningCount === 0;
    critList.parentElement.hidden = criticalCount === 0;
    document.querySelector(".queues-panel").hidden = (warningCount + criticalCount) === 0;
  }

  return { card, fillQueues, queuedReason, needsAttention };
}
