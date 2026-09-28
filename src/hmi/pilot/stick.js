// Rosy Pilot 입력 매핑(D-323 T3). 순수 함수만 — DOM·네트워크·시계를 모른다.
// 모든 입력원(패드·페달·키보드)이 같은 hold-to-drive 원칙 아래 이 매핑을 공유한다.

export const PRESETS = {
  // 클라이언트 측 스케일 상한. CORE는 자기 안전 한도를 별도로 적용한다.
  low: {linear: 0.15, angular: 0.6},
  mid: {linear: 0.35, angular: 1.2},
  high: {linear: 0.6, angular: 2.0},
};

export const DEFAULT_CONFIG = {
  preset: "low",
  deadzone: 0.18,
  curve: "linear",
  invertAngular: false,
};

function clampUnit(value) {
  if (!Number.isFinite(value)) return 0;
  return Math.min(1, Math.max(-1, value));
}

// -1..1 원시 축을 데드존 제거·감도 곡선·클램프한 -1..1 로 변환한다.
// 원점 대칭: shapeAxis(-x) === -shapeAxis(x).
export function shapeAxis(value, config = DEFAULT_CONFIG) {
  const clamped = clampUnit(value);
  const mag = Math.abs(clamped);
  const deadzone = Math.min(0.95, Math.max(0, Number(config.deadzone) || 0));
  if (mag <= deadzone) return 0;
  let shaped = (mag - deadzone) / (1 - deadzone);
  if (config.curve === "expo") shaped *= shaped;
  return Math.sign(clamped) * shaped;
}

function pairAxis(positive, negative) {
  if (positive && negative) return 0;
  if (positive) return 1;
  if (negative) return -1;
  return 0;
}

// source: {kind:"pad", x, y} | {kind:"pedals", forward, reverse, steer}
//       | {kind:"keys", up, down, left, right}
// 반환: {linear, angular} — preset 스케일을 곱한 최종 명령값.
export function mapInput(source = {}, config = DEFAULT_CONFIG) {
  const preset = PRESETS[config.preset] ?? PRESETS.low;
  let linearAxis = 0;
  let angularAxis = 0;
  if (source.kind === "pad") {
    linearAxis = Number(source.y) || 0;
    angularAxis = Number(source.x) || 0;
  } else if (source.kind === "pedals") {
    linearAxis = pairAxis(Boolean(source.forward), Boolean(source.reverse));
    angularAxis = clampUnit(Number(source.steer) || 0);
  } else if (source.kind === "keys") {
    linearAxis = pairAxis(Boolean(source.up), Boolean(source.down));
    angularAxis = pairAxis(Boolean(source.left), Boolean(source.right));
  }
  const direction = config.invertAngular ? -1 : 1;
  return {
    linear: shapeAxis(linearAxis, config) * preset.linear,
    angular: shapeAxis(angularAxis, config) * direction * preset.angular,
  };
}
