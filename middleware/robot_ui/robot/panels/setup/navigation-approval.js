// D-986 — 항법 재승인 카드. 판단은 모두 /api/v1/navigation/approval이 하고, 여기는 그 위의 화면이다.
import { confirmIrreversible } from "/common/ui.js";

const BASE = "/api/v1/navigation/approval";
const HOLD_MS = 100;
const LOSS_HOLD_MS = 1_500;
const TRIALS = [
  {direction: "forward", stop_cause: "button_release", label: "전진"},
  {direction: "reverse", stop_cause: "button_release", label: "후진"},
  {direction: "cw", stop_cause: "button_release", label: "시계 방향 회전"},
  {direction: "ccw", stop_cause: "button_release", label: "반시계 방향 회전"},
  {direction: "forward", stop_cause: "command_loss", label: "전진 후 명령 끊김"},
];
const STATE_LABEL = {missing: "아직 안 함", valid: "통과", invalid: "다시 필요"};

function el(tag, cls, text) { const node = document.createElement(tag); if (cls) node.className = cls; if (text) node.textContent = text; return node; }

export function mount(root, ctx) {
  let disposed = false; let holdTimer = null; let lossTimer = null; let phase = ""; let holding = false;
  const summary = el("ui-status", "", "승인 상태를 불러오는 중입니다.");
  const action = el("ui-status"); action.setAttribute("role", "status"); action.setAttribute("aria-live", "polite");
  const controls = el("ui-actions", "surface-actions");
  const begin = el("ui-button", "", "측정 시작"); const cancel = el("ui-button", "", "측정 취소");
  const sealButton = el("ui-button", "", "봉인"); const navigate = el("ui-button", "", "항법 시작");
  controls.append(begin, cancel, sealButton, navigate);
  const surfaceLabel = el("label", "", "시험 바닥 ");
  const surface = el("select");
  for (const [value, text] of [["floor", "바닥"], ["lifted", "바퀴를 들어 올림"]]) { const option = el("option", "", text); option.value = value; surface.append(option); }
  surfaceLabel.append(surface);
  const rearLabel = el("label", "", " 뒤쪽이 비어 있음을 눈이나 카메라로 확인했습니다");
  const rear = el("input"); rear.type = "checkbox"; rearLabel.prepend(rear);
  const list = el("ul", "surface-list"); const buttons = [];
  for (const trial of TRIALS) {
    const row = el("li"); const button = el("ui-button", "", `${trial.label}: 누르는 동안`); const state = el("span", "", " 확인 중");
    button.type = "button"; row.append(button, state); list.append(row); buttons.push({trial, button, state});
    button.addEventListener("pointerdown", (event) => { event.preventDefault(); void press(trial); });
    for (const name of ["pointerup", "pointercancel", "pointerleave"]) button.addEventListener(name, () => { if (trial.stop_cause === "button_release") void release(); });
    button.addEventListener("keydown", (event) => { if (event.key === " " && !event.repeat) { event.preventDefault(); void press(trial); } });
    button.addEventListener("keyup", (event) => { if (event.key === " " && trial.stop_cause === "button_release") void release(); });
  }
  root.append(summary, action, controls, surfaceLabel, rearLabel, list);

  function say(text, state = "ready") { action.textContent = text; action.setAttribute("state", state); }
  async function call(path, body) { return ctx.api(`${BASE}${path}`, {method: "POST", body: JSON.stringify(body ?? {})}); }
  function endHold() { clearInterval(holdTimer); clearTimeout(lossTimer); holdTimer = null; lossTimer = null; holding = false; }
  async function press(trial) {
    if (holding || phase !== "MEASURING") return;
    holding = true;
    try {
      await call("/trial/start", {direction: trial.direction, stop_cause: trial.stop_cause, rear_confirmed: rear.checked});
      if (!holding) return void call("/trial/stop").catch(() => {});
      say(`${trial.label} 시험 중입니다.`, "pending");
      const send = () => call("/trial/hold").catch((error) => { endHold(); say(`시험이 멈췄습니다: ${error.message}`, "error"); });
      void send(); holdTimer = setInterval(send, HOLD_MS);
      // 명령 끊김 시험은 버튼을 놓아도 멈춤 명령을 보내지 않는다. 보내던 명령이 그냥 끊겨야 한다.
      if (trial.stop_cause === "command_loss") lossTimer = setTimeout(() => { endHold(); say("명령을 끊었습니다. 스스로 서는지 측정 중입니다.", "pending"); }, LOSS_HOLD_MS);
    } catch (error) { endHold(); say(`시험을 시작하지 못했습니다: ${error.message}`, "error"); }
  }
  async function release() {
    if (!holding) return;
    endHold();
    try { await call("/trial/stop"); say("멈췄습니다. 정지 시간을 측정 중입니다.", "pending"); } catch (error) { say(`멈춤 요청 실패: ${error.message}. 비상 정지를 쓰십시오.`, "error"); }
  }
  // 화면을 떠나면 버튼을 놓은 것으로 친다. 서버도 명령이 끊기면 스스로 멈춘다.
  function stopMotion() { void release(); }
  window.addEventListener("rosy:stop-motion", stopMotion); window.addEventListener("blur", stopMotion);

  function run(button, path, prompt, body) {
    button.addEventListener("click", async () => {
      if (button.disabled) return;
      if (prompt && !(await confirmIrreversible({message: prompt, action: button.textContent})) || disposed) return;
      say("요청을 보내는 중입니다.", "pending");
      try { await call(path, body?.()); say("요청을 받았습니다."); } catch (error) { say(`실패: ${error.message}`, "error"); }
    });
  }
  run(begin, "/begin", "충전 선을 빼고 주변을 확인했나요? 충전 중이거나 배터리 상태를 모르면 시작되지 않습니다. 모터 시험 상태로 바꾸며 CORE가 다시 시작됩니다.");
  run(cancel, "/cancel", "측정을 취소하고 원래 상태로 되돌릴까요?");
  run(sealButton, "/seal", "다섯 시험 기록을 내 이름으로 봉인할까요?", () => ({test_surface: surface.value}));
  run(navigate, "/navigation-start", "항법을 시작할까요? 주행 경로를 확인하세요.");

  const stop = ctx.store.poll(BASE, 1_000, (data) => {
    phase = data.phase; const approval = data.approval || {};
    summary.textContent = approval.valid
      ? `승인 유효${approval.carried ? ` (${approval.measured_release_id}에서 이어받음)` : ""}`
      : `측정 필요: ${approval.reason || "승인 기록 없음"}`;
    summary.setAttribute("state", approval.valid ? "ready" : "warning");
    if (data.reason) say(data.reason, phase === "FAILED" ? "error" : "ready");
    else if (phase === "MEASURING" && data.measuring_expires_in_s != null) say(`측정은 ${Math.ceil(data.measuring_expires_in_s / 60)}분 뒤 자동으로 취소됩니다. 충전 선을 뺀 채로 지켜봐 주세요.`);
    const rows = data.trials || [];
    for (const item of buttons) {
      const row = rows.find((candidate) => candidate.direction === item.trial.direction && candidate.stop_cause === item.trial.stop_cause);
      item.state.textContent = ` ${STATE_LABEL[row?.state] || "확인 중"}${row?.reason ? `: ${row.reason}` : ""}`;
      item.button.disabled = phase !== "MEASURING";
    }
    begin.disabled = !["IDLE", "FAILED"].includes(phase);
    cancel.disabled = !["MEASURING", "FAILED"].includes(phase);
    sealButton.disabled = phase !== "MEASURING" || rows.some((row) => row.state !== "valid");
    navigate.disabled = phase !== "IDLE" || !approval.valid;
  }, (error) => { summary.setAttribute("state", "error"); summary.textContent = `승인 상태를 읽지 못했습니다: ${error.message}`; });
  return () => { disposed = true; endHold(); stop(); window.removeEventListener("rosy:stop-motion", stopMotion); window.removeEventListener("blur", stopMotion); };
}
