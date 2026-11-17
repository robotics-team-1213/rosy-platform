// 관제 접속: 잠금·해제, 세션 확인, 토큰 입력과 비밀번호 로그인, 개발 접속 모드(D-248·D-473·D-519).
// 토큰은 셸(console.js)의 auth 에 살고, 이 팩토리는 그 상태를 바꾸는 길을 가진다(D-798 3.2).
import { applyRoleToControls, OPERATOR_REASON } from "/console/assets/authorization.js";
import { capabilityReason, motionCommandReason } from "./motion-readiness.js";
import { createPasswordLogin } from "./password-login.js";
import { showConnection, showSession, showSignedOut, stopNotice } from "/console/assets/fleet-header.js";

const MAP_STATION_ARM = { S2: "arm_a", S3: "arm_s", S5: "arm_b" };
const ARM_FALLBACK_TITLES = {
  arm_s: "Cell S · arm_s (S3 공급)",
  arm_a: "Cell A · arm_a (S5 1·3단)",
  arm_b: "Cell B · arm_b (S5 2단)",
};

export function navigateConsoleAlert(target, { el, getInbox, getRoster, render }) {
  if (!target) return;
  const inbox = getInbox?.(), roster = getRoster?.();
  if (target.robotId && (target.kind === "robot" || target.kind === "stuck" || target.kind === "queue" || target.kind === "log")) {
    roster?.openCard(target.robotId);
    render?.();
  }
  if (target.kind === "stuck") {
    inbox?.select("evidence");
    const row = [...(el("inbox-messages")?.children || [])].find((li) => li.dataset.robotId === target.robotId);
    const fold = row?.querySelector("details");
    if (fold) {
      fold.open = true;
      fold.scrollIntoView({ block: "nearest" });
      fold.querySelector("summary")?.focus({ preventScroll: true });
    }
    return;
  }
  if (target.kind === "queue") {
    const row = [...document.querySelectorAll("#critical-list > li, #warning-list > li")].find((li) => li.dataset.key === target.key);
    const btn = row?.querySelector(".queue-row");
    if (btn && btn.getAttribute("aria-expanded") !== "true") btn.click();
    const queueTarget = btn || document.querySelector(".queues-panel");
    if (queueTarget) {
      if (!btn && !queueTarget.hasAttribute("tabindex")) queueTarget.tabIndex = -1;
      queueTarget.scrollIntoView({ block: "nearest" });
      queueTarget.focus({ preventScroll: true });
    }
    return;
  }
  if (target.kind === "incident") {
    inbox?.select("evidence");
    const row = [...(el("incident-list")?.children || [])].find((li) =>
      (target.reportKey && li.dataset.reportKey === target.reportKey)
      || (target.incidentId && li.dataset.incidentId === target.incidentId)
      || (!target.reportKey && !target.incidentId));
    const fold = row?.querySelector("details");
    if (fold) {
      fold.open = true;
      fold.scrollIntoView({ block: "nearest" });
      fold.querySelector("summary")?.focus({ preventScroll: true });
    } else el("context-evidence")?.focus({ preventScroll: true });
    return;
  }
  if (target.kind === "log") {
    inbox?.select("evidence");
    const logPanel = el("log-panel");
    if (logPanel) {
      logPanel.open = true;
      logPanel.scrollIntoView({ block: "nearest" });
      if (!target.robotId) logPanel.querySelector("summary")?.focus({ preventScroll: true });
    }
  }
}

export function buildRosterSig(view, auth, activeRobotId) {
  return JSON.stringify([
    view.stateLoaded, view.stateUnavailable, view.selected, view.pinning,
    auth.locked, auth.role, auth.principal, activeRobotId || "",
    Boolean(view.formation?.active), view.formation?.leader || "",
    view.robots.map((r) => [
      r.robot_id, r.online, r.link, r.link_reason?.message, r.calibration?.label, r.held,
      r.error?.code, r.goal?.x, r.goal?.y, r.queued?.x, r.queued?.y,
      r.state?.mode, r.state?.safety?.estop, r.state?.safety?.source,
      r.state?.battery?.percent, r.state?.battery?.percentage,
      r.state?.battery_status?.shown_percent, r.power_health?.battery?.percent,
      r.state?.localization?.state, r.state?.localization?.pose_frame,
      r.state?.localization?.confidence, r.state?.localization?.candidates_count,
      r.state?.pose?.x, r.state?.pose?.y, r.state?.pose?.yaw,
      r.state?.line_follow?.mode, r.state?.line_follow?.state,
      r.state?.docking?.state, r.state?.power?.mode, r.state?.motors?.length,
      r.line_stuck?.stuck_id, r.line_stuck?.phase, r.capabilities?.runtime?.mode,
      view.robotNames?.[r.robot_id], view.addresses?.[r.robot_id]?.status,
      view.locByRobot?.[r.robot_id] || null, view.autoLocateByRobot?.[r.robot_id] || null,
      Boolean(view.locStopped?.[r.robot_id]), Boolean(view.locDisabled?.[r.robot_id]),
      view.queuedStarts?.[r.robot_id] || null,
      (view.trafficTrips || []).find((t) => t.robot_id === r.robot_id)?.trip_id || "",
    ]),
  ]);
}

