// Fleet 어댑터: Pinky/OMX 판정·구획 조립(상태·카메라·명령·설정). 감독 우회(/api/fleet/pipeline/*) 경로를 두지 않는다.
import { statusTag } from "/common/status-tag.js";
import { valueText } from "/common/value-text.js";
import { robotProfile } from "/common/robot-profile.js";
import { createCellFrameFeed } from "/console/assets/cell-frames.js";
import { randomUUID } from "/console/assets/uuid.js";
import { fleetRobotProfile } from "./roster-presentation.js";
import { CELL_PHASE } from "/console/assets/charge-bays-model.js";

export const ARM_STOP_NOTE = "팔 단독 정지 없음 · 위 머리의 전체 비상 정지를 쓴다";
export const ARM_DEFS = Object.freeze({
  arm_s: { id: "arm_s", cellId: "cell_s", label: "arm_s (S3)", title: "OMX-AI #3 · arm_s (Cell S · S3 공급 셔틀)" },
  arm_a: { id: "arm_a", cellId: "cell_ab", label: "arm_a (S5)", title: "OMX-AI #1 · arm_a (Cell A · S5 1·3단 적재)" },
  arm_b: { id: "arm_b", cellId: "cell_ab", label: "arm_b (S5)", title: "OMX-AI #2 · arm_b (Cell B · S5 2단 적재·반출)" },
});

const ACCEPTABLE_PHASES = new Set(["", "IDLE", "READY", "AVAILABLE"]);

export function armCameraSpecs(armId) {
  if (armId === "arm_s") {
    return [
      { id: "arm_s_top", label: "S3 상단", source: "arm_s_top" },
      { id: "arm_s_wrist", label: "arm_s 손목", source: "arm_s_wrist" },
    ];
  }
  const wrist = armId === "arm_b" ? "arm_b_wrist" : "arm_a_wrist";
  return [
    { id: "top", label: "S5 상단", source: "top" },
    { id: "side", label: "측면 (A/B)", source: "side" },
    { id: wrist, label: `${armId} 손목`, source: wrist },
  ];
}

export function armCommandReadiness(readbacks = {}) {
  const { operator = false, named = false, live = null, hold = null, humanSafety = false,
    gatePhase = "", ownerConnected = true, staleAfterS = 5 } = readbacks || {};
  if (!operator || !named) return { ok: false, reason: "기명 운영자만 가능" };
  const offline = !live || live.available === false || live.online === false;
  if (offline) {
    const age = Number.isFinite(live?.age_s) ? ` · ${Math.round(live.age_s)}초 전 값` : "";
    return { ok: false, reason: `연결 끊김${age}` };
  }
  if (live.stale === true || (Number.isFinite(live.age_s) && live.age_s > staleAfterS)) {
    const age = Number.isFinite(live.age_s) ? `${Math.round(live.age_s)}초 전` : "지연";
    return { ok: false, reason: `상태 지연 · ${age}` };
  }
  if (humanSafety) return { ok: false, reason: "사람 감지 정지 중 · 현장 확인 필요" };
  if (hold?.held) return { ok: false, reason: `홀드 중 · ${hold.reason || "사유 없음"} · 해제는 현장 사람` };
  const phase = String(gatePhase || "").trim().toUpperCase();
  if (phase && !ACCEPTABLE_PHASES.has(phase)) return { ok: false, reason: `셀 ${phase} · 명령 불가` };
  if (ownerConnected === false) return { ok: false, reason: "실물 실행 경로 미연결" };
  return { ok: true, reason: "명령 가능" };
}

function armDetail(armId, plan, view) {
  const def = ARM_DEFS[armId] || { id: armId, cellId: armId === "arm_s" ? "cell_s" : "cell_ab", label: armId, title: armId };
  const cell = plan?.omx_cells?.[def.cellId] || null;
  const gate = cell?.gate || {};
  const live = plan?.arm_live_states?.[armId] || null;
  const hold = plan?.arm_holds?.[armId] || null;
  const hs = plan?.human_safety || {};
  const humanSafety = Boolean(hs.active_estop || hs.human_detected?.all || hs.human_detected?.[def.cellId] || gate.phase === "HUMAN_HOLD");
  const tasks = Array.isArray(plan?.omx_cell_tasks) ? plan.omx_cell_tasks
    : (Array.isArray(plan?.cell_tasks) ? plan.cell_tasks : (Array.isArray(view?.cellJobs) ? view.cellJobs : []));
  const activeTask = tasks.find((t) => {
    const taskArm = t?.arm_id || t?.instance_id || "";
    const matchesTarget = taskArm ? taskArm === armId : (t?.cell_id === def.cellId || t?.workcell_id === def.cellId);
    return matchesTarget && !["SUCCEEDED", "FAILED", "CANCELED", "CANCELLED", "GOAL_CONFIRMED"].includes(String(t?.status || "").toUpperCase());
  }) || null;
  return { armId, def, cell, gate, live, hold, humanSafety, activeTask, ownerConnected: cell?.owner_connected !== false };
}

