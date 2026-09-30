// OMX-AI Gazebo practice. Every press submits one bounded trajectory goal.
export function mountArm(root, target, driver) {
  const tokenKey = `rosy.pilot.omx-sim.${location.origin}`;
  let token = sessionStorage.getItem(tokenKey) || "";
  let seat = "";
  let state = null;
  let active = "";
  let joint = target.joints[0];
  let disposed = false;

  root.innerHTML = `<h2>OMX-AI Gazebo 연습</h2>
    <p>시뮬레이션 전용 · 실제 로봇과 연결되지 않습니다.</p>
    <div data-sim-pair><label>화면에 표시된 페어링 코드 <input data-sim-code autocomplete="off"></label>
      <button type="button" data-sim-connect>연결</button></div>
    <p data-sim-status role="status">연결 대기</p>
    <div data-sim-controls hidden>
      <label>관절 <select data-sim-joint></select></label>
      <div class="sim-jog"><button type="button" data-sim-delta="-0.02">− 0.02 rad</button>
        <button type="button" data-sim-delta="0.02">+ 0.02 rad</button></div>
      <p>그리퍼</p><div class="sim-jog"><button type="button" data-sim-gripper="-0.02">닫기</button>
        <button type="button" data-sim-gripper="0.02">열기</button></div>
      <button type="button" data-sim-cancel>진행 중 명령 취소</button>
      <pre data-sim-readback></pre>
      <p>카메라: ${target.camera ? "상태 확인 필요" : "이 Gazebo 구성에 없음"} · 연습 기록: 준비 중</p>
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
    controls.querySelectorAll("button[data-sim-delta], button[data-sim-gripper]").forEach((button) => { button.disabled = true; });
  }
  async function connect() {
    try {
      if (!token) {
        const code = $("[data-sim-code]").value.trim();
        const paired = await request("/pair", {method: "POST", body: JSON.stringify({code})});
        token = paired.token;
        sessionStorage.setItem(tokenKey, token);
      }
      await request("/whoami");
      seat = (await request("/seat", {method: "POST"})).seat_id;
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
    if (!seat || disposed) return;
    try {
      state = await request("/state");
      if (active) {
        const goal = await request(`/goals/${encodeURIComponent(active)}`);
        status.textContent = `명령 ${goal.state}${goal.reason ? ` · ${goal.reason}` : ""}`;
        if (["SUCCEEDED", "REJECTED", "CANCELED", "UNKNOWN_HOLD"].includes(goal.state)) active = "";
      } else status.textContent = state.ready ? "조작 가능" : `조작 보류 · ${state.owner_state}`;
      $("[data-sim-readback]").textContent = JSON.stringify({sequence: state.state_sequence,
        age_ms: state.joint_age_ms, joints: state.positions, goal: active || null}, null, 2);
      controls.querySelectorAll("button[data-sim-delta], button[data-sim-gripper]").forEach((button) => {
        button.disabled = !state.ready || Boolean(active);
      });
    } catch (error) { state = null; showError(error); }
  }
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
    if (!seat || disposed) return;
    try { await request(`/seat/${encodeURIComponent(seat)}`, {method: "PUT"}); await refresh(); }
    catch (error) { seat = ""; showError(error); }
  }, 1000);
  if (token) connect();
  return () => {
    disposed = true;
    clearInterval(interval);
    if (seat) request(`/seat/${encodeURIComponent(seat)}`, {method: "DELETE"}).catch(() => {});
  };
}