export function refreshDiagnostics(el, view, deviceDirectory) {
  const diag = (id, text) => { const node = el(id); if (node) node.textContent = text; };
  diag("diag-state", view.stateUnavailable ? "불가" : `${view.robots.length}대 · ${view.stateLoaded ? "갱신됨" : "대기"}`);
  diag("diag-scanner", deviceDirectory.scannerLost ? "끊김" : "정상");
  const robotErrors = view.robots.filter((r) => r.error)
    .map((r) => `${r.robot_id}: ${r.error.held ? "Fleet 보류" : r.error.reachable === false ? "닿지 않음" : "거부"} ${r.error.code ?? ""}`.trim());
  diag("diag-robots", robotErrors.length ? robotErrors.join(" · ") : "오류 없음");
  diag("diag-vision", el("vision-state")?.textContent ?? "—");
}

export function createMapSelectionBar({
  pageScope, el, view, auth, namedReason, getRoster, disarmGoal, commitWorldGoal, render,
}) {
  let lastBarSig = "";
  function mapSelectedRobotId() {
    const id = view.robotSelection?.get?.() || null;
    if (!id || String(id).startsWith("arm_")) return null;
    return view.robots.some((r) => r.robot_id === id) ? id : null;
  }
  function syncBarBtn(btn, { visible = false, text = null, disabled = false, reason = "", pressed = null } = {}) {
    if (!btn) return;
    btn.hidden = !visible;
    if (!visible) return;
    if (text !== null && btn.textContent !== text) btn.textContent = text;
    btn.disabled = Boolean(disabled);
    if (reason) btn.setAttribute("reason", reason); else btn.removeAttribute("reason");
    if (pressed !== null) btn.setAttribute("aria-pressed", String(Boolean(pressed)));
  }
  function renderBar() {
    const bar = el("map-selection-bar");
    if (!bar) return;
    const sel = view.mapSelection, activeId = view.robotSelection?.get?.() || null;
    if (!sel && !activeId) { lastBarSig = ""; bar.hidden = true; return; }
    const kindTag = el("map-sel-kind"), nameEl = el("map-sel-name"), detailEl = el("map-sel-detail");
    const openBtn = el("map-sel-open-panel"), sendBtn = el("map-sel-send");
    const armBtn = el("map-sel-arm-inspect");
    const stopBtn = el("map-sel-stop"), reasonEl = el("map-sel-reason");
    const operatorAllowed = !auth.locked && auth.role === "operator" && !namedReason();
    const mobileSendReason = (mobileId) => {
      if (!mobileId) return "이동할 모바일 로봇을 먼저 선택하세요";
      if (!operatorAllowed) return auth.locked ? "관제 접속 필요" : OPERATOR_REASON;
      if (view.stateUnavailable) return "Fleet 상태를 확인할 수 없습니다";
      const mobileRobot = view.robots.find((r) => r.robot_id === mobileId);
      if (!mobileRobot?.online) return "로봇이 오프라인입니다";
      if (mobileRobot?.state?.safety?.estop !== false) {
        return mobileRobot?.state?.safety?.estop === true ? "비상정지 상태에서는 이동할 수 없습니다" : "안전 상태를 확인할 수 없습니다";
      }
      return capabilityReason(mobileRobot?.capabilities, "navigation.goal_navigation") || motionCommandReason(view, mobileId, "goal") || "";
    };
    const hideAllActions = () => {
      for (const node of [openBtn, sendBtn, armBtn, stopBtn]) if (node) node.hidden = true;
      if (reasonEl) { reasonEl.hidden = true; reasonEl.textContent = ""; }
    };
    if (sel?.kind === "place" && sel.place) {
      const pl = sel.place, pid = String(pl.id), mobileId = mapSelectedRobotId();
      const linkedArm = MAP_STATION_ARM[pid.toUpperCase()] || null, sendWhy = mobileSendReason(mobileId);
      const sig = `place|${pid}|${pl.name}|${pl.x.toFixed(2)},${pl.y.toFixed(2)}|${mobileId || ""}|${sendWhy}|${linkedArm || ""}`;
      if (sig === lastBarSig && !bar.hidden) return;
      lastBarSig = sig; hideAllActions(); bar.hidden = false;
      kindTag.setAttribute("status", "neutral");
      kindTag.textContent = pid.startsWith("C") ? "충전소" : pid.startsWith("P") ? "분기점" : "장소";
      nameEl.textContent = pl.name && pl.name !== pid ? `${pid} · ${pl.name}` : pid;
      detailEl.textContent = `(${pl.x.toFixed(2)}, ${pl.y.toFixed(2)}) m${mobileId ? ` · 선택 로봇: ${mobileId}` : ""}`;
      syncBarBtn(sendBtn, { visible: true, text: mobileId ? `${mobileId} 여기로 이동` : "여기로 이동", disabled: Boolean(sendWhy), reason: sendWhy });
      if (linkedArm) { armBtn.dataset.armId = linkedArm; syncBarBtn(armBtn, { visible: true, text: `연계 팔 ${linkedArm} 보기` }); }
      if (sendWhy && reasonEl) { reasonEl.textContent = sendWhy; reasonEl.hidden = false; }
      return;
    }
    if (sel?.kind === "point") {
      const mobileId = mapSelectedRobotId(), sendWhy = mobileSendReason(mobileId);
      const sig = `point|${sel.x.toFixed(2)},${sel.y.toFixed(2)}|${mobileId || ""}|${sendWhy}`;
      if (sig === lastBarSig && !bar.hidden) return;
      lastBarSig = sig; hideAllActions(); bar.hidden = false;
      kindTag.setAttribute("status", "neutral");
      kindTag.textContent = "좌표";
      nameEl.textContent = `(${sel.x.toFixed(2)}, ${sel.y.toFixed(2)}) m`;
      detailEl.textContent = mobileId ? `선택 로봇: ${mobileId}` : "로봇을 선택하면 이 위치로 보낼 수 있습니다";
      syncBarBtn(sendBtn, { visible: true, text: mobileId ? `${mobileId} 여기로 이동` : "여기로 이동", disabled: Boolean(sendWhy), reason: sendWhy });
      if (sendWhy && reasonEl) { reasonEl.textContent = sendWhy; reasonEl.hidden = false; }
      return;
    }
    const isArm = String(activeId).startsWith("arm_") && !view.robots.some((r) => r.robot_id === activeId);
    const panelMount = el("robot-panel-mount");
    const showOpenBtn = Boolean(panelMount?.hidden || panelMount?.dataset.robotId !== activeId);
    if (isArm) {
      const anchors = Array.isArray(view.anchors) ? view.anchors : Array.isArray(view.guide?.anchors) ? view.guide.anchors : [];
      const anc = anchors.find((a) => a.target_id === activeId);
      const title = anc?.label || ARM_FALLBACK_TITLES[activeId] || activeId.toUpperCase();
      const detail = anc ? `(${anc.base_x.toFixed(2)}, ${anc.base_y.toFixed(2)}) m · ${anc.joints_summary || "관절 정보 대기"}` : "상세 제어 패널에서 셀 상태·이송 제안을 확인합니다";
      const sig = `arm|${activeId}|${title}|${detail}|${showOpenBtn}`;
      if (sig === lastBarSig && !bar.hidden) return;
      lastBarSig = sig; hideAllActions(); bar.hidden = false;
      kindTag.setAttribute("status", "neutral"); kindTag.textContent = "로봇팔";
      nameEl.textContent = title; detailEl.textContent = detail;
      syncBarBtn(openBtn, { visible: showOpenBtn });
      return;
    }
    const robot = view.robots.find((r) => r.robot_id === activeId);
    const guideRow = (view.guide?.robots || []).find((r) => r.robot_id === activeId);
    const pose = view.stateUnavailable ? null : (guideRow?.pose || robot?.pose || robot?.state?.pose);
    const poseText = view.stateUnavailable ? "Fleet 상태를 확인할 수 없습니다"
      : pose && Number.isFinite(pose.x) && Number.isFinite(pose.y)
        ? `(${pose.x.toFixed(2)}, ${pose.y.toFixed(2)}) m${Number.isFinite(pose.yaw) ? ` · ${Math.round((pose.yaw * 180) / Math.PI)}°` : ""}`
        : "지도 좌표 미확인 · 지도 클릭 또는 도크로 위치 확인";
    const disconnected = view.stateUnavailable || robot?.online === false;
    const sig = `mobile|${activeId}|${!disconnected}|${view.stateUnavailable}|${poseText}|${showOpenBtn}`;
    if (sig === lastBarSig && !bar.hidden) return;
    lastBarSig = sig; hideAllActions(); bar.hidden = false;
    kindTag.setAttribute("status", disconnected ? "warn" : "neutral");
    kindTag.textContent = disconnected ? "연결 끊김" : "모바일";
    nameEl.textContent = view.robotNames?.[activeId] ? `${view.robotNames[activeId]} (${activeId})` : activeId;
    detailEl.textContent = poseText;
    syncBarBtn(openBtn, { visible: showOpenBtn });
    syncBarBtn(stopBtn, { visible: showOpenBtn });  // 패널이 열려 있으면 정지는 패널 안 한 곳
  }
  if (el("map-selection-bar")) {
    pageScope.listen(el("map-sel-clear"), "click", () => {
      if (view.mapSelection) view.mapSelection = null;
      else { if (view.selected) disarmGoal("선택 해제로 목표 지정 취소"); view.robotSelection?.set?.(null, { source: "map-bar" }); }
      render();
    });
    pageScope.listen(el("map-sel-open-panel"), "click", () => { const id = view.robotSelection?.get?.(); if (id) getRoster()?.openCard(id); });
    pageScope.listen(el("map-sel-arm-inspect"), "click", () => {
      const armId = el("map-sel-arm-inspect")?.dataset?.armId;
      if (!armId) return;
      view.mapSelection = null; getRoster()?.openCard(armId); render();
    });
    pageScope.listen(el("map-sel-send"), "click", () => {
      const mobileId = mapSelectedRobotId(), sel = view.mapSelection;
      if (!mobileId || !sel) return;
      if (sel.kind === "place" && sel.place) {
        const pl = sel.place, label = pl.name && pl.name !== pl.id ? `${pl.name} (${pl.id})` : String(pl.id);
        void commitWorldGoal({ x: pl.x, y: pl.y }, label, String(pl.id), mobileId);
      } else if (sel.kind === "point") void commitWorldGoal({ x: sel.x, y: sel.y }, "", "", mobileId);
    });
    pageScope.listen(el("map-sel-stop"), "click", () => {
      const selectedId = view.robotSelection?.get?.();
      const id = mapSelectedRobotId() || (selectedId && !String(selectedId).startsWith("arm_") ? selectedId : null);
      if (id) void getRoster()?.stopRobot(id);
    });
  }
  return renderBar;
}

