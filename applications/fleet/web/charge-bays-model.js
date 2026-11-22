// D-941 5/7: DOM-free display model of the charge-bay plan (split from charge-bays-view.js).
import { evidenceAgeText } from "/common/core_ui_logic.js";
const CELL_BUTTONS = {
  cell_s: [
    {label: "S3 셔틀 (Pinky→Belt)", preset: "s3_shuttle"},
    {label: "S3 ACT 정책 구동 (arm_s)", preset: "s3_act_policy", requiresPresence: true},
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

const BAY_STATE = Object.freeze({
  free: ["비어 있음", "neutral"], planned: ["배정됨", "warn"],
  arrived: ["도착 · 연결 확인 중", "warn"], charging: ["충전 중", "active"],
  unknown: ["확인 불가 · 비어 있다고 볼 수 없음", "warn"],
});
const CELL_PHASE = Object.freeze({
  IDLE: ["대기 중", "neutral"], CLAIMED: ["인수됨 · 정지 확인", "warn"],
  ARM_IN_BED_ZONE: ["OMX 작업 중 · AMR 잠금", "active"],
  HUMAN_HOLD: ["사람 감지 비상정지 · 작업 일시중지", "warn"],
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
  const armLiveStates = plan?.arm_live_states || {};
  const stationCameraLinks = plan?.station_camera_links || {};
  const stationZones = plan?.station_zones || {};
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
      const dec = plan?.decisions?.[id] || task?.decision || null;
      const armHolds = plan?.arm_holds || {};
      const cellHeldArms = (id === "cell_s" ? ["arm_s"] : ["arm_a", "arm_b"]).filter((a) => armHolds[a]?.held);
      const holdTxt = cellHeldArms.length ? `홀드(${cellHeldArms.join("/")})` : "";
      const healthParts = [
        maxTemp != null ? `온도 ${maxTemp}°C` : "",
        maxCur != null ? `전류 ${maxCur}mA` : "",
        substage,
        holdTxt,
        dec ? `Decision: ${dec.choice} (${dec.reason})` : "",
      ].filter(Boolean);
      const humanEstop = Boolean(
        plan?.human_safety?.human_detected?.[id] || plan?.human_safety?.active_estop || phase === "HUMAN_HOLD"
      );
      const quickControls = [
        {label: "상황 판단·자동 실행 (Decision)", decisionSubject: id},
        {
          label: humanEstop ? "사람 이탈 · 작업 자동 재개" : "사람 감지 비상정지 (E-Stop)",
          humanSafetyCell: id,
          humanDetected: !humanEstop,
        },
        {
          label: id === "cell_s" ? "반출대3 반출(YAML)" : "반출대2 반출(YAML)",
          zoneId: id === "cell_s" ? "EXP_S3_BELT" : "EXP_S5_PALLET",
        },
        {label: "비전 자동 점검", visionCheckCell: id},
        {label: cellHeldArms.length ? "팔 홀드 해제(확인됨)" : "팔 홀드 점검·해제", clearArmHold: id},
        ...(id === "cell_s" ? [{label: "자동 감지·복구 셔틀", preset: "s3_auto_recover_or_shuttle"}] : []),
        ...(task && (task.status === "QUEUED" || task.status === "RUNNING" || task.status === "PAUSED_HUMAN")
          ? [{label: "작업 취소", cancelTaskId: task.task_id}]
          : []),
        ...(task && (task.status === "COMPLETED" || task.status === "CANCELLED" || task.status === "ABORTED")
          ? [{label: "재실행", retryTaskId: task.task_id}]
          : []),
      ];
      return {
        kind: "omx", id,
        cameraViews: id === "cell_s"
          ? [
              {id: "arm_s_top", label: "S3 상단", source: "arm_s_top"},
              {id: "arm_s_wrist", label: "arm_s 손목", source: "arm_s_wrist"},
            ]
          : [
              {id: "top", label: "S5 상단", source: "top"},
              {id: "side", label: "측면 (A/B)", source: "side"},
              {id: "arm_a_wrist", label: "arm_a 손목", source: "arm_a_wrist"},
              {id: "arm_b_wrist", label: "arm_b 손목", source: "arm_b_wrist"},
            ],
        title: id === "cell_s" ? "cell_s · S3 하역 셔틀 (arm_s)" : "cell_ab · S5 팔레트 적재 (arm_a·arm_b)",
        phase, status, text, task, healthText: healthParts.join(" · "),
        buttons: CELL_BUTTONS[id], quickControls,
      };
    }),
  ];
  const cellOccupants = {
    cell_s: plan?.omx_cells?.cell_s?.gate?.robot_id || null,
    cell_ab: plan?.omx_cells?.cell_ab?.gate?.robot_id || null,
  };
  return { bays, actions, cells, summary, cards, armLiveStates, stationCameraLinks, stationZones, cellOccupants };
}

export function formatArmLiveJointText(armId, armLiveStates = {}, fallbackText = "folded: true (홈 대기)") {
  const st = armLiveStates?.[armId];
  if (!st || !Array.isArray(st.joints_deg) || !st.joints_deg.length) return fallbackText;
  const jointsStr = st.joints_deg.slice(0, 6).map((v, i) => `J${i + 1}:${Number(v).toFixed(1)}°`).join(" ");
  const ageTxt = st.age_s != null ? evidenceAgeText(Math.round(Number(st.age_s))).slice(3) : "";
  const liveBadge = st.fresh !== false ? `LIVE${ageTxt ? ` · ${ageTxt}` : ""}` : `스냅샷${ageTxt ? ` · ${ageTxt}` : ""}`;
  const tempTxt = st.temp_c != null ? `${st.temp_c}°C` : "";
  const curTxt = st.current_ma != null ? `${st.current_ma}mA` : "";
  return [`[${liveBadge}]`, jointsStr, `folded=${Boolean(st.folded)}`, tempTxt, curTxt, st.substage || ""].filter(Boolean).join(" · ");
}

