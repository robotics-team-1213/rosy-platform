// B1/B2 (계획 2026-11-14-rosy-vla-decision-ai-command.md 5 #2·#9·#10, 6.2 R1·R2, 사용자 결정 1·5): AI 팔
// 제안은 별도 화면이 아니라 기존 자리에 있다 — 대기 제안 전부는 작업 큐(L2), 로봇을 막는 건과 스킬
// 이상만 관제 예외 큐(L1)에 오른다. 제안자(requested_by·서비스 신원)는 자기 제안을 승인하지 못한다.
// 실제 경로(C3)가 없어 지금은 dev 샘플(GET /api/fleet/arm-proposals, 전 건 sample: true)만 읽는다:
// 라우트가 없으면 폴링 문이 닫히고 아무것도 그리지 않는다. 상태 글자·태그는 shared/web/skill-state.js
// 표 하나를 쓴다(C20).
import {skillState} from "/common/skill-state.js";
import {createEvidenceLine} from "/common/evidence-line.js";
import {createCauseLine} from "/common/cause-line.js";
import {isSample, sampleTag} from "/common/sample-data.js";
import {statusTag} from "/common/status-tag.js";

/** 승인이 열려 있는 수명주기: 승인 대기(제안됨 포함)와 대체 제안. 대체는 제자리 교체가 아니라 새 승인이다. */
export const WAITING_SKILLS = Object.freeze(new Set(["proposed", "waiting_approval", "fallback_proposed"]));
export const SELF_APPROVAL_REASON = "제안자는 자기 제안을 승인할 수 없습니다";

/** A case (or a robot's arm_skill record) -> skillState input. Extra keys are ignored, never guessed. */
export function skillOf(item) {
  return skillState(item || {});
}

/** The proposer lock: requested_by(요청한 사람)·proposed_by(AI 서비스 신원) 어느 쪽이든 본인이면 승인 불가. */
export function selfApprovalReason(item, principal) {
  if (!item || !principal) return "";
  return [item.requested_by, item.proposed_by].includes(principal) ? SELF_APPROVAL_REASON : "";
}

/** L1 예외 큐 행(계획 6.2 R1): 막는 대기 제안(arm_proposal)과 스킬 이상(arm_skill)만. 정상·대기 제안은 못 오른다. */
export function armAttention(feed) {
  if (!feed || !Array.isArray(feed.cases)) return [];
  const rows = [];
  for (const item of feed.cases) {
    const skill = skillOf(item);
    if (WAITING_SKILLS.has(item.lifecycle)) {
      if (item.blocking === true)
        rows.push({severity: "warn", decision: "arm_proposal", key: `arm-proposal|${item.id}`,
          text: `AI 팔 제안 · 승인 대기 — ${item.title}`});
    } else if (["measured_failure", "stopped", "timed_out"].includes(item.lifecycle)) {
      rows.push({severity: skill.tag?.state === "danger" ? "crit" : "warn", key: `arm-skill|${item.id}`,
        text: `팔 스킬 · ${skill.text} — ${item.title}`});
    }
  }
  return rows;
}

/** L2 작업 큐 행 글(기존 workLine과 같은 셈세): 종류 · 식별자 · 상태 표 글자. */
export function armProposalLine(item) {
  return `팔 제안 · ${item.id} · ${skillOf(item).text}`;
}

/** GET /api/fleet/arm-proposals 폴링. 라우트 없음(404)은 폴링 문이 닫는다(poll-gate.js). */
export function createArmProposalFeed({call, gate, onCases}) {
  let feed = null;  // {sample, cases} | null(기능 없음)
  return {
    get: () => feed,
    async refresh() {
      if (!gate?.due()) return feed;
      try {
        const read = await call("/api/fleet/arm-proposals");
        gate?.ok();
        feed = {sample: read?.sample === true, cases: Array.isArray(read?.cases) ? read.cases : []};
      } catch (error) {
        if (error.name === "AbortError") return feed;
        if (gate?.fail(error.status, error.code) === "absent") feed = null;  // 이 Fleet에는 아직 없는 경로다
      }
      onCases?.(feed);
      return feed;
    },
  };
}

