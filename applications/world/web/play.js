const DIRECTIONS = {ArrowUp: "forward", ArrowDown: "reverse", ArrowLeft: "left", ArrowRight: "right"};

export function initPlay() {
  const byId = (id) => document.getElementById(id);
  const panel = byId("world-play");
  const state = byId("play-status");
  const start = byId("play-start");
  const reset = byId("play-reset");
  const keys = byId("play-keys");
  const pose = byId("play-pose");
  let current, token, held, timer;
  let seq = 0;
  panel.hidden = false;

  function show(code, label) {
    if (state.getAttribute("state") !== code) state.setAttribute("state", code);
    if (state.textContent !== label) state.textContent = label;
  }

  async function command(action, credentials = {}) {
    const response = await fetch("./sim/control", {
      method: "POST", headers: {"Content-Type": "application/json"}, keepalive: action === "stop",
      body: JSON.stringify({action, generation: current?.generation, ...credentials}),
      signal: AbortSignal.timeout(900),
    });
    if (!response.ok) throw new Error("CORE did not accept the command");
    return response.json();
  }

  function stop() {
    if (!held) return;
    held = undefined;
    clearTimeout(timer);
    if (token) void command("stop", {token, seq: ++seq}).catch(() => {});
  }

  function drive(action) {
    if (!token || held || document.hidden || panel.closest("[hidden]")) return;
    const press = {action};
    held = press;
    async function pulse() {
      if (held !== press) return;
      try {
        await command(press.action, {token, seq: ++seq});
      } catch {
        stop();
        show("warning", "조종 명령이 중단됐습니다.");
      }
      if (held === press) timer = setTimeout(pulse, 100);
    }
    void pulse();
  }

  start.addEventListener("click", async () => {
    stop();
    try {
      token = (await command("start")).token;
      keys.hidden = false;
      show("ready", "Gazebo Pinky 조종 중");
    } catch {
      token = undefined;
      keys.hidden = true;
      show("unavailable", "CORE가 조종 시작을 승인하지 않았습니다.");
    }
  });

  reset.addEventListener("click", async () => {
    stop();
    keys.hidden = true;
    token = undefined;
    try {
      await command("reset");
      show("pending", "C2로 초기화 중");
    } catch {
      show("warning", "초기화 요청을 받지 못했습니다.");
    }
  });

  for (const button of keys.querySelectorAll("[data-drive]")) {
    button.addEventListener("pointerdown", (event) => {
      if (event.isPrimary && event.button === 0) drive(button.dataset.drive);
    });
  }
  for (const event of ["pointerup", "pointercancel", "blur", "pagehide"]) window.addEventListener(event, stop);
  document.addEventListener("visibilitychange", () => { if (document.hidden) stop(); });
  new MutationObserver(() => { if (byId("panel-map").hidden) stop(); }).observe(byId("panel-map"), {
    attributes: true, attributeFilter: ["hidden"],
  });
  window.addEventListener("keydown", (event) => {
    if (!token || !Object.hasOwn(DIRECTIONS, event.key) || event.altKey || event.ctrlKey || event.metaKey
        || event.target?.matches?.("input, textarea, select, [contenteditable]") || byId("panel-map").hidden) return;
    event.preventDefault();
    if (!event.repeat) drive(DIRECTIONS[event.key]);
  });
  window.addEventListener("keyup", (event) => {
    if (held && DIRECTIONS[event.key] === held.action) stop();
  });

  async function poll() {
    try {
      const response = await fetch("./sim/control", {cache: "no-store", signal: AbortSignal.timeout(900)});
      if (!response.ok) throw new Error("No simulation");
      const sample = await response.json();
      if (sample.generation !== current?.generation || !sample.armed) {
        stop();
        token = undefined;
        keys.hidden = true;
      }
      current = sample;
      start.hidden = reset.hidden = !sample.pose || sample.booting || sample.failed;
      if (sample.failed) show("error", "Gazebo 초기화에 실패했습니다.");
      else if (sample.booting) show("pending", "Gazebo에서 C2를 여는 중");
      else if (!sample.pose) show("warning", "최근 Gazebo 위치 관측이 없습니다.");
      else if (!token) show("ready", "Gazebo 시뮬레이션 연결됨");
      const p = sample.pose;
      pose.textContent = p
        ? `${sample.run_id} · 지도 v${sample.map_version} · 위치 (${p.pose_m[0].toFixed(3)}, ${p.pose_m[1].toFixed(3)}) m · 속도 ${p.linear_m_s.toFixed(3)} m/s`
        : "";
    } catch {
      stop();
      token = undefined;
      keys.hidden = start.hidden = reset.hidden = true;
      pose.textContent = "";
      show("unavailable", "격리 시뮬레이션에 연결되지 않았습니다.");
    } finally {
      setTimeout(poll, 300);
    }
  }
  void poll();
}
