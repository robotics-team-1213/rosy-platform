// OMX-AI Gazebo practice (D-390, D-411 B). The target's rosy.controls/1 descriptor decides the
// widgets; every input submits one bounded trajectory goal and the next only after it settles.
import {readControls, fallbackOmxControls, gripperPercent, gripperStateLabel} from "../controls.js";
import {homeStep} from "../arm-stick.js";
import {composeControls} from "./compose.js";
import {mountJointJog} from "../widgets/joint_jog.js";
import {mountGripper} from "../widgets/gripper.js";

const TERMINAL = ["SUCCEEDED", "REJECTED", "CANCELED", "UNKNOWN_HOLD"];
const GOAL_POLL_MS = 250;   // a settled goal is seen before the 1 s heartbeat (sequential jog)
const STALE_MS = 500;       // joint readback older than this is shown as stale
const RECORD_LABEL = {idle: "기록 대기", recording: "녹화 중", complete: "기록 완료", incomplete: "기록 불완전"};
const OUTCOME_LABEL = {success: "성공", failure: "실패 사례", unspecified: "결과 없음"};
const deg = (rad) => `${(rad * 180 / Math.PI).toFixed(1)}°`;
const clock = (ms) => { const s = Math.floor(ms / 1000); return `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`; };
function stored(name, key, value) {
  try {
    const storage = window[name];   // the getter itself throws when site data is blocked
    if (value === undefined) return storage.getItem(key);
    if (value === null) storage.removeItem(key); else storage.setItem(key, value);
  } catch { /* private window or blocked storage: the screen works without it */ }
  return null;
}

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
  let pollWanted = false;
  let submitting = false;
  let homing = false;
  let homeNote = "";
  let recordStartedAt = 0;
  const listeners = new Set();
  const homeKey = `rosy.pilot.omx-sim.home.${target.instance_id ?? "sim"}`;
  const taskKey = `rosy.pilot.omx-sim.task.${location.origin}`;
  // The machine's demonstration profile owns the start pose; older servers fall back to this tablet.
  const profileHome = target.start_pose ?? null;
  let home = profileHome;
  if (!home) try { home = JSON.parse(stored("localStorage", homeKey) ?? "null"); } catch { home = null; }

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
        <section class="arm-sensors" aria-labelledby="arm-sensors-head">
          <div class="arm-sensors-head"><h3 id="arm-sensors-head">센서 값</h3>
            <span class="arm-chip" data-sim-sensor-age data-state="stale">수신 대기</span></div>
          <div class="ui-table-scroll"><table class="arm-sensor-table">
            <thead><tr><th scope="col">관절</th><th scope="col">현재 각도</th><th scope="col">움직일 수 있는 범위 안 위치</th><th scope="col">시작 자세까지</th></tr></thead>
            <tbody data-sim-sensors></tbody></table></div>
          <details class="arm-state-details"><summary>원본 값 (JSON)</summary>
            <pre data-sim-readback aria-label="관절 상태 원본"></pre>
          </details>
        </section>
      </section>
      <div class="arm-controls" data-sim-widgets></div>
      <div class="arm-actions">
        <ui-button kind="quiet" type="button" data-sim-cancel disabled reason="진행 중 명령 없음"
          aria-describedby="arm-cancel-help">진행 중 명령 취소</ui-button>
        <p class="arm-hint" id="arm-cancel-help">취소하면 시뮬레이션 팔이 보류(HOLD) 상태가 됩니다. 평소에는 손을 떼면 됩니다.</p>
      </div>
      <section class="arm-record" data-sim-record-panel aria-labelledby="arm-record-head">
        <h3 id="arm-record-head">시연 기록 순서</h3>
        <p class="arm-hint">시작 자세로 맞추고, 과제를 적고, 녹화한 뒤 결과를 골라 끝냅니다. 영상·관절 값·수락된 조작 목표가 함께 남습니다.</p>
        <ol class="arm-steps">
          <li data-sim-step="home"><h4>시작 자세</h4>
            <p class="arm-hint" data-sim-home-status role="status">저장된 시작 자세가 없습니다. 팔을 원하는 자세로 옮긴 뒤 저장하세요.</p>
            <p class="arm-hint" data-sim-home-source ${profileHome ? "" : "hidden"}>이 기계의 시연 프로파일에 정해진 시작 자세입니다.</p>
            <div class="arm-step-actions">
              <ui-button kind="quiet" type="button" data-sim-home-save ${profileHome ? "hidden" : ""}>현재 자세를 시작 자세로 저장</ui-button>
              <ui-button kind="primary" type="button" data-sim-home-go disabled>시작 자세로 이동</ui-button>
            </div></li>
          <li data-sim-step="task" ${target.recording ? "" : "hidden"}><h4>과제 설명</h4>
            <label>무엇을 하는 시연인가요
              <textarea class="ui-field" data-sim-task maxlength="300" rows="3"
                placeholder="예: 파란 상자를 집어 벨트 표시 안에 놓기 · 성공: 표시 안에 놓임 · 실패: 떨어뜨림, 시간 초과"></textarea></label>
            <p class="arm-hint" data-sim-task-count>0 / 300 · 다음 기록에도 그대로 남습니다</p></li>
          <li data-sim-step="record" ${target.recording ? "" : "hidden"}><h4>녹화</h4>
            <ui-button kind="primary" type="button" data-sim-record-start>녹화 시작</ui-button>
            <p class="arm-record-status" data-sim-record-status role="status">기록 대기</p></li>
          <li data-sim-step="stop" ${target.recording ? "" : "hidden"}><h4>종료하고 결과 남기기</h4>
            <p class="arm-record-status" data-sim-record-live data-state="recording" aria-hidden="true" hidden></p>
            <div class="arm-step-actions">
              <ui-button kind="primary" type="button" data-sim-record-stop="success" disabled>성공으로 종료</ui-button>
              <ui-button type="button" data-sim-record-stop="failure" disabled>실패 사례로 종료</ui-button>
              <ui-button kind="quiet" type="button" data-sim-record-stop="unspecified" disabled>결과 없이 종료</ui-button>
            </div>
            <p class="arm-hint" data-sim-record-last hidden></p></li>
        </ol>
      </section>
    </div>`;
  const $ = (selector) => root.querySelector(selector);
  const controls = $("[data-sim-controls]");
  const status = $("[data-sim-status]");
  const cancel = $("[data-sim-cancel]");

  // The status line is a live region: write it only when the text changes (no re-announcing
  // the same "명령 RUNNING" every 250 ms poll).
  function setStatus(text) { if (status.textContent !== text) status.textContent = text; }
  function notify(update) {
    cancel.disabled = !active;
    if (active) cancel.removeAttribute("reason"); else cancel.setAttribute("reason", "진행 중 명령 없음");
    for (const listener of [...listeners]) listener(update);
  }
  async function request(path, options = {}) {
    return driver.request(path, {token, ...options});
  }
  function showError(error) {
    setStatus(`조작 보류 · ${error.message}`);
    controls.querySelectorAll("[data-sim-widgets] ui-button, [data-sim-widgets] input").forEach((button) => {
      button.disabled = true;
      button.setAttribute("reason", "조작 보류");
    });
    notify({state: null, settled: null, error});
  }
  // Drop the goal we were following (seat released or lost, tab hidden): its outcome is no
  // longer ours to see, so widgets hear it as UNKNOWN_HOLD and stop.
  function forget(error) {
    clearTimeout(pollTimer);
    pollTimer = null;
    pollWanted = false;
    const old = active;
    active = "";
    if (old) notify({state: null, settled: {commandId: old, state: "UNKNOWN_HOLD"}, error});
  }
  function schedulePoll() {
    clearTimeout(pollTimer);
    pollTimer = (active || pollWanted) && seat && !disposed
      ? setTimeout(() => refresh({goalOnly: true}), GOAL_POLL_MS) : null;
  }
  const goalStatus = (goal) => `명령 ${goal.state}${goal.reason ? ` · ${goal.reason}` : ""}`;
  async function goalState(id) {
    try { return await request(`/goals/${encodeURIComponent(id)}`); }
    catch (error) {
      // The server no longer knows the goal (restart, receipts dropped): it is settled for us.
      if (/^404\b/.test(error.message)) return {state: "UNKNOWN_HOLD", reason: "goal_unknown"};
      throw error;
    }
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
    pollWanted = false;
    let failed = false;
    try {
      state = await request("/state");
      if (disposed) return;
      if (active) {
        const following = active;
        const goal = await goalState(following);
        if (disposed || active !== following) return;
        setStatus(goalStatus(goal));
        if (TERMINAL.includes(goal.state)) {
          active = "";
          // Tell widgets first: if the re-read below fails, the settle must not be lost (a
          // stick would otherwise wait for it forever). A widget that tries to send now sees
          // the running readback (busy) and asks for the next one.
          notify({state, settled: {commandId: following, state: goal.state}, error: null});
          // The readback above was taken while the goal ran (ready:false, old sequence). The
          // next goal needs a ready, freshly served sequence, so read it again now.
          state = await request("/state");
          if (disposed) return;
        }
      } else {
        setStatus(state.ready ? "조작 가능"
          : state.owner_state === "active" ? "명령 진행 중" : `조작 보류 · ${state.owner_state}`);
      }
      $("[data-sim-readback]").textContent = JSON.stringify({sequence: state.state_sequence,
        age_ms: state.joint_age_ms, joints: state.positions, goal: active || null}, null, 2);
      renderSensors();
      renderHome();
      notify({state, settled: null, error: null});
      if (target.recording && !goalOnly) await refreshRecording();
    } catch (error) { failed = true; state = null; showError(error); }
    finally {
      refreshing = false;
      // A goal submitted while this refresh ran is polled from here (its own refresh was skipped).
      if (!failed) schedulePoll();
    }
  }
  const jogItem = () => items.find((item) => item.kind === "joint_jog");
  const armJoints = () => target.joints.filter((name) => name !== target.gripper);
  const maxStep = () => jogItem()?.max_step_rad ?? 0.02;
  function setReason(button, reason) {
    if (reason) button.setAttribute("reason", reason); else button.removeAttribute("reason");
  }
  function row(cells) {
    const tr = document.createElement("tr");
    cells.forEach((value, index) => {
      const td = document.createElement(index ? "td" : "th");
      if (!index) td.scope = "row";
      td.append(value);
      tr.append(td);
    });
    return tr;
  }
  function meter(value, low, high, label) {
    if (![value, low, high].every(Number.isFinite) || !(low < high)) return "범위 정보 없음";
    const node = document.createElement("meter");
    Object.assign(node, {min: low, max: high, value, title: label});
    node.setAttribute("aria-label", label);
    return node;
  }
  // Every value comes from the readback; text only (no server string becomes HTML).
  function renderSensors() {
    const age = state?.joint_age_ms;
    const chip = $("[data-sim-sensor-age]");
    const fresh = Number.isFinite(age) && age <= STALE_MS;
    chip.dataset.state = fresh ? "fresh" : "stale";
    chip.textContent = Number.isFinite(age) ? `${fresh ? "수신 중" : "오래됨"} · ${age} ms 전` : "수신 없음";
    const ranges = Object.fromEntries((jogItem()?.joints ?? []).map((joint) => [joint.name, joint]));
    const rows = armJoints().map((name) => {
      const value = state?.positions?.[name];
      if (!Number.isFinite(value)) return row([name, "값 없음", "—", "—"]);
      const range = ranges[name];
      const goal = home?.[name];
      const left = Number.isFinite(goal) ? goal - value : null;
      return row([name, `${deg(value)} (${value.toFixed(3)} rad)`,
                  meter(value, range?.lower, range?.upper, `${name} 범위 ${deg(range?.lower ?? 0)} ~ ${deg(range?.upper ?? 0)}`),
                  left === null ? "—" : Math.abs(left) <= 0.01 ? "맞음" : `${left > 0 ? "+" : ""}${deg(left)}`]);
    });
    const g = state?.gripper;
    if (g) {
      const percent = gripperPercent(g.position, g);
      rows.push(row([`${g.joint} (그리퍼)`, percent === null ? "값 없음" : `열림 ${percent}% · ${gripperStateLabel(g.state)}`,
                     percent === null ? "—" : meter(percent, 0, 100, `그리퍼 열림 ${percent}%`), "—"]));
    }
    $("[data-sim-sensors]").replaceChildren(...rows);
  }
  function renderHome() {
    const save = $("[data-sim-home-save]"), go = $("[data-sim-home-go]");
    const positions = state?.positions ?? {};
    const readable = armJoints().some((name) => Number.isFinite(positions[name]));
    const recordingNow = recording?.status === "recording";
    const step = home && homeStep(positions, home, maxStep());
    save.disabled = homing || !readable;
    setReason(save, homing ? "이동 중" : readable ? "" : "관절 값 수신 대기");
    go.textContent = homing ? "이동 멈춤" : "시작 자세로 이동";
    go.disabled = !homing && (!home || !seat || recordingNow || !step);
    setReason(go, homing ? "" : !home ? "먼저 시작 자세를 저장하세요" : recordingNow ? "녹화 중에는 이동하지 않습니다"
      : !step ? "이미 시작 자세입니다" : "");
    const where = !home ? "저장된 시작 자세가 없습니다. 팔을 원하는 자세로 옮긴 뒤 저장하세요."
      : step ? `시작 자세와 다릅니다 · ${step.joint} ${deg(step.remaining)} 남음` : "시작 자세에 있습니다";
    $("[data-sim-home-status]").textContent = homing ? homeNote : [homeNote, where].filter(Boolean).join(" · ");
    $("[data-sim-step='home']").dataset.state = home && !step ? "done" : homing ? "current" : "";
  }
  function nextUpdate(test) {
    return new Promise((resolve) => {
      const off = session.onUpdate((update) => { if (update.error || test(update)) { off(); resolve(update); } });
    });
  }
  // One bounded jog at a time toward the saved pose (D-390 §2); stopping lets the last step finish.
  async function goHome() {
    if (homing) { homing = false; homeNote = "이동을 멈췄습니다. 이미 보낸 한 걸음은 끝까지 움직입니다."; renderHome(); return; }
    homing = true;
    homeNote = "";
    while (homing && !disposed && seat) {
      const step = homeStep(state?.positions, home, maxStep());
      if (!step) { homeNote = ""; break; }
      homeNote = `시작 자세로 이동 중 · ${step.joint} ${deg(step.remaining)} 남음`;
      renderHome();
      const id = await session.submitJog(step.joint, step.delta, jogItem()?.duration_s ?? 0.4);
      if (id === false) { homeNote = "이동이 거절되었습니다. 위 상태 줄의 사유를 확인하세요."; break; }
      if (id === null) {
        session.requestPoll();
        const ready = await nextUpdate((update) => update.state?.ready && !session.busy());
        if (ready.error) { homeNote = `이동이 멈췄습니다 · ${ready.error.message}`; break; }
        continue;
      }
      const done = await nextUpdate((update) => update.settled?.commandId === id);
      if (done.settled?.state !== "SUCCEEDED") {
        homeNote = `이동이 멈췄습니다 · ${done.settled?.state ?? done.error?.message ?? "확인 필요"}`;
        break;
      }
      // The readback at the settle was taken while the goal ran: plan the next step from a fresh one.
      const fresh = await nextUpdate((update) => !update.settled && update.state?.ready);
      if (fresh.error) { homeNote = `이동이 멈췄습니다 · ${fresh.error.message}`; break; }
    }
    homing = false;
    if (disposed) return;
    renderHome();
    if (target.recording) renderRecording();
  }
  let cameraFresh = false;
  function renderRecording() {
    const status = $("[data-sim-record-status]");
    const now = recording?.status ?? "idle";
    const task = $("[data-sim-task]").value.trim();
    const issues = recording?.issues?.length ? ` · ${recording.issues.join(", ")}` : "";
    status.dataset.state = now;
    status.textContent = recordingError || (now === "recording"
      ? `● 녹화 중 · ${clock(Date.now() - recordStartedAt)} · ${recording.frame_count} 프레임${issues}`
      : `${RECORD_LABEL[now] ?? "기록 상태 확인 필요"} · ${recording?.frame_count ?? 0} 프레임${issues}`);
    const start = $("[data-sim-record-start]");
    start.disabled = now === "recording" || !state?.ready || !cameraFresh || homing || !task;
    setReason(start, now === "recording" ? "녹화 중" : homing ? "시작 자세로 이동 중" : !task ? "과제 설명을 먼저 적으세요"
      : !cameraFresh ? "영상 수신 대기" : !state?.ready ? "조작 준비 대기" : "");
    root.querySelectorAll("[data-sim-record-stop]").forEach((button) => {
      button.disabled = now !== "recording";
      setReason(button, now === "recording" ? "" : "녹화 중일 때 누를 수 있습니다");
    });
    const last = $("[data-sim-record-last]");
    last.hidden = !recording?.episode_id || now === "recording";
    last.textContent = last.hidden ? "" : `마지막 기록 · ${OUTCOME_LABEL[recording.task_outcome] ?? "결과 없음"} · ${recording.frame_count} 프레임 · ${recording.episode_id}${issues}`;
    $("[data-sim-step='task']").dataset.state = task ? "done" : "current";
    $("[data-sim-step='record']").dataset.state = now === "recording" ? "current" : "";
    $("[data-sim-step='stop']").dataset.state = now === "complete" ? "done" : now === "recording" ? "current" : "";
    // While recording, the stop card is pinned to the viewport bottom: the stick and the stop stay in one view.
    root.toggleAttribute("data-recording", now === "recording");
    const live = $("[data-sim-record-live]");
    live.hidden = now !== "recording";
    live.textContent = live.hidden ? "" : status.textContent;
  }
  async function refreshRecording() {
    recording = await request("/recordings");
    if (disposed) return;
    if (recording.status !== "recording") recordStartedAt = 0;
    else if (!recordStartedAt) recordStartedAt = Date.now();   // shortcut: counted from when this screen saw it start
    renderRecording();
    renderHome();
    const camera = await request("/camera");
    if (disposed) return;
    cameraFresh = Boolean(camera.fresh);
    $("[data-sim-camera-status]").textContent = camera.fresh ? `영상 수신 · ${camera.age_ms} ms` : "영상 없음 또는 오래됨 · 기록 시작 보류";
    renderRecording();
    $("[data-sim-camera]").hidden = !camera.fresh;
    if (camera.fresh) {
      const blob = await request("/camera/frame", {format: "blob"});
      if (disposed) return;
      if (previewUrl) URL.revokeObjectURL(previewUrl);
      previewUrl = URL.createObjectURL(blob);
      $("[data-sim-camera]").src = previewUrl;
    }
  }
  const task = $("[data-sim-task]");
  task.value = stored("sessionStorage", taskKey) ?? target.task ?? "";
  const countTask = () => { $("[data-sim-task-count]").textContent = `${task.value.length} / 300 · 다음 기록에도 그대로 남습니다`; };
  countTask();
  task.addEventListener("input", () => {
    stored("sessionStorage", taskKey, task.value || null);
    countTask();
    if (target.recording) renderRecording();
  });
  $("[data-sim-home-save]").addEventListener("click", () => {
    const positions = state?.positions ?? {};
    const pose = Object.fromEntries(armJoints().filter((name) => Number.isFinite(positions[name]))
      .map((name) => [name, positions[name]]));
    if (!Object.keys(pose).length) return;
    home = pose;
    stored("localStorage", homeKey, JSON.stringify(pose));
    homeNote = "";
    renderHome();
    renderSensors();
  });
  $("[data-sim-home-go]").addEventListener("click", goHome);
  $("[data-sim-record-start]").addEventListener("click", async () => {
    try {
      recording = await request("/recordings", {method: "POST", body: JSON.stringify({seat_id: seat, task: task.value.trim()})});
      recordingError = "";
      recordStartedAt = Date.now();
      await refresh();
    } catch (error) {
      recordingError = `기록 시작 실패 · ${error.message}`;
      $("[data-sim-record-status]").textContent = recordingError;
    }
  });
  root.querySelectorAll("[data-sim-record-stop]").forEach((button) => button.addEventListener("click", async () => {
    if (recording?.status !== "recording") return;
    try {
      recording = await request(`/recordings/${encodeURIComponent(recording.episode_id)}/stop`, {method: "POST", body: JSON.stringify({seat_id: seat, outcome: button.dataset.simRecordStop})});
      recordingError = "";
      await refresh();
    } catch (error) {
      recordingError = `기록 종료 실패 · ${error.message}`;
      $("[data-sim-record-status]").textContent = recordingError;
    }
  }));
  function release(error = new Error("조작권을 반납했습니다")) {
    connectionGeneration++;
    const released = seat;
    seat = "";
    state = null;
    forget(error);
    if (released) request(`/seat/${encodeURIComponent(released)}`, {method: "DELETE"}).catch(() => {});
  }
  function visibilityChanged() {
    if (document.hidden) {
      const error = new Error("화면이 숨겨져 조작권을 반납했습니다. 다시 연결하세요.");
      release(error);
      showError(error);
      $("[data-sim-pair]").hidden = false;
    }
  }
  document.addEventListener("visibilitychange", visibilityChanged);

  // Optimistic concurrency: the owner wants the exact current joint_state sequence, and a new
  // /joint_states can land between GET /state and POST /goals. That one refusal is retried once
  // with a fresh readback; every other refusal stops (D-411 B review).
  const RETRYABLE = /joint_state_sequence_mismatch|readback_not_recently_served/;
  function postGoal(path, fields) {
    return request(path, {method: "POST", body: JSON.stringify({
      instance_id: target.instance_id, seat_id: seat, request_id: crypto.randomUUID(), ...fields,
      state_sequence: state.state_sequence, expires_at_ms: Date.now() + 5000,
    })});
  }
  // One goal at a time for every widget (jog and gripper share the owner and the receipts).
  // Resolves to the accepted command id; null = not now (busy, readback not ready — retry on
  // the next update); false = not sent or refused (stop).
  async function submitGoal(path, fields) {
    if (!seat || disposed) return false;
    if (session.busy() || !state?.ready) return null;
    submitting = true;
    notify({state, settled: null, error: null});
    try {
      let goal;
      try { goal = await postGoal(path, fields); }
      catch (error) {
        if (!RETRYABLE.test(error.message) || disposed || !seat) throw error;
        state = await request("/state");
        if (disposed || !seat) return false;
        if (!state.ready) return null;
        goal = await postGoal(path, fields);
      }
      if (disposed || !seat) return false;
      if (goal.state === "REJECTED" || goal.state === "UNKNOWN_HOLD") {
        setStatus(goalStatus(goal));
        return false;
      }
      active = goal.command_id;
      setStatus(goalStatus(goal));
      return active;
    } catch (error) { showError(error); return false; }
    finally {
      submitting = false;
      if (!disposed) {
        notify({state, settled: null, error: null});
        if (!refreshing) schedulePoll();
      }
    }
  }

  // What widgets see: the latest readback, one goal at a time, and terminal states.
  const session = {
    target,
    state: () => state,
    // Our goal in flight, a POST under way, or the owner still executing (ready:false, "active").
    busy: () => Boolean(active) || submitting || state?.owner_state === "active",
    onUpdate(listener) { listeners.add(listener); return () => listeners.delete(listener); },
    // A widget waiting to send (stick held while busy) asks for the next readback soon.
    requestPoll() { pollWanted = true; if (!refreshing) schedulePoll(); },
    // submitGoal's id/null/false contract.
    async submitJog(name, delta, durationS = 0.4) {
      if (state?.ready && !(name in (state.positions ?? {}))) return false;
      return submitGoal("/goals", {joint: name, delta_rad: delta, duration_s: durationS});
    },
    // D-411 C: one absolute gripper goal (POST /gripper), same seat/owner/HOLD rules.
    async submitGripper(position, durationS) {
      return submitGoal("/gripper", {position, duration_s: durationS});
    },
  };
  const items = readControls(target.controls) ?? fallbackOmxControls(target);
  const disposeWidgets = composeControls($("[data-sim-widgets]"), items,
                                        {joint_jog: mountJointJog, gripper: mountGripper}, session);

  renderHome();
  $("[data-sim-connect]").addEventListener("click", connect);
  cancel.addEventListener("click", async () => {
    if (!active) return;
    try { await request(`/goals/${encodeURIComponent(active)}/cancel?seat_id=${encodeURIComponent(seat)}`, {method: "POST"}); await refresh(); }
    catch (error) { showError(error); }
  });
  const interval = setInterval(async () => {
    if (!seat || disposed || document.hidden) return;
    try { await request(`/seat/${encodeURIComponent(seat)}`, {method: "PUT"}); }
    catch (error) {
      // Seat lost (lease expired, taken over): stop following our goal and offer pairing again.
      seat = "";
      state = null;
      forget(error);
      showError(error);
      $("[data-sim-pair]").hidden = false;
      return;
    }
    await refresh();
  }, 1000);
  if (token) connect();
  return () => {
    disposed = true;
    homing = false;
    clearInterval(interval);
    clearTimeout(pollTimer);
    disposeWidgets();
    listeners.clear();
    document.removeEventListener("visibilitychange", visibilityChanged);
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    release();
  };
}
