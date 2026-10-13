// Incident evidence display, human review and export; transport/session stay in console.js.
import { CAUSE_LABEL, DECISION_LABEL } from "./line-stuck.js";

const INCIDENT_CAUSES = {
  line_marking: "차선·바닥 표식", obstacle: "장애물", robot_fault: "로봇·센서 오류",
  localization: "위치 추정", traffic_wait: "교통 대기", unknown: "미확인",
};
const DELIVERY_LABEL = {PENDING: '전송 대기', SENDING: '전송 중 · 결과 미확인', SENT: '제공자 수락 · 수신 확인은 별도',
  RETRY: '제한 재시도 대기', UNKNOWN: '전송 여부 불명 · 재전송하지 않음', FAILED: '전송 실패',
  EXPIRED: '통지 기한 종료', SUPERSEDED: '현재 사건·담당·목적지 변경으로 취소'};

export function createIncidentView({scope, el, view, call, log, auth, onReports}) {
const linked = new URLSearchParams(location.search);
const linkedRobot = linked.get('robot'), linkedIncident = linked.get('incident');
let linkedFocused = false;
// D-741 8 — 기록 영역(?view=records)에서는 하위 탐색이 고른 사건만 보이고, 연 사건의 원인과 조치가 오른쪽 칸에 선다.
const records = linked.get("view") === "records", show = linked.get("show");
const kept = !records || linkedIncident ? () => true : show === "open" ? report => !report.closed_at
  : show === "closed" ? report => report.closed_at : report => !report.reviews.length;
if (records) document.querySelector(".incident-panel").dataset.show = show === "facts" ? "facts" : "incidents";
// One list row: the fold, its summary and the developer-diagnostics fold. Open folds survive a repaint.
function incidentRow(key, openReports) {
  const item = document.createElement("li"), detail = document.createElement("details"), summary = document.createElement("summary");
  const raw = document.createElement("details"), rawTitle = document.createElement("summary");
  item.className = "incident-row";
  summary.className = rawTitle.className = "ui-disclosure-row";
  rawTitle.textContent = "개발 진단";
  detail.dataset.reportKey = key;
  raw.dataset.reportKey = `${key}|diagnostics`;
  detail.open = openReports.has(key);
  raw.open = openReports.has(raw.dataset.reportKey);
  detail.append(summary);
  raw.append(rawTitle);
  item.append(detail);
  if (!records) return {item, detail, summary, raw, side: detail};
  const side = document.createElement("div"), seat = el("incident-judgment");
  side.className = "incident-row";
  side.dataset.reportKey = key;
  // One fold at a time, closed here in script: the seat must never hold another incident than the open fold.
  const place = event => {
    if (!detail.open) return side.remove();
    for (const other of document.querySelectorAll(".incident-row > details[open]")) if (other !== detail) other.open = false;
    if (seat.firstChild !== side) seat.replaceChildren(side);
    if (event) seat.scrollIntoView({block: "nearest"});
  };
  detail.addEventListener("toggle", place);
  place();
  return {item, detail, summary, raw, side};
}
function incidentSummary(summary, report, title, side) {
  const name = document.createElement("span");
  name.textContent = title;
  const time = document.createElement("time");
  const opened = report.opened_at ? new Date(report.opened_at) : null;
  time.textContent = opened && Number.isFinite(opened.getTime())
    ? `시작 ${opened.toLocaleString("ko-KR")}` : "시각 미확인";
  if (opened && Number.isFinite(opened.getTime())) time.dateTime = opened.toISOString();
  summary.append(name, time);
  if (side !== summary.parentNode) side.prepend(Object.assign(document.createElement("h3"), {textContent: `${title} · ${time.textContent}`}));
}
function incidentLine(parent, value) {
  const line = document.createElement("p");
  line.textContent = value;
  parent.append(line);
}
function incidentReviewForm(report, path) {
  const form = document.createElement("form");
  const select = document.createElement("select");
  select.className = "ui-field";
  select.setAttribute("aria-label", `${report.robot_ids.map(incidentRobotName).join(", ")} 원인 분류`);
  for (const [value, label] of Object.entries(INCIDENT_CAUSES)) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = label;
    select.append(option);
  }
  select.value = report.reviews.at(-1)?.root_cause || "unknown";
  const note = document.createElement("input");
  note.className = "ui-field";
  note.maxLength = 1000;
  note.placeholder = "판단 근거 또는 수정 내용";
  note.setAttribute("aria-label", `${report.robot_ids.map(incidentRobotName).join(", ")} 검토 메모`);
  const save = document.createElement("ui-button");
  save.setAttribute("kind", "quiet");
  save.type = "submit";
  save.textContent = "검토 기록";
  form.append(select, note, save);
  form.addEventListener("submit", scope.guard(async event => {
    event.preventDefault();
    save.disabled = true;
    save.setAttribute("reason", "검토 기록을 저장하고 있습니다");
    try {
      await call(path, {method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({root_cause: select.value, note: note.value})});
      log(`${report.robot_ids.map(incidentRobotName).join(", ")} 사건 검토를 기록했습니다.`, "good");
      await refreshIncidents();
    } catch (error) {
      log(`사건 검토 기록 실패: ${error.message}`, "bad");
      save.disabled = false;
      save.removeAttribute("reason");
    }
  }));
  return form;
}
function incidentRobotName(robotId) {
  const name = view.robotNames[robotId];
  return name && name !== robotId ? `${name} (${robotId})` : robotId;
}

