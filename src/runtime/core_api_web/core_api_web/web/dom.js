// 대시보드가 공유하는 DOM 접근과 표시 형식.
// 여기 있는 함수는 네트워크도 세션도 모르며, 그래서 어느 모듈에서든 안전하게 부를 수 있다.

export const elements = Object.fromEntries(
  [...document.querySelectorAll("[id]")].map((element) => [element.id, element]),
);

// 낡은 값은 나이를 달고 다닌다. 판정 자체는 서버가 내린 `evidence` 문자열이
// 이미 말하고 있으므로, 화면은 "얼마나 낡았나"만 더한다. 임계값은 읽지 않는다 —
// 클라이언트가 임계를 만지면 판정자가 둘이 된다(D-72 S4, test_dashboard.py).
function ageSeconds(receivedAt) {
  if (!receivedAt) return null;
  const stamp = Date.parse(receivedAt);
  if (!Number.isFinite(stamp)) return null;
  const age = (Date.now() - stamp) / 1000;
  return age >= 0 ? age : null;
}

// 페이지 상태 — 값별 증거 어휘(fresh/delayed/disconnected/unavailable)를
// 재사용하지 않는다(concept 16 §5). "아직 묻지 않았다"와 "물었는데 없다"는
// 운용자에게 완전히 다른 사실이다: 전자는 빈칸, 후자가 em dash다.
let requested = false;

export function markRequested() {
  requested = true;
}

export function setText(id, value, fallback = "—", evidence) {
  const node = elements[id];
  if (!node) return;
  node.textContent = value ?? (requested ? fallback : "");
  delete node.dataset.age;
  if (evidence == null) {
    delete node.dataset.evidence;
    node.removeAttribute("title");
    return;
  }
  const state = typeof evidence === "string" ? evidence : evidence.evidence;
  const received = typeof evidence === "object" ? evidence.received_at : undefined;
  if (state) node.dataset.evidence = state;
  else delete node.dataset.evidence;

  // 신선한 값에는 나이도 임계도 붙이지 않는다 — 여유로울 때 시간을 적으면
  // 화면 전체가 시끄러워진다.
  if (state !== "delayed" && state !== "disconnected") {
    if (received) node.title = received;
    else node.removeAttribute("title");
    return;
  }

  const age = ageSeconds(received);
  const parts = [];
  if (age != null) {
    node.dataset.age = age.toFixed(1);
    parts.push(`${age.toFixed(1)}초 낡음`);
  }
  if (received) parts.push(received);
  if (parts.length) node.title = parts.join(" · ");
  else node.removeAttribute("title");
}

// `Number(null)` is 0, so a missing value must be caught before the cast —
// otherwise "no reading" renders as 0% / 0.00 V, a false alarm (D-82 Law 0).
export function number(value, digits = 1) {
  const amount = metricNumber(value);
  return amount === null ? "—" : amount.toFixed(digits);
}

export function percent(value) {
  const amount = metricNumber(value);
  return amount === null ? "—" : `${Math.round(amount)}%`;
}

export function bytes(value) {
  if (!Number.isFinite(Number(value))) return "—";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let amount = Number(value);
  let unit = 0;
  while (amount >= 1024 && unit < units.length - 1) {
    amount /= 1024;
    unit += 1;
  }
  return `${amount.toFixed(unit > 2 ? 1 : 0)} ${units[unit]}`;
}

export function duration(value) {
  if (!Number.isFinite(Number(value))) return "—";
  const total = Math.floor(Number(value));
  const days = Math.floor(total / 86400);
  const hours = Math.floor((total % 86400) / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  return `${days}일 ${hours}시간 ${minutes}분`;
}

export function setMeter(id, value) {
  const safe = Number.isFinite(Number(value)) ? Math.max(0, Math.min(100, Number(value))) : 0;
  elements[id]?.style.setProperty("--meter", `${safe}%`);
}

export function rate(value) {
  const amount = metricNumber(value);
  return amount === null ? "—" : `${bytes(amount)}/s`;
}

export function metricNumber(value) {
  if (value === null || value === undefined || value === "") return null;
  const amount = Number(value);
  return Number.isFinite(amount) ? amount : null;
}

export function svgText(label, x, y, className) {
  const text = document.createElementNS("http://www.w3.org/2000/svg", "text");
  text.setAttribute("x", x);
  text.setAttribute("y", y);
  text.setAttribute("class", className);
  text.textContent = label;
  return text;
}

export function fillNumberInput(id, value) {
  const input = elements[id];
  if (!input || document.activeElement === input) return;
  input.value = Number.isFinite(Number(value)) ? Number(value).toFixed(2) : "";
}

export function fillSelect(id, value) {
  const input = elements[id];
  if (!input || document.activeElement === input || value == null || value === "") return;
  input.value = value;
}

export function fillTextInput(id, value) {
  const input = elements[id];
  if (!input || document.activeElement === input) return;
  input.value = value == null ? "" : String(value);
}

export function setFieldMessage(id, text) {
  setText(id, text, "");
}

export function setEnabled(id, enabled) {
  const element = document.getElementById(id);
  if (element) element.disabled = !enabled;
}

/** 저장 버튼은 type="button" 이다. Enter 로 submit 되면 셸이 통째로 다시 뜬다. */
export function bindFormSave(formId, buttonId) {
  elements[formId]?.addEventListener("submit", (event) => {
    event.preventDefault();
    elements[buttonId]?.click();
  });
}
