// D-941 5/7: the charge-bay plan remains display-only; task buttons use pipeline APIs.
import { isRouteAbsent } from "/console/assets/poll-gate.js";

const CELL_BUTTONS = {
  cell_s: [
    {label: "S3 셔틀 (Pinky→Belt)", preset: "s3_shuttle"},
    {label: "Belt-Far 이탈 복구", preset: "s3_recover_belt_far"},
    {label: "Floor-Front 바닥 복구", preset: "s3_recover_floor_front"},
  ],
  cell_ab: [
    {label: "1층 적재 (arm_a)", preset: "s5_tier1_arm_a"},
    {label: "2층 적재 (arm_b)", preset: "s5_tier2_arm_b"},
    {label: "3층 적재 (arm_a)", preset: "s5_tier3_arm_a"},
    {label: "S3→S5 연속 실행", preset: "full_s3_to_s5_pipeline"},
  ],
};
const PINKY_BUTTONS = [
  {label: "S3 도킹+하역", pinkyAction: "dock_and_unload_s3"},
  {label: "S3 도킹", pinkyAction: "dock_s3"},
  {label: "충전소(C1)", pinkyAction: "charge_c1"},
  {label: "출구(S1) 출발", pinkyAction: "depart_s1"},
];

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
  const tasks = Array.isArray(plan?.omx_cell_tasks) ? plan.omx_cell_tasks : [];
  const cards = [
    ...["cell_s", "cell_ab"].map((id) => {
      const phase = plan?.omx_cells?.[id]?.gate?.phase || "IDLE";
      const [text, status] = CELL_PHASE[phase] || [phase, "neutral"];
      const task = tasks.filter((entry) => entry.cell_id === id)
        .sort((a, b) => (b.created_at ?? 0) - (a.created_at ?? 0))[0] || null;
      const hs = task?.health_summary || {};
      const stopHealth = task?.hardware_telemetry?.stop_event?.health || {};
      const maxTemp = hs.max_temp_c ?? (Array.isArray(stopHealth.temp_c) && stopHealth.temp_c.length ? Math.max(...stopHealth.temp_c) : null);
      const maxCur = hs.max_current_ma ?? (Array.isArray(stopHealth.current_ma) && stopHealth.current_ma.length ? Math.max(...stopHealth.current_ma) : null);
      const substage = hs.substage || (task?.status === "RUNNING" ? "Grasp → Lift → Place 실행 중" : (task?.status === "COMPLETED" ? "Fold Home 완료" : "대기"));
      const healthParts = [
        maxTemp != null ? `온도 ${maxTemp}°C` : "",
        maxCur != null ? `전류 ${maxCur}mA` : "",
        substage,
      ].filter(Boolean);
      const quickControls = [
        ...(id === "cell_s" ? [{label: "자동 감지·복구 셔틀", preset: "s3_auto_recover_or_shuttle"}] : []),
        ...(task && (task.status === "QUEUED" || task.status === "RUNNING")
          ? [{label: "작업 취소", cancelTaskId: task.task_id}]
          : []),
        ...(task && (task.status === "COMPLETED" || task.status === "CANCELLED" || task.status === "ABORTED")
          ? [{label: "재실행", retryTaskId: task.task_id}]
          : []),
      ];
      return {
        kind: "omx", id, cameraUrl: `/api/fleet/pipeline/cell-camera/${id}`,
        title: id === "cell_s" ? "cell_s · S3 하역 셔틀 (arm_s)" : "cell_ab · S5 팔레트 적재 (arm_a·arm_b)",
        phase, status, text, task, healthText: healthParts.join(" · "),
        buttons: CELL_BUTTONS[id], quickControls,
      };
    }),
    ...(plan?.actions?.length ? plan.actions.map((action) => action.robot_id) : ["rosy_42", "rosy_45", "rosy_46"])
      .filter((id, index, ids) => id && ids.indexOf(id) === index)
      .map((robot_id) => {
        const action = actions.find((row) => row.robot === robot_id);
        const rawAction = plan?.actions?.find((entry) => entry.robot_id === robot_id);
        return {kind: "pinky", id: robot_id, robot_id,
          cameraUrl: "/api/fleet/pipeline/cell-camera/pinky", title: `Pinky AMR · ${robot_id}`,
          status: rawAction?.blocked_by_cell || rawAction?.action === "wait" ? "warn" : "neutral",
          text: action?.text || "작업 정보 없음",
          healthText: "케이블 보호 미세이동 (최대 1.5cm · 0.02m/s)",
          buttons: PINKY_BUTTONS,
          quickControls: [
            {label: "미세 전진 1.5cm", pinkyAction: "micro_forward_2cm"},
            {label: "미세 후진 1.5cm", pinkyAction: "micro_reverse_2cm"},
            {label: "즉시 정지", pinkyAction: "stop_now"},
          ]};
      }),
  ];
  return { bays, actions, cells, summary, cards };
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
    const cellItems = new Map();
    const robotItems = new Map();
    for (const b of rows?.bays || []) {
      const li = document.createElement("li");
      li.append(`${b.id} `, tag(b.text, b.status));
      list.append(li);
    }
    for (const c of rows?.cells || []) {
      const li = document.createElement("li");
      li.append(`${c.id} `, tag(c.text, c.status));
      list.append(li);
      cellItems.set(c.id, li);
    }
    for (const a of rows?.actions || []) {
      const li = document.createElement("li");
      li.textContent = `${a.robot}: ${a.text}`;
      list.append(li);
      robotItems.set(a.robot, li);
    }
    for (const card of rows?.cards || []) {
      const li = (card.kind === "omx" ? cellItems : robotItems).get(card.id) || document.createElement("li");
      if (li.parentNode !== list) list.append(li);
      const article = document.createElement("article");
      article.className = "omx-dense-card";
      const camera = document.createElement("img");
      camera.src = card.cameraUrl;
      camera.loading = "lazy";
      camera.className = "cell-cam-thumb";
      camera.alt = `${card.title} 카메라`;
      const details = document.createElement("div");
      const title = document.createElement("strong");
      title.textContent = card.title;
      const status = document.createElement("p");
      status.append(tag(card.text, card.status));
      const task = document.createElement("p");
      const taskBase = card.task ? `${card.task.task_id} · ${card.task.status} · ${card.task.arm_id || "—"}` : "";
      task.textContent = [taskBase, card.healthText || ""].filter(Boolean).join(" | ");
      const buttons = document.createElement("div");
      buttons.className = "omx-card-actions";
      for (const choice of [...(card.buttons || []), ...(card.quickControls || [])]) {
        const button = document.createElement("ui-button");
        button.setAttribute("kind", choice.cancelTaskId ? "irreversible" : "quiet");
        button.setAttribute("type", "button");
        button.setAttribute("data-work-read", "");
        button.textContent = choice.label;
        button.addEventListener("click", async () => {
          if (auth.locked || button.hasAttribute("disabled")) return;
          button.setAttribute("disabled", "");
          try {
            if (choice.cancelTaskId) {
              await call(`/api/fleet/pipeline/cell-tasks/${choice.cancelTaskId}/cancel`, {method: "POST"});
            } else if (choice.retryTaskId) {
              await call(`/api/fleet/pipeline/cell-tasks/${choice.retryTaskId}/retry`, {method: "POST"});
            } else {
              await call(choice.preset ? "/api/fleet/pipeline/cell-tasks" : "/api/fleet/pipeline/pinky-tasks", {
                method: "POST", headers: {"Content-Type": "application/json"},
                body: JSON.stringify(choice.preset ? {preset: choice.preset} :
                  {robot_id: card.robot_id, action: choice.pinkyAction, cable_guard_micro: true}),
              });
            }
            await refresh();
          } catch (error) {
            hint.textContent = `작업 요청 실패: ${error.message}`;
            hint.hidden = false;
          } finally {
            button.removeAttribute("disabled");
          }
        });
        buttons.append(button);
      }
      details.append(title, status, task, buttons);
      article.append(camera, details);
      li.append(article);
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
      const telemetry = await call("/api/fleet/pipeline/cell-tasks", {signals: [life.signal]})
        .catch(() => null);
      life.check();
      const rows = chargeBayRows({...plan, omx_cell_tasks: telemetry?.tasks || plan.omx_cell_tasks});
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
