// C19 localization adapter & DOM slots for Fleet console (#detail-refusal, #detail-localization, poller, queue, map candidates).
import {
  LOC_TEXT, REFUSAL_TEXT, POSE_REFUSALS,
  refusalText, queueStep, confirmRequest, localizationState,
} from "/common/localization-state.js";
import { statusTag } from "/common/status-tag.js";
import { canvasFont } from "/common/ui.js";
import { openTrip } from "./queues.js";

export { LOC_TEXT, REFUSAL_TEXT, POSE_REFUSALS, refusalText };

function poseAgeS(robot, guideRow, locData, nowMs) {
  const pose = guideRow?.pose;
  if (pose && Number.isFinite(pose.age_s)) return pose.age_s;
  if (pose && Number.isFinite(pose.ts)) return Math.max(0, nowMs / 1000 - pose.ts);
  if (Number.isFinite(robot?.localization?.age_s)) return robot.localization.age_s;
  if (Number.isFinite(locData?.localization?.age_s)) return locData.localization.age_s;
  return null;
}

/** Build the pure localizationState(view) for one robot from console state. */
export function buildLocalizationView(robot, view, isOperator = () => false, nowMs = Date.now()) {
  const id = robot.robot_id;
  const locData = view.locByRobot?.[id] || null;
  const autoLocate = view.autoLocateByRobot?.[id] || null;
  const guideRow = (view.guide?.robots || []).find((r) => r.robot_id === id) || null;
  const formation = !view.stateUnavailable && view.formation?.active ? view.formation : null;
  const inFormation = Boolean(formation && (formation.leader === id || Object.hasOwn(formation.assignment || {}, id)));
  const queue = view.queuedStarts?.[id];
  const loc = locData?.localization || (guideRow?.pose?.state ? { state: guideRow.pose.state } : robot.localization || null);
  return localizationState({
    localization: loc,
    report: locData?.candidates || null,
    motion: locData ? { allowed: locData.motion_allowed, last_operator_request: locData.last_operator_request } : null,
    mission_result: locData?.ladder?.last_mission?.result ?? null,
    session_left_s: autoLocate?.session_left_s ?? null,
    anchor_blocked: Boolean(autoLocate?.anchor_blocked),
    anchor_refused_reason: autoLocate?.anchor_refused_reason ?? null,
    age_s: poseAgeS(robot, guideRow, locData, nowMs),
    operator: Boolean(isOperator()),
    online: !view.stateUnavailable && Boolean(robot.online),
    trip_active: Boolean(openTrip(view, id) || inFormation),
    refused: view.locDisabled?.[id] ? "LOCALIZATION_DISABLED" : (view.locRefused?.[id] || null),
    stopped: Boolean(view.locStopped?.[id]),
    confirming: Boolean(view.locConfirming?.[id]),
    last_requester: view.lastRequesterByRobot?.[id] || null,
    wall_now_s: nowMs / 1000,
    queue: queue && !queue.done ? { since_s: queue.since_s, left_s: Math.max(0, 120 - (nowMs / 1000 - queue.since_s)) } : null,
  });
}

