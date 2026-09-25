// 운용 뷰 맨 위 요약줄 (D-260 결정 5). 로봇 상태는 CORE가
// GET /api/v1/host/status-summary로 낸다 — 부팅 표시(LCD·램프·부저)와 같은
// 규칙표(core_common.robot_state)의 답이므로 여기서 다시 판정하지 않는다.
// 서버 문자열은 textContent로만 넣는다. 장치를 누르면 점검 뷰의 장치 카드로,
// 할 일 개수를 누르면 목록이 펼쳐진다. 셸은 render(payload)와 장치 열기만 준다.

const STATES = new Set(["booting", "failed", "caution", "ready_held", "ready"]);

const STATE_WORDS = {
  no_response: "응답 없음",
  bus_missing: "버스 없음",
  driver_missing: "드라이버 없음",
  needs_human: "사람 확인 필요",
};

function number(value) {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

export function createStatusSummary({ elements, onOpenDevice }) {
  const root = elements["status-summary"];
  const chip = elements["summary-state"];
  const reason = elements["summary-reason"];
  const devices = elements["summary-devices"];
  const power = elements["summary-power"];
  const toggle = elements["summary-todo-toggle"];
  const list = elements["summary-todos"];
  let firstProblem = null;

  function setOpen(open) {
    if (!toggle || !list) return;
    const canOpen = open && list.children.length > 0;
    list.hidden = !canOpen;
    toggle.setAttribute("aria-expanded", String(canOpen));
  }

  toggle?.addEventListener("click", () => setOpen(list?.hidden !== false));
  devices?.addEventListener("click", () => {
    setOpen(false);
    onOpenDevice(firstProblem);
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && list && !list.hidden) {
      setOpen(false);
      toggle?.focus();
    }
  });

  function renderDevices(summary) {
    if (!devices) return;
    const counts = summary && typeof summary === "object" ? summary : {};
    const problems = Array.isArray(counts.problems) ? counts.problems : [];
    firstProblem = problems[0]?.id || null;
    if (counts.available !== true) {
      devices.textContent = "장치 점검 전";
      devices.dataset.state = "unknown";
      return;
    }
    const head = `정상 ${number(counts.ok) ?? 0}/${number(counts.total) ?? 0}`;
    const first = problems[0];
    devices.textContent = first
      ? `${head} · ${first.label || first.id} ${STATE_WORDS[first.state] || first.state || ""}`.trim()
      : head;
    devices.dataset.state = first ? "problem" : "ok";
  }

  function renderPower(payload) {
    if (!power) return;
    const battery = payload.battery && typeof payload.battery === "object" ? payload.battery : {};
    const percent = number(battery.percent);
    const voltage = number(battery.voltage);
    const temperature = number(payload.temperature_c);
    // Compact: the rail has no room for words; the title names the three values.
    const parts = [percent == null ? "— %" : `${Math.round(percent)} %`];
    if (voltage != null) parts.push(`${voltage.toFixed(2)} V`);
    parts.push(temperature == null ? "— °C" : `${temperature.toFixed(0)} °C`);
    power.textContent = parts.join(" · ");
    power.dataset.low = battery.low === true ? "true" : "false";
  }

  function renderTodos(todos) {
    if (!toggle || !list) return;
    const items = Array.isArray(todos) ? todos.filter((item) => item && typeof item.text === "string") : [];
    const wasOpen = !list.hidden;
    list.replaceChildren(...items.map((item) => {
      const row = document.createElement("li");
      row.textContent = item.text;
      if (typeof item.device === "string") row.dataset.device = item.device;
      return row;
    }));
    toggle.textContent = `할 일 ${items.length}`;
    toggle.disabled = items.length === 0;
    setOpen(wasOpen);
  }

  function render(payload) {
    if (!root) return;
    const body = payload && typeof payload === "object" ? payload : {};
    const state = STATES.has(body.state) ? body.state : "unknown";
    root.dataset.state = state;
    if (chip) {
      chip.dataset.state = state;
      chip.textContent = state === "unknown" ? "상태 —" : String(body.label || state);
    }
    if (reason) {
      // Held: the D-247 7 sentence says why it cannot move; otherwise the short reason.
      const text = state === "ready_held" && body.motion_reason ? body.motion_reason : body.reason;
      reason.textContent = typeof text === "string" ? text : "";
      reason.title = reason.textContent;
    }
    renderDevices(body.devices);
    renderPower(body);
    renderTodos(body.todos);
  }

  return { render };
}
