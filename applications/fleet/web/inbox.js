// D-632: view-only context tabs and the request log; transport and polling stay in the console shell.
// 11-18 알림 한 곳: 알림은 .queues-panel 한 곳이다. 벨 숫자는 그 큐의 열린 행 수(긴급+주의)이고 '읽음'은 없다.
// 벨은 큐 패널로 데려간다. '알림' 탭은 없앴고 판단 전달 기록(#inbox-messages)과 기록(#log)은 '기록·근거' 탭에 있다.
// D-1117: #inbox-messages는 큐 행이 이미 말하는 stuckSummary 요약을 다시 쓰지 않고 로봇별 전달 기록만 그린다.
import { createTabs } from "/common/interaction-controls.js";
import { CAUSE_LABEL, DECISION_LABEL, aiProposalText, fleetAnswerText } from "./line-stuck.js";
import { showInboxCount } from "/console/assets/fleet-header.js";

const LOG_MAX = 120;

function stuckMessageJson(stuck) {
  const inquiry = stuck.inquiry, proposal = stuck.ai_proposal, answer = stuck.fleet_answer;
  const facts = stuck.ai_facts || [];
  return JSON.stringify({
    core_inquiry: inquiry ? {
      version: inquiry.version, problem_id: inquiry.problem_id, task: inquiry.task,
      cause: inquiry.observations?.cause, lane_visible: inquiry.observations?.lane_visible,
      front_clear: inquiry.observations?.front_clear, boundary_revision: inquiry.lane_boundary?.revision,
    } : null,
    ai_proposal: proposal ? { decision: proposal.decision, reason: proposal.reason, class: proposal.class, verdict: proposal.verdict, outcome: proposal.outcome } : null,
    ai_facts: facts.map(fact => ({ kind: fact.kind, source: fact.source, stage: fact.stage, confidence: fact.confidence })),
    fleet_answer: answer ? { decision: answer.decision, tier: answer.tier, accepted: answer.accepted, code: answer.code, outcome: answer.outcome } : null,
  }, null, 2);
}