async function refreshIncidents() {
  if (auth.locked) return;
  const status = el("incident-status");
  try {
    const filter = linkedRobot && linkedIncident
      ? `&robot_id=${encodeURIComponent(linkedRobot)}&stuck_id=${encodeURIComponent(linkedIncident)}` : '';
    const payload = await call(`/api/fleet/incidents?limit=${records ? 100 : 10}${filter}`);
    const fetched = payload.reports || [];
    const incidentReports = fetched.filter(kept);
    onReports(fetched);
    const incidentTrafficReports = payload.traffic_reports || [];
    status.textContent = `최근 라인 정지 ${records && fetched.length >= 100 ? "100건 중 " : ""}${incidentReports.length}건 · AI 상황 사실 ${incidentTrafficReports.length}건`;
    el("incident-export").disabled = !incidentReports.length && !incidentTrafficReports.length;
    if (el("incident-export").disabled) el("incident-export").setAttribute("reason", "내보낼 사건이 없습니다");
    else el("incident-export").removeAttribute("reason");
    const list = el("incident-list");
    const openReports = new Set([...document.querySelectorAll('.incident-panel details[data-report-key][open]')].map(node => node.dataset.reportKey));
    const focusedReport = document.activeElement?.closest('[data-report-key]')?.dataset.reportKey;
    const focusedLabel = document.activeElement?.getAttribute("aria-label");
    list.replaceChildren();
    el("incident-judgment").replaceChildren();
    for (const report of incidentReports) {
      const {item, detail, summary, raw, side} = incidentRow(`${report.robot_ids.join("|")}|${report.stuck_id}`, openReports);
      const core = report.evidence.core, fleet = report.evidence.fleet;
      const causeName = CAUSE_LABEL[core.cause] || "원인 미확인";
      incidentSummary(summary, report, `${report.robot_ids.map(incidentRobotName).join(", ")} · ${causeName} · ${report.closed_at ? "과거 · 종료 기록 있음" : "사건 기록 · 종료 미확인"} · ${report.reviews.length ? "검토 기록 있음" : "검토 필요"}`, side);
      incidentLine(detail, `상태: 라인 정지 · ${report.closed_at ? "종료 기록 있음" : "종료 기록 없음"} · 교착 여부는 별도 판정합니다.`);
      incidentLine(detail, `로봇 관측: 정지 ${core.held_s_max ?? "미확인"}초 · 재시도 ${core.attempts_max ?? "미확인"}`);
      incidentLine(detail, `관제 관측: 위치 ${{LOCALIZED: "확정", DEGRADED: "정확도 저하", UNKNOWN: "확인 불가"}[fleet.pose_state] || "미확인"} · 관측 나이 ${fleet.pose_age_s ?? "미확인"}초`);
      const closure = {OPEN: "진행 기록 · 현재 관측은 별도 확인", NATURAL_CLEARANCE: "관측상 자연 해소 · 조치 기록 없음", CLEARANCE_OBSERVED: "관측상 해소 · 조치 성공은 미검증", OBSERVATION_ENDED: "관측 종료 · 문제 해결은 미확인"}[report.closure?.status] || "해소 결과 미확인";
      incidentLine(detail, `해소 확인: ${closure}`);
      incidentLine(raw, `당시 CORE 단계 ${core.phase_at_open || "미확인"} · Fleet 종료 사유 ${fleet.close_reason || "미확인"} · 마지막 수락 답 주체 ${fleet.resolved_by || "미확인"}`);
      const cam = report.evidence.rosy_cam;
      incidentLine(detail, cam ? `현장 카메라: 사건 당시 관측 · 촬영 ${new Date(cam.captured_at * 1000).toLocaleString()}`
        : "Rosy Cam: 사건 시작 ±5초 관측 없음");
      if (cam) incidentLine(raw, `Rosy Cam: ${cam.source_id}, seq ${cam.seq}`);
      incidentLine(detail, report.closed_at
        ? "Pinky 앞 카메라: 사건 종료 후 이미지는 보존되지 않음"
        : "Pinky 앞 카메라: 현재 열린 사건의 영상은 위 개입 목록에서 확인 · 종료 후 이미지는 보존되지 않음");
      const ai = report.evidence.ai_facts || [];
      const draft = ai.find(f => f.kind === "incident_context");
      if (draft) {
        const names = {line_marking: "차선 표시 또는 인식", obstacle: "전방 장애물", unknown: "원인 미확정"};
        incidentLine(detail, `AI PC 원인 초안: ${names[draft.value.cause_draft] || "원인 미확정"} · 검증되지 않은 초안 점수 ${Math.round(draft.confidence * 100)}% · 사람 검토 필요`);
        for (const item of draft.value.support || []) incidentLine(raw, `${item.source} ${item.field}: ${JSON.stringify(item.value)}`);
        incidentLine(detail, `추가 확인: ${(draft.value.missing || []).length ? "누락된 근거가 있습니다. 개발 진단에서 항목을 확인하세요." : "누락 기록 없음"}`);
        incidentLine(raw, `누락 근거: ${(draft.value.missing || []).join(", ")}`);
      }
      incidentLine(raw, ai.length ? `AI 참고: ${ai.map(f => `${f.kind} (${f.stage}, ${Math.round(f.confidence * 100)}%)`).join(" · ")}`
        : "AI 참고: 사건 시작 ±5초 사실 없음");
      incidentLine(detail, report.actions.length ? `관제 지시 → 로봇 응답: ${report.actions.map(a => `${DECISION_LABEL[a.decision] || "조치 미확인"} ${a.accepted === 1 ? "수락됨 · 실행 완료는 별도 확인" : a.accepted === 0 ? "거절됨" : "결과 미확인"}`).join(" · ")}`
        : "조치: 기록 없음");
      incidentLine(raw, `조치 필드: ${JSON.stringify(report.actions)}`);
      const latest = report.reviews.at(-1);
      incidentLine(side, report.handoff
        ? `담당 인수: ${report.handoff.principal_id} · 조치 수락·해소는 별도 확인`
        : '담당 인수: 아직 없음 · 자동 해결기 중지 요청과 구별');
      incidentLine(detail, report.notifications?.length
        ? `외부 알림: ${report.notifications.map(item => `${item.channel} ${item.kind === 'CLOSED' ? '종료 관측' : '검토 요청'} · ${DELIVERY_LABEL[item.state] || '전송 기록 미확인'}`).join(' / ')}`
        : '외부 알림: 전송 기록 없음');
      incidentLine(side, latest ? `사람 검토: ${INCIDENT_CAUSES[latest.root_cause] || "원인 미확인"} · ${latest.note || "메모 없음"}`
        : "사람 검토: 아직 없음");
      if (latest) incidentLine(raw, `검토자 ${latest.principal_id} · 원인 ${latest.root_cause}`);
      if (auth.role === "operator") {
        if (!report.closed_at && !report.handoff && report.judgment_revision) {
          const claim = document.createElement('ui-button');
          claim.setAttribute('kind', 'quiet');
          claim.textContent = '이 사건 맡기';
          claim.addEventListener('click', scope.guard(async () => {
            claim.setAttribute('reason', '담당 인수를 기록하고 있습니다');
            claim.disabled = true;
            try {
              await call(`/api/fleet/robots/${encodeURIComponent(report.robot_ids[0])}/line-stuck/claim`, {
                method: 'POST', headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({stuck_id: report.stuck_id, judgment_revision: report.judgment_revision}),
              });
              log('담당 인수를 기록했습니다. 조치와 해소는 별도 확인합니다.', 'good');
            } catch (error) {
              log(`담당 인수 미확인: ${error.message} · 현재 기록을 다시 확인하세요.`, 'bad');
            }
            await refreshIncidents();
          }));
          side.append(claim);
        }
        side.append(incidentReviewForm(report,
          `/api/fleet/incidents/${encodeURIComponent(report.robot_ids[0])}/${encodeURIComponent(report.stuck_id)}/review`));
      }
      detail.append(raw);
      list.append(item);
      if (!linkedFocused && report.robot_ids[0] === linkedRobot && report.stuck_id === linkedIncident) {
        detail.open = true;
        summary.focus();
        linkedFocused = true;
      }
    }
    if (records && !incidentReports.length) list.append(Object.assign(document.createElement("li"), {textContent: "이 화면에 해당하는 사건이 없습니다."}));
    const trafficList = el("incident-traffic-list");
    trafficList.replaceChildren();
    for (const report of incidentTrafficReports) {
      const ai = report.evidence.ai_fact;
      const {item, detail, summary, raw, side} = incidentRow(report.id, openReports);
      const name = report.classification === "wait_cycle_confirmed"
        ? ai.value?.fleet_agrees === false ? "AI 단독 대기 순환 판단" : "AI·Fleet 대기 순환 일치"
        : {wait_cycle_stale_input: "낡은 입력의 대기 순환 후보", waiting_but_moving: "대기 중 이동",
           livelock: "반복 경로 정체", stalled: "운행 정체", unknown_occupancy_long: "위치 불명 점유 지속"}[report.classification]
          || "상황 분류 미확인";
      incidentSummary(summary, report, `${name} · ${report.robot_ids.map(incidentRobotName).join(", ")}`, side);
      incidentLine(detail, `AI 분석 참고 · 신뢰도 ${Math.round(ai.confidence * 100)}% · 조치 명령과 별도입니다.`);
      incidentLine(raw, `AI ${ai.source} · ${ai.stage} · 분류 ${report.classification}`);
      incidentLine(raw, `측정값: ${JSON.stringify(ai.value)} · 근거: ${JSON.stringify(ai.evidence)}`);
      incidentLine(detail, "CORE·Rosy Cam: 이 AI 사실과 연결된 영속 표본 없음");
      const latest = report.reviews.at(-1);
      incidentLine(side, latest ? `사람 검토: ${INCIDENT_CAUSES[latest.root_cause] || "원인 미확인"} · ${latest.note || "메모 없음"}`
        : "사람 검토: 아직 없음");
      if (latest) incidentLine(raw, `검토자 ${latest.principal_id} · 원인 ${latest.root_cause}`);
      if (auth.role === "operator") side.append(incidentReviewForm(report,
        `/api/fleet/incidents/facts/${ai.fact_row}/review`));
      detail.append(raw);
      trafficList.append(item);
    }
    if (focusedReport) {
      const folds = [...document.querySelectorAll('.incident-panel details[data-report-key], #incident-judgment > [data-report-key]')].filter(node => node.dataset.reportKey === focusedReport);
      const target = folds.flatMap(node => [...node.querySelectorAll('[aria-label]')]).find(node => node.getAttribute("aria-label") === focusedLabel) || folds[0]?.querySelector("summary");
      target?.focus({preventScroll: true});
    }
    if (!incidentTrafficReports.length) {
      const empty = document.createElement("li");
      empty.textContent = "저장된 AI 상황 사실이 없습니다.";
      trafficList.append(empty);
    }
  } catch (error) {
    if (error.name === "AbortError") return;
    onReports([]);
    status.textContent = `사건 기록을 불러오지 못했습니다: ${error.message}`;
  }
}
scope.listen(el("incident-refresh"), "click", refreshIncidents);
scope.listen(el("incident-export"), "click", async () => {
  try {
    const payload = await call("/api/fleet/incidents?limit=100");
    const url = URL.createObjectURL(new Blob([JSON.stringify(payload, null, 2)], {type: "application/json"}));
    const link = document.createElement("a");
    link.href = url;
    link.download = "rosy-incidents.json";
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  } catch (error) {
    if (error.name !== "AbortError") log(`사건 JSON 내보내기 실패: ${error.message}`, "bad");
  }
});

function reset() {
  onReports([]);
  el("incident-list").replaceChildren();
  el("incident-traffic-list").replaceChildren();
  el("incident-judgment").replaceChildren();
  el("incident-export").disabled = true;
  el("incident-export").setAttribute("reason", "관제 접속 후 내보낼 수 있습니다");
  el("incident-status").textContent = "관제 접속 후 사건을 불러옵니다.";
}
return {refresh: refreshIncidents, reset};
}
