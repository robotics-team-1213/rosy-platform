/**
 * C20 arm skill state: one pure function so a robot row's words and the detail panel's words come from the same table
 * (plan 2026-11-14-rosy-vla-decision-ai-command.md 6.2 and 6.3). No DOM, no clock, no three.js; node tests it.
 *
 *   skillState({lifecycle, executor, policyId, version, step, guard, measured, ageS, leaseS, blocking}) -> {text, tag, readout}
 *     lifecycle  "proposed" | "waiting_approval" | "approved" | "running" | "measured_success" | "measured_failure" |
 *                "stopped" | "timed_out" | "fallback_proposed". Anything else reads EVIDENCE_LABEL.unavailable (D-280).
 *                proposed and waiting_approval are one row of the state table (`승인 대기`).
 *     executor   "ik_chunk" -> 규칙 운반, "act" | "smolvla" -> 학습 정책; unknown -> 정보 없음 (the executor is never guessed)
 *     policyId, version   policy name and its sha; the readout shows `policyId@sha8` only for a learned policy
 *     step       {n, of}   running prints `실행 중 n/N`
 *     guard      "ok" | "hold" | "estop" | "lock" | "loaded" | undefined   a guard row appears only when it is not ok
 *     measured   a measurement source (e.g. "verify_placed"). measured_success without one is NOT shown as success:
 *                a model receipt is not a measurement (D-293 4, D-308 5), so it reads 정보 없음.
 *     blocking   waiting for approval while it blocks a robot -> caution tag, else no tag
 *     text       row wording; tag  {state, icon?} for statusTag(tag.state, undefined, {icon: tag.icon}), or null (quiet)
 *     readout    [{label, value}] for the L3 strip: 실행기, 정책, 단계, 가드, 측정, 리스, 관측. Empty items are left out.
 *
 * fallback_proposed is a NEW proposal that needs a named approval, never an in-place swap (user decision 2026-11-14).
 * `fresh` is evidence freshness, not a lifecycle, so no state here uses it. Stop is danger (estop icon for E-stop,
 * safety icon for an owner HOLD); the tag is never the card (D-202).
 */
import {EVIDENCE_LABEL} from "./core_ui_logic.js";

export const SKILL_LIFECYCLES = Object.freeze(["proposed", "waiting_approval", "approved", "running", "measured_success", "measured_failure", "stopped", "timed_out", "fallback_proposed"]);
export const EXECUTOR_LABEL = Object.freeze({ik_chunk: "규칙 운반", act: "학습 정책", smolvla: "학습 정책"});
const LEARNED = new Set(["act", "smolvla"]);
const GUARD_LABEL = Object.freeze({hold: "HOLD", estop: "E-stop", lock: "잠금", loaded: "부하 든 채"});
const CAUTION = Object.freeze({state: "caution"});

const finite = value => typeof value === "number" && Number.isFinite(value);
const stepText = step => (finite(step?.n) && finite(step?.of) ? `${step.n}/${step.of}` : "");
const sha8 = version => String(version ?? "").slice(0, 8);

function row({lifecycle, step, guard, measured, blocking}) {
  switch (lifecycle) {
    case "proposed": case "waiting_approval": return {text: "승인 대기", tag: blocking ? CAUTION : null};
    case "approved": return {text: "승인됨 · 시작 대기", tag: null};
    case "running": return {text: stepText(step) ? `실행 중 ${stepText(step)}` : "실행 중", tag: null};
    case "measured_success": return measured && measured !== "model" ? {text: "측정 성공", tag: null} : null;
    case "measured_failure": return {text: "측정 실패", tag: guard === "lock" || guard === "loaded" ? {state: "danger", icon: "safety"} : CAUTION};
    case "stopped": return {text: "정지 · HOLD", tag: {state: "danger", icon: guard === "estop" ? "estop" : "safety"}};
    case "timed_out": return {text: "시간 초과 · HOLD", tag: CAUTION};
    case "fallback_proposed": return {text: "대체 제안됨 · 승인 필요", tag: CAUTION};
    default: return null;
  }
}

export function skillState(input = {}) {
  const {executor, policyId, version, step, guard, measured, ageS, leaseS} = input;
  const shown = row(input);
  if (!shown) return {text: EVIDENCE_LABEL.unavailable, tag: {state: "unknown"}, readout: []};
  const readout = [{label: "실행기", value: (Object.hasOwn(EXECUTOR_LABEL, executor) ? EXECUTOR_LABEL[executor] : EVIDENCE_LABEL.unavailable)}];
  if (LEARNED.has(executor) && policyId) readout.push({label: "정책", value: `${policyId}@${sha8(version) || EVIDENCE_LABEL.unavailable}`});
  if (stepText(step)) readout.push({label: "단계", value: stepText(step)});
  if (guard && guard !== "ok") readout.push({label: "가드", value: (Object.hasOwn(GUARD_LABEL, guard) ? GUARD_LABEL[guard] : EVIDENCE_LABEL.unavailable)});
  if (measured && measured !== "model" && input.lifecycle.startsWith("measured")) readout.push({label: "측정", value: String(measured)});
  if (finite(leaseS)) readout.push({label: "리스 잔여", value: `${leaseS}초`});
  if (finite(ageS) && ageS >= 0) readout.push({label: "관측", value: `${ageS}초 전`});
  return {...shown, readout};
}