// 승인 거절 사유의 운영자 말(모르는 코드는 서버가 답한 그대로 보인다).
const REFUSAL_LABEL = Object.freeze({
  PROPOSER_CANNOT_APPROVE: "제안자는 자기 제안을 승인할 수 없습니다",
  PROPOSAL_CHANGED: "제안이 바뀌었습니다 · 새 제안을 다시 확인하세요",
  PROPOSAL_NOT_WAITING: "승인 대기가 아닌 제안입니다",
  UNKNOWN_PROPOSAL: "제안을 찾을 수 없습니다",
});

/**
 * B2 (계획 6.2 R2): 작업 큐에서 고른 팔 제안의 상세 패널. 패널 순서는 상태 → 핵심 값 → 근거 줄 →
 * 주 행동 승인(막힌 사유는 C1 원인 줄) → 후보 이유 접힘. 승인은 기명 운영자가 현재 digest·세대로만
 * 보내고, 제안자(사람이든 AI 서비스 신원이든)는 잠긴 단추와 함께 못 한다. 대체 제안은 새 승인이
 * 필요한 새 줄로만 온다: 이 패널은 제자리 교체 단추를 갖지 않는다.
 *
 *   panel.show(item)   paint the given case; panel.hide(); panel.element  the <section> itself
 */
