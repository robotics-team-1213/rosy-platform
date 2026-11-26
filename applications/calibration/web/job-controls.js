import { setOff } from "/common/cause-line.js";
import { postEvalRequest } from "./status-logic.js";

const $ = id => document.getElementById(id);
const moving = new Set(["remap", "pivot-near", "surface", "post-eval"]);
let arms = {}, active = null, arm = "", operator = false, sending = false;
let jobs = [], selected = null, timer = null, wired = false;
let displayJobs = () => {};
const notices = new Map();

function readId() {
  try { return localStorage.getItem("calibration.job." + arm); } catch { return null; }
}

async function api(url, options) {
  const res = await fetch(url, {cache: "no-store", ...options});
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
  return data;
}

function showJob(id) {
  clearTimeout(timer);
  selected = id;
  $("jobDetail").hidden = !id;
  $("jobOutput").textContent = "";
  if (!id) return;
  const owner = arm;
  $("jobProgress").textContent = id + " · 조회 중";
  async function poll() {
    try {
      const job = await api("/api/calibration/jobs/" + encodeURIComponent(id));
      if (selected !== id || arm !== owner) return;
      if (job.id !== id || job.arm !== owner) throw new Error("선택한 팔의 작업 기록과 일치하지 않습니다.");
      jobs = jobs.map(row => row.id === id ? job : row);
      displayJobs(jobs);
      fields();
      const label = {running: "실행 중", done: "종료", failed: "실패", interrupted: "중단 · 완료 여부 미확인"}[job.status] || job.status;
      $("jobProgress").textContent = [owner, id, label, job.error].filter(Boolean).join(" · ");
      $("jobOutput").textContent = [job.error, job.result && JSON.stringify(job.result, null, 2), job.log_tail].filter(Boolean).join("\n");
      if (job.status !== "running") return;
    } catch (err) {
      if (selected !== id || arm !== owner) return;
      $("jobProgress").textContent = `${id} · 조회 실패 · ${err.message}`;
    }
    timer = setTimeout(poll, 2500);
  }
  poll();
}

function fields() {
  const step = $("jobStep").value;
  $("jobTargetsLabel").hidden = step !== "pivot-near";
  $("jobRemapNote").hidden = step !== "remap";
  $("jobSurfaceLabel").hidden = step !== "surface";
  $("jobVisitLabel").hidden = step !== "post-eval";
  $("jobVisitSite").required = step === "post-eval";
  $("jobSwitchLabel").hidden = !moving.has(step);
  $("jobSwitchText").textContent = step === "surface" && $("jobSurface").value
    ? `${arm}의 고정된 ${$("jobSurface").value} 측정 지점과 팔 이동 경로에 물체와 사람이 없음을 확인했고, 전원 스위치 옆에 있습니다.`
    : `이번 ${arm} 동작 동안 전원 스위치 옆에 입회합니다.`;
  $("jobTargets").required = step === "pivot-near";
  $("jobSurface").required = step === "surface";
  $("jobSwitch").required = moving.has(step);
  $("jobForm").hidden = !operator || !Object.keys(arms).length;
  const busy = jobs.some(job => job.arm === arm && job.status === "running");
  const missingVisit = step === "post-eval" && arms[arm]?.sites?.[$("jobVisitSite").value]?.can_post_eval !== true;
  const reason = !arm ? "등록된 팔을 선택하세요." : sending ? "작업을 요청하고 있습니다." : busy ? "이 팔에서 작업이 실행 중입니다."
    : missingVisit ? "팔 기준 XY가 등록된 칸을 선택하세요." : "";
  setOff($("jobStart"), !!reason, reason, "jobActionNote");
  const note = notices.get(arm) || reason;
  if ($("jobActionNote").textContent !== note) $("jobActionNote").textContent = note;
}

