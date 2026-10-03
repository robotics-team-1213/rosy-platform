// 보조 자율(D-344)과 의도 띠(D-364 §6). drive.js 에서 나눴다: "진행"을 누르는 동안만
// CORE 차선 추종, 차선 자동 토글, 영상 안에 겨누는 점과 CORE 의 실제 조향 방향.
// 상태 기계는 autonomy.js, 이 파일은 화면 배선만 한다.

import {createAutoSession, intentView} from "../autonomy.js";
import {MODE_LABEL} from "/common/core_ui_logic.js";

const DEG = 180 / Math.PI;
const LF_REASON = {
  tracking: "차선 추종", camera_no_observation: "차선 관측 대기", camera_line_not_visible: "차선 안 보임",
  camera_low_confidence: "차선 신뢰 낮음", camera_observation_stale: "차선 관측 늦음",
  camera_reselection_required: "차선 놓침 — 다시 누르세요", driver_released: "손 뗌 — 정지",
  obstacle_ahead: "앞 물체 — 정지", obstacle_sensor_stale: "LiDAR 끊김 — 정지",
  lane_edge_left: "왼쪽 경계선 — 오른쪽으로 비킴", lane_edge_right: "오른쪽 경계선 — 왼쪽으로 비킴",
  lane_departure: "차선 밟음 — 정지, 수동으로 빼세요", lane_guard_stale: "IR 차선 감시 끊김 — 정지",
  nominal_ground_requires_driver: "공칭 지면 — 진행을 누르고 있어야 함",
  limit_level_too_low: "수동 한도 L1 이상에서만 차선 자동", angular_limit_zero: "조향 한도 없음 — 정지",
  calibration: "보정 중 — 조작 잠김",
};

// onIdle: 자동이 끝났을 때 수동 경로를 되돌린다(상한 표시·명령 경로 재개·슬루 초기화).
// releaseAll: "진행"을 누르면 수동 입력을 먼저 모두 놓는다.
export function mountAutoMode({drive, element, apiGet, releaseAll, onIdle}) {
  // 같은 section 에 다시 마운트된다 — 지난 주행의 자동 모드 표시를 물려받지 않는다.
  drive.dataset.autoMode = "off";
  // 시한: 켜기(CAMERA_LINE) 요청이 매달리면 손을 뗀 뒤에도 "누르는 중"으로 보인다. 끊기면 idle 로 떨어진다.
  const REQUEST_TIMEOUT_MS = 1500;
  const request = (method, path, body) => method === "GET"
    ? apiGet(path, {timeoutMs: REQUEST_TIMEOUT_MS})
    : apiGet(path, {method, body: JSON.stringify(body ?? {}), timeoutMs: REQUEST_TIMEOUT_MS});
  // 진행 버튼은 실제로 도는 동안, 또는 켜는 중이면서 아직 누르고 있을 때만 채운다.
  let goHeld = false;
  let autoState = "idle";
  const paintGo = () => element.go?.classList.toggle(
    "active", autoState === "running" || (autoState === "starting" && goHeld));
  const auto = createAutoSession({
    request,
    schedule: (fn, ms) => { const id = setTimeout(fn, ms); return () => clearTimeout(id); },
    onChange: ({state, reason}) => {
      autoState = state;
      paintGo();
      if (state === "idle") {
        onIdle();
        const benign = !reason || reason === "released" || reason === "takeover";
        element.motion.dataset.kind = benign ? "idle" : "warn";
        element.motion.textContent = benign ? MODE_LABEL.IDLE : `자동 멈춤 — ${LF_REASON[reason] ?? reason}`;
        renderIntent(null);
      }
    },
    onStatus: (lf) => {
      const tracking = lf.state === "TRACKING";
      element.cap.textContent = `자동 ${Number(lf.linear ?? 0).toFixed(2)} m/s · ${Math.round(Number(lf.angular ?? 0) * DEG)}°/s`;
      element.motion.dataset.kind = tracking ? "auto" : "warn";
      const ahead = lf.clearance_m == null ? "" : ` · 앞 ${Number(lf.clearance_m).toFixed(2)} m`;
      element.motion.textContent = tracking
        ? `차선 추종 · 신뢰 ${Number(lf.confidence ?? 0).toFixed(2)} · 오차 ${Number(lf.error ?? 0) >= 0 ? "+" : ""}${Number(lf.error ?? 0).toFixed(2)}${ahead}`
        : `${LF_REASON[lf.reason] ?? lf.reason ?? lf.state}${ahead}`;
      renderIntent(lf);
    },
  });
  // 자동의 의도(D-364 §6): 겨누는 곳과 CORE 가 실제로 도는 방향. 표시만 한다.
  function renderIntent(lf) {
    const view = intentView(lf, DEG);
    if (!element.intent) return;
    element.intent.hidden = !view.visible;
    if (!view.visible) return;
    element.intent.dataset.state = view.tracking ? (view.guard ? "guard" : "tracking") : "hold";
    element.intent.dataset.dir = view.dir;
    element.intentTarget.hidden = view.target == null;
    if (view.target != null) element.intentTarget.style.left = `${view.target}%`;
    element.intentSteer.textContent = view.text;
    placeIntent();
  }
  // 영상 틀은 영상보다 넓을 수 있다(contain 의 검은 띠·옆 조작부). 띠는 실제로 그려진 영상 안에만 둔다.
  function placeIntent() {
    const frame = element.frame, strip = element.intent;
    if (!frame?.naturalWidth || !strip) return;
    const box = frame.getBoundingClientRect(), view = element.view.getBoundingClientRect();
    const scale = Math.min(box.width / frame.naturalWidth, box.height / frame.naturalHeight);
    const width = frame.naturalWidth * scale, height = frame.naturalHeight * scale;
    const left = box.left + (box.width - width) / 2 - view.left;
    const top = box.top + (box.height - height) / 2 - view.top;
    const visibleLeft = Math.max(left, 0), visibleRight = Math.min(left + width, view.width);
    const visibleBottom = Math.min(top + height, view.height);
    const inset = (visibleRight - visibleLeft) * 0.06;
    strip.style.left = `${visibleLeft + inset}px`;
    strip.style.width = `${Math.max(0, visibleRight - visibleLeft - 2 * inset)}px`;
    strip.style.top = `${Math.max(0, visibleBottom - strip.offsetHeight - 10)}px`;
  }
  function takeover() {
    if (auto.active()) auto.release("takeover");
  }
  if (element.go) {
    element.go.addEventListener("pointerdown", (event) => {
      event.preventDefault();
      if (navigator.vibrate) navigator.vibrate(10);
      releaseAll();
      goHeld = true;
      auto.press();
    });
    for (const name of ["pointerup", "pointercancel", "pointerleave"]) {
      element.go.addEventListener(name, () => {
        goHeld = false;
        paintGo();
        auto.release("released");
      });
    }
    element.go.addEventListener("contextmenu", (event) => event.preventDefault());
  }
  if (element.autoToggle) {
    element.autoToggle.addEventListener("click", () => {
      const on = drive.dataset.autoMode !== "on";
      if (!on) takeover();
      drive.dataset.autoMode = on ? "on" : "off";
      element.autoToggle.setAttribute("aria-pressed", String(on));
    });
  }

  return {
    active: () => auto.active(),
    release: (reason) => auto.release(reason),
    takeover,
  };
}