export function createArmProposalPanel({scope, call, approveReason, principal, confirm, onAdmitted}) {
  const section = document.createElement("section");
  section.id = "arm-proposal";
  section.className = "arm-proposal";
  section.hidden = true;
  section.setAttribute("aria-labelledby", "arm-proposal-heading");
  const heading = document.createElement("h3");
  heading.id = "arm-proposal-heading";
  heading.textContent = "팔 제안";
  const headTags = document.createElement("div");
  headTags.className = "arm-proposal-head";
  headTags.append(heading);
  const stateLine = document.createElement("p");
  stateLine.id = "arm-proposal-state";
  const readout = document.createElement("dl");
  readout.id = "arm-proposal-readout";
  readout.className = "ui-readout";
  readout.dataset.form = "strip";
  const facts = document.createElement("p");
  facts.className = "hint";
  facts.id = "arm-proposal-facts";
  const evidence = document.createElement("div");
  evidence.id = "arm-proposal-evidence";
  const admit = document.createElement("ui-button");
  admit.id = "arm-proposal-admit";
  admit.setAttribute("kind", "primary");
  admit.setAttribute("type", "button");
  admit.textContent = "승인";
  const causeLine = document.createElement("ui-status");
  const cause = createCauseLine(section, {line: causeLine});
  const candidates = document.createElement("details");
  candidates.id = "arm-proposal-candidates";
  section.append(headTags, stateLine, readout, facts, evidence, admit, causeLine, candidates);
  scope.listen(admit, "click", () => void approve());

  let current = null, busy = false, refused = "";

  const lockReason = () => !current ? ""
    : busy ? "요청 처리 중입니다"
    : selfApprovalReason(current, principal()) || approveReason() || "";

  function paint() {
    const waiting = Boolean(current) && WAITING_SKILLS.has(current.lifecycle);
    admit.hidden = !waiting;  // 승인 대기가 아니면 승인할 것이 없다(대체는 새 줄의 새 승인)
    cause.set([admit], waiting ? (refused || lockReason()) : "");
    headTags.replaceChildren(heading);
    // C22(계획 6.3 마지막 줄): 거절된 자기 승인 견본은 잠금 표시가 이름을 말한다.
    if (waiting && selfApprovalReason(current, principal())) headTags.append(statusTag("locked"));
    if (isSample(current)) headTags.append(sampleTag());
  }

  function show(item) {
    current = item;
    refused = "";
    const skill = skillOf(item);
    stateLine.replaceChildren(`상태 ${skill.text}`);
    if (skill.tag) stateLine.append(statusTag(skill.tag.state, undefined, {icon: skill.tag.icon}));
    readout.replaceChildren(...skill.readout.map(row => {
      const cell = document.createElement("div");
      cell.append(Object.assign(document.createElement("dt"), {textContent: row.label}),
        Object.assign(document.createElement("dd"), {textContent: row.value}));
      return cell;
    }));
    facts.textContent = `제안 ${item.id} · 요청 ${item.requested_by ?? "정보 없음"}`
      + `${item.proposed_by ? ` · 제출 ${item.proposed_by}` : ""} · 세대 ${item.generation ?? "정보 없음"}`
      + (item.supersedes ? ` · ${item.supersedes}의 대체 제안 · 새 승인이 필요합니다` : "");
    const isCellS = item.cell_id === "cell_s" || item.arm_id === "arm_s";
    const isCellA = item.arm_id === "arm_a";
    const isCellB = item.arm_id === "arm_b";
    const isCellAb = item.cell_id === "cell_ab";
    const cellLink = document.createElement("a");
    cellLink.className = "ui-action-link";
    cellLink.dataset.kind = "quiet";
    cellLink.dataset.armProposalCellLink = "";
    cellLink.href = isCellS ? "/console/cell?cell=cell_s#observation-heading"
      : isCellA ? "/console/cell?cell=cell_a#observation-heading"
      : isCellB ? "/console/cell?cell=cell_b#observation-heading"
      : isCellAb ? "/console/cell?cell=cell_ab#observation-heading" : "/console/cell#mission-heading";
    cellLink.textContent = isCellS ? "Cell S 작업대 열기"
      : isCellA ? "Cell A 작업대 열기"
      : isCellB ? "Cell B 작업대 열기"
      : isCellAb ? "Cell A/B 작업대 열기" : "셀 작업대 열기";
    facts.append(" · ", cellLink);
    evidence.replaceChildren(createEvidenceLine(item.evidence || []));
    // sampleTag() = <ui-tag data-sample>샘플 데이터</ui-tag>(C22): 실제가 아닌 상태는 머리에서 이름을 밝힌다.
    const summary = document.createElement("summary");
    summary.className = "ui-disclosure-row";
    summary.textContent = "후보 이유";
    candidates.replaceChildren(summary);
    const list = document.createElement("ul");
    for (const entry of item.candidates || []) {
      const row = document.createElement("li");
      row.textContent = `${entry.label} — ${entry.reason}`;
      list.append(row);
    }
    candidates.append(list);
    section.hidden = false;
    paint();
  }

  async function approve() {
    if (!current || busy || refused || lockReason()) return;
    const snapshot = current;
    await confirm({message: `${snapshot.id} 팔 제안(${snapshot.title}) 실행을 승인할까요? 승인 후 팔이 움직일 수 있습니다.`,
      opener: admit, kind: "arm-proposal",
      eligible: () => current === snapshot && !busy && !refused && !lockReason(),
      request: async owner => {
        busy = true; paint();
        try {
          await call(`/api/fleet/arm-proposals/${encodeURIComponent(snapshot.id)}/admit`, {
            method: "POST", headers: {"Content-Type": "application/json"}, signals: [owner.signal],
            body: JSON.stringify({expected_proposal_digest: snapshot.digest, expected_generation: snapshot.generation}),
          });
          owner.check();
          await onAdmitted?.();
        } finally { busy = false; }
      },
      onError: error => {
        if (current !== snapshot) return;
        const known = REFUSAL_LABEL[error.code];
        refused = error.status >= 400 && error.status < 500
          ? `승인이 거절됐습니다 · ${known || error.message}`  // 바뀐 제안은 다시 확인한다: 자동 재전송 없음
          : "승인 결과 미확인 · 원장을 확인하세요";
        paint();
      }});
    if (current === snapshot) paint();
  }

  return {element: section, show, hide() { section.hidden = true; current = null; refused = ""; paint(); }};
}

