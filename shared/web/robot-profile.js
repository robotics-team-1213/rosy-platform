/**
 * C14 robot profile: the one pure model behind a robot row (robot-row.js). Robot arms and mobile robots become the
 * same shape, so a screen cannot show them in two vocabularies. No DOM, no import of ui.js: node can test it.
 *
 *   robotProfile(source, {staleAfterS = 5, lowBatteryPct = 20}) -> profile
 *
 *   source (the adopter maps its own record to this; every field but id and kind may be missing = unknown)
 *     id, name, kind        kind "mobile" | "arm"
 *     online, ageS          online false = disconnected; ageS (seconds since the last report) > staleAfterS = delayed;
 *                           neither given = unavailable. `evidence` ("fresh"|"delayed"|"disconnected"|"unavailable")
 *                           overrides this when the server already judged it (D-280).
 *     battery {percent, voltage, charging}                       mobile
 *     servo {currentMa, temperatureC}, torque true|false         arm
 *     task, place, pose {x, y} (m)                               task text; place text (station, cell) or a pose
 *     estop true|false      alarm {level: "caution"|"danger", text} overrides everything below
 *     detail                secondary text for the toggletip (voltage, joints, stop reason)
 *
 *   profile: {id, name, kind, kindLabel, link: {state, text, ageS}, power: {text, state, charging, torque},
 *             task: {text, state}, place: {text, state}, alarm: null | {level, text, tag}, detail}
 *     link.state is the freshness axis; alarm is the severity axis. They never share a colour (concept principle 3).
 *     alarm.tag is the statusTag state to draw ("caution" | "danger" | "unknown"); null alarm draws nothing.
 *
 * A value is never a constant: a missing one is EVIDENCE_LABEL.unavailable (valueText), a stale one carries its age.
 */
import {valueText} from "./value-text.js";
import {EVIDENCE_LABEL} from "./core_ui_logic.js";

export const ROBOT_KIND_LABEL = Object.freeze({arm: "로봇암", mobile: "이동로봇"});
const EVIDENCE_STATES = ["fresh", "delayed", "disconnected", "unavailable"];
const finite = value => typeof value === "number" && Number.isFinite(value);

function linkOf(source, staleAfterS) {
  const age = finite(source.ageS) && source.ageS >= 0 ? source.ageS : undefined;
  let state = EVIDENCE_STATES.includes(source.evidence) ? source.evidence : null;
  if (!state) {
    if (source.online === false) state = "disconnected";
    else if (source.online === true && age !== undefined) state = age > staleAfterS ? "delayed" : "fresh";
    else if (source.online === true) state = "fresh";
    else state = "unavailable";
  }
  const text = state === "delayed" && age !== undefined ? `${EVIDENCE_LABEL.delayed} · ${Math.round(age)}초 전` : EVIDENCE_LABEL[state];
  return {state, text, ageS: age};
}

// A value read through a link: fresh as is, stale with its age, unknown when the link says nothing.
function readValue(raw, link, opts = {}) {
  if (link.state === "unavailable") return valueText(null);
  if (link.state === "fresh") return valueText(raw, opts);
  return valueText(raw, {...opts, age: link.ageS, evidence: "delayed"});
}

function powerOf(source, kind, link) {
  if (kind === "mobile") {
    const battery = source.battery || {};
    const shown = readValue(finite(battery.percent) && battery.percent >= 0 && battery.percent <= 100 ? battery.percent : null, link, {unit: "%", digits: 0});
    const charging = battery.charging === true ? true : battery.charging === false ? false : null;
    const text = charging && shown.state !== "unavailable" ? `${shown.text} · 충전 중` : shown.text;
    return {text, state: shown.state, charging, torque: null};
  }
  const servo = source.servo || {};
  const torque = source.torque === true ? true : source.torque === false ? false : null;
  const torqueText = `토크 ${torque === null ? EVIDENCE_LABEL.unavailable : torque ? "켜짐" : "꺼짐"}`;
  // the link age is added once to the whole line, not to each reading
  const bare = link.state === "fresh" || link.state === "unavailable" ? link : {...link, ageS: undefined};
  const current = readValue(finite(servo.currentMa) && servo.currentMa >= 0 ? servo.currentMa : null, bare, {unit: " mA", digits: 0});
  const heat = readValue(finite(servo.temperatureC) ? servo.temperatureC : null, bare, {unit: " °C", digits: 0});
  const known = [current, heat].filter(part => part.state !== "unavailable");
  // torque is a plain fact, not a verdict: off is calm text, the arm just is not holding
  const text = known.length ? [torqueText, ...(current.state === "unavailable" ? [] : [`전류 ${current.text}`]), ...(heat.state === "unavailable" ? [] : [`온도 ${heat.text}`])].join(" · ") + (link.state === "delayed" && link.ageS !== undefined ? ` · ${Math.round(link.ageS)}초 전` : "") : torqueText;
  return {text, state: known.some(part => part.state === "delayed") ? "delayed" : known.length ? "fresh" : "unavailable", charging: null, torque};
}

function alarmOf(source, kind, link, lowBatteryPct) {
  const explicit = source.alarm;
  if (explicit && (explicit.level === "caution" || explicit.level === "danger") && explicit.text) {
    return {level: explicit.level, text: explicit.text, tag: explicit.level};
  }
  if (source.estop === true) return {level: "danger", text: "비상 정지", tag: "danger", icon: "estop"};
  const percent = source.battery?.percent;
  if (kind === "mobile" && link.state === "fresh" && finite(percent) && percent >= 0 && percent < lowBatteryPct && source.battery?.charging !== true) {
    return {level: "caution", text: "배터리 낮음", tag: "caution"};
  }
  // an arm reports no stop latch, so only a mobile robot's missing safety reading is an "unknown" alarm
  if (kind === "mobile" && link.state === "fresh" && source.estop !== false) return {level: "unknown", text: "안전 정보 없음", tag: "unknown"};
  return null; // normal is quiet; a stale or lost link is already said by the link tag
}

export function robotProfile(source, {staleAfterS = 5, lowBatteryPct = 20} = {}) {
  if (!source || (source.kind !== "arm" && source.kind !== "mobile")) throw new RangeError("robotProfile needs source.kind arm|mobile");
  const kind = source.kind;
  const link = linkOf(source, staleAfterS);
  const place = typeof source.place === "string" && source.place.trim() ? source.place.trim()
    : finite(source.pose?.x) && finite(source.pose?.y) ? `x ${source.pose.x.toFixed(2)} · y ${source.pose.y.toFixed(2)} m` : null;
  const id = String(source.id ?? "");
  return {
    id, kind, kindLabel: ROBOT_KIND_LABEL[kind], name: source.name || id,
    link,
    power: powerOf(source, kind, link),
    task: readValue(source.task, link),
    place: readValue(place, link),
    alarm: alarmOf(source, kind, link, lowBatteryPct),
    detail: typeof source.detail === "string" && source.detail.trim() ? source.detail.trim() : null,
  };
}

/** Group profiles for the roster: arms first, then mobile robots; each group keeps the given order. */
export function groupRobots(profiles) {
  return ["arm", "mobile"].map(kind => ({kind, label: ROBOT_KIND_LABEL[kind], rows: profiles.filter(profile => profile.kind === kind)}));
}