/** One poller per console tick: auto-locate (all) + /localization (selected or candidates/rotating only). */
export function createLocalizationPoller({ scope = null, call, view, isOperator = () => false, render = () => {} }) {
  const disabled = new Set();
  let inFlight = false;
  scope?.onDispose?.(() => {
    disabled.clear();
    inFlight = false;
  });
  async function poll(nowMs = Date.now()) {
    const life = scope?.capture?.() || null;
    if (inFlight || view.stateUnavailable || (life && !life.current())) return;
    inFlight = true;
    const callOpts = life ? { signals: [life.signal] } : undefined;
    try {
      view.autoLocateByRobot ??= {};
      view.locByRobot ??= {};
      view.lastRequesterByRobot ??= {};
      view.locDisabled ??= {};
      view.locConfirming ??= {};
      view.locStopped ??= {};
      try {
        const auto = await call("/api/fleet/auto-locate", callOpts);
        if (life && !life.current()) return;
        const next = {};
        for (const row of auto?.robots || []) if (row?.robot_id) next[row.robot_id] = row;
        view.autoLocateByRobot = next;
      } catch (err) {
        if (err?.name === "AbortError" || (life && !life.current())) return;
        /* auto-locate optional if 404/unavailable */
      }

      const targets = new Set();
      const activeRobotId = typeof view.robotSelection?.get === "function" ? view.robotSelection.get() : null;
      if (activeRobotId) targets.add(activeRobotId);
      for (const r of view.robots || []) {
        const prev = buildLocalizationView(r, view, isOperator, nowMs);
        if (prev.state === "candidates" || prev.state === "rotating") targets.add(r.robot_id);
      }
      await Promise.all([...targets].map(async (id) => {
        if (disabled.has(id) || (life && !life.current())) return;
        try {
          const data = await call(`/api/fleet/robots/${encodeURIComponent(id)}/localization`, callOpts);
          if (life && !life.current()) return;
          view.locByRobot[id] = data;
          const by = data?.motion?.last_operator_request?.by ?? data?.last_operator_request?.by;
          if (by) view.lastRequesterByRobot[id] = by;
          if (data?.motion_allowed !== undefined && !data.motion) {
            data.motion = { allowed: data.motion_allowed, last_operator_request: data.last_operator_request || null };
          }
          if (data?.localization?.state === "LOCALIZED") {
            view.locStopped[id] = false;
            view.locConfirming[id] = false;
          }
          if (data?.localization?.reason && data.localization.reason !== "checking") {
            view.locConfirming[id] = false;
          }
        } catch (err) {
          if (err?.name === "AbortError" || (life && !life.current())) return;
          if (err?.status === 503 || err?.code === "LOCALIZATION_DISABLED") {
            disabled.add(id);
            view.locDisabled[id] = true;
          }
        }
      }));
      if (life && !life.current()) return;
      stepQueuedStarts({ view, isOperator, nowMs, render });
    } finally {
      if (!life || life.current()) inFlight = false;
    }
  }
  return { poll };
}

/** Queue a start request when refused for unknown pose (client-only, 120 s, never persisted). */
export function enqueuePoseStart({ view, robotId, code, request, nowMs = Date.now() }) {
  if (!POSE_REFUSALS.has(code)) return false;
  view.queuedStarts ??= {};
  view.queueEndText ??= {};
  delete view.queueEndText[robotId];
  view.queuedStarts[robotId] = { since_s: nowMs / 1000, lastCode: code, request, done: false };
  return true;
}

/** Step all queued starts; fires at most once when pose is localized and fresh (age_s <= 30). */
export function stepQueuedStarts({ view, isOperator = () => false, nowMs = Date.now(), stoppedRobotId = null, pinnedRobotId = null, render = () => {} }) {
  if (!view.queuedStarts) return;
  view.queueEndText ??= {};
  for (const [id, q] of Object.entries(view.queuedStarts)) {
    const robot = (view.robots || []).find((r) => r.robot_id === id) || { robot_id: id, online: true };
    const guideRow = (view.guide?.robots || []).find((r) => r.robot_id === id) || null;
    const locData = view.locByRobot?.[id] || null;
    const pinned = pinnedRobotId === id;
    const locState = (locData?.localization?.state || guideRow?.pose?.state || robot.localization?.state || "").toUpperCase();
    const localized = pinned || locState === "LOCALIZED";
    const age_s = pinned ? 0 : poseAgeS(robot, guideRow, locData, nowMs);
    const stopped = stoppedRobotId === id || Boolean(view.locStopped?.[id]);
    const step = queueStep(q, { now_s: nowMs / 1000, code: q.lastCode, localized, age_s, stopped });
    if (step.action === "fire") {
      delete view.queuedStarts[id];
      const req = q.request;
      if (typeof req === "function") Promise.resolve(req()).catch(() => {});
    } else if (step.action === "end") {
      delete view.queuedStarts[id];
      if (step.text) view.queueEndText[id] = step.text;
    }
  }
  if (stoppedRobotId || pinnedRobotId) render();
}

function actionButton(label, { primary = false, disabled = false, reason = "", dataAttr, onClick }) {
  const btn = document.createElement("ui-button");
  if (primary) btn.setAttribute("kind", "primary");
  else btn.setAttribute("kind", "quiet");
  btn.type = "button";
  btn.textContent = label;
  btn.disabled = Boolean(disabled);
  if (disabled && reason) btn.setAttribute("reason", reason);
  if (dataAttr) for (const [k, v] of Object.entries(dataAttr)) btn.dataset[k] = v;
  btn.addEventListener("click", onClick);
  return btn;
}

