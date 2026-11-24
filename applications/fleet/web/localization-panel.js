// Pinky localization & D-1022 map-binding monitoring + command controls inside the C24 robot panel.
import { OPERATOR_REASON } from "/console/assets/authorization.js";
import { html, render as renderDom } from "/common/vendor/htm-preact.esm.min.js";
import { PanelKvList } from "/console/assets/cockpit-hosts.js";
import { node, patchHidden, patchText } from "/common/control-dom.js";
import { setOffBy } from "/common/cause-line.js";
import {
  bindingSpanM, buildBindingPayload, captureBindingSample, confirmReason,
  MIN_BINDING_SAMPLES, MIN_BINDING_SPAN_M, relocalizeReason, summarizeLocalizationPanel,
} from "/console/assets/localization-panel-logic.js";

const POLL_MS = 2000;

function quietButton(label, { workRead = false } = {}) {
  const btn = document.createElement("ui-button");
  btn.setAttribute("kind", "quiet");
  btn.type = "button";
  btn.textContent = label;
  if (workRead) btn.dataset.workRead = "";
  return btn;
}

export function createLocalizationPanel({
  scope, view, auth, call, log = () => {}, render = () => {}, confirmedAction,
  isOperator = () => false, namedReason = () => "",
}) {
  const root = node("div", "", "ui-control-stack");
  const kvHost = document.createElement("div");
  const candRow = node("div", "", "ui-control-stack");
  const candSelect = document.createElement("select");
  candSelect.className = "ui-field";
  candSelect.dataset.workRead = "";
  candSelect.setAttribute("aria-label", "확정할 위치 후보 선택");
  candRow.append(candSelect);
  candRow.hidden = true;

  const locActions = node("div", "", "robot-actions");
  const refreshBtn = quietButton("새로고침", { workRead: true });
  const confirmBtn = quietButton("후보 위치 확정");
  const relocalizeBtn = quietButton("재탐색 요청");
  locActions.append(refreshBtn, confirmBtn, relocalizeBtn);

  const bindActions = node("div", "", "robot-actions");
  const sampleBtn = quietButton("결속점 채집");
  const clearSamplesBtn = quietButton("채집 초기화");
  const approveBindBtn = quietButton("지도 결속 승인");
  const revokeBindBtn = quietButton("결속 해제");
  bindActions.append(sampleBtn, clearSamplesBtn, approveBindBtn, revokeBindBtn);

  const noteEl = node("p", "", "hint");
  const errorEl = node("p", "", "hint");
  errorEl.hidden = true;
  root.append(kvHost, candRow, locActions, bindActions, noteEl, errorEl);

  const cache = new Map();
  const sampleBuffers = new Map();
  let activeId = null;
  let lastRobot = null;
  let lastKvSig = "";
  let lastCandSig = "";

  const ensure = (map, id, init) => map.get(id) || map.set(id, init()).get(id);
  const stateFor = (id) => ensure(cache, id, () => ({ loc: null, binding: null, track: null, fetchedAtMs: 0, inFlight: false, error: "", candIdx: 0 }));
  const samplesFor = (id) => ensure(sampleBuffers, id, () => ({ gridId: null, samples: [] }));

  async function refresh(id, { force = false } = {}) {
    if (!id || auth?.locked) return;
    const entry = stateFor(id);
    if (entry.inFlight || (!force && Date.now() - entry.fetchedAtMs < POLL_MS)) return;
    entry.inFlight = true;
    const life = scope.capture();
    try {
      const [loc, binding, ident] = await Promise.all([
        call(`/api/fleet/robots/${encodeURIComponent(id)}/localization`),
        call(`/api/fleet/robots/${encodeURIComponent(id)}/map-binding`),
        call("/api/fleet/tracking/identity").catch(() => null),
      ]);
      if (!life.current()) return;
      entry.loc = loc;
      entry.binding = binding;
      if (ident?.robots) entry.track = ident.robots.find((row) => row.robot_id === id) || null;
      entry.fetchedAtMs = Date.now();
      entry.error = "";
    } catch (err) {
      if (err?.name !== "AbortError") {
        entry.fetchedAtMs = Date.now();
        entry.error = err?.message || "위치 세부 상태를 불러오지 못했습니다.";
      }
    } finally {
      entry.inFlight = false;
      if (life.current() && activeId === id && lastRobot) paint(lastRobot);
    }
  }

  function paint(robot) {
    if (!robot) return;
    const id = robot.robot_id;
    const entry = stateFor(id);
    const buf = samplesFor(id);
    const op = Boolean(isOperator());
    const named = namedReason() || "";
    const unavailable = Boolean(view?.stateUnavailable);
    const summary = summarizeLocalizationPanel({ robot, locPayload: entry.loc, bindingPayload: entry.binding, trackRow: entry.track });

    const kvSig = `${id}:${JSON.stringify(summary.kvRows)}`;
    if (kvSig !== lastKvSig) {
      lastKvSig = kvSig;
      renderDom(html`<${PanelKvList} rows=${summary.kvRows} />`, kvHost);
    }

    if (entry.candIdx >= summary.candidates.length) entry.candIdx = 0;
    const candSig = `${id}:${summary.candidates.map((c) => `${c.x?.toFixed?.(2)},${c.y?.toFixed?.(2)},${c.scan_fit?.toFixed?.(3)}`).join("|")}`;
    patchHidden(candRow, summary.candidates.length <= 1);
    if (candSig !== lastCandSig) {
      lastCandSig = candSig;
      candSelect.replaceChildren(...summary.candidates.map((c, idx) => {
        const opt = document.createElement("option");
        opt.value = String(idx);
        const fitTxt = typeof c.scan_fit === "number" ? c.scan_fit.toFixed(2) : "—";
        opt.textContent = `후보 ${idx + 1} · (${Number(c.x).toFixed(2)}, ${Number(c.y).toFixed(2)}) · 적합도 ${fitTxt}`;
        return opt;
      }));
      candSelect.value = String(entry.candIdx);
    }

    const common = { robot, isOperator: op, operatorReason: OPERATOR_REASON, namedReason: named, stateUnavailable: unavailable };
    setOffBy(refreshBtn, auth?.locked ? "관제에 접속하면 새로고칩니다." : "");
    setOffBy(confirmBtn, confirmReason({ ...common, locPayload: entry.loc, candidateIndex: entry.candIdx }));
    setOffBy(relocalizeBtn, relocalizeReason({ ...common, locPayload: entry.loc }));

    const spanM = bindingSpanM(buf.samples);
    const sampleReady = buildBindingPayload(buf.samples) !== null;
    const opGate = unavailable ? "Fleet 상태를 확인할 수 없습니다." : !op ? OPERATOR_REASON : named;
    const onlineGate = !robot.online ? "로봇이 오프라인입니다." : "";
    setOffBy(sampleBtn, unavailable ? "Fleet 상태를 확인할 수 없습니다." : onlineGate || opGate);
    setOffBy(clearSamplesBtn, buf.samples.length ? "" : "채집된 결속점이 없습니다.");
    setOffBy(approveBindBtn, unavailable ? "Fleet 상태를 확인할 수 없습니다."
      : onlineGate || opGate || (sampleReady ? "" : `결속점 ${MIN_BINDING_SAMPLES}개 이상, 최대 폭 ${MIN_BINDING_SPAN_M.toFixed(1)} m 이상 채집 후 승인하세요.`));

    const hasActiveBinding = Boolean(entry.binding?.active);
    patchHidden(revokeBindBtn, !hasActiveBinding);
    if (hasActiveBinding) setOffBy(revokeBindBtn, opGate);

    patchText(noteEl, `결속점 ${buf.samples.length}/${MIN_BINDING_SAMPLES} · 폭 ${spanM.toFixed(2)} m (마지막 1점은 검증점)`);
    patchHidden(errorEl, !entry.error);
    if (entry.error) patchText(errorEl, entry.error);
  }

  function onAction(btn, build) {
    btn.addEventListener("click", scope.guard(() => {
      const id = activeId;
      if (!id || !confirmedAction) return;
      const cfg = build(id);
      if (!cfg) return;
      return confirmedAction.run({
        kind: `${cfg.kind}:${id}`,
        opener: btn,
        message: cfg.message,
        eligible: () => activeId === id && cfg.eligible(id),
        request: async (owner) => {
          await cfg.request(owner);
          owner.check();
          cfg.onOk?.();
          log(`${id} ${cfg.okMsg}`, cfg.okTone || "good");
          await refresh(id, { force: true });
          render();
        },
        onError: (err) => log(`${id} ${cfg.errLabel} · ${err.message}`, "bad"),
      });
    }));
  }

  candSelect.addEventListener("change", () => {
    if (!activeId) return;
    stateFor(activeId).candIdx = Number(candSelect.value) || 0;
    if (lastRobot) paint(lastRobot);
  });

  refreshBtn.addEventListener("click", scope.guard(() => { if (activeId) void refresh(activeId, { force: true }); }));

  onAction(confirmBtn, (id) => {
    const idx = stateFor(id).candIdx;
    return {
      kind: "loc-confirm",
      message: `${id}의 후보 ${idx + 1} 위치를 확정해 자율 주행을 허용할까요?`,
      eligible: () => Boolean(lastRobot?.online) && !confirmBtn.disabled,
      request: (owner) => call(`/api/fleet/robots/${encodeURIComponent(id)}/localization/confirm`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ candidate_id: idx }), signals: [owner.signal],
      }),
      okMsg: "후보 위치 확정 요청을 보냈습니다.",
      errLabel: "위치 확정 거절",
    };
  });

  onAction(relocalizeBtn, (id) => ({
    kind: "relocalize",
    message: `${id}이 제자리 회전하며 위치를 재탐색하도록 요청할까요? (주변 케이블·충전기 확인 필요)`,
    eligible: () => Boolean(lastRobot?.online) && !relocalizeBtn.disabled,
    request: (owner) => call(`/api/fleet/robots/${encodeURIComponent(id)}/relocalize`, { method: "POST", signals: [owner.signal] }),
    okMsg: "위치 재탐색을 요청했습니다.",
    errLabel: "재탐색 거절",
  }));

  sampleBtn.addEventListener("click", scope.guard(async () => {
    const id = activeId;
    const robotSnapshot = lastRobot;
    if (!id || !robotSnapshot) return;
    const life = scope.capture();
    try {
      const ident = await call("/api/fleet/tracking/identity", { signals: [life.signal] });
      life.check();
      if (activeId !== id) return;
      const trackRow = (ident?.robots || []).find((row) => row.robot_id === id) || null;
      stateFor(id).track = trackRow;
      const buf = samplesFor(id);
      const res = captureBindingSample({ robot: robotSnapshot, trackRow, existingSamples: buf.samples, existingGridId: buf.gridId });
      if (!res.ok) {
        log(`${id} 결속점 채집 보류 · ${res.reason}`, "bad");
      } else {
        buf.gridId = res.gridId;
        buf.samples = res.samples;
        log(`${id} 결속점 ${buf.samples.length}번 채집 완료 (폭 ${res.spanM.toFixed(2)} m)`, "good");
      }
      paint(robotSnapshot);
    } catch (err) {
      if (err?.name !== "AbortError") log(`${id} 천장 추적 조회 실패 · ${err.message}`, "bad");
    }
  }));

  clearSamplesBtn.addEventListener("click", scope.guard(() => {
    if (!activeId || !lastRobot) return;
    sampleBuffers.set(activeId, { gridId: null, samples: [] });
    paint(lastRobot);
  }));

  onAction(approveBindBtn, (id) => {
    const body = buildBindingPayload(samplesFor(id).samples);
    return body && {
      kind: "bind-approve",
      message: `${id}의 지도 결속(${body.pairs.length}쌍 + 검증 ${body.holdout.length}쌍)을 검증하고 승인할까요?`,
      eligible: () => Boolean(lastRobot?.online) && buildBindingPayload(samplesFor(id).samples) !== null,
      request: (owner) => call(`/api/fleet/robots/${encodeURIComponent(id)}/map-binding`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body), signals: [owner.signal],
      }),
      onOk: () => sampleBuffers.set(id, { gridId: null, samples: [] }),
      okMsg: "지도 결속을 승인했습니다.",
      errLabel: "지도 결속 거절",
    };
  });

  onAction(revokeBindBtn, (id) => ({
    kind: "bind-revoke",
    message: `${id}의 활성 지도 결속을 해제할까요?`,
    eligible: () => Boolean(stateFor(id).binding?.active),
    request: (owner) => call(`/api/fleet/robots/${encodeURIComponent(id)}/map-binding`, { method: "DELETE", signals: [owner.signal] }),
    okMsg: "지도 결속을 해제했습니다.",
    okTone: "info",
    errLabel: "결속 해제 거절",
  }));

  return {
    element: () => root,
    sync(robot) {
      if (!robot?.robot_id) return;
      const switched = activeId !== robot.robot_id;
      activeId = robot.robot_id;
      lastRobot = robot;
      paint(robot);
      if (robot.online) void refresh(robot.robot_id, { force: switched });
    },
    clear() {
      activeId = null;
      lastRobot = null;
      lastKvSig = "";
      lastCandSig = "";
      renderDom(null, kvHost);
    },
  };
}
