// Rosy Pilot 입력 매핑(D-323 T3). 순수 함수만 — DOM·네트워크·시계를 모른다.
// 모든 입력원(스틱·페달·제자리 회전·키보드·게임패드)이 같은 hold-to-drive 원칙
// 아래 이 매핑을 공유한다.
//
// 부호 규약은 ROS REP-103 이다: linear > 0 전진, angular > 0 반시계(좌회전).
// 화면·게임패드의 x 축은 오른쪽이 + 이므로 turn = -x 로 뒤집는다. 이 한 줄이
// 틀리면 휠을 오른쪽으로 꺾었는데 가제보·실기가 왼쪽으로 돈다.

// 프리셋은 CORE 가 실제로 허용하는 수동 상한의 비율이다. 절대값을 두면 CORE 가
// 축마다 따로 잘라(box clip) 저·중·고가 같아지고 회전 반경까지 틀어진다.
export const PRESETS = {
  low: 0.4,
  mid: 0.7,
  high: 1.0,
};

// 정밀 모드 배율 — 좁은 곳 맞추기, 제자리 미세 조향. 팔 조그도 같은 개념을 쓴다.
export const FINE_SCALE = 0.3;

// CORE 한도를 아직 못 읽었을 때 쓰는 보수값(rosy_default.yaml safety.manual_*).
export const FALLBACK_LIMITS = {linear: 0.15, angular: 0.6};

// 스틱을 옆으로 민 방향이 수평에서 이 각도 안이면 전후진을 0 으로 붙인다(제자리 회전).
// 손가락은 정확히 수평으로 못 민다 — 붙이지 않으면 제자리 회전이 작은 호로 샌다.
export const PIVOT_SNAP_DEG = 12;

export const DEFAULT_CONFIG = {
  preset: "mid",
  deadzone: 0.12,
  curve: "expo",
  invertAngular: false,
  fine: false,
};

function clampUnit(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return 0;
  return Math.min(1, Math.max(-1, n));
}

// A CORE limit: finite and >= 0, else unknown (null). 0 is real — the drive is announced but
// limited to standstill (D-411 B, PUT /safety/limits accepts 0) — so it never falls back.
function positive(value) {
  if (value === null || value === undefined || value === "") return null;
  const n = Number(value);
  return Number.isFinite(n) && n >= 0 ? n : null;
}

function curveOf(value, config) {
  // expo 는 x^2 대신 0.35x + 0.65x^3 — 중앙은 섬세하고 끝은 1 에 닿는다.
  return config.curve === "expo" ? 0.35 * value + 0.65 * value ** 3 : value;
}

function deadzoneOf(config) {
  return Math.min(0.95, Math.max(0, Number(config.deadzone) || 0));
}

// -1..1 원시 축 하나를 데드존 제거·감도 곡선·클램프한 -1..1 로 변환한다.
// 원점 대칭: shapeAxis(-x) === -shapeAxis(x).
export function shapeAxis(value, config = DEFAULT_CONFIG) {
  const clamped = clampUnit(value);
  const mag = Math.abs(clamped);
  const deadzone = deadzoneOf(config);
  if (mag <= deadzone) return 0;
  return Math.sign(clamped) * curveOf((mag - deadzone) / (1 - deadzone), config);
}

// 2 축 스틱: 원형(radial) 데드존으로 크기만 깎고 방향은 보존한다. 축마다 깎으면
// 대각선 입력이 축 쪽으로 끌려가 "살짝 오른쪽 앞" 이 "직진" 으로 뭉개진다.
export function shapeStick(x, y, config = DEFAULT_CONFIG) {
  let sx = clampUnit(x);
  let sy = clampUnit(y);
  const mag = Math.hypot(sx, sy);
  if (mag > 1) {
    sx /= mag;
    sy /= mag;
  }
  const r = Math.min(1, mag);
  const deadzone = deadzoneOf(config);
  if (r <= deadzone) return {x: 0, y: 0};
  const scaled = curveOf((r - deadzone) / (1 - deadzone), config) / r;
  return {x: sx * scaled, y: sy * scaled};
}

function pairAxis(positiveKey, negativeKey) {
  if (positiveKey && negativeKey) return 0;
  if (positiveKey) return 1;
  if (negativeKey) return -1;
  return 0;
}