function resolveCameraSource(source, obs = null) {
  const cams = obs?.cameras || [];
  if (!cams.length || !source) return source;
  if (cams.some((c) => c.source_id === source)) return source;
  const aliases = { arm_s_top: "omx_arm_s_top", arm_s_wrist: "omx_arm_s_wrist", top: "omx_overhead", side: "omx_side", arm_a_wrist: "omx_wrist_a", arm_b_wrist: "omx_wrist_b" };
  const mapped = aliases[source];
  return mapped && cams.some((c) => c.source_id === mapped) ? mapped : source;
}

export function inspectorTargetsFromRows(rows, obs = null) {
  const cards = rows?.cards || [];
  const s3 = cards.find((c) => c.id === "cell_s") || {};
  const s5 = cards.find((c) => c.id === "cell_ab") || {};
  const armLive = rows?.armLiveStates || {};
  const cellSOccupant = rows?.cellOccupants?.cell_s || null;
  const cellAbOccupant = rows?.cellOccupants?.cell_ab || null;
  const mapViews = (views) => views.map((v) => (v.source ? { ...v, source: resolveCameraSource(v.source, obs) } : v));
  return [
    {
      id: "arm_s",
      cell_id: "cell_s",
      station_id: "S3",
      shortTab: "ARM_S · S3",
      title: "OMX-AI #3 · arm_s (cell_s · S3 하역 셔틀)",
      status: s3.status || "neutral",
      text: s3.text || "대기 중",
      healthText: s3.healthText || "folded: true (홈 대기)",
      jointLiveText: formatArmLiveJointText("arm_s", armLive, s3.healthText || "folded: true (홈 대기)"),
      task: s3.task || null,
      robot_id: cellSOccupant,
      dualPair: ["arm_s_top", "arm_s_wrist"],
      cameraViews: mapViews([
        {id: "arm_s_wrist", label: "arm_s 손목", source: "arm_s_wrist"},
        {id: "arm_s_top", label: "S3 상단", source: "arm_s_top"},
        ...(cellSOccupant ? [{id: "pinky_dock", label: "도킹 확대 (천장 Cam)", roiTarget: cellSOccupant}] : []),
      ]),
      buttons: s3.buttons || CELL_BUTTONS.cell_s,
      quickControls: (s3.quickControls || []).map((c) => c.clearArmHold ? {...c, clearArmHold: "arm_s"} : c),
    },
    {
      id: "arm_a",
      cell_id: "cell_ab",
      station_id: "S2",
      shortTab: "ARM_A · S5",
      title: "OMX-AI #1 · arm_a (cell_ab · S5 1·3층 적재)",
      status: s5.status || "neutral",
      text: s5.text || "대기 중",
      healthText: s5.healthText || "folded: true (홈 대기)",
      jointLiveText: formatArmLiveJointText("arm_a", armLive, s5.healthText || "folded: true (홈 대기)"),
      task: s5.task || null,
      robot_id: cellAbOccupant,
      dualPair: ["top", "arm_a_wrist"],
      cameraViews: mapViews([
        {id: "arm_a_wrist", label: "arm_a 손목", source: "arm_a_wrist"},
        {id: "top", label: "S5 상단", source: "top"},
        {id: "side", label: "측면 (A/B)", source: "side"},
        {id: "arm_b_wrist", label: "arm_b 손목", source: "arm_b_wrist"},
      ]),
      buttons: s5.buttons || CELL_BUTTONS.cell_ab,
      quickControls: (s5.quickControls || []).map((c) => c.clearArmHold ? {...c, clearArmHold: "arm_a"} : c),
    },
    {
      id: "arm_b",
      cell_id: "cell_ab",
      station_id: "S5",
      shortTab: "ARM_B · S5",
      title: "OMX-AI #2 · arm_b (cell_ab · S5 2층 적재·반출)",
      status: s5.status || "neutral",
      text: s5.text || "대기 중",
      healthText: s5.healthText || "folded: true (홈 대기)",
      jointLiveText: formatArmLiveJointText("arm_b", armLive, s5.healthText || "folded: true (홈 대기)"),
      task: s5.task || null,
      robot_id: cellAbOccupant,
      dualPair: ["top", "arm_b_wrist"],
      cameraViews: mapViews([
        {id: "arm_b_wrist", label: "arm_b 손목", source: "arm_b_wrist"},
        {id: "top", label: "S5 상단", source: "top"},
        {id: "side", label: "측면 (A/B)", source: "side"},
        {id: "arm_a_wrist", label: "arm_a 손목", source: "arm_a_wrist"},
      ]),
      buttons: s5.buttons || CELL_BUTTONS.cell_ab,
      quickControls: (s5.quickControls || []).map((c) => c.clearArmHold ? {...c, clearArmHold: "arm_b"} : c),
    },
    ...(s3.id ? [{...s3, cameraViews: mapViews(s3.cameraViews || []), shortTab: "CELL_S", dualPair: ["arm_s_top", "arm_s_wrist"], jointLiveText: formatArmLiveJointText("arm_s", armLive, s3.healthText)}] : []),
    ...(s5.id ? [{...s5, cameraViews: mapViews(s5.cameraViews || []), shortTab: "CELL_AB", dualPair: ["top", "arm_a_wrist"], jointLiveText: formatArmLiveJointText("arm_a", armLive, s5.healthText)}] : []),
  ];
}
