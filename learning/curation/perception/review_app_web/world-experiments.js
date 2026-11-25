import "/common/ui.js";
import {setOffBy} from "/common/cause-line.js";
import {accountFetch} from "/account-session.js";
import {fillSelectOptions, makeUuid} from "/learning-ui.js";

const api = "/api/learning/world-experiments";
const $ = id => document.getElementById(`experiment-${id}`);
const statuses = {
  pending: ["준비 중", "pending"],
  launching: ["준비 중", "pending"],
  starting: ["준비 중", "pending"],
  running: ["학습 중", "ready"],
  stopping: ["중지 중", "warning"],
  stop_requested: ["중지 중", "warning"],
  stopped: ["중지됨", "empty"],
  cancelled: ["중지됨", "empty"],
  succeeded: ["완료", "ready"],
  failed: ["실패", "error"],
};
const stateOf = run => String(run?.status ?? "").toLowerCase();
const statusOf = run => Object.hasOwn(statuses, stateOf(run)) ? statuses[stateOf(run)] : ["확인 필요", "warning"];
const terminal = new Set(["succeeded", "failed", "stopped", "cancelled"]);
const stoppable = new Set(["pending", "launching", "starting", "running"]);
let snapshot, current = new URL(location.href).searchParams.get("run"), fresh = false;
let pendingStart, refreshing = false, mutating = false, revision = 0;

function status(id, state, text) {
  const element = $(id);
  element.setAttribute("state", state);
  if (element.textContent !== text) element.textContent = text;
}

function error(message) {
  $("error").hidden = !message;
  $("error").textContent = message;
}

async function request(path, options = {}) {
  const response = await accountFetch(path, {cache: "no-store", signal: AbortSignal.timeout(5500), ...options});
  const value = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(value.error || "Learning 연결을 확인하세요.");
  return value;
}

function select(id) {
  current = id;
  const url = new URL(location.href);
  if (id) url.searchParams.set("run", id);
  else url.searchParams.delete("run");
  if (url.href !== location.href) history.replaceState(null, "", url);
}

function render() {
  const runs = snapshot?.runs ?? [];
  const active = runs.find(row => !terminal.has(stateOf(row)));
  const selected = runs.find(row => row.id === current) ?? active ?? runs[0];
  const preset = snapshot?.preset;
  fillSelectOptions($("run"), runs.map(row => [row.id, `${row.id} · ${statusOf(row)[0]}`]),
    runs.length ? null : "실행 기록 없음");
  if (selected) {
    $("run").value = selected.id;
    select(selected.id);
  }
  $("details").hidden = !selected;
  if (selected) {
    const [label, state] = statusOf(selected);
    const observed = selected.status_uncertain ? `${label} · 상태 확인 필요` : label;
    status("state", fresh && !selected.status_uncertain ? state : "warning", fresh ? observed : `${observed} · 마지막 수신 상태`);
    $("run-error").textContent = selected.error || "";
    $("run-error").hidden = !selected.error;
    const step = selected.progress?.step ?? selected.result?.optimizer_steps;
    const steps = selected.progress?.steps ?? preset?.steps;
    $("step").textContent = Number.isInteger(step) ? (Number.isInteger(steps) ? `${step} / ${steps}` : step) : "—";
    $("loss").textContent = Number.isFinite(selected.progress?.loss) ? selected.progress.loss.toPrecision(4) : "—";
    $("scene").textContent = selected.scene_sha256 || "—";
    $("checkpoint").textContent = selected.result?.policy_sha256 || "—";
  }
  const blocked = mutating ? "요청을 처리하는 중입니다." : !fresh ? "실행 상태를 확인하세요."
    : !snapshot.can_manage ? "프로젝트 관리 권한이 필요합니다." : "";
  setOffBy($("start"), blocked || (!preset ? "등록된 실험이 없습니다." : active && !pendingStart ? "진행 중인 실행이 있습니다." : ""));
  const retryStop = selected?.status_uncertain && ["stopping", "stop_requested"].includes(stateOf(selected));
  setOffBy($("stop"), blocked || (!stoppable.has(stateOf(selected)) && !retryStop ? "중지할 수 있는 실행을 선택하세요." : ""));
  $("stop-label").textContent = retryStop ? "이 실행 중지 다시 요청" : "이 실행 중지";
  if (snapshot) $("preset").textContent = preset ? `${preset.label} · 오프라인 ACT · ${preset.steps} 스텝` : "Learning에 등록된 World 실험이 없습니다.";
  $("start-label").textContent = pendingStart ? "시작 요청 다시 확인" : "학습 시작";
}

