// D-941 5/7: the active map's charge bays, read-only. Fleet shows the plan and does not
// dispatch from it (`dispatch: false`); nothing here sends a goal.
import { isRouteAbsent } from "/console/assets/poll-gate.js";

const BAY_STATE = Object.freeze({
  free: ["비어 있음", "neutral"], planned: ["배정됨", "warn"],
  arrived: ["도착 · 연결 확인 중", "warn"], charging: ["충전 중", "active"],
  unknown: ["확인 불가 · 비어 있다고 볼 수 없음", "warn"],
});
const CELL_PHASE = Object.freeze({
  IDLE: ["대기 중", "neutral"], CLAIMED: ["인수됨 · 정지 확인", "warn"],
  ARM_IN_BED_ZONE: ["OMX 작업 중 · AMR 잠금", "active"],
  RELEASED: ["인계 완료 · 출발 가능", "neutral"], ABORTED: ["작업 중단 · 점검 필요", "warn"],
});
const ACTION = Object.freeze({
  go: "충전 칸으로", after_trip: "운행 끝나면 충전", wait: "대기", stay: "칸에 머무름",
  reseat: "다시 대기 · USB 미연결", leave: "충전 끝 · 나가도 됨",
});
const REASON = Object.freeze({
  low_battery: "배터리 낮음", battery_unknown: "배터리 모름", no_free_bay: "빈 칸 없음",
  connecting: "전압 상승 기다림", charging: "충전 중", charged: "목표 충전 도달",
  charge_rate_not_measured: "충전 속도 미측정", usb_not_connected: "전압이 오르지 않음",
  misaligned_on_bay: "중심선 정렬 불량 · 전진 후 재접안 필요",
  queued_for_exit: "출구 가까운 순서 출발 대기",
  corridor_busy: "공유 출구 통로 주행 중 대기",
  pose_unknown: "로봇 위치를 확인할 수 없음 · 칸을 직접 확인",
  bay_unknown: "칸이 비었는지 확인 불가 · 오프라인·위치 없는 로봇 확인",
  locked_by_cell: "OMX 셀 작업 중 구동 잠금",
});
const DOCK_VERDICT = Object.freeze({
  TURN_AT_ENTRY: "진입점 회전 대기",
  BACKING_ALIGNED: "중심선 후진 정렬",
  BACKING_DRIFT: "중심선 편차 보정 중",
  CONTACT_STOP: "접점 도달 정지",
  RETRY_FROM_P: "이탈 · 재정렬 필요",
});

/** Pure: the plan as display rows. */
export function chargeBayRows(plan) {
  const bays = (plan?.bays || []).map((b) => {
    const [text, status] = BAY_STATE[b.state] || ["알 수 없음", "neutral"];
    return { id: b.bay, text: b.robot_id ? `${text} · ${b.robot_id}` : text, status };
  });
  const actions = (plan?.actions || []).map((a) => {
    const parts = [ACTION[a.action] || a.action];
    if (a.bay && a.action === "go") parts.push(a.bay);
    if (Number.isFinite(a.estimated_percent)) parts.push(`추정 ${Math.round(a.estimated_percent)}%`);
    else if (Number.isFinite(a.arrived_percent)) parts.push(`도착 ${Math.round(a.arrived_percent)}%`);
    parts.push(REASON[a.reason] || a.reason || "");
    if (a.blocked_by_cell || a.cell_id) parts.push(`OMX 셀(${a.cell_id || ""}) 잠금`);
    if (a.docking && typeof a.docking === "object") {
      const v = DOCK_VERDICT[a.docking.verdict] || a.docking.verdict || "";
      const mm = Number.isFinite(a.docking.offset_m) ? `${Math.round(a.docking.offset_m * 1000)}mm` : "";
      const deg = Number.isFinite(a.docking.yaw_err_deg) ? `${a.docking.yaw_err_deg.toFixed(1)}°` : "";
      parts.push([v, mm, deg].filter(Boolean).join(" "));
    }
    if (Number.isFinite(a.exit_rank) && Number.isFinite(a.exit_distance_m)) {
      const aheadTxt = Array.isArray(a.ahead) && a.ahead.length ? ` (선행: ${a.ahead.join(", ")})` : "";
      parts.push(`출구#${a.exit_rank} (${a.exit_place || "S1"} ${a.exit_distance_m.toFixed(2)}m)${aheadTxt}`);
    }
    return { robot: a.robot_id, text: parts.filter(Boolean).join(" · ") };
  });
  const cells = Object.entries(plan?.omx_cells || {}).map(([cid, c]) => {
    const phase = c.gate?.phase || "IDLE";
    const [text, status] = CELL_PHASE[phase] || [phase, "neutral"];
    const details = [c.station?.station_place || "", c.gate?.robot_id || "",
      c.gate?.amr_motion_inhibited === true && !text.includes("AMR 잠금") ? "AMR 잠금" : ""].filter(Boolean);
    return { id: cid, text: [text, ...details].join(" · "), status };
  });
  const t = plan?.thresholds || {};
  const rate = Number.isFinite(t.rate_pct_per_min) ? `${t.rate_pct_per_min}%/분` : "미측정";
  const summary = `${t.go_percent ?? "—"}% 이하면 충전 · ${t.leave_percent ?? "—"}%면 나감 · 충전 속도 ${rate} · 보기 전용`;
  return { bays, actions, cells, summary };
}

export function createChargeBaysView({ scope, el, call, auth }) {
  const state = el("charge-bays-state");
  const list = el("charge-bay-rows");
  const hint = el("charge-bays-hint");
  let inFlight = false;
  let unavailable = false;

  function tag(text, status) {
    const t = document.createElement("ui-tag");
    t.setAttribute("status", status);
    t.textContent = text;
    return t;
  }

  function show(rows, note) {
    list.replaceChildren();
    for (const b of rows?.bays || []) {
      const li = document.createElement("li");
      li.append(`${b.id} `, tag(b.text, b.status));
      list.append(li);
    }
    for (const c of rows?.cells || []) {
      const li = document.createElement("li");
      li.append(`${c.id} `, tag(c.text, c.status));
      list.append(li);
    }
    for (const a of rows?.actions || []) {
      const li = document.createElement("li");
      li.textContent = `${a.robot}: ${a.text}`;
      list.append(li);
    }
    hint.textContent = note;
    hint.hidden = !note;
  }

  async function refresh() {
    const life = scope.capture();
    life.check();
    if (inFlight || unavailable || auth.locked) return;
    inFlight = true;
    try {
      const plan = await call("/api/fleet/charge-bays", { signals: [life.signal] });
      life.check();
      const rows = chargeBayRows(plan);
      state.textContent = `칸 ${rows.bays.length}`;
      show(rows, rows.bays.length ? rows.summary : "활성 지도에 충전 칸(charge)이 없습니다");
    } catch (error) {
      if (error.name === "AbortError") return;
      if (isRouteAbsent(error.status, error.code)) unavailable = true;
      state.textContent = "—";
      show(null, error.code === "NO_ACTIVE_MAP" ? "활성 지도가 없습니다" : "충전 칸 계획을 읽지 못했습니다");
    } finally {
      inFlight = false;
    }
  }

  return { refresh };
}
