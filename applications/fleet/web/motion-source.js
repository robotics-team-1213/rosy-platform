// Why a robot moves or who holds it, from facts that prove it. DOM-free.
// Fleet and CORE do not say who sent an accepted teleop (a console and a robot's own dashboard look the same
// to CORE), so a manual mode or a motion with no proving fact is shown as 확인 불가, never as a guess.
import { evidenceAgeText } from "/common/core_ui_logic.js";
import { staleAgeS } from "./state-age.js";
import { measuredMotion, motionLabel } from "/console/assets/measured-motion.js";

const LAB = { unknown: "출처 확인 불가", idle: "정지 · 대기" };

/**
 * { key, text, cls, attention, title } for one roster robot.
 * cls is the card tag class ("" neutral, "nav" active, "warn", "crit"); attention is true when an operator must look.
 */
export function motionSource(robot, view, nowMs = Date.now()) {
  const make = (key, text, cls = "", title = "", attention = false) => ({ key, text, cls, title, attention });
  if (view.stateUnavailable || !robot.online || !robot.state)
    return make("unknown", LAB.unknown, "warn", "Fleet이 로봇 상태를 읽지 못했습니다");
  const state = robot.state;
  const stale = staleAgeS(robot, view.receivedAtMs, nowMs);
  if (stale !== null) return make("unknown", `${LAB.unknown} · 상태 ${evidenceAgeText(stale).slice(3)} 값`, "warn", "오래된 상태라 지금 움직이는지 알 수 없습니다");
  const moving = measuredMotion(robot, view, nowMs);
  const owned = (key, label, title) => make(key, `${label} · ${motionLabel(moving)}`, moving === true ? "nav" : "", title);
  const lease = state.trip_lease;
  const trip = (view.trafficTrips || []).some(row => row.robot_id === robot.robot_id);
  const dock = state.docking?.state;
  if (state.activity || robot.calibration) return owned("calibration", "보정 작업", "보정 세션이 로봇을 쥐고 있습니다");
  if (view.manualDriveRobot === robot.robot_id) return owned("console_manual", "관제에서 직접 조종", "이 관제 화면에서 조종 단추를 누르는 중입니다");
  if (lease || trip) {
    const who = lease?.operator_name ? ` · ${lease.operator_name}` : "";
    return owned("trip", `배차${who}`, lease ? "CORE의 운행 임차(lease)가 살아 있습니다" : "Fleet에 열린 운행이 있습니다");
  }
  if (robot.yielding) return owned("recovery", "양보 요청", "Fleet이 경로 양보를 요청했습니다");
  if (dock === "DOCKING" || dock === "UNDOCKING")
    return owned("dock", dock === "DOCKING" ? "충전 복귀" : "출차", "CORE 도킹 상태");
  if (state.swarm?.active) return owned("formation", "대형 지정", "CORE 군집 상태가 켜져 있습니다");
  if (robot.goal) return owned("fleet_goal", "관제 목표", "Fleet이 낸 목표가 살아 있습니다");
  if (moving === null) return make("unknown", LAB.unknown, "warn", "신선한 속도 근거가 없어 움직임을 판단할 수 없습니다");
  const lane = state.line_follow?.mode;
  const laneOn = lane === "CAMERA_LINE" || lane === "IR_LINE";
  if (state.mode === "MANUAL")
    return make("manual_unknown", "수동 모드 · 조종 주체 확인 불가", moving ? "crit" : "warn", "CORE 모드만으로는 관제인지 로봇 화면인지 알 수 없습니다", moving);
  if (moving) {
    const why = state.mode === "NAVIGATION" || state.navigation === "NAVIGATING" ? "목표 주행" : laneOn ? "차선 주행" : "";
    return make("unowned", why ? `${why} · 지시자 확인 불가` : "원인 불명 이동", "crit", "Fleet이 모르는 이동입니다. 로봇을 확인하세요", true);
  }
  if (state.mode === "NAVIGATION" || state.navigation === "NAVIGATING" || laneOn)
    return make("unowned", "주행 설정 · 지시자 확인 불가", "warn", "멈춰 있지만 Fleet이 낸 지시가 아닙니다");
  return make("idle", LAB.idle, "", "신선한 속도가 0이고 지시한 곳이 없습니다");
}
