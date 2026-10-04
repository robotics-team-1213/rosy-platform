// 보조 자율(D-344)과 의도 띠(D-364 §6). drive.js 에서 나눴다: "진행"을 누르는 동안만
// CORE 차선 추종, 차선 자동 토글, 영상 안에 겨누는 점과 CORE 의 실제 조향 방향.
// 상태 기계는 autonomy.js, 이 파일은 화면 배선만 한다.

import {createAutoSession, intentView} from "../autonomy.js";
import {MODE_LABEL} from "/common/core_ui_logic.js";

const DEG = 180 / Math.PI;
const PAINT_LABEL = {learned: "학습 모델", denoise: "OpenCV 반사 제거", threshold: "기존 검출"};
const ACTUAL_PAINT_LABEL = {...PAINT_LABEL, denoise_fallback: "학습 미사용 · 전처리 대체"};
function actualPaintText(config) {
  const source = ACTUAL_PAINT_LABEL[config.applied_paint_source];
  if (!source || !Number.isFinite(config.applied_source_age_s)
      || config.applied_source_age_s < 0 || config.applied_source_age_s > 2) return "확인 대기";
  const revision = config.applied_paint_source === "learned" && config.applied_model_revision
    ? ` · 모델 ${config.applied_model_revision}` : "";
  const age = Number.isFinite(config.applied_source_age_s)
    ? ` · ${config.applied_source_age_s.toFixed(1)}초 전` : "";
  return `${source}${revision}${age}`;
}
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
export function mountAutoMode({drive, element, apiGet, releaseAll, onIdle, blocked = () => false}) {
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
    drive.dataset.autoMode = "off";
    element.autoToggle?.setAttribute("aria-pressed", "false");
    element.manual?.setAttribute("aria-pressed", "true");
  }
  if (element.go) {
    element.go.addEventListener("pointerdown", (event) => {
      event.preventDefault();
      if (blocked() || element.go.disabled || drive.dataset.autoMode !== "on") return;
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
      element.manual?.setAttribute("aria-pressed", String(!on));
    });
  }
  element.manual?.addEventListener("click", () => {
    takeover();
    drive.dataset.autoMode = "off";
    element.autoToggle?.setAttribute("aria-pressed", "false");
    element.manual.setAttribute("aria-pressed", "true");
  });

  return {
    active: () => auto.active(),
    release: (reason) => auto.release(reason),
    takeover,
  };
}

// Configuration and live inference are different evidence. Never paint a failed PUT as applied.
export function mountLanePerception(root, {apiGet, onPending = () => {}, blocked = () => false}) {
  const panel = document.createElement("details");
  panel.className = "pilot-models";
  const summary = document.createElement("summary"); summary.textContent = "차선 인식";
  const select = document.createElement("select"); select.className = "ui-field";
  select.setAttribute("aria-label", "차선 인식 방식"); select.dataset.lanePerception = "";
  for (const [value, label] of Object.entries(PAINT_LABEL)) {
    const option = document.createElement("option"); option.value = value; option.textContent = label; select.append(option);
  }
  const apply = document.createElement("ui-button"); apply.textContent = "인식 적용";
  apply.type = "button"; apply.setAttribute("kind", "quiet"); apply.dataset.laneApply = "";
  const status = document.createElement("ui-status"); status.textContent = "차선 인식 설정 확인 중"; status.setAttribute("role", "status");
  status.setAttribute("aria-live", "polite"); status.dataset.lanePerceptionStatus = "";
  const disabledReason = document.createElement("ui-status"); disabledReason.id = "pilot-lane-perception-reason";
  select.setAttribute("aria-describedby", disabledReason.id);
  panel.append(summary, select, apply, status, disabledReason); root.append(panel);
  let config = null, idle = false, idleAt = 0, admin = false, pending = false, disposed = false, dirty = false;
  select.addEventListener("change", () => { dirty = true; });
  function render() {
    const reason = pending ? "인식 적용 중" : !config ? "인식 설정을 확인할 수 없습니다" : !admin
      ? "관리자 권한이 필요합니다" : !idle || Date.now() - idleAt > 2000 || blocked() ? "정지 · 설정 버튼으로 멈춘 뒤 적용하세요" : "";
    apply.disabled = Boolean(reason); select.disabled = Boolean(reason);
    if (reason) apply.setAttribute("reason", reason); else apply.removeAttribute("reason");
    if (reason) select.setAttribute("reason", reason); else select.removeAttribute("reason");
    disabledReason.textContent = reason; disabledReason.hidden = !reason;
    if (config) summary.textContent = `차선 인식 · 설정 ${PAINT_LABEL[config.paint_source]}`;
  }
  async function refresh() {
    if (disposed || pending) return;
    const [configuration, identity, state, lf] = await Promise.all([
      apiGet("/api/v1/line-follow/perception").catch(() => null),
      apiGet("/api/v1/auth/whoami").catch(() => null),
      apiGet("/api/v1/robot/state").catch(() => null),
      apiGet("/api/v1/line-follow").catch(() => null),
    ]);
    if (disposed || pending) return;
    admin = identity?.status === 200 && identity.body?.role === "administrator";
    const velocity = state?.body?.velocity;
    idle = state?.status === 200 && state.body?.mode === "IDLE" && velocity
      && velocity.linear === 0 && velocity.angular === 0 && lf?.status === 200 && lf.body?.mode === "OFF";
    idleAt = Date.now();
    config = configuration?.status === 200 && PAINT_LABEL[configuration.body?.paint_source] ? configuration.body : null;
    if (config) {
      if (!dirty) select.value = config.paint_source;
      status.textContent = `설정: ${PAINT_LABEL[config.paint_source]} · 실제 추론: ${actualPaintText(config)}`;
    } else status.textContent = configuration?.status === 404 ? "이 서버는 차선 인식 선택을 지원하지 않습니다" : "차선 인식 설정 확인 실패";
    render();
  }
  apply.addEventListener("click", async () => {
    if (pending || !idle || Date.now() - idleAt > 2000 || !admin || !config || blocked()) return;
    const requested = select.value;
    pending = true; onPending(true); render();
    status.textContent = "인식 설정 적용 중 — 카메라를 다시 시작합니다";
    try {
      const response = await apiGet("/api/v1/line-follow/perception", {
        method: "PUT", body: JSON.stringify({paint_source: requested}), timeoutMs: 75000,
      });
      if (response?.status !== 200 || response.body?.applied !== true) throw new Error(response?.body?.detail?.message ?? response?.body?.detail ?? `HTTP ${response?.status}`);
      const readback = await apiGet("/api/v1/line-follow/perception", {timeoutMs: 75000});
      if (readback?.status !== 200 || readback.body?.paint_source !== requested) throw new Error("설정 readback 불일치");
      config = readback.body;
      dirty = false;
      status.textContent = `설정 적용: ${PAINT_LABEL[config.paint_source]} · 실제 추론: ${actualPaintText(config)}`;
    } catch (error) {
      status.textContent = `인식 적용 실패: ${error.message} · 설정을 다시 확인하세요`;
      config = null;
    } finally { pending = false; onPending(false); render(); }
  });
  render();
  const timer = setInterval(refresh, 1000); refresh();
  return {refresh, dispose() { disposed = true; clearInterval(timer); }};
}
