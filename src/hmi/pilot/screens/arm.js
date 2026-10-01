// OMX-AI Gazebo practice. Every press submits one bounded trajectory goal.
export function mountArm(root, target, driver) {
  const tokenKey = `rosy.pilot.omx-sim.${location.origin}`;
  let token = sessionStorage.getItem(tokenKey) || "";
  let seat = "";
  let state = null;
  let active = "";
  let joint = target.joints[0];
  let disposed = false;
  let refreshing = false;
  let recording = null;
  let previewUrl = "";
  let connectionGeneration = 0;

  root.innerHTML = `<h2>OMX-AI Gazebo 연습</h2>
    <p>시뮬레이션 전용 · 실제 로봇과 연결되지 않습니다.</p>
    <div data-sim-pair><label>화면에 표시된 페어링 코드 <input class="ui-field" data-sim-code autocomplete="off"></label>
      <ui-button kind="primary" type="button" data-sim-connect>연결</ui-button></div>
    <p data-sim-status role="status">연결 대기</p>
    <div data-sim-controls hidden>
      <label>관절 <select class="ui-field" data-sim-joint></select></label>
      <div class="sim-jog"><ui-button kind="quiet" type="button" data-sim-delta="-0.02">− 0.02 rad</ui-button>
        <ui-button kind="quiet" type="button" data-sim-delta="0.02">+ 0.02 rad</ui-button></div>
      <p>그리퍼</p><div class="sim-jog"><ui-button kind="quiet" type="button" data-sim-gripper="-0.02">닫기</ui-button>
        <ui-button kind="quiet" type="button" data-sim-gripper="0.02">열기</ui-button></div>
      <ui-button kind="quiet" type="button" data-sim-cancel>진행 중 명령 취소</ui-button>
      <pre data-sim-readback></pre>
      <section data-sim-record-panel ${target.recording ? "" : "hidden"}>
        <h3>시연 기록</h3>
        <p>영상·관절 상태·수락된 조작 목표를 기록합니다. 결과는 직접 선택하세요.</p>
        <img data-sim-camera alt="Gazebo 작업 공간" width="320" height="240" hidden>
        <p data-sim-camera-status role="status">영상 확인 중</p>
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
  const select = $("[data-sim-joint]");
  for (const name of target.joints) select.add(new Option(name, name));
  select.addEventListener("change", () => { joint = select.value; });

  async function request(path, options = {}) {
    return driver.request(path, {token, ...options});
  }
  function showError(error) {
    status.textContent = `조작 보류 · ${error.message}`;
    controls.querySelectorAll("[data-sim-delta], [data-sim-gripper]").forEach((button) => {
      button.disabled = true;
      button.setAttribute("reason", "조작 보류");
    });
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
  async function refresh() {
    if (!seat || disposed || refreshing) return;
    refreshing = true;
    try {
      state = await request("/state");
      if (disposed) return;
      if (active) {
        const goal = await request(`/goals/${encodeURIComponent(active)}`);
        status.textContent = `명령 ${goal.state}${goal.reason ? ` · ${goal.reason}` : ""}`;
        if (["SUCCEEDED", "REJECTED", "CANCELED", "UNKNOWN_HOLD"].includes(goal.state)) active = "";
      } else status.textContent = state.ready ? "조작 가능" : `조작 보류 · ${state.owner_state}`;
      $("[data-sim-readback]").textContent = JSON.stringify({sequence: state.state_sequence,
        age_ms: state.joint_age_ms, joints: state.positions, goal: active || null}, null, 2);
      controls.querySelectorAll("[data-sim-delta], [data-sim-gripper]").forEach((button) => {
        button.disabled = !state.ready || Boolean(active);
        if (!button.disabled) button.removeAttribute("reason");
        else button.setAttribute("reason", active ? "명령 진행 중" : "조작 보류");
      });
      if (target.recording) await refreshRecording();
    } catch (error) { state = null; showError(error); }
    finally { refreshing = false; }
  }
  async function refreshRecording() {
    recording = await request("/recordings");
    if (disposed) return;
    $("[data-sim-record-status]").textContent = `${recording.status} · ${recording.frame_count} 프레임${recording.issues.length ? ` · ${recording.issues.join(", ")}` : ""}`;
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
      await refresh();
    } catch (error) { $("[data-sim-record-status]").textContent = `기록 시작 실패 · ${error.message}`; }
  });
  $("[data-sim-record-stop]").addEventListener("click", async () => {
    if (recording?.status !== "recording") return;
    try {
      recording = await request(`/recordings/${encodeURIComponent(recording.episode_id)}/stop`, {method: "POST", body: JSON.stringify({seat_id: seat, outcome: $("[data-sim-outcome]").value})});
      await refresh();
    } catch (error) { $("[data-sim-record-status]").textContent = `기록 종료 실패 · ${error.message}`; }
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
  async function jog(name, delta) {
    if (!seat || !state?.ready || active || !state.positions || !(name in state.positions)) return;
    const requestId = crypto.randomUUID();
    try {
      const goal = await request("/goals", {method: "POST", body: JSON.stringify({
        instance_id: target.instance_id, seat_id: seat, request_id: requestId,
        joint: name, delta_rad: delta, duration_s: 0.4,
        state_sequence: state.state_sequence, expires_at_ms: Date.now() + 5000,
      })});
      active = goal.command_id;
      await refresh();
    } catch (error) { showError(error); }
  }
  $("[data-sim-connect]").addEventListener("click", connect);
  root.querySelectorAll("[data-sim-delta]").forEach((button) => button.addEventListener("click", () => jog(joint, Number(button.dataset.simDelta))));
  root.querySelectorAll("[data-sim-gripper]").forEach((button) => button.addEventListener("click", () => jog(target.gripper, Number(button.dataset.simGripper))));
  $("[data-sim-cancel]").addEventListener("click", async () => {
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
    document.removeEventListener("visibilitychange", visibilityChanged);
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    release();
  };
}
