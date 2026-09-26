// 분류 — 셋이 동시에 잘못됐을 때 하나만 머리를 차지한다(concept 16 Law 1, D-72).
//
// 색 예산을 경보 둘로 줄여 놓았는데(D-82) 동시 고장 규칙이 없으면 빨간 것이
// 셋 생기고 그 작업이 무의미해진다. 그래서 화면은 언제나 **하나**를 머리에
// 두고 나머지는 색 없는 맥락으로 내린다.
//
// 서버 필드를 새로 요구하지 않는다. 이미 오는 것만 읽는다:
// safety.estop, battery_status.level, 채널별 state.evidence, navigation,
// inventory descriptors의 blocked 이유.

// 순서는 심각도가 아니라 **운용자가 지금 할 수 있는 일**이다. 못 고치는 것이
// 머리를 차지하면 화면이 쓸모없어진다. 이 표가 규칙이고, 계약 시험이 이 표를
// 지킨다 — 저장소에 JS 실행 러너가 없어 함수가 아니라 표를 단언한다.
export const CATEGORY_ORDER = [
  "hazard", // 물리적 위험 — 사람이나 장비가 다칠 수 있다
  "blocked", // 이동 차단 — 지금 못 간다
  "mission", // 임무 위협 — 갈 수는 있지만 끝내지 못한다
  "accuracy", // 정확도 저하 — 간다, 다만 믿음이 덜하다
  "observation", // 관측 결손 — 로봇은 멀쩡한데 내가 못 본다
];

// 채널이 낡거나 끊겼을 때 어느 범주에 들어가는지. 위치 추정은 주행 정확도를
// 깎고, 나머지는 내가 못 보는 것이다.
const CHANNEL_CATEGORY = {
  pose: "accuracy",
  velocity: "observation",
  battery: "observation",
  navigation: "observation",
  safety: "hazard",
  docking: "observation",
};

const CHANNEL_LABEL = {
  pose: "위치 추정",
  velocity: "속도",
  battery: "배터리",
  navigation: "주행 상태",
  safety: "안전 회로",
  docking: "도킹",
};

const BATTERY_FAULT = {
  warning: { category: "mission", title: "배터리 부족", detail: "이 임무를 끝내기 전에 충전이 필요할 수 있습니다." },
  critical: { category: "mission", title: "배터리 위험", detail: "지금 도크로 돌려보내세요." },
  deep: { category: "hazard", title: "배터리 고갈", detail: "모터가 멈추고 호스트가 곧 꺼집니다." },
};

// CORE-only runtime (D-161): the server blocks every hardware descriptor with
// this reason. It is one fact, not five faults, and it is a deliberate
// configuration rather than a failure, so it is told once and without colour.
export const CORE_ONLY_REASON = "runtime_mode:core";
export const CORE_ONLY_TEXT = "하드웨어 런타임 꺼짐 (CORE-only)";
// rosy-io in no-motion mode (D-192): battery/odometry flow, motor/ready is
// false, torque is off and cmd_vel has no subscriber.
export const DRIVE_DISABLED_REASON = "drive_disabled:no_motion";
export const DRIVE_DISABLED_TEXT = "하드웨어 런타임 켜짐 · 구동 꺼짐 (무동작)";
export const NAVIGATION_ABSENT_REASON = "navigation_absent";
export const NAVIGATION_ABSENT_TEXT = "내비게이션 스택 없음";

// Server reason codes (API Ref §9.1, v1.21) in operator words. Unknown codes
// are shown as sent.
const REASON_TEXT = {
  [CORE_ONLY_REASON]: CORE_ONLY_TEXT,
  [DRIVE_DISABLED_REASON]: DRIVE_DISABLED_TEXT,
  [NAVIGATION_ABSENT_REASON]: NAVIGATION_ABSENT_TEXT,
  drive_absent: "모터 드라이버 보고 없음 (motor/ready 미수신)",
  drive_lease_expired: "모터 준비 신호 끊김",
  hardware_silent: "하드웨어 런타임 신호 끊김",
  "device_state:SAFE_STOP": "정지 상태",
  "device_state:BOOTING": "기동 중",
  "device_state:FAULT": "고장",
};

export function reasonText(reason) {
  return REASON_TEXT[reason] || reason;
}

// Configurations, not faults: each is told once, without colour, however
// many descriptors it blocks.
export const CONFIGURED_REASONS = {
  [CORE_ONLY_REASON]: {
    id: "runtime.core_only",
    title: CORE_ONLY_TEXT,
    detail: "모터·센서 출처가 구성되지 않아 이동과 위치 추정을 제공하지 않습니다.",
  },
  [DRIVE_DISABLED_REASON]: {
    id: "runtime.drive_disabled",
    title: DRIVE_DISABLED_TEXT,
    detail: "배터리·주행계는 들어오지만 motor/ready가 false입니다. torque가 꺼져 있고 cmd_vel을 받지 않아 이동을 제공하지 않습니다.",
  },
  [NAVIGATION_ABSENT_REASON]: {
    id: "runtime.navigation_absent",
    title: NAVIGATION_ABSENT_TEXT,
    detail: "Nav2/SLAM 노드가 활성으로 보고되지 않아 목표 주행과 위치 추정을 제공하지 않습니다.",
  },
};

