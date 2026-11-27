// ARM-CELL run/recover for OMX arms A/B through Fleet's /api/fleet/cells/{cell}/jobs proxy to the cell job API.
// Every arm guard stays in the job API; this panel only gates the buttons it shows. Errors stay inline here.
import { html } from "/common/vendor/htm-preact.esm.min.js";
import { UiButton } from "/common/preact-ui.js";
import { evidenceAgeText } from "/common/core_ui_logic.js";

const READINESS_MS = 3000;
const MODES = [["act", "ACT 정책"], ["hybrid", "혼합"], ["taught", "가르친 동작"]];
export const DEFAULT_FORM = Object.freeze({ arm: "arm_a", mode: "act", paced: false, model: "", maxChunks: 1, dryRun: true, proposer: "" });

/** Pure: the key a real run must share with a passed dry run (dry_run itself and the proposer are not part of it). */
export const runParamsKey = (form) => JSON.stringify([form.arm, form.mode, Boolean(form.paced), form.model || "", Number(form.maxChunks)]);

/** Pure: the run button's lock reason; "" means it may be pressed. */
export function runReason(form, { lockReason = "", passedDryRunKey = "", busy = false, running = false } = {}) {
  if (lockReason) return lockReason;
  if (busy) return "요청을 보내는 중입니다.";
  if (running) return "이 화면에서 보낸 작업이 아직 실행 중입니다.";
  if (!String(form.proposer || "").trim()) return "제안자 이름을 적으세요. 운영자와 다른 사람이어야 합니다.";
  const n = Number(form.maxChunks);
  if (!Number.isInteger(n) || n < 1 || n > 60) return "청크 수는 1~60입니다.";
  if (form.mode !== "taught" && !form.model) return "모델을 고르세요.";
  if (!form.dryRun && passedDryRunKey !== runParamsKey(form)) return "같은 조건의 시험 실행이 먼저 성공해야 합니다.";
  return "";
}

/** Pure: which recovery jobs the arm's readiness says apply right now. */
export function armRecoveryActions(arm) {
  if (!arm || arm.active_job_id) return { recoverHold: false, safeHome: false };
  return { recoverHold: arm.human_hold_latched === true, safeHome: arm.incident_held === true || arm.folded === false };
}

/** Pure: one Korean line per readiness fact of an arm. */
export function armReadinessText(arm) {
  if (!arm) return ["준비 상태를 받지 못했습니다."];
  // evidenceAgeText prefixes " · "; these lines are already joined by it.
  const age = typeof arm.live_state_age_s === "number" ? `관측 ${evidenceAgeText(arm.live_state_age_s).replace(" · ", "")}` : "관측 없음";
  return [
    arm.folded === true ? "접힘" : arm.folded === false ? "펼쳐짐" : "접힘 미확인",
    arm.human_hold_latched ? "보류 · 자동 복구 재시도 중" : "보류 없음",
    arm.incident_held ? `사건 보류: ${arm.incident_reason || "사유 없음"}` : "사건 없음",
    arm.session_lock_held ? "세션 잠금 있음" : "세션 잠금 없음",
    arm.fault ? `고장: ${arm.fault}` : null,
    arm.active_job_id ? `실행 중 작업 ${arm.active_job_id}` : null,
    age,
  ].filter(Boolean);
}

/** Pure: the refusal the server or the job API gave, as said by it. */
export function jobErrorText(err) {
  if (err?.name === "AbortError") return "";
  if (err?.status === 403) return "이름 있는 운영자만 팔 작업을 보낼 수 있습니다.";
  const reason = err?.message && !/^HTTP \d+$/.test(err.message) ? err.message : "";
  return `거절됨${err?.code ? ` (${err.code})` : ""}${reason ? `: ${reason}` : `: HTTP ${err?.status ?? "?"}`}`;
}

/** Pure: a job status line. */
export function jobStateText(job) {
  if (!job) return "";
  if (job.running) return `${job.job} 실행 중 (${job.id})`;
  return job.exit === 0 ? `${job.job} 완료 (${job.id})` : `${job.job} 실패: 종료 코드 ${job.exit} (${job.id})`;
}