async function runAction(act, { robot, view, call, scope, render, log, onPin, onStop }) {
  const id = robot.robot_id;
  if (act.id === "pin") { onPin?.(id); return; }
  if (act.id === "stop") { view.locStopped ??= {}; view.locStopped[id] = true; onStop?.(id); render(); return; }
  if (act.id === "cancel-queue") {
    delete view.queuedStarts?.[id];
    view.queueEndText ??= {};
    view.queueEndText[id] = "출발 대기를 취소했습니다";
    render();
    return;
  }
  const life = scope.capture();
  try {
    if (act.id === "auto-locate") {
      await call("/api/fleet/auto-locate", { method: "POST" });
    } else if (act.id === "lift-block") {
      await call(`/api/fleet/auto-locate/${encodeURIComponent(id)}/lift-block`, { method: "POST" });
    } else if (act.id === "relocalize") {
      view.locStopped ??= {};
      view.locStopped[id] = false;
      view.locRefused ??= {};
      delete view.locRefused[id];
      const res = await call(`/api/fleet/robots/${encodeURIComponent(id)}/relocalize`, { method: "POST" });
      if (!life.current()) return;
      view.locByRobot ??= {};
      view.locByRobot[id] = { ...(view.locByRobot[id] || {}), motion_allowed: res?.motion_allowed ?? true, last_operator_request: res?.last_operator_request || null };
      const by = res?.last_operator_request?.by;
      if (by) { view.lastRequesterByRobot ??= {}; view.lastRequesterByRobot[id] = by; }
    }
  } catch (err) {
    if (err?.name === "AbortError") return;
    const code = err?.code || err?.detail?.code;
    view.locRefused ??= {};
    view.locRefused[id] = code || err?.message || "UNKNOWN_ERROR";
    log?.(`${id} ${refusalText(code || err?.message)}`, "bad");
  }
  if (life.current()) render();
}

/** Render #detail-refusal (only when a refusal, queued start, or queue-end message exists). */
export function renderRefusalSlot({ slot, robot, view, call, scope, isOperator, render, log, onPin, onStop }) {
  const id = robot.robot_id;
  const loc = buildLocalizationView(robot, view, isOperator);
  const refusal = view.tripRefusalByRobot?.[id] || null;
  const qEnd = view.queueEndText?.[id] || "";
  const hasQueue = Boolean(view.queuedStarts?.[id] && !view.queuedStarts[id].done);
  if (!refusal && !hasQueue && !qEnd) { slot.replaceChildren(); return; }
  const box = document.createElement("div");
  box.className = "detail-refusal-box";
  if (refusal) {
    const p = document.createElement("p");
    p.className = "detail-refusal-line";
    p.textContent = refusal.text;
    box.append(p);
  }
  if (hasQueue || qEnd) {
    const qp = document.createElement("p");
    qp.className = "detail-queue-line";
    qp.textContent = hasQueue ? loc.reason : qEnd;
    box.append(qp);
  }
  const inlineIds = new Set(["pin", "auto-locate", "relocalize", "cancel-queue"]);
  const row = document.createElement("div");
  row.className = "detail-refusal-actions";
  for (const act of loc.actions.filter((a) => inlineIds.has(a.id))) {
    row.append(actionButton(act.label, {
      disabled: act.disabled,
      reason: act.reason,
      dataAttr: { locAction: act.id, robotId: id },
      onClick: scope.guard(() => runAction(act, { robot, view, call, scope, render, log, onPin, onStop })),
    }));
  }
  if (row.childElementCount) box.append(row);
  slot.replaceChildren(box);
}

