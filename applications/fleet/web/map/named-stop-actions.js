// Operator decision-slot controls for named-stop custody release and precision repark clearance.
import { setOffBy } from "/common/cause-line.js";
import { node } from "/common/control-dom.js";
import { OPERATOR_REASON } from "/console/assets/authorization.js";
import { createDecisionSlotFiller } from "/console/assets/decision-slot.js";
import { tripErrorText } from "/console/assets/trip-display.js";

const ISOLATION_METHODS = [
  ["power_off", "전원 차단 (power_off)"],
  ["hardware_estop_latched", "하드웨어 비상정지 래치 (hardware_estop_latched)"],
  ["removed_from_site", "현장에서 기체 분리 (removed_from_site)"],
];

/** Whether an open trip carries a complete precision-stop correction awaiting operator clearance. */
export function hasPendingCorrection(trip) {
  if (!trip || trip.hold) return false;
  const precision = trip.detail?.named_stop_precision;
  if (!precision || (precision.decision !== "HOLD" && precision.decision !== "REPARK")) return false;
  if (typeof precision.forward_m !== "number" || !Number.isFinite(precision.forward_m)) return false;
  if (!Array.isArray(precision.site_end) || precision.site_end.length !== 2) return false;
  if (!precision.site_end.every((v) => typeof v === "number" && Number.isFinite(v))) return false;
  const runId = trip.detail?.named_stop_operation?.run_id;
  const mapSha = trip.detail?.named_stop_dispatch?.map_sha256;
  return typeof runId === "string" && runId.length === 36 && /^[a-f0-9]{64}$/.test(mapSha || "");
}

/** Exact JSON request body for `POST /api/fleet/trips/{trip_id}/correction-clearance`. */
export function correctionPayload(trip, cableAndPathClear) {
  const precision = trip.detail.named_stop_precision;
  return {
    nav_run_id: trip.detail.named_stop_operation.run_id,
    map_sha256: trip.detail.named_stop_dispatch.map_sha256,
    forward_m: precision.forward_m,
    site_end: [Number(precision.site_end[0]), Number(precision.site_end[1])],
    cable_and_path_clear: Boolean(cableAndPathClear),
  };
}

/** Pure presentation + validation view for one named-stop custody hold row. */
export function custodyView(robot, {
  operator,
  named = "",
  busy = false,
  reasonText = "",
  isolated = false,
  isolationEvidence = "",
} = {}) {
  const custody = robot?.named_stop_custody || {};
  const lines = [
    custody.reservation_id ? `점유 예약 ${custody.reservation_id}` : "점유 예약 미상",
    custody.missing_proof ? `미확인 근거: ${custody.missing_proof}` : "",
    custody.operator_action ? `안내: ${custody.operator_action}` : "",
  ].filter(Boolean);
  const lock = !operator ? OPERATOR_REASON : named ? named : busy ? "요청을 보내는 중" : "";
  const releaseReason = lock
    || (String(reasonText).trim().length < 3 ? "해제 사유를 3자 이상 입력하세요" : "")
    || (isolated && String(isolationEvidence).trim().length < 3 ? "물리 격리 근거를 3자 이상 입력하세요" : "");
  return { lines, releaseReason };
}

/** Pure presentation + validation view for one precision correction clearance row. */
export function correctionView(trip, {
  operator,
  named = "",
  busy = false,
  cableClear = false,
} = {}) {
  const precision = trip?.detail?.named_stop_precision || {};
  const place = trip?.detail?.named_stop_dispatch?.place;
  const forwardM = precision.forward_m;
  const end = precision.site_end;
  const lines = [
    place ? `정지 장소 ${place}` : "",
    Number.isFinite(forwardM) ? `전후 보정 거리 ${forwardM.toFixed(3)} m` : "",
    Array.isArray(end) && end.length === 2 ? `목표 위치 (${Number(end[0]).toFixed(2)}, ${Number(end[1]).toFixed(2)}) m` : "",
    precision.reason ? `보정 사유: ${precision.reason}` : "",
  ].filter(Boolean);
  const lock = !operator ? OPERATOR_REASON : busy ? "요청을 보내는 중" : "";
  const confirmReason = lock || named || (!cableClear ? "케이블·경로 이상 없음 확인을 체크하세요" : "");
  return { lines, confirmReason, cancelReason: lock };
}