// CORE 한도(GET /api/v1/safety limits) × 프리셋 × 정밀 → 이번 틱 상한.
// CORE 는 manual_* 와 max_* 중 작은 쪽으로 자르므로 여기서도 같게 맞춘다.
export function resolveLimits(serverLimits = null, config = DEFAULT_CONFIG) {
  const linearCap = Math.min(
    positive(serverLimits?.manual_linear) ?? FALLBACK_LIMITS.linear,
    positive(serverLimits?.max_linear) ?? Infinity,
    positive(serverLimits?.session_linear) ?? Infinity,
  );
  const angularCap = Math.min(
    positive(serverLimits?.manual_angular) ?? FALLBACK_LIMITS.angular,
    positive(serverLimits?.max_angular) ?? Infinity,
  );
  const fraction = PRESETS[config.preset] ?? PRESETS.low;
  const fine = config.fine ? FINE_SCALE : 1;
  return {
    linear: linearCap * fraction * fine,
    angular: angularCap * fraction * fine,
    linearCap,
    angularCap,
  };
}

// source:
//   {kind:"stick", x, y}            화면 스틱 — x 오른쪽 +, y 위(전진) +
//   {kind:"pad", x, y}              게임패드 — stick 과 같은 규약(y 는 호출자가 뒤집어 넘긴다)
//   {kind:"pedals", forward, reverse, x}  홀드 페달 + 스틱 x 조향
//   {kind:"pivot", dir}             제자리 회전 — dir +1 좌(반시계), -1 우(시계)
//   {kind:"keys", up, down, left, right}
// 반환: {linear, angular, pivot} — CORE 상한 안의 최종 명령값. pivot 은 전후진 0 에
//        회전만 있는 제자리 회전인가.
export function mapInput(source = {}, config = DEFAULT_CONFIG, limits = resolveLimits(null, config)) {
  let throttle = 0;
  let turn = 0;
  if (source.kind === "stick" || source.kind === "pad") {
    const shaped = shapeStick(source.x, source.y, config);
    const snap = Math.tan((PIVOT_SNAP_DEG * Math.PI) / 180);
    throttle = Math.abs(shaped.y) <= Math.abs(shaped.x) * snap ? 0 : shaped.y;
    turn = -shaped.x;
  } else if (source.kind === "pedals") {
    throttle = pairAxis(Boolean(source.forward), Boolean(source.reverse));
    turn = -shapeAxis(source.x ?? 0, config);
  } else if (source.kind === "pivot") {
    turn = Math.sign(Number(source.dir) || 0);
  } else if (source.kind === "keys") {
    throttle = pairAxis(Boolean(source.up), Boolean(source.down));
    turn = pairAxis(Boolean(source.left), Boolean(source.right));
  }
  // 반전은 조향 입력에만 건다. 제자리 회전 버튼·키는 이름표(↺/↻)가 곧 방향이다.
  const direction = config.invertAngular && source.kind !== "pivot" ? -1 : 1;
  const linear = throttle * limits.linear;
  const angular = turn * direction * limits.angular;
  return {
    // -0 은 JSON·비교에서 혼란만 준다.
    linear: linear === 0 ? 0 : linear,
    angular: angular === 0 ? 0 : angular,
    pivot: linear === 0 && angular !== 0,
  };
}

// 가속 램프 — 게임식 스로틀 감각. 명령 크기를 키울 때만 초당 rate 로 올린다.
// 줄이기·놓기·방향 전환은 즉시다: 정지가 늦어지는 램프는 안전 규칙(놓으면 바로 0)을 깬다.
// 방향이 바뀌면 0 에서 다시 오른다.
export const SLEW_RATES = {linear: 0.5, angular: 3.0};   // m/s², rad/s²

function slewAxis(previous, target, step) {
  const reversing = previous !== 0 && target !== 0 && Math.sign(previous) !== Math.sign(target);
  const base = reversing ? 0 : previous;
  if (!reversing && Math.abs(target) <= Math.abs(previous)) return target;
  const delta = target - base;
  return base + Math.sign(delta) * Math.min(Math.abs(delta), step);
}

// previous·target: {linear, angular}. dtSeconds 는 지난 틱 이후 시간(상한 0.25 s —
// 탭이 멈췄다 돌아와도 한 번에 뛰지 않게).
export function slewCommand(previous, target, dtSeconds, rates = SLEW_RATES) {
  const dt = Math.min(0.25, Math.max(0, Number(dtSeconds) || 0));
  const linear = slewAxis(previous?.linear ?? 0, target.linear, rates.linear * dt);
  const angular = slewAxis(previous?.angular ?? 0, target.angular, rates.angular * dt);
  return {
    ...target,
    linear: linear === 0 ? 0 : linear,
    angular: angular === 0 ? 0 : angular,
  };
}
