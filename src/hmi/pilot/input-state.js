// 입력 홀드 상태와 stick 매핑(D-323 T7/T8). DOM 을 모른다 — Node 시험 가능.
// 설정은 브라우저 localStorage(screens/inputs.js, T8)가 쓰고 여기선 읽기만 한다.

import {mapInput, DEFAULT_CONFIG} from "./stick.js";

const STATE = {steer: 0, forward: false, reverse: false};
const CONFIG_KEY = "rosy.pilot.input";

function clampUnit(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return 0;
  return Math.min(1, Math.max(-1, n));
}

export function setSteerInput(value) {
  STATE.steer = clampUnit(value);
}

export function setPedal(key, value) {
  if (key === "forward" || key === "reverse") STATE[key] = Boolean(value);
}

export function currentCommandSource() {
  if (STATE.forward || STATE.reverse || STATE.steer !== 0) {
    return {kind: "pedals", forward: STATE.forward, reverse: STATE.reverse, steer: STATE.steer};
  }
  return null;
}

export function inputConfig() {
  try {
    return {...DEFAULT_CONFIG, ...JSON.parse(localStorage.getItem(CONFIG_KEY) ?? "{}")};
  } catch (error) {
    return {...DEFAULT_CONFIG};
  }
}

export function saveInputConfig(patch) {
  const merged = {...inputConfig(), ...patch};
  localStorage.setItem(CONFIG_KEY, JSON.stringify(merged));
  return merged;
}

export function stickMap(source) {
  return mapInput(source ?? {kind: "pedals", forward: false, reverse: false, steer: 0},
    inputConfig());
}
