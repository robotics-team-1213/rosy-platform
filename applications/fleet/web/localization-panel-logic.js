// Pure monitoring & D-1022 command-readiness logic for Pinky localization in the Fleet robot panel.

import { tripPreviewSummary } from "/console/assets/trip-preview-summary.js";
import { tripStartReason } from "/console/assets/site-map-model.js";
import { tripErrorText } from "/console/assets/trip-display.js";

const MIN_CONFIRM_FIT = 0.85;
export const MIN_BINDING_SAMPLES = 4;
export const MIN_BINDING_SPAN_M = 1.0;
export const STILL_LINEAR_MPS = 0.01;
export const STILL_ANGULAR_RADPS = 0.02;
const MAX_TRACK_AGE_S = 1.0;

const LOC_LABELS = { LOCALIZED: "위치 확정", CANDIDATES: "후보 대기", SUSPECT: "위치 확인 필요", UNKNOWN: "위치 미확인" };
const NAV_REASONS = { navigation_absent: "위치 확정 후 항법 준비" };
const BINDING_REASONS = {
  MAP_BINDING_REQUIRED: "지도 결속 필요",
  MAP_BINDING_GRID_CHANGED: "지도 격자 변경됨 · 재결속 필요",
  MAP_BINDING_SITE_CHANGED: "현장 지도 변경됨 · 재결속 필요",
};

export function consoleTripStartReason(input) {
  const common = tripStartReason(input), code = input.plan?.nav2_preflight?.code;
  if (common || !code) return common;
  return code === "ROBOT_POSE_UNTRUSTED" ? "로봇 CORE의 지도 위치가 확정되어야 Nav2로 출발할 수 있습니다"
    : (BINDING_REASONS[code] || tripErrorText(code));
}

export function consolePlanSummaryText(plan) {
  const parking = plan.parking_handoff;
  const road = tripPreviewSummary(plan);
  const summary = parking ? `${road} · ${parking.staging_place_id} 정차 후 ${parking.bay_id} 후진 주차` : road;
  const frame = plan.nav2_preflight;
  if (!frame) return summary;
  return !frame.binding_required && frame.binding_status !== "MATCHED"
    ? `${summary} · Nav2 · 승인 지도 결속 미확인 (현장 설정상 선택)` : `${summary} · Nav2`;
}

const finite = (v) => (typeof v === "number" && Number.isFinite(v) ? v : null);
const candidatesOf = (locPayload) => (Array.isArray(locPayload?.candidates?.candidates) ? locPayload.candidates.candidates : []);

export const candidateHeadingLabel = (yaw) => (Number.isFinite(yaw) ? `방향 ${Math.round(yaw * 180 / Math.PI)}°` : "방향 미확인");

function baseGate({ robot, isOperator, operatorReason = "", namedReason, stateUnavailable }) {
  if (stateUnavailable) return "Fleet 상태를 확인할 수 없습니다.";
  if (!robot?.online) return "로봇이 오프라인입니다.";
  if (!isOperator) return operatorReason || "조작 권한 없음";
  return namedReason || "";
}

export function bindingSpanM(samples) {
  if (!Array.isArray(samples) || samples.length < 2) return 0;
  let worst = 0;
  for (let i = 0; i < samples.length; i += 1) {
    const a = samples[i]?.site;
    if (!Array.isArray(a) || a.length < 2) continue;
    for (let j = i + 1; j < samples.length; j += 1) {
      const b = samples[j]?.site;
      if (Array.isArray(b) && b.length >= 2) worst = Math.max(worst, Math.hypot(a[0] - b[0], a[1] - b[1]));
    }
  }
  return worst;
}

export function buildBindingPayload(samples) {
  if (!Array.isArray(samples) || samples.length < MIN_BINDING_SAMPLES) return null;
  if (bindingSpanM(samples) < MIN_BINDING_SPAN_M) return null;
  const pick = (s) => ({ robot: s.robot, site: s.site });
  return { pairs: samples.slice(0, -1).map(pick), holdout: samples.slice(-1).map(pick) };
}