async function refresh() {
  if (refreshing || mutating) return;
  refreshing = true;
  const startedAt = revision;
  try {
    const response = await request(api);
    if (startedAt !== revision) return;
    if (!Array.isArray(response.runs) || typeof response.can_manage !== "boolean") throw new Error("실행 상태 형식이 올바르지 않습니다.");
    snapshot = response;
    fresh = true;
    status("connection", "ready", response.can_manage ? "Learning 연결됨" : "Learning 연결됨 · 조회 전용");
  } catch {
    if (startedAt !== revision) return;
    fresh = false;
    status("connection", "warning", "실행 상태를 다시 확인하는 중입니다.");
  } finally {
    refreshing = false;
    render();
  }
}

async function change(action, body) {
  mutating = true;
  revision += 1;
  error("");
  render();
  try {
    const session = await request("/api/accounts/session");
    if (typeof session.token !== "string" || !session.token) throw new Error("Learning 로그인이 필요합니다.");
    const row = await request(`${api}/${action}`, {method: "POST", headers: {
      "Content-Type": "application/json", "X-Pinky-Token": session.token,
    }, body: JSON.stringify(body)});
    if (typeof row.id !== "string" || !row.id) throw new Error("요청 상태를 실행 기록에서 확인하세요.");
    if (action === "start") pendingStart = null;
    snapshot.runs = [row, ...snapshot.runs.filter(item => item.id !== row.id)];
    select(row.id);
  } catch (failure) {
    error(failure.message);
  } finally {
    mutating = false;
    render();
    void refresh();
  }
}

$("run").addEventListener("change", () => { select($("run").value); render(); });
$("start").addEventListener("click", () => {
  if ($("start").disabled) return;
  pendingStart ??= {preset_id: snapshot.preset.id, request_id: makeUuid()};
  void change("start", pendingStart);
});
$("stop").addEventListener("click", () => {
  if (!$("stop").disabled) void change("stop", {id: current});
});

async function poll() {
  await refresh();
  setTimeout(poll, 2500);
}
void poll();

const s3 = id => $(`s3-${id}`);
const policies = {ik: "고정 IK", learned: "학습 정책"};
const results = {placed: "배치 성공", safe_refusal: "안전 거부", guard_refusal: "집기 거부",
  forbidden_contact: "금지 접촉", lifted_not_placed: "배치 실패", not_lifted: "집기 실패"};
const phases = {ready: "준비", approach: "접근", lower: "하강", close: "집기", lift: "들기", transfer: "이송",
  place: "놓기", release: "놓아주기", retreat: "퇴피", settle: "안착"};
const conditionFields = ["seed", "stratum", "box_dx_m", "box_dy_m", "box_yaw_rad",
  "observed_dx_m", "observed_dy_m", "observed_yaw_rad"];
const sha256 = value => typeof value === "string" && /^[a-f0-9]{64}$/.test(value);
let evaluation, episodes = new Map(), replay, tickId, importRevision = 0;

const validCondition = value => value && Number.isSafeInteger(value.seed) && value.seed >= 0
  && ["nominal", "overhang", "wrong-yaw"].includes(value.stratum) && conditionFields.slice(2).every(key => Number.isFinite(value[key]));
const sameCondition = (left, right) => validCondition(left) && validCondition(right)
  && conditionFields.every(key => left[key] === right[key]);
const vector = (value, length) => Array.isArray(value) && value.length === length && value.every(Number.isFinite);
const sameBinding = (left, right) => ["run_id", "scene_sha256", "task", "registration", "engine"].every(key => left[key] === right[key]);

async function localJson(file) {
  if (!file || file.size > 2 * 1024 * 1024) throw new Error("2 MB 이하의 JSON 파일을 선택하세요.");
  return JSON.parse(await file.text());
}

function reportFor(value) {
  if (value?.schema !== "rosy.world.s3-evaluation.v1" || value.engine !== "mujoco"
      || value.registration !== "unregistered-arm-local-proxy" || value.task !== "omx-s-s3-pickup-alignment"
      || typeof value.run_id !== "string" || !value.run_id || value.run_id.length > 160
      || !sha256(value.scene_sha256) || !sha256(value.checkpoint_sha256)
      || !Array.isArray(value.pairs) || !value.pairs.length || value.pairs.length > 24) throw new Error("지원하는 S3 평가 보고서를 선택하세요.");
  const expected = new Map();
  for (const pair of value.pairs) {
    if (!sameCondition(pair?.ik?.condition, pair?.learned?.condition)) throw new Error("같은 조건으로 비교한 에피소드가 필요합니다.");
    for (const policy of Object.keys(policies)) {
      const row = pair[policy];
      const name = `episode-${row.condition.seed}-${policy}.json`;
      if (row.replay !== name || expected.has(name) || !Object.hasOwn(results, row.result)) throw new Error("에피소드 참조 또는 결과를 확인하세요.");
      expected.set(name, {...row, policy});
    }
  }
  return {value, expected};
}

