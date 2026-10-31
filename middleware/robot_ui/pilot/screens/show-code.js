import {requestEnrollmentCode} from "../client.js";

function el(tag, text, attrs = {}) {
  const node = document.createElement(tag);
  if (text !== undefined && text !== null) node.textContent = text;
  for (const [name, value] of Object.entries(attrs)) node.setAttribute(name, value);
  return node;
}

// --- 연동 코드 보여주기 (D-193 §5 등록 코드) ---
// 화면이 없는 상대 기기와 연동할 때: 이 태블릿이 코드를 보여 주고 상대 기기에서
// 입력한다. 반대 방향(상대 화면 코드 → 이 태블릿 입력)은 접속 폼의 pairWithCode.
// 발급은 관리자만(CORE 403) — 운영자 화면에서는 항목을 보여 주되, 발급 거절 시
// 관리자 코드로 전환하는 길(기존 토큰 폼)을 바로 제공한다.
export function mountShowCode(root, onSwitchCredential) {
  const section = el("div", null, {"data-enroll-section": ""});
  section.append(el("ui-text", "연동 코드 보여주기", {scale: "label"}));
  section.append(el("p", "입력 화면이 있는 상대 기기는 이 코드를 보고 그 화면에서 입력합니다. " +
    "입력 수단이 없는 로봇은 로봇 화면의 코드를 이 태블릿 접속 폼에 입력하세요.",
    {"data-enroll-guidance": ""}));
  const button = el("ui-button", "코드 발급", {type: "button", "data-show-code": ""});
  button.setAttribute("kind", "segment");
  const status = el("ui-status", "", {role: "status", "data-enroll-status": ""});
  const timer = el("ui-text", "", {scale: "value", "data-enroll-timer": "", hidden: ""});
  let tick = null;
  const stopTick = () => { if (tick) { clearInterval(tick); tick = null; } };
  button.addEventListener("click", async () => {
    button.disabled = true;
    status.textContent = "코드 발급 중…";
    section.querySelector("[data-enroll-code]")?.remove();
    let result = null;
    try { result = await requestEnrollmentCode("operator"); }
    catch { result = null; }
    button.disabled = false;
    if (!result || result.status !== 201 || typeof result.body?.code !== "string") {
      stopTick(); timer.hidden = true;
      if (result?.status === 403) {
        status.textContent = "발급은 관리자 권한이 필요합니다.";
        section.querySelector("[data-enroll-upgrade]")?.remove();
        const upgrade = el("ui-button", "관리자 코드로 전환", {type: "button", "data-enroll-upgrade": ""});
        upgrade.setAttribute("kind", "quiet");
        upgrade.addEventListener("click", () => onSwitchCredential?.());
        section.insertBefore(upgrade, timer);
      } else {
        status.textContent = "코드를 발급할 수 없습니다. 연결을 확인하세요.";
      }
      return;
    }
    section.querySelector("[data-enroll-upgrade]")?.remove();
    const code = el("ui-text", result.body.code, {scale: "display", "data-enroll-code": ""});
    const role = {viewer: "조회용", operator: "운전자용"}[result.body.role] ?? `${result.body.role}용`;
    status.textContent = `${role} 코드입니다. 상대 기기에서 입력하세요.`;
    section.append(code);
    // 남은 유효 시간 표시(D-193 등록 코드 수명). 0 이되면 갱신 안내만 하고 자동 재발급하지 않는다.
    stopTick();
    const deadline = Date.now() + (result.body.expires_in_s ?? 300) * 1000;
    timer.hidden = false;
    const render = () => {
      const left = Math.max(0, Math.round((deadline - Date.now()) / 1000));
      timer.textContent = `유효 ${String(Math.floor(left / 60)).padStart(2, "0")}:${String(left % 60).padStart(2, "0")}`;
      if (left <= 0) {
        stopTick();
        status.textContent = "코드가 만료됐습니다. 다시 발급해 주세요.";
      }
    };
    render();
    tick = setInterval(render, 1000);
  });
  section.append(button, status, timer);
  root.append(section);
  root.__enrollDispose = stopTick;
}
