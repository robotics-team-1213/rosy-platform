// D-721 Amendment (S1): a low-battery robot's station recovery request, as one attention-queue row.
// Fleet approves an actionable request by itself (approved_by "fleet:auto"); an operator may approve first.
// Approval is only recorded. S1 sends no motion, and this file says so on the row.
// No import from queues.js: queues.js imports the text helper below.
import { isRouteAbsent } from "/console/assets/poll-gate.js";

const REASON = Object.freeze({
  no_station: "지도에 충전 스테이션이 없습니다",
  no_free_bay: "빈 충전 칸이 없습니다",
  position_unknown: "위치 확인 불가 — 로봇 위치를 먼저 지정하세요",
  state_unknown: "로봇 상태 확인 불가",
  already_stopped: "이미 비상 정지 중 — 스테이션 복구는 정지를 풀지 않습니다. 사람이 충전 위치로 옮겨야 합니다",
  busy: "운행 또는 이동 중입니다",
  another_returning: "다른 로봇이 복귀 중입니다",
  battery_evidence_missing: "배터리 근거 확인 불가",
});
export const NO_MOTION = "승인은 기록만 합니다. 아직 로봇은 움직이지 않습니다.";

/** Pure: why this request cannot be served, in a sentence, or "" when it can. */
export function recoveryReason(request) {
  if (!request.reason) return "";
  if (request.reason === "no_free_bay" && request.bays_unknown > 0) return "빈 충전 칸 확인 불가";
  return REASON[request.reason] || `확인 불가 (${request.reason})`;
}

/** Pure: the attention-queue sentence for one request, or "" when it is not a request. */
export function recoveryHeadline(request) {
  if (!request || request.request !== true) return "";
  const level = Number.isFinite(request.percent) ? ` (배터리 ${Math.round(request.percent)}%)` : "";
  const why = recoveryReason(request);
  return why ? `: 스테이션 복구 요청${level} — ${why}`
    : `: 스테이션 복구 요청${level} — 충전 칸 ${request.bay} 후보 · ${approvedText(request.approved_by)}, 아직 아무것도 움직이지 않음`;
}

/** Pure: who approved, in words. */
export function approvedText(by) {
  return !by ? "승인 대기" : by === "fleet:auto" ? "자동 승인됨" : `${by} 승인`;
}

/** Pure: what the opened row shows. The approve button exists only when the answer allows it. */
export function recoveryView(request, { operator, named = "", busy = false }) {
  const allowed = request.request === true && !request.reason && Boolean(request.bay) && !request.approved_by;
  const lock = !operator ? "운영자 권한이 필요합니다" : busy ? "답을 보내는 중" : named;
  return { lines: [recoveryHeadline(request).replace(/^:\s*/, ""), NO_MOTION], approve: allowed, approveReason: lock };
}

export function createStationRecovery({ scope, view, call, log, isOperator, namedReason = () => "" }) {
  const busy = new Set(), results = new Map(), signatures = new Map();
  let inFlight = false, unavailable = false;

  async function refresh() {
    const life = scope.capture();
    life.check();
    if (inFlight || unavailable) return;
    inFlight = true;
    try {
      const answer = await call("/api/fleet/station-recovery", { signals: [life.signal] });
      life.check();
      view.stationRecovery = { requests: answer.enabled ? answer.requests || [] : [] };
    } catch (error) {
      if (error.name === "AbortError") return;
      if (isRouteAbsent(error.status, error.code)) unavailable = true;
      view.stationRecovery = { requests: [] };  // unknown is never shown as a request
    } finally {
      inFlight = false;
    }
  }

  async function approve(robotId) {
    if (busy.has(robotId)) return;
    const life = scope.capture();
    busy.add(robotId);
    render();
    try {
      const done = await call(`/api/fleet/station-recovery/${encodeURIComponent(robotId)}/approve`, { method: "POST" });
      life.check();
      results.set(robotId, { text: `${robotId} 승인 기록됨${done.started ? "" : " · 로봇은 움직이지 않았습니다"}`, kind: "good" });
    } catch (err) {
      if (err.name === "AbortError") return;
      results.set(robotId, { text: `${robotId} 승인 거절 · ${err.detail?.reason ? REASON[err.detail.reason] || err.detail.reason : err.code || err.message}`, kind: "bad" });
    } finally {
      if (life.current()) {
        log(results.get(robotId).text, results.get(robotId).kind);
        busy.delete(robotId);
        refresh();
        render();
      }
    }
  }

  function render() {
    const operator = isOperator(), named = namedReason();
    for (const request of view.stateUnavailable ? [] : (view.stationRecovery?.requests || []).filter((r) => r.request)) {
      const key = `${request.robot_id}|recovery`;
      const slot = document.querySelector(`[data-decision-slot="${CSS.escape(key)}"]`);
      const spec = recoveryView(request, { operator, named, busy: busy.has(request.robot_id) });
      const signature = JSON.stringify([request, spec, results.get(request.robot_id) || null]);
      if (!slot || (slot.firstElementChild && signatures.get(key) === signature)) continue;
      const box = document.createElement("div");
      box.className = "stuck-item";
      for (const text of spec.lines) {
        const line = document.createElement("p");
        line.className = "stuck-resolver";
        line.textContent = text;
        box.append(line);
      }
      if (spec.approve) {
        const button = document.createElement("ui-button");
        button.setAttribute("kind", "primary");
        button.type = "button";
        button.textContent = "복구 승인 (기록만)";
        button.dataset.recovery = "approve";
        button.disabled = Boolean(spec.approveReason);
        if (spec.approveReason) button.setAttribute("reason", spec.approveReason);
        button.addEventListener("click", scope.guard(() => approve(request.robot_id)));
        const actions = document.createElement("div");
        actions.className = "stuck-actions ui-action-bar";
        actions.setAttribute("role", "group");
        actions.setAttribute("aria-label", `${request.robot_id} 스테이션 복구`);
        actions.append(button);
        box.append(actions);
      }
      const last = results.get(request.robot_id);
      if (last) {
        const line = document.createElement("p");
        line.className = "stuck-result";
        line.dataset.kind = last.kind;
        line.setAttribute("role", last.kind === "bad" ? "alert" : "status");
        line.textContent = last.text;
        box.append(line);
      }
      slot.replaceChildren(box);
      signatures.set(key, signature);
    }
  }

  return { refresh, render };
}