export function createCellJobPanel({ call, cell = "cell_ab", onChange = () => {} }) {
  const base = `/api/fleet/cells/${encodeURIComponent(cell)}/jobs`;
  const s = { options: null, readiness: null, readAt: 0, error: "", form: { ...DEFAULT_FORM }, job: null, jobDry: false,
    jobKey: "", passedDryRunKey: "", busy: false, notConfigured: false };
  let seq = 0;
  let inFlight = false;
  const changed = () => { seq += 1; onChange(); };

  async function refresh(signal) {
    if (inFlight) return;
    inFlight = true;
    try {
      if (!s.options && !s.notConfigured) s.options = await call(`${base}/options`, { signal });
      if (s.notConfigured) return;
      if (Date.now() - s.readAt >= READINESS_MS) {
        s.readAt = Date.now();
        s.readiness = await call(`${base}/readiness`, { signal });
      }
      if (s.job?.running) {
        s.job = await call(`${base}/${encodeURIComponent(s.job.id)}`, { signal });
        if (!s.job.running && s.jobDry && s.job.exit === 0) s.passedDryRunKey = s.jobKey;
      }
    } catch (err) {
      if (err?.name === "AbortError") return;
      if (err?.code === "CELL_JOBS_NOT_CONFIGURED") s.notConfigured = true;
      else s.error = jobErrorText(err);
    } finally {
      inFlight = false;
    }
    changed();
  }

  async function send(job, body) {
    s.busy = true; s.error = ""; changed();
    try {
      const out = await call(`${base}/${job}`, { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body), timeoutMs: 10000 });
      s.job = { id: out.id, job, running: true, exit: null };
      s.jobDry = job === "cell_policy_drive" && body.dry_run === true;
      s.jobKey = runParamsKey(s.form);
      s.readAt = 0;
    } catch (err) {
      s.error = jobErrorText(err);
    } finally {
      s.busy = false; changed();
    }
  }

  const set = (patch) => { s.form = { ...s.form, ...patch }; changed(); };
  const runBody = () => ({ arm: s.form.arm, proposer: s.form.proposer.trim(), mode: s.form.mode, paced_chunks: Boolean(s.form.paced),
    max_chunks: Number(s.form.maxChunks), dry_run: Boolean(s.form.dryRun), ...(s.form.model ? { model: s.form.model } : {}) });

  function view({ lockReason = "" } = {}) {
    if (s.notConfigured) return html`<p class="hint" data-cell-jobs-off="">이 셀의 작업 API가 Fleet에 설정되지 않았습니다.</p>`;
    const f = s.form;
    const arms = s.options?.arms?.length ? s.options.arms : ["arm_a", "arm_b"];
    const running = Boolean(s.job?.running);
    const reason = runReason(f, { lockReason, passedDryRunKey: s.passedDryRunKey, busy: s.busy, running });
    const recoverReason = lockReason || (s.busy ? "요청을 보내는 중입니다." : running ? "이 화면에서 보낸 작업이 아직 실행 중입니다."
      : !f.proposer.trim() ? "제안자 이름을 적으세요. 운영자와 다른 사람이어야 합니다." : "");
    const off = Boolean(lockReason);
    return html`<div class="cell-context-clear" data-cell-jobs="">
      <ul class="cell-context-list">
        ${arms.map((arm) => {
          const r = s.readiness?.arms?.[arm];
          const acts = armRecoveryActions(r);
          return html`<li class="cell-context-item" key=${arm} data-arm=${arm}>
            <div class="cell-context-item-head"><strong>${arm === "arm_a" ? "팔 A" : arm === "arm_b" ? "팔 B" : arm}</strong></div>
            <p class="cell-context-reason">${armReadinessText(r).join(" · ")}</p>
            ${acts.recoverHold || acts.safeHome ? html`<div class="cell-context-item-actions">
              ${acts.recoverHold ? html`<${UiButton} kind="primary" type="button" data-job="recover_hold" disabled=${Boolean(recoverReason)}
                reason=${recoverReason} onClick=${() => send("recover_hold", { arm, proposer: f.proposer.trim() })}>보류 복구</${UiButton}>` : null}
              ${acts.safeHome ? html`<${UiButton} kind="primary" type="button" data-job="safe_home" disabled=${Boolean(recoverReason)}
                reason=${recoverReason} onClick=${() => send("safe_home", { arm, proposer: f.proposer.trim() })}>안전 홈 복귀</${UiButton}>` : null}
            </div>` : null}
          </li>`;
        })}
      </ul>
      <select class="ui-field" aria-label="팔" value=${f.arm} disabled=${off} onChange=${(e) => set({ arm: e.target.value })}>
        ${arms.map((arm) => html`<option key=${arm} value=${arm}>${arm}</option>`)}
      </select>
      <select class="ui-field" aria-label="동작 방식" value=${f.mode} disabled=${off} onChange=${(e) => set({ mode: e.target.value })}>
        ${MODES.map(([v, label]) => html`<option key=${v} value=${v}>${label}</option>`)}
      </select>
      <select class="ui-field" aria-label="모델" value=${f.model} disabled=${off} onChange=${(e) => set({ model: e.target.value })}>
        <option value="">모델 선택</option>
        ${(s.options?.models || []).map((m) => html`<option key=${m.id} value=${m.id}>${m.label || m.id}</option>`)}
      </select>
      <input class="ui-field" type="number" min="1" max="60" aria-label="최대 청크 수" value=${f.maxChunks} disabled=${off}
        onInput=${(e) => set({ maxChunks: e.target.value })} />
      <label class="ui-check"><input type="checkbox" checked=${f.paced} disabled=${off}
        onChange=${(e) => set({ paced: e.target.checked })} /> 청크마다 정착 대기</label>
      <input class="ui-field" type="text" maxLength=${64} aria-label="제안자" placeholder="제안자 이름 (운영자와 다른 사람)"
        value=${f.proposer} disabled=${off} onInput=${(e) => set({ proposer: e.target.value })} />
      <label class="ui-check"><input type="checkbox" checked=${f.dryRun} disabled=${off}
        onChange=${(e) => set({ dryRun: e.target.checked })} /> 시험 실행 (팔을 움직이지 않음)</label>
      <${UiButton} kind="primary" type="button" data-job="cell_policy_drive" disabled=${Boolean(reason)} reason=${reason}
        onClick=${() => send("cell_policy_drive", runBody())}>${f.dryRun ? "시험 실행" : "실제 실행"}</${UiButton}>
      ${s.job ? html`<p class="hint" role="status" data-job-state="">${jobStateText(s.job)}</p>` : null}
      ${s.error ? html`<p class="hint" role="alert" data-job-error="">${s.error}</p>` : null}
    </div>`;
  }

  return { refresh, view, sig: () => seq, set, runDry: () => send("cell_policy_drive", runBody()), state: () => s };
}