export function armRobotProfile(armId, plan, view, staleAfterS = 5) {
  const d = armDetail(armId, plan, view);
  const online = d.live ? (d.live.available !== false && d.live.online !== false) : undefined;
  const ageS = Number.isFinite(d.live?.age_s) ? d.live.age_s : undefined;
  const evidence = d.live?.stale === true ? "delayed" : undefined;
  const servo = (d.live?.current_ma != null || d.live?.temp_c != null)
    ? { currentMa: d.live.current_ma, temperatureC: d.live.temp_c }
    : undefined;
  const task = d.activeTask
    ? `${d.activeTask.task_id || d.activeTask.mission_id || "작업"} · ${d.activeTask.status || ""}`.trim()
    : (CELL_PHASE[d.gate?.phase]?.[0] ?? "대기");
  const alarm = !d.humanSafety && d.hold?.held
    ? { level: "caution", text: `홀드 · ${d.hold.reason || "현장 확인"}` }
    : undefined;
  return {
    ...robotProfile({
      id: armId,
      name: d.def.label,
      kind: "arm",
      online,
      ageS,
      evidence,
      torque: typeof d.live?.torque === "boolean" ? d.live.torque : undefined,
      servo,
      estop: d.humanSafety ? true : undefined,
      task,
      place: armId === "arm_s" ? "Cell S · S3" : armId === "arm_a" ? "Cell A · S5" : "Cell B · S5",
      alarm,
    }, { staleAfterS }),
    detail: d,
  };
}

export function mobileRobotProfile(robot, view, staleAfterS = 5) {
  const base = fleetRobotProfile(robot, view, staleAfterS);
  const online = view?.stateUnavailable ? false : Boolean(robot?.online);
  const ageS = base.link?.ageS;
  const evidence = online && (
    robot?.state?.evidence?.pose?.evidence === "delayed"
    || (Number.isFinite(ageS) && ageS > staleAfterS)
  )
    ? "delayed"
    : undefined;
  const freshBase = robotProfile({
    id: base.id,
    name: base.name,
    kind: "mobile",
    online,
    ageS,
    evidence,
    estop: typeof robot?.state?.safety?.estop === "boolean" ? robot.state.safety.estop : undefined,
    alarm: base.alarm || undefined,
  }, { staleAfterS });
  return { ...base, link: freshBase.link };
}

export function buildDockEntries(view, chargeBaysPlan) {
  const entries = [];
  const seen = new Set();
  for (const robot of (view?.robots || [])) {
    if (!robot?.robot_id) continue;
    seen.add(robot.robot_id);
    entries.push({ profile: mobileRobotProfile(robot, view), robot, detail: { robot } });
  }
  const plan = chargeBaysPlan || view?.chargeBaysPlan || null;
  const hasArms = Boolean(plan && (plan.omx_cells || plan.arm_live_states || plan.arm_holds));
  if (hasArms) {
    for (const armId of Object.keys(ARM_DEFS)) {
      if (seen.has(armId)) continue;
      const cellId = ARM_DEFS[armId].cellId;
      if (plan.omx_cells && !(cellId in plan.omx_cells) && !(armId in (plan.arm_live_states || {})) && !(armId in (plan.arm_holds || {}))) continue;
      const profile = armRobotProfile(armId, plan, view);
      entries.push({ profile, robot: null, detail: profile.detail });
    }
  }
  return entries;
}

export function summarizeFleetProfiles(entries) {
  const counts = { total: entries.length, ok: 0, warn: 0, down: 0 };
  for (const { profile } of entries) {
    const link = profile?.link?.state;
    if (link === "disconnected" || link === "unavailable") counts.down += 1;
    else if (profile?.alarm || link === "delayed") counts.warn += 1;
    else counts.ok += 1;
  }
  return `로봇 ${counts.total}대 · 정상 ${counts.ok} · 주의 ${counts.warn} · 끊김 ${counts.down}`;
}

