// D-982: the trip form's `현장 규칙 판정` — ask the site rules "go / wait / refuse" for a what-if state with
// the same pure functions Fleet uses live (`POST /api/fleet/site-rules/judge`). Advice only: nothing is sent
// to a robot and nothing changes. Picks are selects, so a poll keeps the card while one has focus.
import { quietButton } from "./queues.js";

const SECONDS = [0, 5, 10, 20, 30, 60];
/** kind -> label and the picks: [key, label, choices, default]; `null` means "use the rule's default". */
export const RULE_KINDS = Object.freeze({
  return: { label: "충전 복귀", picks: [
    ["percent", "배터리 %", [5, 10, 15, 20, 30, 50, 80, 100], 50],
    ["bays", "충전 칸 수", [0, 1, 2, 3, 4], 2],
    ["taken", "이미 찬 칸 수", [0, 1, 2, 3, 4], 0]] },
  departure: { label: "출발 순서", picks: [
    ["mine", "이 로봇이 기다린 초", SECONDS, 0],
    ["other", "먼저 기다린 다른 로봇의 초", SECONDS, 0]] },
  formation: { label: "편대 시작", picks: [
    ["followers", "팔로워 수", [1, 2, 3, 4], 1],
    ["spacing", "간격 m (기본: 규칙 값)", [null, 0.3, 0.4, 0.5, 0.6, 0.8, 1], null],
    ["speed", "속도 m/s (기본: 규칙 값)", [null, 0.05, 0.1, 0.15, 0.2], null]] },
});
const VERDICT = Object.freeze({ go: ["감", "active"], wait: ["대기", "warn"], refuse: ["거절됨", "crit"] });
const REASON = Object.freeze({
  first_in_order: "내 차례", queued_behind: "앞선 로봇이 먼저", pose_unknown: "위치를 모름", unknown_robot: "알 수 없는 로봇",
  low_battery: "배터리가 기준 이하", battery_unknown: "배터리를 모름", no_free_bay: "빈 충전 칸 없음", after_trip: "운행이 끝난 뒤",
  not_needed: "충전 기준보다 높음", offline: "오프라인", connecting: "충전 연결 확인 중",
  invalid_formation: "만들 수 없는 대형", gap_below_site_min: "현장 최소 간격보다 좁음",
  speed_above_site_max: "현장 최고 속도보다 빠름", within_rules: "규칙 안",
});

/** Pure: the `state` of a judge request for this robot from the picked values. */
export function ruleJudgeState(kind, robotId, v) {
  if (kind === "return") {
    const bays = Array.from({ length: v.bays }, (_, i) => `칸${i + 1}`);
    const taken = Math.min(v.taken, bays.length);
    const others = bays.slice(0, taken).map((_, i) => ({ robot_id: `다른${i + 1}`, percent: 90 }));
    return { kind, robot_id: robotId, robots: [{ robot_id: robotId, percent: v.percent }, ...others], bays,
      occupied: Object.fromEntries(bays.slice(0, taken).map((bay, i) => [bay, `다른${i + 1}`])) };
  }
  if (kind === "departure") {
    return { kind, robot_id: robotId, robots: [{ robot_id: robotId, waiting_s: v.mine },
      { robot_id: "다른1", waiting_s: v.other }] };
  }
  const state = { kind, formation: "COLUMN", followers: v.followers };
  if (v.spacing !== null) state.spacing = v.spacing;
  if (v.speed !== null) state.max_speed = v.speed;
  return state;
}

/** Pure: "감 · 내 차례" style text for an answer. */
export function ruleAnswerText(answer) {
  const [text] = VERDICT[answer.verdict] || [answer.verdict];
  return `${text} · ${REASON[answer.reason] || answer.reason}`;
}