// Every e-stop CORE knows of is a software stop: CORE holds cmd_vel at zero.
// None of them is a physical motor power cut, so none may claim one.
export function estopFault(source) {
  const text = String(source || "");
  if (text.startsWith("api:")) {
    return {
      title: `API 비상정지 (${text.slice(4) || "?"})`,
      detail: "소프트웨어 정지입니다. CORE가 이동 명령을 0으로 막고 있습니다. 모터 전원을 끊은 것은 아닙니다. 해제 권한이 있는 운용자가 해제합니다.",
    };
  }
  if (text.startsWith("battery")) {
    return {
      title: "배터리 보호 정지",
      detail: "배터리 정책이 건 소프트웨어 정지입니다. 충전 뒤 해제하세요.",
    };
  }
  if (text.startsWith("control:")) {
    return {
      title: "제어 정책 정지",
      detail: `정책(${text.slice(8) || "?"})이 건 소프트웨어 정지입니다. 원인을 확인한 뒤 해제하세요.`,
    };
  }
  return {
    title: "비상정지",
    detail: text
      ? `CORE가 이동 명령을 0으로 막고 있습니다(출처: ${text}).`
      : "CORE가 이동 명령을 0으로 막고 있습니다.",
  };
}

const BLOCKING_NAVIGATION = {
  BLOCKED: "경로를 찾지 못했습니다. 목표를 바꾸거나 장애물을 치우세요.",
  FAILED: "주행이 실패했습니다. 다시 하달하기 전에 원인을 확인하세요.",
};

function evidenceOf(state, channel) {
  return state?.evidence?.[channel]?.evidence;
}

/** 지금 살아 있는 고장을 모은다. 순서는 매기지 않는다. */
function collectFaults({ state, inventory, safetySource } = {}) {
  const faults = [];

  if (state?.safety?.estop) {
    faults.push({ id: "safety.estop", category: "hazard", ...estopFault(safetySource) });
  }

  const level = state?.battery_status?.level;
  const battery = BATTERY_FAULT[level];
  if (battery) {
    faults.push({ id: `battery.${level}`, category: battery.category, title: battery.title, detail: battery.detail });
  }

  const navDetail = BLOCKING_NAVIGATION[state?.navigation];
  if (navDetail) {
    faults.push({ id: `navigation.${state.navigation}`, category: "blocked", title: "주행 불가", detail: navDetail });
  }

  for (const [channel, category] of Object.entries(CHANNEL_CATEGORY)) {
    const judged = evidenceOf(state, channel);
    if (judged !== "delayed" && judged !== "disconnected") continue;
    const label = CHANNEL_LABEL[channel] || channel;
    faults.push({
      id: `evidence.${channel}`,
      category,
      title: judged === "disconnected" ? `${label} 수신 끊김` : `${label} 지연`,
      detail:
        judged === "disconnected"
          ? "출처는 있는데 값이 오지 않습니다."
          : "값이 임계보다 오래됐습니다. 이 값에 기대는 조작은 잠깁니다.",
    });
  }

  const configured = new Set();
  for (const row of inventory?.descriptors || []) {
    if (row?.state !== "blocked") continue;
    if (CONFIGURED_REASONS[row.reason]) {
      configured.add(row.reason);
      continue;
    }
    faults.push({
      id: `capability.${row.id}`,
      category: "blocked",
      title: `${row.id} 사용 불가`,
      detail: row.reason ? `이유: ${reasonText(row.reason)}` : "서버가 이유를 주지 않았습니다.",
    });
  }
  for (const reason of configured) {
    faults.push({ category: "observation", ...CONFIGURED_REASONS[reason] });
  }

  return faults;
}

/**
 * 범주 순으로 정렬한다. 같은 범주면 **최근에 생긴 것**이 앞선다 — 운용자가
 * 마지막으로 한 행동과 이어져 있을 확률이 높다.
 *
 * `seenAt`은 고장 id를 처음 본 시각의 맵이다. 서버가 발생 시각을 주지 않으므로
 * 화면이 기억한다.
 */
function orderFaults(faults, seenAt = {}) {
  return [...faults].sort((a, b) => {
    const rank = CATEGORY_ORDER.indexOf(a.category) - CATEGORY_ORDER.indexOf(b.category);
    if (rank !== 0) return rank;
    return (seenAt[b.id] || 0) - (seenAt[a.id] || 0);
  });
}

/** 처음 본 시각을 기록하고 사라진 고장은 잊는다. */
function trackSeen(faults, seenAt, now) {
  const next = {};
  for (const fault of faults) next[fault.id] = seenAt[fault.id] || now;
  return next;
}

export function triage({ state, inventory, safetySource, seenAt = {}, now = Date.now() } = {}) {
  const faults = collectFaults({ state, inventory, safetySource });
  const tracked = trackSeen(faults, seenAt, now);
  const ordered = orderFaults(faults, tracked);
  return { headline: ordered[0] || null, context: ordered.slice(1), seenAt: tracked };
}
