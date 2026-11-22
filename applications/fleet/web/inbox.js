// D-632: view-only notification and drawer owner; transport and polling stay in the console shell.
import { CAUSE_LABEL, DECISION_LABEL, aiProposalText, fleetAnswerText, stuckSummary } from "./line-stuck.js";
import { appendLogEntry } from "/console/assets/activity-log.js";
import { setTopbarOpen, showInboxCount } from "/console/assets/fleet-header.js";

const LOG_MAX = 120;

export function createInboxPanel({ scope, el, readView, isLocked = () => false }) {
  const contextTabs = [...document.querySelectorAll("[data-context-tab]")];
  const params = new URLSearchParams(location.search);
  const hasIncidentParam = params.has("incident");
  const linkedRobot = params.get("robot") || "";
  let pendingDrawerDeepLink = !hasIncidentParam && (params.get("inbox") === "1" || params.get("queue") === "1");
  let contextChoice = hasIncidentParam ? "evidence" : "status";
  let drawerOpen = false;

  const drawer = el("queues-panel");
  const bell = el("fleet-inbox");
  if (bell) {
    bell.setAttribute("aria-controls", "queues-panel");
    bell.setAttribute("aria-expanded", "false");
  }
  if (drawer && !drawer.dataset.open) drawer.dataset.open = "false";

  function paintBadge() {
    const unread = el("header-unread");
    const locked = isLocked();
    const critCount = locked ? 0
      : [...document.querySelectorAll("#critical-list > li")].filter((node) => node.dataset?.key).length;
    const warnCount = locked ? 0
      : [...document.querySelectorAll("#warning-list > li")].filter((node) => node.dataset?.key).length;
    const total = critCount + warnCount;
    if (bell && unread && typeof document.getElementById === "function"
        && document.getElementById("fleet-inbox") === bell && document.getElementById("header-unread") === unread) {
      showInboxCount(locked ? 0 : total);
    } else if (unread) {
      unread.textContent = !locked && total ? String(total) : "";
      unread.hidden = locked || total === 0;
    }
    if (!bell) return;
    if (locked) {
      delete bell.dataset.crit;
      delete bell.dataset.hasAlerts;
      bell.setAttribute("aria-label", "알림 창");
      bell.setAttribute("data-ui-tooltip", "알림 창");
      bell.title = "관제 알림";
      return;
    }
    if (critCount > 0) bell.dataset.crit = "true";
    else delete bell.dataset.crit;
    if (total > 0) bell.dataset.hasAlerts = "true";
    else delete bell.dataset.hasAlerts;
    const label = total === 0
      ? "알림 창 · 활성 알림 없음"
      : critCount > 0
        ? `알림 창 · 활성 알림 ${total}건 (최우선 ${critCount}건)`
        : `알림 창 · 활성 알림 ${total}건`;
    bell.setAttribute("aria-label", label);
    bell.setAttribute("data-ui-tooltip", `${label} · 해결할 때까지 표시됩니다`);
    bell.title = "확인이나 읽음으로 알림이 사라지지 않습니다";
  }

  function setDrawerOpen(open, { focus = false, restoreFocus = false } = {}) {
    const next = Boolean(open) && !isLocked();
    const active = document.activeElement;
    drawerOpen = next;
    if (drawer) drawer.dataset.open = String(next);
    if (bell) bell.setAttribute("aria-expanded", String(next));
    if (next) {
      if (el("topbar-more")?.getAttribute("aria-expanded") === "true") setTopbarOpen(false);
      if (focus && drawer) {
        const target = drawer.querySelector(".queue-row, details > summary, #queues-close") || drawer;
        if (target === drawer && drawer.tabIndex < 0) drawer.tabIndex = -1;
        target.focus?.({ preventScroll: true });
      }
      return;
    }
    if (restoreFocus && bell) {
      if (!active || active === document.body || active === document.documentElement || drawer?.contains?.(active)) {
        bell.focus?.({ preventScroll: true });
      }
    }
  }

  // B-2: land on the exact queue row (decision, folded cause or plain) inside the drawer.
  // Rows are matched by dataset.key over the elements — never by interpolating key into a selector.
  function jumpToQueueRow(key) {
    setDrawerOpen(true);
    const target = [...document.querySelectorAll("#critical-list > li, #warning-list > li")]
      .find((node) => node.dataset?.key === key);
    if (!target) {
      if (drawer) {
        if (drawer.tabIndex < 0) drawer.tabIndex = -1;
        drawer.focus?.({ preventScroll: true });
      }
      return false;
    }
    target.scrollIntoView?.({ block: "nearest" });
    const toggle = target.dataset.decision ? target.querySelector(".queue-row") : null;
    if (toggle) {
      if (toggle.getAttribute("aria-expanded") !== "true") toggle.click();
      toggle.focus?.({ preventScroll: true });
      return true;
    }
    const details = target.querySelector("details");
    if (details) {
      details.open = true;
      (details.querySelector("summary") || details).focus?.({ preventScroll: true });
      return true;
    }
    target.tabIndex = -1;
    target.focus?.({ preventScroll: true });
    return true;
  }

  function paintInboxMessages() {
    const view = readView();
    const list = el("inbox-messages");
    if (!list) return;
    if (view.stateUnavailable) {
      list.textContent = "상태 갱신 실패 · 현재 전달 기록을 확인할 수 없습니다.";
      return;
    }
    const old = new Map([...list.children].map((node) => [node.dataset.robotId, node]));
    const nodes = view.robots.filter((robot) => robot.line_stuck).map((robot) => {
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
        const focused = item.contains?.(document.activeElement);
        item.querySelectorAll("details").forEach((fold) => { fold.open = false; });
        if (focused) item.querySelector(":scope > details > summary")?.focus({ preventScroll: true });
      }
      item.dataset.stuckId = stuck.stuck_id;
      const facts = stuck.ai_facts || [];
      item.querySelector("[data-message-summary]").textContent = stuckSummary(stuck);
      item.querySelector("[data-message-evidence]").textContent = `로봇 문의: ${CAUSE_LABEL[inquiry?.observations?.cause || stuck.cause] || "원인 미확인"} · AI 분석: ${proposal ? "제안 있음" : facts.length ? "참고 관측 있음" : "기록 없음"} · 관제: ${answer ? "지시 기록 있음" : "전달 기록 미확인"} · 로봇: ${answer?.accepted === true ? "수락 · 완료는 별도 확인" : answer?.code === "ROBOT_UNREACHABLE" ? "연결 실패 · 전달하지 못함" : answer?.accepted === false ? "거절 · 개발 진단에서 응답 확인" : "응답 미확인"}`;
      const values = [
        inquiry ? `${CAUSE_LABEL[inquiry.observations?.cause] || "원인 미확인"} · 문의 수신` : "기록 없음",
        proposal ? `AI 제안 ${DECISION_LABEL[proposal.decision] || proposal.decision} · ${proposal.reason || "판단 근거 기록 없음"}` : facts.length ? facts.map((fact) => `${fact.kind} · 신뢰도 ${Math.round(fact.confidence * 100)}%`).join(" · ") : "기록 없음",
        answer ? `전송 ${DECISION_LABEL[answer.decision] || answer.decision}` : proposal ? proposal.verdict === "forwarded" ? "CORE로 전달" : aiProposalText(proposal) : "기록 없음",
        fleetAnswerText(answer) || (proposal && ["accepted", "refused", "pending"].includes(proposal.class)
          ? `${aiProposalText(proposal)} · 실행 완료는 별도 확인` : "CORE 전달·응답 기록 없음 · 실행 완료 미확인"),
      ];
      item.querySelectorAll("dd").forEach((node, index) => { node.textContent = values[index]; });
      // Show only known message fields; never dump a state row or credentials.
      const message = JSON.stringify({
        core_inquiry: inquiry ? {
          version: inquiry.version, problem_id: inquiry.problem_id, task: inquiry.task,
          cause: inquiry.observations?.cause, lane_visible: inquiry.observations?.lane_visible,
          front_clear: inquiry.observations?.front_clear, boundary_revision: inquiry.lane_boundary?.revision,
        } : null,
        ai_proposal: proposal ? { decision: proposal.decision, reason: proposal.reason, class: proposal.class, verdict: proposal.verdict, outcome: proposal.outcome } : null,
        ai_facts: facts.map((fact) => ({ kind: fact.kind, source: fact.source, stage: fact.stage, confidence: fact.confidence })),
        fleet_answer: answer ? { decision: answer.decision, tier: answer.tier, accepted: answer.accepted, code: answer.code, outcome: answer.outcome } : null,
      }, null, 2);
      item.dataset.message = message;
      item.querySelector("pre").textContent = message;
      return item;
    });
    if (list.childElementCount !== nodes.length || [...list.children].some((node, index) => node !== nodes[index])) {
      list.replaceChildren(...nodes);
    }
    if (!nodes.length) list.textContent = "현재 열린 판단 문의의 전달 기록이 없습니다. 지난 판단은 사건 기록에서 확인하세요.";
  }

  function refreshInbox() {
    paintInboxMessages();
    paintBadge();
    if (pendingDrawerDeepLink && !isLocked() && readView().stateLoaded) openPendingDeepLink();
  }

  function openPendingDeepLink() {
    if (!pendingDrawerDeepLink || isLocked()) return;
    pendingDrawerDeepLink = false;
    if (linkedRobot) {
      const stuckKey = `${linkedRobot}|stuck`;
      const hit = [...document.querySelectorAll("#critical-list > li, #warning-list > li")]
        .some((node) => node.dataset?.key === stuckKey);
      if (hit) {
        jumpToQueueRow(stuckKey);
        return;
      }
    }
    setDrawerOpen(true, { focus: true });
  }

  function selectContext(choice, focus = false) {
    const valid = contextTabs.some((tab) => tab.dataset.contextTab === choice);
    contextChoice = valid ? choice : "status";
    for (const tab of contextTabs) {
      const selected = tab.dataset.contextTab === contextChoice;
      tab.setAttribute("aria-selected", String(selected));
      tab.tabIndex = selected ? 0 : -1;
      const panel = el(tab.getAttribute("aria-controls"));
      if (panel) panel.hidden = !selected;
      if (selected && focus) tab.focus({ preventScroll: true });
    }
  }

  function clear() {
    setDrawerOpen(false);
    paintBadge();
    const list = el("inbox-messages");
    if (list) list.textContent = "관제 접속 후 판단 전달 기록을 확인할 수 있습니다.";
  }

  scope.listen(document, "rosy:inbox", (event) => {
    event.preventDefault();
    const next = !drawerOpen;
    setDrawerOpen(next, { focus: next, restoreFocus: !next });
  });
  scope.listen(el("queues-close"), "click", () => setDrawerOpen(false, { restoreFocus: true }));
  scope.listen(el("topbar-more"), "click", () => {
    if (drawerOpen) setDrawerOpen(false);
  });
  scope.listen(document, "keydown", (event) => {
    if (event.key !== "Escape" || event.defaultPrevented || !drawerOpen) return;
    if (document.querySelector("dialog[open]") || el("topbar-more")?.getAttribute("aria-expanded") === "true"
      || drawer?.querySelector?.(".stuck-confirm")) return;
    event.preventDefault();
    setDrawerOpen(false, { restoreFocus: true });
  });
  scope.listen(document, "pointerdown", (event) => {
    if (!drawerOpen || document.querySelector("dialog[open]")) return;
    if (drawer?.contains?.(event.target) || bell?.contains?.(event.target)) return;
    setDrawerOpen(false);
  }, { capture: true });

  for (const tab of contextTabs) {
    scope.listen(tab, "click", () => selectContext(tab.dataset.contextTab));
    scope.listen(tab, "keydown", (event) => {
      const index = contextTabs.indexOf(tab);
      const next = {
        ArrowRight: (index + 1) % contextTabs.length,
        ArrowLeft: (index + contextTabs.length - 1) % contextTabs.length,
        Home: 0,
        End: contextTabs.length - 1,
      }[event.key];
      if (next === undefined) return;
      event.preventDefault();
      selectContext(contextTabs[next].dataset.contextTab, true);
    });
  }
  // A result link must reveal its destination tab before native #log anchor scrolling.
  scope.listen(el("cancel-all-details"), "click", () => selectContext("evidence"));

  const log = (text, kind) => appendLogEntry(el("log"), text, kind, LOG_MAX);

  scope.listen(el("log-clear"), "click", () => {
    const box = el("log");
    box.replaceChildren(document.createElement("ui-empty"));
    box.firstChild.textContent = "지웠습니다.";
    el("cancel-all-details").hidden = true;
  });

  paintBadge();
  return {
    refresh: refreshInbox,
    log,
    clear,
    setDrawerOpen,
    jumpToQueueRow,
    openPendingDeepLink,
    focusInitial() { openPendingDeepLink(); },
    select: selectContext,
    get choice() { return contextChoice; },
    get open() { return drawerOpen; },
  };
}