function errorMessage(err) {
  const code = err?.detail?.code || err?.code;
  return code ? tripErrorText(code, err.detail) : (err?.message || "요청 실패");
}

function buildFieldRow(labelText, control) {
  const label = node("label", "", "ui-field-label");
  label.append(node("span", labelText), control);
  return label;
}

export function createNamedStopActions({ scope, view, call, log, isOperator, namedReason = () => "", confirmedAction }) {
  const busy = new Set();
  const results = new Map();
  const custodyDrafts = new Map();
  const correctionClear = new Map();
  const fill = createDecisionSlotFiller({ focusAttr: "namedStopAction" });

  function draftOf(robotId) {
    if (!custodyDrafts.has(robotId)) {
      custodyDrafts.set(robotId, {
        reasonText: "현장 정지 확인 완료",
        isolatedOpen: false,
        isolated: false,
        isolationMethod: "power_off",
        isolationEvidence: "",
      });
    }
    return custodyDrafts.get(robotId);
  }

  async function releaseCustody(robot, draft, opener) {
    const custody = robot.named_stop_custody;
    const key = `${robot.robot_id}|custody`;
    if (busy.has(key) || !custody?.reservation_id) return;
    await confirmedAction.run({
      message: `${robot.robot_id} 정밀 정지 점유(${custody.reservation_id})를 해제할까요?`,
      opener,
      eligible: () => {
        if (view.stateUnavailable) return false;
        const current = (view.robots || []).find((r) => r.robot_id === robot.robot_id);
        return Boolean(current?.named_stop_custody?.reservation_id === custody.reservation_id)
          && !custodyView(current, {
            operator: isOperator(),
            named: namedReason(),
            busy: busy.has(key),
            reasonText: draft.reasonText,
            isolated: draft.isolated,
            isolationEvidence: draft.isolationEvidence,
          }).releaseReason;
      },
      request: async (owner) => {
        busy.add(key);
        render();
        try {
          const payload = {
            reservation_id: custody.reservation_id,
            reason: draft.reasonText.trim(),
          };
          if (draft.isolated) {
            payload.physical_isolation = {
              method: draft.isolationMethod,
              robot_physically_isolated: true,
              evidence: draft.isolationEvidence.trim(),
            };
          }
          await call(`/api/fleet/robots/${encodeURIComponent(robot.robot_id)}/named-stop-custody/release`, {
            method: "POST",
            signals: [owner.signal],
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
          });
          owner.check();
          results.set(key, { text: `${robot.robot_id} 점유 해제를 완료했습니다`, kind: "good" });
          log(results.get(key).text, "good");
        } finally {
          busy.delete(key);
          render();
        }
      },
      onError: (err) => {
        if (err.name === "AbortError") return;
        const text = `${robot.robot_id} 점유 해제 거절 · ${errorMessage(err)}`;
        results.set(key, { text, kind: "bad" });
        log(text, "bad");
        render();
      },
    });
  }

  async function submitCorrection(trip, opener) {
    const key = `${trip.robot_id}|correction`;
    if (busy.has(key) || !hasPendingCorrection(trip)) return;
    const forwardM = trip.detail.named_stop_precision.forward_m;
    await confirmedAction.run({
      message: `${trip.robot_id} 정밀 정지 보정(${forwardM.toFixed(3)} m)을 실행할까요?`,
      opener,
      eligible: () => {
        if (view.stateUnavailable) return false;
        const current = (view.trafficTrips || []).find((t) => t.trip_id === trip.trip_id);
        return hasPendingCorrection(current)
          && !correctionView(current, {
            operator: isOperator(),
            named: namedReason(),
            busy: busy.has(key),
            cableClear: Boolean(correctionClear.get(trip.trip_id)),
          }).confirmReason;
      },
      request: async (owner) => {
        busy.add(key);
        render();
        try {
          await call(`/api/fleet/trips/${encodeURIComponent(trip.trip_id)}/correction-clearance`, {
            method: "POST",
            signals: [owner.signal],
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(correctionPayload(trip, true)),
          });
          owner.check();
          results.set(key, { text: `${trip.robot_id} 정밀 보정 지시를 보냈습니다`, kind: "good" });
          log(results.get(key).text, "good");
        } finally {
          busy.delete(key);
          render();
        }
      },
      onError: (err) => {
        if (err.name === "AbortError") return;
        const text = `${trip.robot_id} 보정 승인 거절 · ${errorMessage(err)}`;
        results.set(key, { text, kind: "bad" });
        log(text, "bad");
        render();
      },
    });
  }

  async function cancelCorrectionTrip(trip) {
    const key = `${trip.robot_id}|correction`;
    if (busy.has(key)) return;
    const life = scope.capture();
    busy.add(key);
    render();
    try {
      await call(`/api/fleet/trips/${encodeURIComponent(trip.trip_id)}/cancel`, {
        method: "POST",
        signals: [life.signal],
      });
      life.check();
      results.set(key, { text: `${trip.robot_id} 운행을 취소했습니다`, kind: "good" });
    } catch (err) {
      if (err.name === "AbortError") return;
      results.set(key, { text: `${trip.robot_id} 운행 취소 거절 · ${errorMessage(err)}`, kind: "bad" });
    } finally {
      if (life.current()) {
        const last = results.get(key);
        if (last) log(last.text, last.kind);
        busy.delete(key);
        render();
      }
    }
  }

  function renderCustodySlot(robot, operator, named) {
    const custody = robot.named_stop_custody;
    const key = `${robot.robot_id}|custody`;
    const draft = draftOf(robot.robot_id);
    const result = results.get(key) || null;
    const spec = custodyView(robot, {
      operator, named, busy: busy.has(key),
      reasonText: draft.reasonText,
      isolated: draft.isolated,
      isolationEvidence: draft.isolationEvidence,
    });
    fill(key, JSON.stringify([custody, operator, named, busy.has(key), result]), () => {
      const box = node("div", "", "stuck-item");
      for (const text of spec.lines) box.append(node("p", text, "stuck-resolver"));

      const reasonInput = document.createElement("input");
      reasonInput.className = "ui-field";
      reasonInput.type = "text";
      reasonInput.value = draft.reasonText;
      reasonInput.placeholder = "현장 확인 사유 (3자 이상)";
      box.append(buildFieldRow("점유 해제 사유", reasonInput));

      const details = document.createElement("details");
      details.open = Boolean(draft.isolatedOpen);
      const summary = document.createElement("summary");
      summary.className = "ui-disclosure-row";
      summary.textContent = "물리 격리 예외 해제 정보";

      const isoLabel = node("label", "", "ui-check");
      const isoCheck = document.createElement("input");
      isoCheck.className = "ui-field";
      isoCheck.type = "checkbox";
      isoCheck.checked = Boolean(draft.isolated);
      isoLabel.append(isoCheck, node("span", "로봇 물리 격리 확인"));

      const methodSelect = document.createElement("select");
      methodSelect.className = "ui-field";
      for (const [val, label] of ISOLATION_METHODS) {
        const opt = document.createElement("option");
        opt.value = val;
        opt.textContent = label;
        opt.selected = val === draft.isolationMethod;
        methodSelect.append(opt);
      }

      const evidenceInput = document.createElement("input");
      evidenceInput.className = "ui-field";
      evidenceInput.type = "text";
      evidenceInput.value = draft.isolationEvidence;
      evidenceInput.placeholder = "격리 확인 근거 (3자 이상)";

      details.append(summary, isoLabel, buildFieldRow("격리 방식", methodSelect), buildFieldRow("물리 격리 근거", evidenceInput));
      box.append(details);

      const releaseBtn = document.createElement("ui-button");
      releaseBtn.setAttribute("kind", "primary");
      releaseBtn.type = "button";
      releaseBtn.textContent = "점유 해제…";
      releaseBtn.dataset.namedStopAction = "release";

      const syncReleaseBtn = () => {
        const nextSpec = custodyView(robot, {
          operator, named, busy: busy.has(key),
          reasonText: draft.reasonText,
          isolated: draft.isolated,
          isolationEvidence: draft.isolationEvidence,
        });
        setOffBy(releaseBtn, nextSpec.releaseReason);
      };
      syncReleaseBtn();
      reasonInput.addEventListener("input", () => { draft.reasonText = reasonInput.value; syncReleaseBtn(); });
      isoCheck.addEventListener("change", () => { draft.isolated = isoCheck.checked; syncReleaseBtn(); });
      methodSelect.addEventListener("change", () => { draft.isolationMethod = methodSelect.value; });
      evidenceInput.addEventListener("input", () => { draft.isolationEvidence = evidenceInput.value; syncReleaseBtn(); });
      details.addEventListener("toggle", () => { draft.isolatedOpen = details.open; });
      releaseBtn.addEventListener("click", scope.guard(() => releaseCustody(robot, draft, releaseBtn)));

      const actions = node("div", "", "stuck-actions ui-action-bar");
      actions.setAttribute("role", "group");
      actions.setAttribute("aria-label", `${robot.robot_id} 정밀 정지 점유 해제`);
      actions.append(releaseBtn);
      box.append(actions);

      if (result) {
        const line = node("p", result.text, "stuck-result");
        line.dataset.kind = result.kind;
        line.setAttribute("role", result.kind === "bad" ? "alert" : "status");
        box.append(line);
      }
      return box;
    });
  }

  function renderCorrectionSlot(trip, operator, named) {
    const key = `${trip.robot_id}|correction`;
    const result = results.get(key) || null;
    const clearChecked = Boolean(correctionClear.get(trip.trip_id));
    const spec = correctionView(trip, { operator, named, busy: busy.has(key), cableClear: clearChecked });
    const sig = JSON.stringify([
      trip.trip_id,
      trip.detail?.named_stop_precision,
      trip.detail?.named_stop_operation?.run_id,
      trip.detail?.named_stop_dispatch?.map_sha256,
      operator,
      named,
      busy.has(key),
      result,
    ]);
    fill(key, sig, () => {
      const box = node("div", "", "stuck-item");
      for (const text of spec.lines) box.append(node("p", text, "stuck-resolver"));

      const clearLabel = node("label", "", "ui-check");
      const clearCheck = document.createElement("input");
      clearCheck.className = "ui-field";
      clearCheck.type = "checkbox";
      clearCheck.checked = Boolean(correctionClear.get(trip.trip_id));
      clearCheck.dataset.namedStopClear = "check";
      clearLabel.append(clearCheck, node("span", "케이블·경로 이상 없음 확인"));
      box.append(clearLabel);

      const clearBtn = document.createElement("ui-button");
      clearBtn.setAttribute("kind", "primary");
      clearBtn.type = "button";
      clearBtn.textContent = "정밀 보정 실행…";
      clearBtn.dataset.namedStopAction = "correction";

      const cancelBtn = document.createElement("ui-button");
      cancelBtn.setAttribute("kind", "quiet");
      cancelBtn.type = "button";
      cancelBtn.textContent = "운행 취소";
      cancelBtn.dataset.namedStopAction = "cancel";

      const syncClearBtn = () => {
        const nextSpec = correctionView(trip, {
          operator, named, busy: busy.has(key), cableClear: Boolean(correctionClear.get(trip.trip_id)),
        });
        setOffBy(clearBtn, nextSpec.confirmReason);
        setOffBy(cancelBtn, nextSpec.cancelReason);
      };
      syncClearBtn();
      clearCheck.addEventListener("change", () => {
        correctionClear.set(trip.trip_id, clearCheck.checked);
        syncClearBtn();
      });
      clearBtn.addEventListener("click", scope.guard(() => submitCorrection(trip, clearBtn)));
      cancelBtn.addEventListener("click", scope.guard(() => cancelCorrectionTrip(trip)));

      const actions = node("div", "", "stuck-actions ui-action-bar");
      actions.setAttribute("role", "group");
      actions.setAttribute("aria-label", `${trip.robot_id} 정밀 보정 승인`);
      actions.append(clearBtn, cancelBtn);
      box.append(actions);

      if (result) {
        const line = node("p", result.text, "stuck-result");
        line.dataset.kind = result.kind;
        line.setAttribute("role", result.kind === "bad" ? "alert" : "status");
        box.append(line);
      }
      return box;
    });
  }

  function render() {
    if (view.stateUnavailable) return;
    const operator = isOperator();
    const named = namedReason();
    for (const robot of view.robots || []) {
      if (robot.named_stop_custody?.reservation_id) renderCustodySlot(robot, operator, named);
    }
    for (const trip of view.trafficTrips || []) {
      if (hasPendingCorrection(trip)) renderCorrectionSlot(trip, operator, named);
    }
  }

  return { render };
}
