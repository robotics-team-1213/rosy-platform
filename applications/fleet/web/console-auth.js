// 관제 접속: 잠금·해제, 세션 확인, 토큰 입력과 비밀번호 로그인, 개발 접속 모드(D-248·D-473·D-519).
// 토큰은 셸(console.js)의 auth 에 살고, 이 팩토리는 그 상태를 바꾸는 길을 가진다(D-798 3.2).
import { applyRoleToControls } from "/console/assets/authorization.js";
import { issueDevelopmentSession } from "/console/assets/development-auth.js";
import { createPasswordLogin } from "./password-login.js";
import { showSession, showSignedOut, stopNotice } from "/console/assets/fleet-header.js";

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
        stateLoaded: false, stateUnavailable: false, focusRobot: null, selected: null, pinning: null, cursor: null, formation: null, signals: {},
        traffic: null, trafficTrips: [], endedTrips: [], trafficClock: null});
      visionView.reset(); visionView.refreshSources(); trackingView.reset();
    }
    render();
    // D-473 4 — the first 401 of a lock asks once whether this console is in development mode.
    if (firstLock && reason === "auth") renewDevelopmentSession();
    // D-519 6 — paired consoles offer 아이디·비밀번호 once per lock.
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
      el("development-badge").hidden = info?.mode !== "development";
      return info?.mode === "development";
    } catch (_err) {
      return false;
    }
  }

  // Called on the first 401 of a lock only, so a refused or rate-limited issue (403/429) is one
  // request, not a loop. useToken() invalidates in-flight polls so their stale 401s are dropped.
  async function renewDevelopmentSession() {
    if (!(await connectionMode())) return;
    let token;
    try {
      token = await issueDevelopmentSession(fleetClient);  // at most one per minute per page
    } catch (_err) {
      return;
    }
    if (token) useToken(token);
  }

  return { markLocked, markUnlocked, refreshAuthorization, connectionMode };
}