function pick(label, choices, value, onChange) {
  const wrap = document.createElement("label");
  const select = document.createElement("select");
  select.className = "ui-field";
  select.replaceChildren(...choices.map((choice) => new Option(choice === null ? "규칙 기본값" : String(choice), String(choice))));
  select.value = String(value);
  select.addEventListener("change", () => onChange(select.value === "null" ? null : Number(select.value)));
  wrap.append(label, select);
  return wrap;
}

/** The disclosure for one trip form; `mine.rule` keeps the picks and the last answer across renders. */
export function ruleJudgeSection({ mine, robot, call, scope, render }) {
  const rule = mine.rule ||= { kind: "return", values: {}, answer: null, note: null, busy: false, draft: false };
  const kind = RULE_KINDS[rule.kind];
  const box = document.createElement("div");
  box.className = "trip-rule";
  const kinds = document.createElement("label");
  const kindSelect = document.createElement("select");
  kindSelect.className = "ui-field";
  kindSelect.dataset.ruleKind = robot.robot_id;
  kindSelect.replaceChildren(...Object.entries(RULE_KINDS).map(([id, spec]) => new Option(spec.label, id)));
  kindSelect.value = rule.kind;
  kindSelect.addEventListener("change", () => { Object.assign(rule, { kind: kindSelect.value, values: {}, answer: null, note: null }); render(); });
  kinds.append("현장 규칙 판정", kindSelect);
  box.append(kinds);
  const fresh = robot.power_health?.battery?.evidence === "fresh" ? robot.power_health.battery.percent : null;
  const values = {};
  for (const [key, label, choices, fallback] of kind.picks) {
    const start = key === "percent" && fresh !== null ? choices.reduce((a, b) => Math.abs(b - fresh) < Math.abs(a - fresh) ? b : a) : fallback;
    values[key] = key in rule.values ? rule.values[key] : start;
    box.append(pick(label, choices, values[key], (value) => { rule.values[key] = values[key] = value; rule.answer = null; }));
  }
  const draft = document.createElement("label");
  draft.className = "ui-check";
  const check = document.createElement("input");
  check.className = "ui-field";
  check.type = "checkbox";
  check.checked = rule.draft;
  check.addEventListener("change", () => { rule.draft = check.checked; rule.answer = null; });
  const draftText = document.createElement("span");
  draftText.textContent = "저장한 초안 규칙으로";
  draft.append(check, draftText);
  const ask = quietButton("규칙으로 판정");
  ask.dataset.ruleJudge = robot.robot_id;
  ask.addEventListener("click", scope.guard(async () => {
    const life = scope.capture();
    rule.busy = true;
    rule.note = null;
    try {
      const body = { state: ruleJudgeState(rule.kind, robot.robot_id, values), source: rule.draft ? "draft" : "active" };
      const answer = await call("/api/fleet/site-rules/judge",
        { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      life.check();
      rule.answer = answer;
    } catch (err) {
      if (err.name === "AbortError") return;
      rule.answer = null;
      rule.note = "판정을 받지 못했습니다. 다시 눌러 주세요.";
    } finally {
      rule.busy = false;
      if (life.current()) render();
    }
  }));
  ask.disabled = rule.busy;
  ask.setAttribute("reason", "판정 중");
  const out = document.createElement("p");
  out.className = "hint";
  out.setAttribute("role", "status");
  if (rule.answer) {
    const tag = document.createElement("ui-tag");
    tag.setAttribute("status", (VERDICT[rule.answer.verdict] || [])[1] || "neutral");
    tag.textContent = ruleAnswerText(rule.answer);
    const source = { given: "입력한", draft: "초안", active: "활성", default: "기본값(문서 없음)" }[rule.answer.rules_source] || "";
    const open = rule.answer.detail?.enforced === false ? " · 편대 시작은 아직 이 한도로 막지 않음" : "";
    out.append(tag, ` 규칙: ${source} · 보내지 않음${open}`);
  } else {
    out.textContent = rule.note || "가정 상태로 묻는 판정입니다 · 로봇에 보내지 않습니다";
  }
  box.append(draft, ask, out);
  return box;
}