export function summarizeLocalizationPanel({ robot, locPayload, bindingPayload, trackRow }) {
  const inner = robot?.state || {};
  const loc = locPayload?.localization || inner.localization || robot?.localization || {};
  const locState = loc.state || "UNKNOWN";
  const candidates = candidatesOf(locPayload);
  const fits = candidates.map((c) => finite(c?.scan_fit)).filter((v) => v !== null);
  const bestFit = fits.length ? Math.max(...fits) : null;

  let locLabel = LOC_LABELS[locState] || "위치 미확인";
  if (locState !== "LOCALIZED" && candidates.length) {
    locLabel = `후보 ${candidates.length}건${bestFit !== null ? ` · 적합도 ${bestFit.toFixed(2)}` : ""}`;
  } else if (locState === "LOCALIZED" && finite(inner.pose?.x) !== null && finite(inner.pose?.y) !== null) {
    locLabel = `위치 확정 (${inner.pose.x.toFixed(2)}, ${inner.pose.y.toFixed(2)})`;
  }

  const navReady = Boolean(robot?.capabilities?.navigation?.goal_navigation);
  const navLabel = !robot?.online ? "로봇 오프라인" : navReady ? "주행 가능" : (NAV_REASONS[robot?.capabilities?.withheld?.reason] || "위치 확정 대기");
  const gridId = inner.map_grid_id || bindingPayload?.robot_grid_id || null;
  const bindingMatched = Boolean(bindingPayload?.matches);
  const gapM = finite(bindingPayload?.slam_camera_gap_m);
  const bindingReason = bindingPayload?.reason || null;
  const bindingLabel = bindingMatched
    ? `결속 완료${gapM !== null ? ` · 오차 ${gapM.toFixed(2)} m` : ""}`
    : (BINDING_REASONS[bindingReason] || "지도 결속 필요");

  const tx = finite(trackRow?.x);
  const ty = finite(trackRow?.y);
  const trackConfirmed = trackRow?.state === "CONFIRMED" && tx !== null && ty !== null;
  const trackLabel = trackConfirmed ? `확인됨 (${tx.toFixed(2)}, ${ty.toFixed(2)})` : "미확인";
  const kvRows = [["위치 상태", locLabel], ["자율 항법", navLabel], ["지도 결속", bindingLabel], ["격자 식별자", gridId], ["천장 추적", trackLabel]];
  return { locState, locLabel, candidates, bestFit, navReady, bindingMatched, bindingReason, gridId, gapM, trackConfirmed, trackLabel, kvRows };
}

export function confirmReason({ robot, locPayload, candidateIndex = 0, isOperator, operatorReason = "", namedReason, stateUnavailable }) {
  const blocked = baseGate({ robot, isOperator, operatorReason, namedReason, stateUnavailable });
  if (blocked) return blocked;
  const loc = locPayload?.localization || robot?.state?.localization || {};
  if (loc.state === "LOCALIZED") return "이미 위치가 확정되었습니다.";
  const candidates = candidatesOf(locPayload);
  if (!candidates.length) return "확정할 위치 후보가 아직 없습니다.";
  if (!Number.isInteger(candidateIndex) || candidateIndex < 0 || candidateIndex >= candidates.length) return "후보 번호가 올바르지 않습니다.";
  const fit = finite(candidates[candidateIndex]?.scan_fit);
  if (fit === null || fit < MIN_CONFIRM_FIT) return `후보 스캔 적합도(${fit === null ? "—" : fit.toFixed(2)})가 기준 ${MIN_CONFIRM_FIT.toFixed(2)} 미만입니다.`;
  return "";
}

export function relocalizeReason({ robot, locPayload, isOperator, operatorReason = "", namedReason, stateUnavailable }) {
  const blocked = baseGate({ robot, isOperator, operatorReason, namedReason, stateUnavailable });
  if (blocked) return blocked;
  const loc = locPayload?.localization || robot?.state?.localization || {};
  if (loc.state === "LOCALIZED") return "이미 위치가 확정되었습니다.";
  return robot?.state?.safety?.estop !== false ? "비상정지 해제 상태를 확인한 뒤 재탐색하세요." : "";
}

export function captureBindingSample({ robot, trackRow, existingSamples = [], existingGridId = null }) {
  if (!robot?.online) return { ok: false, reason: "로봇이 오프라인입니다." };
  const inner = robot.state || {};
  const loc = inner.localization || {};
  if (loc.state !== "LOCALIZED" || loc.pose_frame !== "map") return { ok: false, reason: "먼저 위치 확정을 완료해야 결속점을 채집할 수 있습니다." };
  const lin = finite(inner.velocity?.linear ?? 0);
  const ang = finite(inner.velocity?.angular ?? 0);
  if (lin === null || ang === null || Math.abs(lin) >= STILL_LINEAR_MPS || Math.abs(ang) >= STILL_ANGULAR_RADPS) {
    return { ok: false, reason: "로봇을 완전히 정지시킨 뒤 결속점을 채집하세요." };
  }
  const gridId = inner.map_grid_id;
  if (typeof gridId !== "string" || !gridId) return { ok: false, reason: "로봇 지도 격자 정보가 아직 없습니다." };
  if (existingGridId && existingGridId !== gridId) return { ok: false, reason: "지도 격자가 바뀌어 기존 채집점을 초기화한 뒤 다시 채집하세요." };
  const rx = finite(inner.pose?.x);
  const ry = finite(inner.pose?.y);
  if (rx === null || ry === null) return { ok: false, reason: "로봇 현재 좌표를 읽을 수 없습니다." };
  const sx = finite(trackRow?.x);
  const sy = finite(trackRow?.y);
  const age = finite(trackRow?.age_s);
  if (trackRow?.state !== "CONFIRMED" || sx === null || sy === null) return { ok: false, reason: "천장 카메라에서 로봇 위치가 아직 확인되지 않았습니다." };
  if (age === null || age < 0 || age > MAX_TRACK_AGE_S) return { ok: false, reason: "천장 카메라 추적 값이 오래되어 정지 후 다시 채집하세요." };
  const sample = { robot: [Number(rx.toFixed(6)), Number(ry.toFixed(6))], site: [Number(sx.toFixed(6)), Number(sy.toFixed(6))] };
  const samples = [...existingSamples, sample];
  const spanM = bindingSpanM(samples);
  return { ok: true, gridId, sample, samples, spanM, ready: samples.length >= MIN_BINDING_SAMPLES && spanM >= MIN_BINDING_SPAN_M };
}