function armCommandContext(profile, detail, { operator = false, named = false } = {}) {
  const readiness = armCommandReadiness({
    operator,
    named,
    live: detail?.live,
    hold: detail?.hold,
    humanSafety: detail?.humanSafety,
    gatePhase: detail?.gate?.phase || "",
    ownerConnected: detail?.ownerConnected,
  });
  const missionId = detail?.activeTask?.mission_id || "";
  const taskId = detail?.activeTask?.task_id || missionId || "";
  const cancelReason = !operator || !named ? "기명 운영자만 가능"
    : !missionId ? (taskId ? "셀 작업 취소는 작업대 화면에서 진행" : "진행 중인 셀 작업 없음") : "";
  const sig = JSON.stringify([profile?.id || "", readiness.ok, readiness.reason, taskId, missionId, cancelReason]);
  return { readiness, missionId, taskId, cancelReason, sig };
}

function armCommandsSig(profile, detail, auth = {}) {
  return armCommandContext(profile, detail, auth).sig;
}

export function buildArmSections({ call, view, isOperator, namedReason, refresh, scope }) {
  let busyArm = null;
  let feedback = null;
  let gen = 0;
  let cellFeed = null;

  function reset() {
    gen += 1;
    busyArm = null;
    feedback = null;
    cellFeed?.setRunning(false);
  }
  scope?.onDispose?.(reset);

  function readState(detail) {
    return armCommandReadiness({
      operator: isOperator(),
      named: !namedReason(),
      live: detail.live,
      hold: detail.hold,
      humanSafety: detail.humanSafety,
      gatePhase: detail.gate?.phase || "",
      ownerConnected: detail.ownerConnected,
    });
  }

  function commandsSig(profile, detail) {
    return armCommandsSig(profile, detail, { operator: isOperator(), named: !namedReason() });
  }

  function status(profile, detail) {
    const wrap = document.createElement("div");
    wrap.className = "robot-panel-arm-status";
    const readiness = readState(detail);
    const line = document.createElement("p");
    line.className = "robot-arm-readiness";
    line.setAttribute("data-arm-readiness", "");
    line.textContent = readiness.reason;
    const dl = document.createElement("dl");
    dl.className = "facts";
    const row = (k, v) => {
      const box = document.createElement("div");
      const dt = document.createElement("dt"); dt.textContent = k;
      const dd = document.createElement("dd"); dd.textContent = v;
      box.append(dt, dd);
      dl.append(box);
    };
    const isSupplyCell = detail.def.cellId === "cell_s";
    row("셀", isSupplyCell ? "셀 S · S3 공급 작업대"
      : profile.id === "arm_a" ? "셀 A · S5 1·3단 적층 작업대"
      : profile.id === "arm_b" ? "셀 B · S5 2단 적층·반출 작업대"
      : "셀 A/B · S5 적층 작업대");
    row("작업 단계", detail.gate?.phase || valueText(null).text);
    if (isSupplyCell) {
      row("이동 로봇 잠금", detail.gate?.amr_motion_inhibited ? "잠금 (하역 중)" : "해제");
    } else {
      row("담당 적층", profile.id === "arm_b" ? "2단 적재·반출 (협동 통로 공유)" : "1·3단 적재 (협동 통로 공유)");
    }
    row("홀드", detail.hold?.held ? `홀드 중 · ${detail.hold.reason || "사유 없음"}` : "해제");
    const joints = Array.isArray(detail.live?.joints_deg) && detail.live.joints_deg.length
      ? detail.live.joints_deg.slice(0, 6).map((v, i) => `J${i + 1}:${Number(v).toFixed(1)}°`).join(" ")
      : valueText(null).text;
    row("관절", joints);
    wrap.append(line, dl);
    if (detail.humanSafety) wrap.append(statusTag("danger", "사람 감지 정지"));
    return wrap;
  }

  function camera(profile) {
    const wrap = document.createElement("div");
    wrap.className = "robot-panel-arm-cameras";
    cellFeed ??= createCellFrameFeed({ call, scope });
    cellFeed.setRunning(false);
    const refs = [];
    for (const spec of armCameraSpecs(profile.id)) {
      const fig = document.createElement("figure");
      fig.className = "robot-arm-cam";
      fig.setAttribute("data-arm-camera", spec.source);
      const img = document.createElement("img");
      img.alt = `${profile.id} ${spec.label}`;
      const cap = document.createElement("figcaption");
      const title = document.createElement("span");
      title.textContent = spec.label;
      const badge = document.createElement("ui-tag");
      badge.setAttribute("status", "neutral");
      badge.textContent = "대기";
      cap.append(title, badge);
      fig.append(img, cap);
      wrap.append(fig);
      refs.push({ view: { source: spec.source }, img, badge, label: spec.label });
    }
    for (const ref of refs) cellFeed.bind(ref.img, ref.view, ref.badge, ref.label);
    cellFeed.setRunning(true);
    wrap._disposeCamera = () => cellFeed?.setRunning(false);
    return wrap;
  }

  function commands(profile, detail, links) {
    const wrap = document.createElement("div");
    wrap.className = "robot-panel-arm-commands";
    const { readiness, missionId, taskId, cancelReason, sig } = armCommandContext(
      profile,
      detail,
      { operator: isOperator(), named: !namedReason() },
    );
    if (feedback && (feedback.id !== profile.id || (!readiness.ok && feedback.readinessOk))) {
      feedback = null;
    }
    wrap.dataset.armCmdSig = sig;
    if (busyArm === profile.id) wrap.dataset.armCmdBusy = "1";

    const reason = document.createElement("p");
    reason.className = "hint";
    reason.setAttribute("data-arm-command-reason", "");
    reason.textContent = (feedback?.id === profile.id ? feedback.text : "") || readiness.reason;

    const actions = document.createElement("div");
    actions.className = "robot-actions";

    const proposeBtn = document.createElement("ui-button");
    proposeBtn.setAttribute("kind", "quiet");
    proposeBtn.setAttribute("type", "button");
    proposeBtn.setAttribute("data-arm-transfer-propose", profile.id);
    proposeBtn.textContent = "이송 제안 보내기";
    proposeBtn.disabled = !readiness.ok || busyArm === profile.id;
    if (!readiness.ok) proposeBtn.setAttribute("reason", readiness.reason);
    proposeBtn.addEventListener("click", async () => {
      if (proposeBtn.disabled) return;
      const callGen = gen;
      const life = scope?.capture?.() || null;
      const sig = life?.signal || scope?.signal;
      busyArm = profile.id;
      feedback = null;
      wrap.dataset.armCmdBusy = "1";
      proposeBtn.disabled = true;
      proposeBtn.setAttribute("reason", "이송 제안 전송 중");
      try {
        const spec = [detail.cell?.transfer_request, detail.def.transferRequest].find(
          (candidate) => candidate && (!candidate.instance_id || candidate.instance_id === profile.id),
        );
        const body = spec?.object_ref && spec?.source && spec?.target
          ? {
              request_key: randomUUID(),
              workcell_id: spec.workcell_id || detail.def.cellId,
              instance_id: spec.instance_id || profile.id,
              object_ref: spec.object_ref,
              source: spec.source,
              target: spec.target,
            }
          : { arm_id: profile.id, cell_id: detail.def.cellId };
        await call("/api/fleet/arm-transfers/jobs", {
          method: "POST",
          headers: { "Content-Type": "application/json", "Idempotency-Key": randomUUID() },
          body: JSON.stringify(body),
          ...(sig ? { signals: [sig] } : {}),
        });
        if (callGen !== gen || (life && !life.current())) return;
        reason.textContent = "이송 제안을 등록했습니다 · 승인은 작업 화면에서 진행합니다";
        feedback = { id: profile.id, readinessOk: readiness.ok, text: reason.textContent };
        refresh?.();
      } catch (err) {
        if (callGen !== gen || err?.name === "AbortError" || (life && !life.current())) return;
        reason.textContent = err?.message || "명령을 접수하지 못했습니다";
        feedback = { id: profile.id, readinessOk: readiness.ok, text: reason.textContent };
        proposeBtn.setAttribute("reason", reason.textContent);
      } finally {
        if (callGen === gen) {
          if (busyArm === profile.id) busyArm = null;
          delete wrap.dataset.armCmdBusy;
          const nextReadiness = readState(detail);
          proposeBtn.disabled = !nextReadiness.ok;
          if (!nextReadiness.ok) proposeBtn.setAttribute("reason", nextReadiness.reason);
          else proposeBtn.removeAttribute("reason");
        }
      }
    });

    const cancelBtn = document.createElement("ui-button");
    cancelBtn.setAttribute("kind", "quiet");
    cancelBtn.setAttribute("type", "button");
    cancelBtn.setAttribute("data-arm-job-cancel", profile.id);
    cancelBtn.textContent = "작업 취소";
    cancelBtn.disabled = Boolean(cancelReason) || busyArm === profile.id;
    if (cancelReason) cancelBtn.setAttribute("reason", cancelReason);
    cancelBtn.addEventListener("click", async () => {
      if (!missionId || cancelBtn.disabled) return;
      const callGen = gen;
      const life = scope?.capture?.() || null;
      const sig = life?.signal || scope?.signal;
      busyArm = profile.id;
      feedback = null;
      wrap.dataset.armCmdBusy = "1";
      cancelBtn.disabled = true;
      cancelBtn.setAttribute("reason", "작업 취소 요청 중");
      try {
        await call(`/api/fleet/cell-jobs/${encodeURIComponent(missionId)}/cancel`, {
          method: "POST",
          headers: { "Content-Type": "application/json", "Idempotency-Key": randomUUID() },
          body: JSON.stringify({}),
          ...(sig ? { signals: [sig] } : {}),
        });
        if (callGen !== gen || (life && !life.current())) return;
        reason.textContent = `${missionId} 취소를 요청했습니다`;
        feedback = { id: profile.id, readinessOk: readiness.ok, text: reason.textContent };
        refresh?.();
      } catch (err) {
        if (callGen !== gen || err?.name === "AbortError" || (life && !life.current())) return;
        reason.textContent = err?.message || "작업 취소에 실패했습니다";
        feedback = { id: profile.id, readinessOk: readiness.ok, text: reason.textContent };
        cancelBtn.disabled = false;
        cancelBtn.removeAttribute("reason");
      } finally {
        if (callGen === gen) {
          if (busyArm === profile.id) busyArm = null;
          delete wrap.dataset.armCmdBusy;
        }
      }
    });

    actions.append(proposeBtn, cancelBtn);
    wrap.append(reason, actions);
    if (typeof links?.taskRow === "function") {
      const nav = document.createElement("a");
      nav.className = "ui-action-link robot-panel-work-link";
      nav.dataset.kind = "quiet";
      nav.href = links.taskRow(taskId);
      nav.textContent = "작업 화면으로";
      wrap.append(nav);
    }
    const targetWorkspace = armWorkspaceId(profile.id, detail.def.cellId);
    const cellLink = document.createElement("a");
    cellLink.className = "ui-action-link robot-panel-cell-link";
    cellLink.dataset.kind = "quiet";
    cellLink.href = `/console/cell?cell=${encodeURIComponent(targetWorkspace)}#observation-heading`;
    cellLink.textContent = profile.id === "arm_s" ? "셀 S 작업대 열기"
      : profile.id === "arm_a" ? "셀 A 작업대 열기"
      : profile.id === "arm_b" ? "셀 B 작업대 열기"
      : "셀 A/B 작업대 열기";
    wrap.append(cellLink);
    return wrap;
  }

  function armWorkspaceId(armId, fallback) {
    return armId === "arm_s" ? "cell_s"
      : armId === "arm_a" ? "cell_a"
      : armId === "arm_b" ? "cell_b"
      : fallback;
  }

  function settings(profile, detail) {
    const wrap = document.createElement("div");
    wrap.className = "robot-panel-settings-body";
    const dl = document.createElement("dl");
    dl.className = "facts";
    for (const [k, v] of [
      ["식별자", profile.id],
      ["셀", profile.id === "arm_s" ? "셀 S (S3)" : profile.id === "arm_a" ? "셀 A (S5)" : profile.id === "arm_b" ? "셀 B (S5)" : detail.def.cellId],
      ["단계", detail.gate?.phase || valueText(null).text],
      ["제어권", detail.gate?.allowed_owners ? [].concat(detail.gate.allowed_owners).join(", ") : valueText(null).text],
    ]) {
      const box = document.createElement("div");
      const dt = document.createElement("dt"); dt.textContent = k;
      const dd = document.createElement("dd"); dd.textContent = v;
      box.append(dt, dd);
      dl.append(box);
    }
    const setupLink = document.createElement("a");
    setupLink.className = "ui-action-link";
    setupLink.dataset.kind = "quiet";
    setupLink.href = "/console/cell?cell=prep#cell-heading";
    setupLink.textContent = "셀 작업대·보정 설정";
    wrap.append(dl, setupLink);
    return wrap;
  }

  return { status, camera, commands, commandsSig, settings, reset };
}
