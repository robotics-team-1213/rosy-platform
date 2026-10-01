// 수동 조종(teleop) — 홀드-티커와 전송·정지 절차(D-250). app.js에서 분리된
// 모듈(D-362 P1). 홀드 티커의 100ms 운율과 해제 zero는 여기가 소유하고,
// 자격 판정(teleopEligible)과 문구도 함께 산다. 셸은 시작·정지 지점과
// 상태 갱신 시점(updateTeleopControls)만 부른다.
import { setOff, setText } from "./dom.js";
import { api, session } from "./client.js";
import { reasonText } from "./triage.js";
import { createHoldTicker } from "/common/hold-ticker.js";
import { evidenceOf, motionEvidenceBlocks } from "./telemetry.js";

export function teleopEligible() {
  return Boolean(
    session.token
      && session.capabilities?.teleop === true
      && session.robotState?.mode === "MANUAL"
      && session.robotState?.safety?.estop === false
      && !motionEvidenceBlocks(session.robotState),
  );
}

// 사유는 teleopEligible과 같은 조건을 같은 순서로 읽는다.
function teleopBlockReason() {
  if (!session.token) return "로그인 필요";
  if (session.capabilities?.teleop !== true) return "수동 운전 기능 없음";
  if (session.robotState?.mode !== "MANUAL") return "수동 모드에서만";
  if (session.robotState?.safety?.estop !== false) return "안전 상태 확인 필요";
  if (motionEvidenceBlocks(session.robotState)) return "센서 증거 부족";
  return "";
}

export function updateTeleopControls() {
  const enabled = teleopEligible();
  const reason = teleopBlockReason();
  document.querySelectorAll("[data-teleop]").forEach((button) => {
    setOff(button, !enabled, reason);
  });
  if (!session.token) {
    setText("teleop-message", "operator 접속 키가 필요합니다.");
  } else if (session.capabilities && session.capabilities.teleop !== true) {
    // D-247 7: a runtime mode that holds the motors is not a permission problem.
    const byMode = String(session.capabilities.withheld?.reason || "").startsWith("runtime_mode:");
    // v1.21: otherwise say which reason withholds teleop, in operator words.
    const withheld = session.capabilities.withheld?.reasons?.teleop;
    setText("teleop-message", byMode && session.motionReason
      ? session.motionReason
      : withheld
        ? `teleop 사용 불가: ${reasonText(withheld)}`
        : "현재 하드웨어 설정에서는 저속 운전을 쓸 수 없습니다.");
  } else if (session.robotState?.safety?.estop) {
    setText("teleop-message", "비상정지가 활성화되어 있습니다.");
  } else if (motionEvidenceBlocks(session.robotState)) {
    const pose = evidenceOf(session.robotState, "pose") || "unavailable";
    const velocity = evidenceOf(session.robotState, "velocity") || "unavailable";
    setText("teleop-message", `pose ${pose} · velocity ${velocity}`);
  } else if (session.robotState?.mode !== "MANUAL") {
    setText("teleop-message", "수동 모드로 전환해야 합니다.");
  } else if (!holdTicker.active) {
    setText("teleop-message", "버튼을 누르고 있는 동안만 저속 명령을 보냅니다.");
  }
}

export function teleopActive() {
  return holdTicker.active;
}

function sendTeleop(linear, angular, keepalive = false) {
  return api("/api/v1/teleop", {
    method: "POST",
    body: JSON.stringify({ linear, angular }),
    keepalive,
  });
}

function queueTerminalZero(immediate = false) {
  const prior = session.teleopPending || Promise.resolve();
  if (immediate) {
    const immediateZero = sendTeleop(0, 0, true);
    immediateZero.catch(() => null);
  }
  const terminal = prior
    .catch(() => null)
    .then(() => sendTeleop(0, 0, true));
  session.teleopPending = terminal;
  terminal
    .catch((error) => {
      setText("teleop-message", `정지 전송 실패 · watchdog 대기: ${error.message}`);
    })
    .finally(() => {
      if (session.teleopPending === terminal) session.teleopPending = null;
    });
}

let teleopHoldTimeout = null;
export function stopTeleop(message = "정지 명령을 전송했습니다.", immediate = false) {
  if (teleopHoldTimeout !== null) { clearTimeout(teleopHoldTimeout); teleopHoldTimeout = null; }
  // D-250: interval 수명과 zero 1회는 티커가 소유한다. 자격·전송·문구는 셸의 몫이다.
  holdTicker.stop(immediate);
  document.querySelectorAll("[data-teleop]").forEach((button) => button.setAttribute("aria-pressed", "false"));
  setText("teleop-message", message);
  updateTeleopControls();
}

async function transmitTeleop(linear, angular) {
  if (!holdTicker.active || session.teleopPending) return;
  const request = sendTeleop(linear, angular);
  session.teleopPending = request;
  try {
    await request;
  } catch (error) {
    if (holdTicker.active) stopTeleop(`주행 명령 실패: ${error.message}`);
  } finally {
    if (session.teleopPending === request) session.teleopPending = null;
  }
}

let teleopCommand = { linear: 0, angular: 0 };
// D-250: 홀드-티커는 100ms 운율과 해제 zero만 낸다. 자격은 teleopEligible,
// 전송은 transmitTeleop, zero 절차는 queueTerminalZero가 가진다.
const holdTicker = createHoldTicker({
  intervalMs: session.teleopIntervalMs,
  onTick: () => transmitTeleop(teleopCommand.linear, teleopCommand.angular),
  onZero: (immediate) => {
    if (session.token) queueTerminalZero(immediate);
  },
});

export function startTeleop(button, event) {
  event.preventDefault();
  if (!teleopEligible() || holdTicker.active) return;
  const linear = Number(button.dataset.linear);
  const angular = Number(button.dataset.angular);
  if (!Number.isFinite(linear) || !Number.isFinite(angular)) return;

  teleopCommand = { linear, angular };
  button.setAttribute("aria-pressed", "true");
  setText("teleop-message", `${button.querySelector("small")?.textContent || "주행"} 명령 전송 중…`);
  holdTicker.start();
  teleopHoldTimeout = setTimeout(() => stopTeleop("2초 한도에 도달해 정지했습니다.", true), 2_000);
}
