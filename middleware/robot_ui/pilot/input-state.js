// 입력 홀드 상태와 stick 매핑(D-323 T7/T8). DOM 을 모른다 — Node 시험 가능.
// 설정은 브라우저 localStorage(screens/inputs.js, T8)가 쓰고 여기선 읽기만 한다.
// CORE 한도는 주행 화면이 GET /api/v1/safety 로 읽어 setServerLimits 로 넣는다.

import {mapInput, resolveLimits, DEFAULT_CONFIG} from "./stick.js";

const STATE = {x: 0, y: 0, forward: false, reverse: false, pivotLeft: false, pivotRight: false};
const CONFIG_KEY = "rosy.pilot.input";
let serverLimits = null;

function clampUnit(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return 0;
  return Math.min(1, Math.max(-1, n));
}

// 화면 스틱: x 오른쪽 +, y 위(전진) +.
export function setStickInput(x, y) {
  STATE.x = clampUnit(x);
  STATE.y = clampUnit(y);
}

export function setPedal(key, value) {
  if (key === "forward" || key === "reverse") STATE[key] = Boolean(value);
}

// 제자리 회전 버튼: "left"(반시계)·"right"(시계) 각각 누름 상태. 둘 다면 0.
export function setPivot(side, held) {
  if (side === "left") STATE.pivotLeft = Boolean(held);
  if (side === "right") STATE.pivotRight = Boolean(held);
}

export function releaseAll() {
  Object.assign(STATE, {x: 0, y: 0, forward: false, reverse: false, pivotLeft: false, pivotRight: false});
}

// 우선순위: 제자리 회전 > 페달(+스틱 x 조향) > 스틱. 제자리 회전은 전후진을
// 무시한다 — 누르는 동안 로봇은 그 자리에서만 돈다.
export function currentCommandSource() {
  if (STATE.pivotLeft !== STATE.pivotRight) return {kind: "pivot", dir: STATE.pivotLeft ? 1 : -1};
  if (STATE.forward || STATE.reverse) {
    return {kind: "pedals", forward: STATE.forward, reverse: STATE.reverse, x: STATE.x};
  }
  if (STATE.x !== 0 || STATE.y !== 0) return {kind: "stick", x: STATE.x, y: STATE.y};
  return null;
}

export function setServerLimits(limits) {
  serverLimits = limits && typeof limits === "object" ? {...limits} : null;
}

// D-411 B: a device whose base_velocity says `fine: false` has no fine scale; a stored
// preference stays stored but does not apply to it.
let fineAllowed = true;
export function setFineAllowed(allowed) {
  fineAllowed = allowed !== false;
}

export function inputConfig() {
  let config;
  try {
    config = {...DEFAULT_CONFIG, ...JSON.parse(localStorage.getItem(CONFIG_KEY) ?? "{}")};
  } catch (error) {
    config = {...DEFAULT_CONFIG};
  }
  return fineAllowed ? config : {...config, fine: false};
}

export function saveInputConfig(patch) {
  const merged = {...inputConfig(), ...patch};
  try {
    localStorage.setItem(CONFIG_KEY, JSON.stringify(merged));
  } catch (error) {
    // 저장이 막힌 브라우저(사생활 창 등)에서도 이번 세션 값은 돌려준다.
  }
  return merged;
}

export function currentLimits() {
  return resolveLimits(serverLimits, inputConfig());
}

export function stickMap(source) {
  const config = inputConfig();
  return mapInput(source ?? {kind: "stick", x: 0, y: 0}, config, resolveLimits(serverLimits, config));
}
