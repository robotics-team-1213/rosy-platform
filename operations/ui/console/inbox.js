// D-632: view-only notification owner; transport and polling stay in the console shell.
import { CAUSE_LABEL, DECISION_LABEL, aiProposalText, fleetAnswerText, stuckSummary } from "./line-stuck.js";
import { showInboxCount } from "/console/assets/fleet-header.js";

const LOG_MAX = 120;

export function createInboxPanel({scope, el, readView}) {
  const contextTabs = [...document.querySelectorAll('[data-context-tab]')];
  let contextChoice = new URLSearchParams(location.search).get("inbox") === "1" ? "inbox" : "status";
  const inboxAttention = new Map();
  let lastLogMessage = "";
  function paintInbox() {
    const reading = contextChoice === "inbox";
    if (reading) {
      for (const item of inboxAttention.values()) item.unread = false;
      el("log").querySelectorAll('[data-unread]').forEach(line => delete line.dataset.unread);
    }
    const count = [...inboxAttention.values()].filter(item => item.unread).length
      + el("log").querySelectorAll('[data-unread]').length;
    showInboxCount(count);
  }
  function refreshInbox() {
    const rows = [...document.querySelectorAll('#critical-list > li, #warning-list > li')];
    const keys = new Set();
    const summary = el("inbox-current");
    const focusedKey = document.activeElement?.closest('#inbox-current > li')?.dataset.key;
    summary.replaceChildren();
    for (const row of rows) {
      const key = row.dataset.key;
      if (!key) continue;
      keys.add(key);
      const text = (row.querySelector('.queue-row') || row).textContent.trim();
      const signature = text.replace(/\d+/g, "#");
      const old = inboxAttention.get(key);
      if (!old || old.signature !== signature) inboxAttention.set(key, {signature, unread: true});
      const item = document.createElement("li"), link = document.createElement("a");
      item.dataset.key = key;
      item.append(document.createTextNode(`${text} `));
      link.href = "#queues-heading";
      link.textContent = "개입 목록으로";
      link.addEventListener("click", () => {
        const queue = document.querySelector('.queues-panel');
        queue.tabIndex = -1;
        queue.focus();
      });
      item.append(link);
      summary.append(item);
      if (key === focusedKey) link.focus({preventScroll: true});
    }
    for (const key of inboxAttention.keys()) if (!keys.has(key)) inboxAttention.delete(key);
    if (!rows.length) summary.textContent = "현재 개입 요청이 없습니다.";
    paintInboxMessages();
    paintInbox();
  }
  function paintInboxMessages() {
    const view = readView();
    const list = el("inbox-messages");
    if (view.stateUnavailable) {
      list.textContent = "상태 갱신 실패 · 현재 전달 기록을 확인할 수 없습니다.";
      return;
    }
    const old = new Map([...list.children].map(node => [node.dataset.robotId, node]));
    const nodes = view.robots.filter(robot => robot.line_stuck).map(robot => {
      const stuck = robot.line_stuck, inquiry = stuck.inquiry, proposal = stuck.ai_proposal, answer = stuck.fleet_answer;
      let item = old.get(robot.robot_id);
      if (!item) {
        item = document.createElement("li");
        item.dataset.robotId = robot.robot_id;
        const heading = document.createElement("strong"), stages = document.createElement("dl");
        const status = document.createElement("p");
        status.dataset.messageSummary = "";
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
        item.append(heading, status, evidence);
      }
      if (item.dataset.stuckId && item.dataset.stuckId !== stuck.stuck_id) {
        const focused = item.contains(document.activeElement);
        item.querySelectorAll("details").forEach(fold => { fold.open = false; });
        if (focused) item.querySelector(":scope > details > summary").focus({preventScroll: true});
      }
      item.dataset.stuckId = stuck.stuck_id;
      const facts = stuck.ai_facts || [];
      item.querySelector('[data-message-summary]').textContent = stuckSummary(stuck);
      item.querySelector('[data-message-evidence]').textContent = `로봇 문의: ${CAUSE_LABEL[inquiry?.observations?.cause || stuck.cause] || "원인 미확인"} · AI 분석: ${proposal ? "제안 있음" : facts.length ? "참고 관측 있음" : "기록 없음"} · 관제: ${answer ? "지시 기록 있음" : "전달 기록 미확인"} · 로봇: ${answer?.accepted === true ? "수락 · 완료는 별도 확인" : answer?.code === "ROBOT_UNREACHABLE" ? "연결 실패 · 전달하지 못함" : answer?.accepted === false ? "거절 · 개발 진단에서 응답 확인" : "응답 미확인"}`;
      const values = [inquiry ? `${CAUSE_LABEL[inquiry.observations?.cause] || "원인 미확인"} · 문의 수신` : "기록 없음",
        proposal ? `AI 제안 ${DECISION_LABEL[proposal.decision] || proposal.decision} · ${proposal.reason || "판단 근거 기록 없음"}` : facts.length ? facts.map(fact => `${fact.kind} · 신뢰도 ${Math.round(fact.confidence * 100)}%`).join(" · ") : "기록 없음",
        answer ? `전송 ${DECISION_LABEL[answer.decision] || answer.decision}` : proposal ? proposal.verdict === "forwarded" ? "CORE로 전달" : aiProposalText(proposal) : "기록 없음",
        fleetAnswerText(answer) || (proposal && ["accepted", "refused", "pending"].includes(proposal.class)
          ? `${aiProposalText(proposal)} · 실행 완료는 별도 확인` : "CORE 전달·응답 기록 없음 · 실행 완료 미확인")];
      item.querySelectorAll("dd").forEach((node, index) => { node.textContent = values[index]; });
      // Show only known message fields; never dump a state row or credentials.
      const message = JSON.stringify({
        core_inquiry: inquiry ? {version: inquiry.version, problem_id: inquiry.problem_id, task: inquiry.task,
          cause: inquiry.observations?.cause, lane_visible: inquiry.observations?.lane_visible,
          front_clear: inquiry.observations?.front_clear, boundary_revision: inquiry.lane_boundary?.revision} : null,
        ai_proposal: proposal ? {decision: proposal.decision, reason: proposal.reason, class: proposal.class, verdict: proposal.verdict, outcome: proposal.outcome} : null,
        ai_facts: facts.map(fact => ({kind: fact.kind, source: fact.source, stage: fact.stage, confidence: fact.confidence})),
        fleet_answer: answer ? {decision: answer.decision, tier: answer.tier, accepted: answer.accepted, code: answer.code, outcome: answer.outcome} : null,
      }, null, 2);
      if (item.dataset.message !== message) {
        item.dataset.message = message;
        if (contextChoice !== "inbox") {
          const attention = inboxAttention.get(`${robot.robot_id}|stuck`);
          if (attention) attention.unread = true;
        }
      }
      item.querySelector("pre").textContent = message;
      return item;
    });
    if (list.childElementCount !== nodes.length || [...list.children].some((node, index) => node !== nodes[index]))
      list.replaceChildren(...nodes);
    if (!nodes.length) list.textContent = "현재 열린 판단 문의의 전달 기록이 없습니다. 지난 판단은 사건 기록에서 확인하세요.";
  }
  function selectContext(choice, focus = false) {
    contextChoice = choice;
    for (const tab of contextTabs) {
      const selected = tab.dataset.contextTab === choice;
      tab.setAttribute("aria-selected", String(selected));
      tab.tabIndex = selected ? 0 : -1;
      el(tab.getAttribute("aria-controls")).hidden = !selected;
      if (selected && focus) tab.focus({preventScroll: true});
    }
    paintInbox();
  }
  scope.listen(document, "rosy:inbox", event => {
    event.preventDefault();
    selectContext("inbox");
    el("context-inbox").focus();
    el("context-inbox").scrollIntoView({block: "nearest"});
  });
  for (const tab of contextTabs) {
    scope.listen(tab, "click", () => selectContext(tab.dataset.contextTab));
    scope.listen(tab, "keydown", event => {
      const index = contextTabs.indexOf(tab);
      const next = {ArrowRight: (index + 1) % contextTabs.length,
        ArrowLeft: (index + contextTabs.length - 1) % contextTabs.length, Home: 0, End: contextTabs.length - 1}[event.key];
      if (next === undefined) return;
      event.preventDefault();
      selectContext(contextTabs[next].dataset.contextTab, true);
    });
  }
  // A result link must reveal its destination before native anchor scrolling.
  scope.listen(el("cancel-all-details"), "click", () => selectContext("inbox"));
  scope.listen(el("inbox-evidence"), "click", () => {
    selectContext("evidence");
    el("context-evidence").focus({preventScroll: true});
  });
  function markLog(line, text, kind) {
    const signature = `${kind || ""}:${text}`;
    if (contextChoice !== "inbox" && signature !== lastLogMessage) line.dataset.unread = "true";
    lastLogMessage = signature;
  }
  function log(text, kind) {
    const line = document.createElement("div");
    if (kind) line.className = kind;
    markLog(line, text, kind);
    const now = new Date().toTimeString().slice(0, 8);
    line.textContent = `${now}  ${text}`;
    const box = el("log");
    box.querySelector("ui-empty")?.remove();
    box.prepend(line);
    while (box.childElementCount > LOG_MAX) box.lastElementChild.remove();
    paintInbox();
  }

  scope.listen(el("log-clear"), "click", () => {
    const box = el("log");
    box.replaceChildren(document.createElement("ui-empty"));
    box.firstChild.textContent = "지웠습니다.";
    lastLogMessage = "";
    paintInbox();
    el("cancel-all-details").hidden = true;
  });
  return {refresh: refreshInbox, log,
    focusInitial() {
      if (contextChoice !== "inbox") return;
      el("context-inbox").focus();
      el("context-inbox").scrollIntoView({block: "nearest"});
    },
    select: selectContext, get choice() { return contextChoice; }};
}
