// 관제 화면의 읽기 갱신: 발행 제어 띠와 재허가, 현장 경로, Fleet 상태 폴링, 전체 주행 취소.
// 폴링 주기는 셸(console.js)이 쥐고 이 팩토리의 함수를 부른다(D-798 3.2).
import { namedOperatorReason } from "/console/assets/authorization.js";
import { noteLink, showFleet } from "/console/assets/fleet-header.js";
import { fleetRow, proxyRow, visionRow, sitePathSummary } from "./site-path.js";

export function createConsoleRefresh({ pageScope, el, view, auth, call, fleetApi, log, render, confirmedAction,
  dispatchGate, resetRobotApps, disarmGoal, openCard }) {
  // A chooser deep link only reveals/focuses an existing card; it never arms a goal.
  let requestedRobotFocus = new URLSearchParams(location.search).get("robot");

  function cancelAllNotice(message = "", details = false) {
    const result = el("cancel-all-result"), link = el("cancel-all-details");
    result.textContent = message;
    result.hidden = !message;
    link.hidden = !details;
  }

  async function refreshDispatchControl(life = pageScope.capture()) {
    life.check();
    const title = el("dispatch-control-title");
    const detail = el("dispatch-control-detail");
    const rearm = el("dispatch-rearm");
    if (!dispatchGate.due()) return view.dispatchControl;
    try {
      const state = await call("/api/fleet/dispatch-control", {signals: [life.signal]});
      life.check();
      dispatchGate.ok();
      view.dispatchControl = state;
      // D-493 — 띠의 글은 알릴 상태가 있을 때만 보인다(styles.css가 data-state로 접는다).
      el("dispatch-control").dataset.state = state.dispatch_enabled ? "enabled"
        : state.reason === "PROCESS_RESTARTED" ? "restarted" : "latched";
      if (state.dispatch_enabled) {
        title.textContent = "발행 허용";
        detail.textContent = `세대 ${state.generation} · 대기 작업 ${state.queued_tasks}개`;
      } else if (state.reason === "PROCESS_RESTARTED") {
        title.textContent = "재시작 뒤 발행 대기";
        detail.textContent = `세대 ${state.generation} · 대기 작업 ${state.queued_tasks}개 · 미확정 동작 ${state.unresolved_actions}개`;
      } else {
        title.textContent = "정지 래치로 발행 차단";
        detail.textContent = `세대 ${state.generation} · 대기 작업 ${state.queued_tasks}개 · 미확정 동작 ${state.unresolved_actions}개`;
      }
      rearm.hidden = !(auth.role === "operator" && !state.dispatch_enabled);
      // D-540 9: 재허가는 대기 작업을 다시 움직이므로 이름 있는 운영자만.
      const rearmNamed = namedOperatorReason(auth.role, auth.principal);
      rearm.disabled = auth.locked || !state.rearm_available || Boolean(rearmNamed);
      if (rearm.disabled) rearm.setAttribute("reason", auth.locked ? "관제 토큰 필요" : rearmNamed || "재허가 조건 미충족");
      else rearm.removeAttribute("reason");
      return state;
    } catch (err) {
      if (err.name === "AbortError") return;
      if (auth.locked) return;
      view.dispatchControl = null;
      const absent = dispatchGate.fail(err.status, err.code) === "absent";
      el("dispatch-control").dataset.state = absent ? "absent" : "error";
      if (absent) {
        // 작업 대기열이 없는 Fleet — 발행 래치 자체가 없다. 오류가 아니다.
        title.textContent = "발행 제어 미설정";
        detail.textContent = "이 Fleet에는 작업 대기열이 설정되지 않았습니다.";
      } else {
        title.textContent = "발행 상태를 확인할 수 없음";
        detail.textContent = "상태 확인에 실패해 재허가를 사용할 수 없습니다.";
      }
      rearm.hidden = true;
      rearm.disabled = true;
      rearm.setAttribute("reason", "발행 상태 확인 불가");
      return null;
    }
  }

  pageScope.listen(el("dispatch-rearm"), "click", async () => {
    const state = view.dispatchControl;
    await confirmedAction.run({message: `세대 ${state?.generation}의 대기 발행을 재허가할까요?`, opener: el("dispatch-rearm"),
      eligible: () => state?.rearm_available && view.dispatchControl?.rearm_available && state.generation === view.dispatchControl.generation,
      request: async owner => {
      await call("/api/fleet/dispatch/rearm", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ expected_generation: state.generation }),
        signals: [owner.signal],
      });
      if (!owner.current()) return;
      log("대기 작업 발행을 재허가했습니다.", "good");
      await refreshDispatchControl(owner);
    }, onError: err => log(`발행 재허가 거부: ${err.message}`, "bad")});
  });

  const pathSample = { proxy: null, fleet: null, vision: null };
  let statePollInFlight = false;

  function paintSitePath() {
    const list = el("site-path-list");
    const rows = [proxyRow(pathSample.proxy), fleetRow(pathSample.fleet), visionRow(pathSample.vision)];
    const summary = sitePathSummary(rows);
    const summaryNode = el("site-path-summary");
    if (summaryNode.textContent !== summary) summaryNode.textContent = summary;
    summaryNode.dataset.kind = rows.find((row) => row.kind === "crit")?.kind
      || rows.find((row) => row.kind === "warn")?.kind || "good";
    list.replaceChildren(...rows.map((row) => {
      const item = document.createElement("li");
      const name = document.createElement("b");
      name.textContent = row.name;
      const word = document.createElement("ui-tag");
      // ui-tag's nominal status is active. kind "good" is that word; "good" itself has no rule.
      word.setAttribute("status", row.kind === "good" ? "active" : row.kind);
      word.textContent = row.word;
      item.append(name, word);
      return item;
    }));
  }

  async function refreshHealthz() {
    const life = pageScope.capture();
    try {
      const response = await fetch("/healthz", { cache: "no-store", signal: life.signal });
      const body = await response.json();
      if (!life.current()) return;
      pathSample.proxy = { finished: true, status: response.status, body };
    } catch (err) {
      if (err.name === "AbortError") return;
      pathSample.proxy = { finished: false };
    }
    paintSitePath();
  }
  pageScope.onDispose(() => {
    resetRobotApps();
    statePollInFlight = false;
    view.focusRobot = null;
    view.pinning = null;
    view.selected = null;
    view.cursor = null;
    document.querySelectorAll("dialog[open]").forEach(dialog => dialog.close("cancel"));
  });
  async function refreshState() {
    const life = pageScope.capture();
    life.check();
    // A signed-out console still asks Fleet's open endpoint, so the link word does not drift to 지연.
    if (auth.locked) return void fleetApi("/api/fleet/auth/connection", {signals: [life.signal]}).then(() => noteLink(), noteLink);
    if (statePollInFlight) return;
    statePollInFlight = true;
    let fleetAnswered = false;
    const motorHealthRequestedAtMs = Date.now();
    try {
      const snapshot = await call("/api/fleet/state");
      life.check();
      pathSample.fleet = { finished: true, status: 200 };
      fleetAnswered = true;
      paintSitePath();
      const motorHealthReceivedAtMs = Date.now();
      view.robots = snapshot.robots.map(robot => ({...robot, motorHealthRequestedAtMs, motorHealthReceivedAtMs}));
      view.receivedAtMs = Date.now();  // D-493: 큐 신선도는 받은 뒤 흐른 시간을 더한다
      if (requestedRobotFocus) openCard(requestedRobotFocus);
      view.stateUnavailable = false;
      view.stateLoaded = true;
      if (view.selected) {
        const selectedRobot = view.robots.find((robot) => robot.robot_id === view.selected);
        if (!selectedRobot?.online || selectedRobot.state?.safety?.estop !== false) {
          disarmGoal("안전·연결 상태가 바뀌어 목표 지정 취소");
        }
      }
      view.signals = snapshot.signals || {};
      showFleet(snapshot.fleet, snapshot.robots);
      render();
      if (requestedRobotFocus) {
        const card = [...el("roster").querySelectorAll("article")]
          .find(node => node.dataset.robotId === requestedRobotFocus);
        if (card) card.focus();
        requestedRobotFocus = null;
      }
    } catch (err) {
      if (err.name === "AbortError") return;
      if (!fleetAnswered) {
        pathSample.fleet = typeof err.status === "number"
          ? { finished: true, status: err.status }
          : { finished: false };
        paintSitePath();
      }
      // D-248: 잠금 pill(토큰 필요)을 서버 없음으로 덮지 않는다 — 401의 이유를 남긴다.
      if (auth.locked) return;
      view.stateUnavailable = true;
      if (view.selected) disarmGoal("Fleet 상태를 확인할 수 없어 목표 지정 취소");
      render();
      const pill = el("online-pill");
      pill.textContent = "Fleet 서버 없음";
      pill.setAttribute("status", "crit");
    } finally {
      if (life.current()) statePollInFlight = false;
    }
  }

  // D-421 — 래치 없는 전체 주행 취소. 응답은 CORE 응답 수이지 물리 정지가 아니다(D-298).
  const CANCEL_ALL_RESULT = { failed: "실패", unreachable: "응답 없음" };
  const CANCEL_ALL_STEP = { swarm: "대형 추종", navigation: "내비게이션", line_follow: "차선 추종" };
  // D-540 6 (user decision 2026-10-10): a stop — no confirm, any operator, no latch; the line says it was sent.
  pageScope.listen(el("cancel-all"), "click", async () => {
    if (auth.locked) return;
    const life = pageScope.capture();
    cancelAllNotice(`전체 주행 취소를 보냈습니다 · ${view.robots.length}대 · 응답 기다리는 중`);
    try {
      const result = await call("/api/fleet/cancel-all", { method: "POST", signals: [life.signal] });
      if (!life.current()) return;
      // 0/0 은 성공이 아니다 — 취소할 로봇이 없었다.
      const allAnswered = result.total > 0 && result.cancelled === result.total;
      const summary = result.total === 0 ? "주행 취소 대상 로봇 없음 — 등록된 로봇을 확인하세요"
        : `주행 취소 요청 응답: ${result.cancelled}/${result.total} · 물리 정지 미확인`;
      cancelAllNotice(result.total === 0 ? summary : `전체 주행 취소를 보냈습니다 · ${result.total}대 · ${summary}`,
        result.total > 0 && !allAnswered);
      log(summary, allAnswered ? undefined : "bad");
      result.robots.filter((r) => r.result !== "cancelled").forEach((r) => {
        const steps = Object.entries(r.steps).filter(([, step]) => !step.ok).map(([name, step]) =>
          step.error?.sent === false && name === "line_follow" ? "주소 미확인 — 차선 추종 끄기 미전송"
            : `${CANCEL_ALL_STEP[name] || name} ${step.error?.code || "—"}`);
        log(`  ${r.robot_id} 주행 취소 ${CANCEL_ALL_RESULT[r.result] || r.result} — ${steps.join(" · ")}`, "bad");
      });
      const awaiting = result.robots.reduce((n, r) => n + r.tasks.awaiting_core_result.length, 0);
      log(result.tasks.error ? "대기 작업 취소 실패 — 작업 저장소를 확인하세요"
        : `대기 작업 ${result.tasks.canceled.length}개 취소 · 로봇 취소 확인 대기 작업 ${awaiting}개`,
      result.tasks.error ? "bad" : undefined);
      // CORE 가 취소를 확인하면 그 로봇은 다시 배정되고, 확인이 없으면 작업은 대조가 필요하다.
      if (awaiting) log("  확인 대기 작업: 로봇이 취소를 알리면 다시 배정, 알리지 않으면 대조 필요", "bad");
      await refreshDispatchControl(life);
    } catch (err) {
      if (err.name === "AbortError" || !life.current()) return;
      cancelAllNotice(err.status >= 500 || !err.status
        ? "주행 취소 결과 확인 불가 — Fleet 연결과 로봇 상태를 다시 확인하세요."
        : `주행 취소 요청 거절 — ${err.message}`);
      log(`전체 주행 취소 실패 — ${err.message}`, "bad");
    }
  });

  return { cancelAllNotice, refreshDispatchControl, pathSample, paintSitePath, refreshHealthz, refreshState };
}