export function createInboxPanel({scope, el, readView}) {
  const params = new URLSearchParams(location.search);
  // ?inbox=1은 예전 '알림' 탭 링크(판단 전달 기록) — 이제 '기록·근거' 탭이다. ?queue=1은 다른 Fleet 문서의 벨.
  let contextChoice = params.get("inbox") === "1" ? "evidence" : "status";
  let wantsQueue = params.get("queue") === "1";  // focus the queue once its first state has painted

  function queuePanel() {
    const queue = typeof document !== "undefined" ? document.querySelector?.(".queues-panel") : null;
    if (queue && !queue.hasAttribute?.("tabindex")) queue.tabIndex = -1;
    return queue;
  }
  function focusQueue(queue = queuePanel()) {
    queue?.scrollIntoView({block: "nearest"});
    queue?.focus({preventScroll: true});
  }
  queuePanel();

  // 벨(#fleet-inbox): 큐가 이 화면에 보이면 그리로 포커스, 아니면 막지 않아 /console?queue=1로 간다.
  scope.listen(document, "rosy:inbox", event => {
    const queue = queuePanel();
    if (!queue || (queue.checkVisibility && !queue.checkVisibility())) return;
    event.preventDefault();
    focusQueue(queue);
  });

  // 벨 숫자 = 큐의 열린 개입 행 수. 탭·기록과 무관하다.
  function paintBell() {
    showInboxCount(document.querySelectorAll('#critical-list > li[data-key], #warning-list > li[data-key]').length);
  }
  const tabKeys = ["status", "evidence", "tools"];
  const tabs = createTabs({
    id: "context",
    label: "관제 상세 보기",
    activation: "automatic",
    tabs: [
      { id: "status", panelId: "context-status", label: "로봇·작업", icon: "robot", content: el("context-status-body") || el("context-status") },
      { id: "evidence", panelId: "context-evidence", label: "기록·근거", icon: "list", content: el("context-evidence-body") || el("context-evidence") },
      { id: "tools", panelId: "context-tools", label: "운영 도구", icon: "tools", content: el("context-tools-body") || el("context-tools") },
    ],
    onChange: (key) => {
      contextChoice = key;
      refreshInbox();
    },
  });
  tabs.element.querySelector('[role="tablist"]')?.classList.add("context-tabs");
  const tabButtons = [...tabs.element.querySelectorAll('[role=tab]')];
  const tabPanels = [...tabs.element.querySelectorAll('[role=tabpanel]')];
  tabKeys.forEach((key, index) => {
    const button = tabButtons[index], panel = tabPanels[index];
    button.id = `context-${key}-tab`;
    button.dataset.contextTab = key;
    panel.classList.add("context-panel");
    panel.setAttribute("aria-labelledby", button.id);
  });
  (el("context-tabs-mount") || document.querySelector(".console-context > .context-tabs"))?.replaceWith(tabs.element);
  scope.onDispose(() => tabs.dispose());
  if (contextChoice !== "status") tabs.select(contextChoice);

  function refreshInbox() {
    paintInboxMessages();
    paintBell();
    if (wantsQueue && readView().stateLoaded) { wantsQueue = false; focusQueue(); }
  }

  function paintInboxMessages() {
    const view = readView();
    const stuckRobots = view.stateUnavailable ? [] : (view.robots || []).filter(robot => robot.line_stuck);
    const messagesByRobot = new Map();
    for (const robot of stuckRobots) {
      const message = stuckMessageJson(robot.line_stuck);
      messagesByRobot.set(robot.robot_id, message);
    }
    if (contextChoice !== "evidence") return;
    const list = el("inbox-messages");
    if (view.stateUnavailable) {
      list.textContent = "상태 갱신 실패 · 현재 전달 기록을 확인할 수 없습니다.";
      return;
    }
    const old = new Map([...list.children].map(node => [node.dataset.robotId, node]));
    const nodes = stuckRobots.map(robot => {
      const stuck = robot.line_stuck, inquiry = stuck.inquiry, proposal = stuck.ai_proposal, answer = stuck.fleet_answer;
      let item = old.get(robot.robot_id);
      if (!item) {
        item = document.createElement("li");
        item.dataset.robotId = robot.robot_id;
        const heading = document.createElement("strong"), stages = document.createElement("dl");
        heading.textContent = robot.robot_id;
        stages.className = "diag-readout";
        for (const label of ["로봇 문의 (CORE)", "AI 분석", "관제 전달 (Fleet)", "로봇 응답 (CORE)"]) {
          const term = document.createElement("dt");
          term.textContent = label;
          stages.append(term, document.createElement("dd"));
        }
        const raw = document.createElement("details"), summary = document.createElement("summary");
        summary.className = "ui-disclosure-row";
        summary.textContent = "개발 진단 · 전달 필드 보기";
        raw.append(summary, stages, document.createElement("pre"));
        const evidence = document.createElement("details"), title = document.createElement("summary");
        title.className = "ui-disclosure-row";
        title.textContent = "판단 근거";
        const receipt = document.createElement("p");
        receipt.dataset.messageEvidence = "";
        evidence.append(title, receipt, raw);
        item.append(heading, evidence);
      }
      if (item.dataset.stuckId && item.dataset.stuckId !== stuck.stuck_id) {
        const focused = item.contains(document.activeElement);
        item.querySelectorAll("details").forEach(fold => { fold.open = false; });
        if (focused) item.querySelector(":scope > details > summary").focus({preventScroll: true});
      }
      item.dataset.stuckId = stuck.stuck_id;
      const facts = stuck.ai_facts || [];
      // 큐 패널 행이 이미 stuckSummary 요약을 말한다(D-1117 중복 제거) — 여기는 전달 기록(영수증)만.
      item.querySelector('[data-message-evidence]').textContent = `로봇 문의: ${CAUSE_LABEL[inquiry?.observations?.cause || stuck.cause] || "원인 미확인"} · AI 분석: ${proposal ? "제안 있음" : facts.length ? "참고 관측 있음" : "기록 없음"} · 관제: ${answer ? "지시 기록 있음" : "전달 기록 미확인"} · 로봇: ${answer?.accepted === true ? "수락 · 완료는 별도 확인" : answer?.code === "ROBOT_UNREACHABLE" ? "연결 실패 · 전달하지 못함" : answer?.accepted === false ? "거절 · 개발 진단에서 응답 확인" : "응답 미확인"}`;
      const values = [inquiry ? `${CAUSE_LABEL[inquiry.observations?.cause] || "원인 미확인"} · 문의 수신` : "기록 없음",
        proposal ? `AI 제안 ${DECISION_LABEL[proposal.decision] || proposal.decision} · ${proposal.reason || "판단 근거 기록 없음"}` : facts.length ? facts.map(fact => `${fact.kind} · 신뢰도 ${Number.isFinite(fact.confidence) ? `${Math.round(fact.confidence * 100)}%` : "정보 없음"}`).join(" · ") : "기록 없음",
        answer ? `전송 ${DECISION_LABEL[answer.decision] || answer.decision}` : proposal ? proposal.verdict === "forwarded" ? "CORE로 전달" : aiProposalText(proposal) : "기록 없음",
        fleetAnswerText(answer) || (proposal && ["accepted", "refused", "pending"].includes(proposal.class)
          ? `${aiProposalText(proposal)} · 실행 완료는 별도 확인` : "CORE 전달·응답 기록 없음 · 실행 완료 미확인")];
      item.querySelectorAll("dd").forEach((node, index) => { node.textContent = values[index]; });
      // Show only known message fields; never dump a state row or credentials.
      const message = messagesByRobot.get(robot.robot_id);
      if (item.dataset.message !== message) {
        item.dataset.message = message;
        item.querySelector("pre").textContent = message;
      }
      return item;
    });
    if (list.childElementCount !== nodes.length || [...list.children].some((node, index) => node !== nodes[index]))
      list.replaceChildren(...nodes);
    if (!nodes.length) {
      const emptyText = "현재 열린 판단 문의의 전달 기록이 없습니다. 지난 판단은 사건 기록에서 확인하세요.";
      if (list.textContent !== emptyText) list.textContent = emptyText;
    }
  }
  function selectContext(choice, focus = false) {
    contextChoice = choice;
    tabs.select(choice);
    if (focus) tabButtons[tabKeys.indexOf(choice)]?.focus({preventScroll: true});
    refreshInbox();
  }
  scope.listen(el("cancel-all-details"), "click", () => selectContext("evidence"));
  function log(text, kind) {
    const line = document.createElement("div");
    if (kind) line.className = kind;
    const now = new Date().toTimeString().slice(0, 8);
    line.textContent = `${now}  ${text}`;
    const box = el("log");
    box.querySelector("ui-empty")?.remove();
    box.prepend(line);
    while (box.childElementCount > LOG_MAX) box.lastElementChild.remove();
  }

  scope.listen(el("log-clear"), "click", () => {
    const box = el("log");
    box.replaceChildren(document.createElement("ui-empty"));
    box.firstChild.textContent = "지웠습니다.";
    el("cancel-all-details").hidden = true;
  });
  return {refresh: refreshInbox, log,
    focusInitial() {
      if (contextChoice !== "evidence") return;
      el("context-evidence").focus();
      el("context-evidence").scrollIntoView({block: "nearest"});
    },
    select: selectContext, get choice() { return contextChoice; }};
}