/** Render #detail-localization (state line, evidence, relocalize button + cause line, candidate confirm gate). */
export function renderLocalizationSlot({ slot, robot, view, call, scope, isOperator, render, log, onPin, onStop }) {
  const id = robot.robot_id;
  const loc = buildLocalizationView(robot, view, isOperator);
  const box = document.createElement("div");
  box.className = "detail-localization-box";
  const line = document.createElement("p");
  line.className = "detail-localization-line";
  const label = document.createElement("strong");
  label.textContent = "위치";
  line.append(label, " ", statusTag(loc.tag, loc.tag_text), " ", loc.text);
  box.append(line);
  if (loc.evidence) {
    const ev = document.createElement("p");
    ev.className = "hint detail-localization-evidence";
    ev.textContent = loc.evidence;
    box.append(ev);
  }
  if (loc.reason && !view.queuedStarts?.[id]) {
    const reasonEl = document.createElement("p");
    reasonEl.className = "hint detail-localization-reason";
    reasonEl.textContent = loc.reason;
    box.append(reasonEl);
  }
  const actions = document.createElement("div");
  actions.className = "detail-localization-actions";
  for (const act of loc.actions.filter((a) => a.id === "relocalize" || a.id === "stop" || a.id === "lift-block")) {
    actions.append(actionButton(act.label, {
      disabled: act.disabled,
      reason: act.reason,
      dataAttr: { locAction: act.id, robotId: id },
      onClick: scope.guard(() => runAction(act, { robot, view, call, scope, render, log, onPin, onStop })),
    }));
  }
  if (actions.childElementCount) box.append(actions);

  if (loc.state === "candidates" && loc.candidates.length) {
    const list = document.createElement("ul");
    list.className = "detail-candidate-list";
    const shownReport = view.locByRobot?.[id]?.candidates || null;
    for (const c of loc.candidates) {
      const li = document.createElement("li");
      li.className = "detail-candidate-item";
      li.dataset.candidateId = String(c.id);
      if (view.candidateSelection?.get?.() === `${id}:${c.id}`) li.dataset.selected = "true";
      const txt = document.createElement("span");
      txt.textContent = `${c.label} (${c.x.toFixed(2)}, ${c.y.toFixed(2)})`;
      li.append(txt);
      const confirmAct = loc.actions.find((a) => a.id === "confirm" && a.candidate_id === c.id);
      if (confirmAct) {
        li.append(actionButton(confirmAct.label, {
          primary: true,
          disabled: confirmAct.disabled,
          reason: confirmAct.reason,
          dataAttr: { locConfirm: String(c.id), robotId: id },
          onClick: scope.guard(async () => {
            const life = scope.capture();
            try {
              const fresh = await call(`/api/fleet/robots/${encodeURIComponent(id)}/localization`);
              if (!life.current()) return;
              const checked = confirmRequest(shownReport, fresh?.candidates || null, c.id);
              if (!checked.ok) {
                view.locRefused ??= {};
                view.locRefused[id] = checked.code;
                log?.(`${id} ${checked.text}`, "bad");
                render();
                return;
              }
              view.locConfirming ??= {};
              view.locConfirming[id] = true;
              delete view.locRefused?.[id];
              render();
              await call(`/api/fleet/robots/${encodeURIComponent(id)}/localization/confirm`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(checked.body),
              });
            } catch (err) {
              if (err?.name === "AbortError") return;
              view.locConfirming[id] = false;
              const code = err?.code || err?.detail?.code;
              view.locRefused ??= {};
              view.locRefused[id] = code || err?.message || "UNKNOWN_ERROR";
              log?.(`${id} ${refusalText(code || err?.message)}`, "bad");
            }
            if (life.current()) render();
          }),
        }));
      }
      list.append(li);
    }
    box.append(list);
  }
  slot.replaceChildren(box);
}

/** Draw dashed unconfirmed candidate markers ("후보 · 확정 전") on the site map; never draws a route. */
export function drawLocalizationCandidates({ ctx, view, toPoint, css }) {
  if (!ctx || !toPoint) return;
  const selectedKey = view.candidateSelection?.get?.() || null;
  for (const robot of view.robots || []) {
    const loc = buildLocalizationView(robot, view, () => false);
    if (!loc.candidates.length) continue;
    for (const c of loc.candidates) {
      const p = toPoint(c.x, c.y);
      const isSelected = selectedKey === `${robot.robot_id}:${c.id}`;
      ctx.save();
      ctx.setLineDash([4, 4]);
      ctx.lineWidth = isSelected ? 3 : 2;
      ctx.strokeStyle = isSelected ? css("--selection") : css("--flag-warn-ink");
      ctx.beginPath();
      ctx.arc(p.x, p.y, 12, 0, Math.PI * 2);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = isSelected ? css("--selection") : css("--text-primary");
      ctx.font = canvasFont("micro", "body");
      ctx.fillText(`후보 · 확정 전 · ${c.label}`, p.x + 14, p.y + 4);
      ctx.restore();
    }
  }
}
