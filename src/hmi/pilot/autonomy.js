// 보조 자율(D-344): 누르고 있는 동안만 CORE 차선 추종이 진행한다.
// DOM·fetch 를 모른다 — request/schedule/now 를 주입받아 Node 로 시험한다.
//
//   idle ──press()──▶ starting ──PUT mode(CAMERA_LINE, hold_s)=200──▶ running
//   running ──tick(100ms)──▶ POST /hold  (409 이면 CORE 가 이미 내렸다 → ended)
//   press 해제·스틱 개입·탭 이탈·오류 ──release(reason)──▶ PUT mode OFF → POST /mode MANUAL → idle
//
// 안전의 최종 책임은 CORE 다(hold_s 가 끊기면 CORE 가 스스로 멈춘다). 이 모듈은 운전자의
// 의도를 빨리 전하고, 끝나면 수동 운전으로 되돌려 놓는다.

export const HOLD_S = 0.5;
export const HOLD_EVERY_MS = 100;
export const STATUS_EVERY_MS = 300;

export function createAutoSession({request, schedule, onChange = () => {}, onStatus = () => {}} = {}) {
  let state = "idle";          // idle | starting | running | stopping
  let reason = "";
  let holdTimer = null;
  let statusTimer = null;
  let pressed = false;

  function set(next, why = reason) {
    state = next;
    reason = why;
    onChange({state, reason});
  }

  function clearTimers() {
    if (typeof holdTimer === "function") holdTimer();
    if (typeof statusTimer === "function") statusTimer();
    holdTimer = null;
    statusTimer = null;
  }

  function loopHold() {
    holdTimer = schedule(async () => {
      if (state !== "running") return;
      const response = await request("POST", "/api/v1/line-follow/hold").catch(() => null);
      if (!response || response.status !== 200) {
        // 409: CORE 가 이미 내렸다(운전자 확인 만료·차선 상실 후 OFF 등). 수동으로 되돌린다.
        await finish(response ? "core_released" : "link_lost");
        return;
      }
      loopHold();
    }, HOLD_EVERY_MS);
  }

  function loopStatus() {
    statusTimer = schedule(async () => {
      if (state !== "running" && state !== "starting") return;
      const response = await request("GET", "/api/v1/line-follow").catch(() => null);
      if (response?.status === 200) onStatus(response.body);
      loopStatus();
    }, STATUS_EVERY_MS);
  }

  async function finish(why) {
    clearTimers();
    set("stopping", why);
    await request("PUT", "/api/v1/line-follow/mode", {mode: "OFF"}).catch(() => null);
    const manual = await request("POST", "/api/v1/mode", {mode: "MANUAL"}).catch(() => null);
    set("idle", manual?.status === 200 ? why : `${why}; manual_failed`);
    return manual;
  }

  return {
    async press() {
      pressed = true;
      if (state !== "idle") return null;
      set("starting", "");
      const response = await request("PUT", "/api/v1/line-follow/mode",
                                     {mode: "CAMERA_LINE", hold_s: HOLD_S}).catch(() => null);
      if (!response || response.status !== 200) {
        const detail = response?.body?.error ?? response?.body?.detail ?? {};
        set("idle", detail.code || detail.message || (response ? `http_${response.status}` : "link_lost"));
        await request("POST", "/api/v1/mode", {mode: "MANUAL"}).catch(() => null);
        return response;
      }
      if (!pressed) {           // 켜지는 사이에 이미 손을 뗐다
        await finish("released");
        return response;
      }
      set("running", "");
      loopHold();
      loopStatus();
      return response;
    },
    async release(why = "released") {
      pressed = false;
      if (state === "running") return finish(why);
      return null;
    },
    state: () => state,
    reason: () => reason,
    active: () => state === "starting" || state === "running" || state === "stopping",
  };
}

// 자동의 의도(D-364 §6): CORE 가 낸 차선 상태를 화면 표시로만 바꾼다 — 조향을 계산하지 않는다.
// target: 로봇이 겨누는 곳(차선 오차, −1 왼쪽 … +1 오른쪽)을 가로 백분율로.
// steer: CORE 가 실제로 낸 각속도의 방향(REP-103: 양수 = 왼쪽으로 돈다).
export const STEER_DEADBAND = 0.02;   // rad/s — 이보다 작으면 직진으로 본다
export function intentView(lf, DEG = 180 / Math.PI) {
  if (!lf || lf.mode === "OFF" || lf.state === "OFF") return {visible: false};
  const error = Number(lf.error);
  const hasTarget = lf.error != null && Number.isFinite(error);
  const angular = Number(lf.angular ?? 0);
  const rate = Math.round(Math.abs(angular) * DEG);
  const dir = !Number.isFinite(angular) || Math.abs(angular) < STEER_DEADBAND ? "straight"
    : angular > 0 ? "left" : "right";
  const edge = lf.reason === "lane_edge_left" || lf.reason === "lane_edge_right";
  return {
    visible: true,
    tracking: lf.state === "TRACKING",
    target: hasTarget ? 50 + Math.max(-1, Math.min(1, error)) * 50 : null,
    dir,
    guard: edge,
    text: lf.state !== "TRACKING" ? "멈춤"
      : dir === "left" ? `◀ 왼쪽 ${rate}°/s`
      : dir === "right" ? `오른쪽 ${rate}°/s ▶`
      : "▲ 직진",
  };
}