function selectArm(next) {
  const changed = next !== arm;
  arm = next;
  if (changed) {
    $("jobSwitch").checked = false;
    $("jobTargets").value = "";
  }
  const rows = arms[arm]?.sites || {};
  const sites = Object.keys(rows);
  const measured = sites.filter(name => rows[name].can_remeasure_surface === true);
  const visitSites = sites.filter(name => rows[name]?.can_post_eval === true);
  const visit = changed ? "" : $("jobVisitSite").value;
  $("jobVisitSite").replaceChildren(new Option(visitSites.length ? "검증할 칸 선택" : "XY 검증 가능한 칸 없음", ""),
    ...visitSites.map(name => new Option(name, name)));
  $("jobVisitSite").disabled = !visitSites.length;
  if (visitSites.includes(visit)) $("jobVisitSite").value = visit;
  if (visit !== $("jobVisitSite").value) $("jobSwitch").checked = false;
  const surface = changed ? "" : $("jobSurface").value;
  $("jobSurface").replaceChildren(new Option(measured.length ? "측정할 고정 지점 선택" : "등록된 고정 측정 지점 없음", ""),
    ...measured.map(s => new Option(s, s)));
  if (measured.includes(surface)) $("jobSurface").value = surface;
  if (surface !== $("jobSurface").value) $("jobSwitch").checked = false;
  $("jobSites").textContent = sites.map(name => {
    const map = rows[name].map;
    const grade = {coarse: "개략 맵", fine: "정밀 맵"}[map?.grade] || "맵 종류 미확인";
    const kind = !map ? "맵 없음" : map.inherited ? "다른 위치 맵 참조 · " + grade : grade;
    return name + " (" + kind + ")";
  }).join(", ");
  const remembered = readId();
  const id = jobs.find(j => j.arm === arm && j.status === "running")?.id ||
    (jobs.find(j => j.arm === arm && j.id === remembered)?.id) || jobs.find(j => j.arm === arm)?.id;
  if (changed || id && selected !== id) showJob(id || null);
  fields();
}

function sync() {
  if (!$("jobForm")) return;
  wire();
  const options = active ? [active].filter(x => Object.hasOwn(arms, x)) : Object.keys(arms);
  const next = options.includes(arm) ? arm : options[0] || "";
  $("jobArm").replaceChildren(...options.map(a => new Option(a, a)));
  $("jobArm").value = next;
  selectArm(next);
}

export function setJobOperator(value) {
  operator = value === true;
  setRoutePanels(arms, jobs, operator, api);
  if (!operator) notices.clear();
  sync();
}

export function setJobArm(value) {
  if (value === active) return;
  active = value;
  sync();
}

export function setJobData(status, rows, onJobs) {
  arms = status?.arms || {};
  jobs = rows;
  setRoutePanels(arms, jobs, operator, api);
  if (onJobs) displayJobs = onJobs;
  sync();
}

function wire() {
  if (wired) return;
  wired = true;
  $("jobArm").addEventListener("change", () => selectArm($("jobArm").value));
  $("jobStep").addEventListener("change", resetApproval);
  $("jobSurface").addEventListener("change", resetApproval);
  $("jobVisitSite").addEventListener("change", resetApproval);
  $("jobTargets").addEventListener("input", resetApproval);
  $("jobForm").addEventListener("submit", submit);
}

function resetApproval() {
  $("jobSwitch").checked = false;
  notices.delete(arm);
  fields();
}

async function submit(event) {
  event.preventDefault();
  if (!operator || sending || $("jobStart").disabled || !Object.hasOwn(arms, arm)) return;
  const owner = arm, step = $("jobStep").value;
  const payload = step === "post-eval"
    ? postEvalRequest(arm, arms[arm].sites, $("jobVisitSite").value, $("jobSwitch").checked)
    : {arm, step};
  if (!payload) return;
  if (moving.has(step)) {
    if (!$("jobSwitch").checked) return;
    payload.person_at_switch = true;
  }
  if (step === "surface") {
    const site = $("jobSurface").value;
    if (arms[arm].sites?.[site]?.can_remeasure_surface !== true) return;
    payload.site = site;
    payload.surface_clear = true;
  }
  if (step === "pivot-near") {
    payload.targets = $("jobTargets").value.trim().split(/\s+/);
    if (!payload.targets.every(t => /^[A-Za-z0-9_][A-Za-z0-9_-]{0,63}:-?\d+(\.\d+)?,-?\d+(\.\d+)?$/.test(t)
        && Object.hasOwn(arms[arm].sites || {}, t.split(":")[0]))) {
      notices.set(arm, "등록된 위치 이름과 좌표를 site:x,y 형식으로 입력하세요.");
      fields();
      return;
    }
  }
  sending = true;
  resetApproval();
  try {
    const job = await api("/api/calibration/jobs", {method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify(payload)});
    if (!job.id || job.arm !== owner) throw new Error("요청한 팔의 작업 ID를 확인할 수 없습니다.");
    jobs = [job, ...jobs.filter(row => row.id !== job.id)];
    displayJobs(jobs);
    try { localStorage.setItem("calibration.job." + owner, job.id); } catch { /* The server retains the job. */ }
    if (arm === owner) showJob(job.id);
  } catch (err) {
    notices.set(owner, `${owner} · 요청 결과를 확인하세요. ${err.message}`);
  } finally {
    sending = false;
    fields();
  }
}
import { setRoutePanels } from "./route-panels.js";