export function createConsoleAuth({ pageScope, el, view, auth, call, fleetClient, render, operatorControls, assistant,
  confirmedAction, connectionView, workView, incidents, visionView, trackingView, mapView, formation,
  dispatchGate, discoveryGate, cancelAllNotice, resetRobotApps, refreshState, refreshRobotApps,
  refreshDispatchControl, refreshDiscovery }) {
  function markLocked(reason = "auth") {
    assistant?.setIdentity({locked:true});
    resetRobotApps();
    confirmedAction.cancel();
    stopNotice();
    cancelAllNotice();
    const firstLock = !auth.locked;
    auth.locked = true;
    workView.reset();
    auth.role = null;
    incidents.reset();
    showSignedOut({refused: reason === "auth"});
    applyRoleToControls(null, operatorControls());
    const pill = el("online-pill");
    pill.textContent = "접속 전";
    pill.setAttribute("status", "neutral");
    pill.dataset.locked = "true"; // 해제 때 문구가 아니라 이 표시로 잠금 pill을 알아본다
    if (auth.token && reason === "auth") el("console-token").setAttribute("aria-invalid", "true");
    const canvas = el("map-canvas"); canvas.getContext("2d").clearRect(0, 0, canvas.width, canvas.height);
    // D-493 — 잠기면 지도 칸의 큰 영상과 크게 보기 선택을 같이 내린다. 지난 프레임을 살아 있는 듯 두지 않는다.
    el("map-birdseye").hidden = true;
    delete el("map-stage").dataset.view;
    el("birdseye-toggle").setAttribute("aria-pressed", "false");
    connectionView.show(reason, auth.token);
    if (firstLock) {
      Object.assign(view, {robots: [], robotPeers: [], map: null, siteMap: null, sightings: [], cameraTracking: {robots: [], unknown: []},
        stateLoaded: false, stateUnavailable: false, selected: null, pinning: null, cursor: null, formation: null, signals: {},
        traffic: null, trafficTrips: [], endedTrips: [], trafficClock: null, trafficLoaded: false});
      visionView.reset(); visionView.refreshSources(); trackingView.reset();
    }
    render();
    // Connection metadata changes the badge, never the authenticated identity.
    if (firstLock && reason === "auth") connectionMode();
    // Offer human login once per lock.
    if (firstLock && reason === "auth") loginForm.refresh(true);
  }

  function markUnlocked() {
    auth.locked = false;
    connectionView.hide();
    el("console-token").removeAttribute("aria-invalid");
  }

  async function refreshAuthorization(credentialChange = false) {
    const life = pageScope.capture();
    life.check();
    // 로그인·토큰 저장마다 꺼진 기능을 한 번씩 다시 묻는다.
    dispatchGate.reset();
    discoveryGate.reset();
    mapView.resetPolling();
    try {
      const identity = await call("/api/fleet/session");
      life.check();
      if (auth.role !== identity.role || auth.principal !== identity.principal_id) {
        resetRobotApps(); confirmedAction.cancel(); workView.reset();
      }
      auth.role = identity.role;
      auth.principal = identity.principal_id;
      assistant?.setIdentity(auth);
      showSession(identity, {credentialChange});
      // The session already proves the token: unlock now. The state gather can take seconds
      // when a robot times out, and must not hold the operator's controls locked behind it.
      const pill = el("online-pill");
      if (pill.dataset.locked === "true") {
        delete pill.dataset.locked;
        pill.textContent = "상태 확인 중";
        pill.setAttribute("status", "neutral");
      }
      applyRoleToControls(auth.role, operatorControls());
      loginForm.refresh(false);
      render();
      // Independent panels refresh side by side; one slow source does not delay the rest.
      // The map too: a token issued after a lock must not wait for the next 5 s map poll (field check 2026-10-10).
      // Abort any pre-session in-flight site-map fetch started before /api/fleet/session resolved.
      mapView.resetPolling();
      await Promise.allSettled([
        incidents.refresh(),
        workView.refresh(),
        mapView.refresh(),
        refreshState(),
        refreshRobotApps(),
        refreshDispatchControl(),
        refreshDiscovery(),
        formation.refreshFormation(),
      ]);
      life.check();
      render();
    } catch (_err) {
      if (_err.name === "AbortError") return;
      if (!auth.locked) markLocked(_err.status === 401 || _err.code === 'PASSWORD_CHANGE_REQUIRED' ? "auth" : "connection");
    }
  }

  // 토큰 입력 — Enter 와 버튼 모두 저장한다 (form 이 아니라 keydown 이다).
  el("console-token").value = auth.token;
  function saveToken() {
    useToken(el("console-token").value.trim(), true);
  }

  function useToken(token, credentialChange = false) {
    workView.reset();
    stopNotice();
    cancelAllNotice();
    pageScope.invalidate();
    auth.token = token;
    // 새 토큰은 직접 재시도한다 — 잠금 플래그가 있으면 직접 호출도 건너뛰므로 먼저 푼다.
    auth.role = null;
    applyRoleToControls(null, operatorControls());
    incidents.reset();
    if (auth.token) {
      sessionStorage.setItem("rosy-console-token", auth.token);
    } else {
      sessionStorage.removeItem("rosy-console-token");
    }
    visionView.reset();
    trackingView.reset();
    trackingView.refresh();
    refreshAuthorization(credentialChange);
    visionView.refreshSources();
  }
  pageScope.listen(el("token-save"), "click", saveToken);
  // D-519 — login and logout change the cookie; drop any token so the cookie (or the lock) decides.
  const loginForm = createPasswordLogin(el("password-login"), {onChange: () => {
    el("console-token").value = "";
    useToken("", true);
  }});
  pageScope.listen(el("console-token"), "keydown", (event) => {
    if (event.key === "Enter") saveToken();
  });

  // D-473 — development connection mode. The badge is on only while the server says development;
  // paired, 404 (an older Fleet) or an error leaves the token field as the way in.
  async function connectionMode() {
    try {
      const info = await fleetClient("/api/fleet/auth/connection");
      showConnection(info);
      return info?.mode === "development";
    } catch (_err) {
      return false;
    }
  }

  return { markLocked, markUnlocked, refreshAuthorization, connectionMode };
}
