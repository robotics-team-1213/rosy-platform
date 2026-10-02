// OMX-AI Gazebo practice (D-390, D-411 B). The target's rosy.controls/1 descriptor decides the
// widgets; every input submits one bounded trajectory goal and the next only after it settles.
import {readControls, fallbackOmxControls} from "../controls.js";
import {composeControls} from "./compose.js";
import {mountJointJog} from "../widgets/joint_jog.js";

const TERMINAL = ["SUCCEEDED", "REJECTED", "CANCELED", "UNKNOWN_HOLD"];
const GOAL_POLL_MS = 250;   // a settled goal is seen before the 1 s heartbeat (sequential jog)

export function mountArm(root, target, driver) {
  const tokenKey = `rosy.pilot.omx-sim.${location.origin}`;
  let token = sessionStorage.getItem(tokenKey) || "";
  let seat = "";
  let state = null;
  let active = "";
  let disposed = false;
  let refreshing = false;
  let recording = null;
  let recordingError = "";
  let previewUrl = "";
  let connectionGeneration = 0;
  let pollTimer = null;
  const listeners = new Set();

  root.innerHTML = `<header class="arm-head"><h2>OMX-AI Gazebo 연습</h2>
      <p>시뮬레이션 전용 · 실제 로봇과 연결되지 않습니다.</p></header>
    <div data-sim-pair><label>화면에 표시된 페어링 코드 <input class="ui-field" data-sim-code autocomplete="off"></label>
      <ui-button kind="primary" type="button" data-sim-connect>연결</ui-button></div>
    <p data-sim-status role="status" aria-live="polite">연결 대기</p>
    <div class="arm-console" data-sim-controls hidden>
      <section class="arm-view" aria-label="작업 공간">
        <figure class="arm-camera" ${target.recording ? "" : "hidden"}>
          <img data-sim-camera alt="Gazebo 작업 공간" width="320" height="240" hidden>
          <figcaption data-sim-camera-status role="status">영상 확인 중</figcaption>
        </figure>
        <pre data-sim-readback aria-label="관절 readback"></pre>
      </section>
      <div class="arm-controls" data-sim-widgets></div>
      <div class="arm-actions">
        <ui-button kind="quiet" type="button" data-sim-cancel disabled reason="진행 중 명령 없음"
          aria-describedby="arm-cancel-help">진행 중 명령 취소</ui-button>
        <p class="arm-hint" id="arm-cancel-help">취소하면 시뮬레이션 팔이 보류(HOLD) 상태가 됩니다. 평소에는 손을 떼면 됩니다.</p>
      </div>
      <section data-sim-record-panel ${target.recording ? "" : "hidden"}>
        <h3>시연 기록</h3>
        <p>영상·관절 상태·수락된 조작 목표를 기록합니다. 결과는 직접 선택하세요.</p>
        <label>연습 과제 <input class="ui-field" data-sim-task maxlength="300" placeholder="예: 물체를 향해 관절을 이동"></label>
        <ui-button kind="primary" type="button" data-sim-record-start>기록 시작</ui-button>
        <label>과제 결과 <select class="ui-field" data-sim-outcome><option value="unspecified">결과 선택</option>
          <option value="success">성공</option><option value="failure">실패</option></select></label>
        <ui-button kind="quiet" type="button" data-sim-record-stop disabled>기록 종료</ui-button>
        <p data-sim-record-status role="status">기록 대기</p>
      </section>
    </div>`;
  const $ = (selector) => root.querySelector(selector);
  const controls = $("[data-sim-controls]");
  const status = $("[data-sim-status]");
  const cancel = $("[data-sim-cancel]");

  function notify(update) {
    cancel.disabled = !active;
    if (active) cancel.removeAttribute("reason"); else cancel.setAttribute("reason", "진행 중 명령 없음");
    for (const listener of [...listeners]) listener(update);
  }
  async function request(path, options = {}) {
    return driver.request(path, {token, ...options});
  }
  function showError(error) {
    status.textContent = `조작 보류 · ${error.message}`;
    controls.querySelectorAll("[data-sim-widgets] ui-button, [data-sim-widgets] input").forEach((button) => {
      button.disabled = true;
      button.setAttribute("reason", "조작 보류");
    });
    notify({state: null, settled: null, error});
  }
  function schedulePoll() {
    clearTimeout(pollTimer);
    pollTimer = active && !disposed ? setTimeout(() => refresh({goalOnly: true}), GOAL_POLL_MS) : null;
  }
  async function connect() {
    if (disposed || document.hidden) return;
    const generation = ++connectionGeneration;
    try {
      if (!token) {
        const code = $("[data-sim-code]").value.trim();
        const paired = await request("/pair", {method: "POST", body: JSON.stringify({code})});
        token = paired.token;
        sessionStorage.setItem(tokenKey, token);
      }
      await request("/whoami");
      if (disposed || document.hidden || generation !== connectionGeneration) return;
      seat = (await request("/seat", {method: "POST"})).seat_id;
      if (disposed || document.hidden || generation !== connectionGeneration) { release(); return; }
      $("[data-sim-pair]").hidden = true;
      controls.hidden = false;
      await refresh();
    } catch (error) {
      token = "";
      sessionStorage.removeItem(tokenKey);
      showError(error);
    }
  }
  async function refresh({goalOnly = false} = {}) {
    if (!seat || disposed || refreshing) return;
    refreshing = true;
    let failed = false;
    try {
      state = await request("/state");
      if (disposed) return;
      let settled = null;
      if (active) {
        const goal = await request(`/goals/${encodeURIComponent(active)}`);
        if (disposed) return;
        status.textContent = `명령 ${goal.state}${goal.reason ? ` · ${goal.reason}` : ""}`;
        if (TERMINAL.includes(goal.state)) { settled = {commandId: active, state: goal.state}; active = ""; }
      } else status.textContent = state.ready ? "조작 가능" : `조작 보류 · ${state.owner_state}`;
      $("[data-sim-readback]").textContent = JSON.stringify({sequence: state.state_sequence,
        age_ms: state.joint_age_ms, joints: state.positions, goal: active || null}, null, 2);
      notify({state, settled, error: null});
      if (target.recording && !goalOnly) await refreshRecording();
    } catch (error) { failed = true; state = null; showError(error); }
    finally {
      refreshing = false;
      // A goal submitted while this refresh ran is polled from here (its own refresh was skipped).
      if (!failed) schedulePoll();
    }
  }
  async function refreshRecording() {
    recording = await request("/recordings");
    if (disposed) return;
    $("[data-sim-record-status]").textContent = recordingError || `${recording.status} · ${recording.frame_count} 프레임${recording.issues.length ? ` · ${recording.issues.join(", ")}` : ""}`;
    $("[data-sim-record-start]").disabled = recording.status === "recording" || !state?.ready;
    $("[data-sim-record-stop]").disabled = recording.status !== "recording";
    const camera = await request("/camera");
    if (disposed) return;
    $("[data-sim-camera-status]").textContent = camera.fresh ? `영상 수신 · ${camera.age_ms} ms` : "영상 없음 또는 오래됨 · 기록 시작 보류";
    $("[data-sim-record-start]").disabled ||= !camera.fresh;
    $("[data-sim-camera]").hidden = !camera.fresh;
    if (camera.fresh) {
      const blob = await request("/camera/frame", {format: "blob"});
      if (disposed) return;
      if (previewUrl) URL.revokeObjectURL(previewUrl);
      previewUrl = URL.createObjectURL(blob);
      $("[data-sim-camera]").src = previewUrl;
    }
  }
  $("[data-sim-record-start]").addEventListener("click", async () => {
    try {
      recording = await request("/recordings", {method: "POST", body: JSON.stringify({seat_id: seat, task: $("[data-sim-task]").value.trim()})});
      recordingError = "";
      await refresh();
    } catch (error) {
      recordingError = `기록 시작 실패 · ${error.message}`;
      $("[data-sim-record-status]").textContent = recordingError;
    }
  });
  $("[data-sim-record-stop]").addEventListener("click", async () => {
    if (recording?.status !== "recording") return;
    try {
      recording = await request(`/recordings/${encodeURIComponent(recording.episode_id)}/stop`, {method: "POST", body: JSON.stringify({seat_id: seat, outcome: $("[data-sim-outcome]").value})});
      recordingError = "";
      await refresh();
    } catch (error) {
      recordingError = `기록 종료 실패 · ${error.message}`;
      $("[data-sim-record-status]").textContent = recordingError;
    }
  });
  function release() {
    connectionGeneration++;
    const released = seat;
    seat = "";
    state = null;
    if (released) request(`/seat/${encodeURIComponent(released)}`, {method: "DELETE"}).catch(() => {});
  }
  function visibilityChanged() {
    if (document.hidden) {
      release();
      showError(new Error("화면이 숨겨져 조작권을 반납했습니다. 다시 연결하세요."));
      $("[data-sim-pair]").hidden = false;
    }
  }
  document.addEventListener("visibilitychange", visibilityChanged);

  // What widgets see: the latest readback, one goal at a time, and terminal states.
  const session = {
    target,
    state: () => state,
    busy: () => Boolean(active),
    onUpdate(listener) { listeners.add(listener); return () => listeners.delete(listener); },
    // Resolves to the accepted command id, or null when nothing was sent or it was refused.
    async submitJog(name, delta, durationS = 0.4) {
      if (!seat || !state?.ready || active || !state.positions || !(name in state.positions)) return null;
      try {
        const goal = await request("/goals", {method: "POST", body: JSON.stringify({
          instance_id: target.instance_id, seat_id: seat, request_id: crypto.randomUUID(),
          joint: name, delta_rad: delta, duration_s: durationS,
          state_sequence: state.state_sequence, expires_at_ms: Date.now() + 5000,
        })});
        if (disposed) return null;
        active = goal.command_id;
        status.textContent = `명령 ${goal.state}`;
        notify({state, settled: null, error: null});
        if (!refreshing) schedulePoll();
        return active;
      } catch (error) { showError(error); return null; }
    },
    async submitGripper() { return null; },   // D-411 C
  };
  const items = readControls(target.controls) ?? fallbackOmxControls(target);
  const disposeWidgets = composeControls($("[data-sim-widgets]"), items, {joint_jog: mountJointJog}, session);

  $("[data-sim-connect]").addEventListener("click", connect);
  cancel.addEventListener("click", async () => {
    if (!active) return;
    try { await request(`/goals/${encodeURIComponent(active)}/cancel?seat_id=${encodeURIComponent(seat)}`, {method: "POST"}); await refresh(); }
    catch (error) { showError(error); }
  });
  const interval = setInterval(async () => {
    if (!seat || disposed || document.hidden) return;
    try { await request(`/seat/${encodeURIComponent(seat)}`, {method: "PUT"}); await refresh(); }
    catch (error) { seat = ""; showError(error); }
  }, 1000);
  if (token) connect();
  return () => {
    disposed = true;
    clearInterval(interval);
    clearTimeout(pollTimer);
    disposeWidgets();
    listeners.clear();
    document.removeEventListener("visibilitychange", visibilityChanged);
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    release();
  };
}