function replayFor(file, value, report) {
  const row = report.expected.get(file.name);
  if (!row || value?.schema !== "rosy.world.s3-replay.v1" || !sameBinding(value, report.value) || value.policy !== row.policy
      || value.checkpoint_sha256 !== (row.policy === "learned" ? report.value.checkpoint_sha256 : null)
      || value.result !== row.result || !sameCondition(value.condition, row.condition)
      || !Array.isArray(value.frames) || !value.frames.length || value.frames.length > 1000
      || !value.frames.every((frame, index, frames) => frame && Number.isFinite(frame.sim_time_s)
        && frame.sim_time_s >= 0 && (!index || frame.sim_time_s > frames[index - 1].sim_time_s)
        && Object.hasOwn(phases, frame.phase) && vector(frame.arm_joints_rad, 6) && vector(frame.box_pose_m_wxyz, 7))) {
    throw new Error("실행, 장면, 모델 및 자세가 평가 보고서와 일치하는 에피소드만 열 수 있습니다.");
  }
  return value;
}

function showFrame(index) {
  const frame = replay.frames[index];
  s3("scrub").value = index;
  s3("time").textContent = `${frame.sim_time_s.toFixed(2)}초 · ${phases[frame.phase]}`;
  const coordinates = values => values.map(value => value.toFixed(4)).join(", ");
  s3("box").textContent = coordinates(frame.box_pose_m_wxyz.slice(0, 3));
  s3("rotation").textContent = coordinates(frame.box_pose_m_wxyz.slice(3));
  s3("arm").textContent = coordinates(frame.arm_joints_rad);
}

function pause() {
  cancelAnimationFrame(tickId);
  tickId = undefined;
  s3("play-label").textContent = "재생";
}

function selectReplay() {
  pause();
  replay = episodes.get(s3("select").value);
  s3("player").hidden = !replay;
  if (replay) {
    s3("scrub").max = replay.frames.length - 1;
    showFrame(0);
  }
  setOffBy(s3("play"), replay?.frames.length === 1 ? "정지 프레임만 기록되었습니다." : "");
}

function reportError(message) {
  s3("error").textContent = message;
  s3("error").hidden = !message;
}

s3("report").addEventListener("change", async event => {
  const selected = ++importRevision;
  const file = event.target.files[0];
  event.target.value = "";
  reportError("");
  try {
    const next = reportFor(await localJson(file));
    if (selected !== importRevision) return;
    evaluation = next;
    episodes = new Map();
    s3("id").textContent = next.value.run_id;
    for (const policy of Object.keys(policies)) {
      const rows = next.value.pairs.map(pair => pair[policy]);
      const count = result => rows.filter(row => row.result === result).length;
      s3(policy).textContent = `${rows.length}회 · 배치 성공 ${count("placed")}회 · 안전 거부 ${count("safe_refusal")}회 · 금지 접촉 ${count("forbidden_contact")}회`;
    }
    s3("results").hidden = false;
    fillSelectOptions(s3("select"), [], "에피소드 파일 선택 필요");
    s3("notice").textContent = "평가 보고서를 열었습니다. 재생할 에피소드 파일을 선택하세요.";
    selectReplay();
  } catch (failure) {
    if (selected === importRevision) reportError(failure instanceof SyntaxError ? "JSON 파일을 읽을 수 없습니다." : failure.message);
  }
});

s3("files").addEventListener("change", async event => {
  const selected = ++importRevision;
  const report = evaluation;
  const files = [...event.target.files];
  event.target.value = "";
  reportError("");
  try {
    if (!report || !files.length || files.length > report.expected.size) throw new Error("평가 보고서와 일치하는 에피소드 파일을 선택하세요.");
    const next = new Map(episodes);
    for (const file of files) next.set(file.name, replayFor(file, await localJson(file), report));
    if (selected !== importRevision) return;
    episodes = next;
    fillSelectOptions(s3("select"), [...episodes].map(([name, data]) => [name,
      `${data.condition.seed} · ${policies[data.policy]} · ${results[data.result]}`]));
    s3("notice").textContent = `일치하는 에피소드 ${episodes.size}개를 열었습니다.`;
    selectReplay();
  } catch (failure) {
    if (selected === importRevision) reportError(failure instanceof SyntaxError ? "JSON 파일을 읽을 수 없습니다." : failure.message);
  }
});

s3("select").addEventListener("change", selectReplay);
s3("scrub").addEventListener("input", event => { pause(); showFrame(Number(event.target.value)); });
s3("play").addEventListener("click", () => {
  if (tickId !== undefined) return pause();
  let index = Number(s3("scrub").value);
  if (index === replay.frames.length - 1) index = 0;
  s3("play-label").textContent = "일시 정지";
  const start = performance.now() - replay.frames[index].sim_time_s * 1000;
  function advance(now) {
    while (index + 1 < replay.frames.length && replay.frames[index + 1].sim_time_s * 1000 <= now - start) index++;
    showFrame(index);
    if (index + 1 === replay.frames.length) pause();
    else tickId = requestAnimationFrame(advance);
  }
  tickId = requestAnimationFrame(advance);
});
