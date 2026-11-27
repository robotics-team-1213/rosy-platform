import { node, patchAttr, patchHidden, patchText } from "/common/control-dom.js";
import { setOffBy } from "/common/cause-line.js";
// 예외 큐 (Fleet 분해 3에서 roster.js로부터 옮김, D-540 단계 (d) 크기 재판정). 주의/개입 큐의
// 규칙(attentionItems, D-493 한 규칙)과 행 채우기, 큐 펼침의 버튼 헬퍼를 가진다. 카드는 roster.js다.
import { BATTERY_LEVEL_LABEL, DOCK_STATE_LABEL, EVIDENCE_LABEL, enumLabel, evidenceAgeText} from "/common/core_ui_logic.js";
import { ruleMTag } from "./link-tag.js";
import { localizationAttention } from "./localization-badge.js";
import { staleAgeS } from "./state-age.js";
import { powerHealthView } from "./power-health-view.js";
import { estopText } from "./motion-readiness.js";
import { motionSource } from "./motion-source.js";
import {routeAttention, trafficAttention} from "/console/assets/site-map-model.js";
import {tripEndText, tripWaitText} from "/console/assets/trip-display.js";
import { guideAttention } from "/console/assets/guide-layer.js";
import { recoveryHeadline } from "./station-recovery.js";
import { personHeadline, requestsFor } from "./person-request.js";
import { armIncidentAlertRows } from "/console/assets/arm-incident-clear.js";
import { hasPendingCorrection } from "/console/assets/named-stop-actions.js";

/** A row's text after its robot name. Rows read "<b>rosy_41</b>: …"; a later row of the same robot hides the
 * name, so it drops the leading ": " (field check 2026-10-10: ": Rosy Cam이 …" with no name). */
export function queueRowText(text, named) {
  return named ? text : text.replace(/^:\s*/, "");
}

/** One warn cause on several robots is one row (decision rows never group; crit rows are not passed here).
 * B-1: a per-robot stale rollup (noGroup) never merges — its folded causes belong to that robot. */
export function groupRows(rows, min = 2) {
  const same = new Map();
  for (const row of rows) if (!row.decision && !row.noGroup && !String(row.text || "").includes("관리자가 해제해야 움직입니다")) {
    same.set(row.text, [...(same.get(row.text) || []), row]);
  }
  const out = [], done = new Set();
  for (const row of rows) {
    const group = row.decision || row.noGroup || String(row.text || "").includes("관리자가 해제해야 움직입니다") ? null : same.get(row.text);
    if (!group || group.length < min) { out.push(row); continue; }
    if (!done.has(row.text)) out.push({ severity: row.severity, text: row.text, robotId: "",
      group: group.map((r) => r.robotId), key: `group|${row.text}` });
    done.add(row.text);
  }
  return out;
}

/** "배터리 값 멈춤 — 센서 연결 확인 · 9대 (rosy_001 · rosy_002 · rosy_003 외 6대)" */
export function groupText(text, ids, shown = 3) {
  const few = ids.slice(0, shown).join(" · ");
  return `${text.replace(/^:\s*/, "")} · ${ids.length}대 (${few}${ids.length > shown ? ` 외 ${ids.length - shown}대` : ""})`;
}

/** D-540 3: the queue row open on its decision. The operator's last pick holds while that row lives;
 * otherwise the most urgent decision row (critical first) is open. */
export function openDecisionKey(keys, choice) {
  if (choice && keys.includes(choice.key)) return choice.open ? choice.key : null;
  return keys[0] ?? null;
}

// D-540 3 — a disclosure (queue row, folded card line, fold) shows and hides; it never moves a robot.
export function disclosure(className, expanded, onClick) {
  const node = document.createElement("button");
  node.type = "button";
  node.className = `${className} ui-disclosure-row`;
  node.setAttribute("aria-expanded", String(expanded));
  node.addEventListener("click", onClick);
  return node;
}

// 계약(D-359 §5.2)은 버튼마다 글자 kind 를 요구한다 — 변수 kind 헬퍼는 정적 검사가
// 못 본다. 종류별 헬퍼가 리터럴을 담는다.
export function quietButton(text) {
  const node = document.createElement("ui-button");
  node.setAttribute("kind", "quiet");
  node.type = "button";
  node.textContent = text;
  return node;
}

export function primaryButton(text) {
  const node = document.createElement("ui-button");
  node.setAttribute("kind", "primary");
  node.type = "button";
  node.textContent = text;
  return node;
}

/** The robot's open trip as the console last read it, or null. */
export function openTrip(view, robotId) {
  return (view.trafficTrips || []).find((trip) => trip.robot_id === robotId) || null;
}

/** Why the robot's last trip stopped or failed ('' while a trip is open or the last one arrived or was canceled). */
export function endedTripText(view, robotId) {
  if (openTrip(view, robotId)) return "";
  const last = (view.endedTrips || []).find((trip) => trip.robot_id === robotId);
  if (last?.state === "canceled" && (last.detail?.stop_sent === false || last.detail?.error))
    return "운행 취소 · 기체 정지 응답 미확인";
  return tripEndText(last);
}

// D-577 8: an escalated stuck nobody answered within this many seconds rises to the top. The robot
// keeps holding; nothing moves on silence. Console only — no phone or messenger alert (user, 2026-10-09).
const HUMAN_DEADLINE_S = 30;

export function stuckOverdue(stuck) {
  const note = stuck && stuck.resolver;
  return Boolean(note && note.escalated && note.escalated !== "human_claimed"
    && typeof note.age_s === "number" && note.age_s >= HUMAN_DEADLINE_S);
}

export function nextStepFor(robot, kindOrText = "") {
  const k = String(kindOrText || "");
  if (k === "custody" || k.startsWith(": 정밀 정지 점유 보류")) {
    return robot?.named_stop_custody?.operator_action ? { text: robot.named_stop_custody.operator_action } : null;
  }
  if ((k === "estop" || k.startsWith(": 비상 정지 걸림"))
      && robot?.state?.safety?.estop === true && robot?.state?.safety?.releases_when_charged !== true) {
    return { text: `로봇 등록 → ${robot.robot_id} → 비상정지 해제…`, href: "/console/install#robots", linkText: "로봇 등록 열기" };
  }
  if (k === "dock_failed" || k.startsWith(": 도킹 실패")) return { text: "충전 칸 정렬 확인 후 전진·재접안 또는 로봇 카드에서 다시 보내세요" };
  if (k === "nav_failed" || k.startsWith(": 목표 실패")) return { text: "주변 장애물·위치 확인 후 지도에서 목표를 다시 지정하세요" };
  if (k === "off_map" || k.startsWith(": 지도 밖")) return { text: "정지 확인 후 지도 위 운영자 핀으로 위치를 다시 잡으세요" };
  return null;
}

export function createQueues({ scope, el, view, render, streamEvidence }) {
  // D-493 — 예외 큐와 로봇 카드의 "주의" 보기는 이 한 규칙을 쓴다. 카드에 빨간 표지가 붙은
  // 로봇이 큐에 없으면 "예외가 먼저"(D-201)가 거짓말이 된다(2026-10-07 회차: 릴레이 끊김).
  function attentionItems(robot) {
    const state = robot.state;
    // D-407 / D-540 3: a stuck robot waits for an answer; the row opens into its decision. An offline
    // robot keeps the row (last value, answers locked) so the question does not vanish with the link.
    const staleS = staleAgeS(robot, view.receivedAtMs, Date.now());
    const staleNote = staleS === null ? "" : ` (상태 ${evidenceAgeText(staleS).slice(3)} 값)`;
    const overdue = stuckOverdue(robot.line_stuck);
    const stuck = robot.line_stuck
      ? [{ severity: "crit", decision: "stuck", overdue,
           text: overdue ? `: 판단 요청 — 30초 넘게 답 없음, 로봇은 멈춰 기다립니다${staleNote}`
             : `: 판단 요청 — 차선 추종이 막혔습니다${staleNote}` }] : [];
    // 2026-10-02 관제 회차 — 로봇 전원이 닿지 않아도 큐는 비어 있었다. 가장 흔한 예외부터 말한다.
    if (!robot.online && robot.link === "degraded") return [{ severity: "warn", text: ": 응답 지연" }, ...stuck];
    if (!robot.online) return [{ severity: "warn", text: `: ${EVIDENCE_LABEL.disconnected}` }, ...stuck];
    if (!state) return [{ severity: "warn", text: ": 상태 확인 불가" }, ...stuck];
    const items = [];
    const level = state.battery_status?.level;
    // B-1 (IEC 62682 alarm summarization): 스냅샷에서 온 주의 4종만 묶는다. 심각 배터리는 묶지 않는다.
    if (level && level !== "ok") {
      const severe = level === "critical" || level === "deep";
      items.push(severe ? { severity: "crit", text: `: ${enumLabel(BATTERY_LEVEL_LABEL, level)}` }
        : { severity: "warn", text: `: ${enumLabel(BATTERY_LEVEL_LABEL, level)}`, snapshotWarn: true });
    }
    if (state.docking?.state === "DOCK_FAILED")
      items.push({ severity: "warn", text: `: ${enumLabel(DOCK_STATE_LABEL, "DOCK_FAILED")}`, snapshotWarn: true });
    const power = powerHealthView(robot, view.receivedAtMs, Date.now());
    if ("power_health" in robot && power.problem)
      items.push({ severity: "warn", text: `: ${power.problem}` });
    items.push(...stuck);
    // D-494 5 / D-540 3: a trip held at a place for a changed route waits for the operator's confirm.
    if ((view.trafficTrips || []).some((trip) => trip.robot_id === robot.robot_id && trip.hold)) {
      items.push({ severity: "crit", text: ": 바뀐 경로 확인 — 운행이 장소에서 기다립니다", decision: "replan" });
    }
    // D-540 (d): a trip Fleet stopped (lease lost, stall, junction …) until the robot's next trip; not arrive/cancel.
    const ended = endedTripText(view, robot.robot_id);
    if (ended) items.push({ severity: "warn", text: `: ${ended}` });
    const trip = openTrip(view, robot.robot_id);  // D-763 rev 2 Q7: past its bound a warn row; 개입 is the resolver's hand-off
    if (trip?.wait?.over_bound) items.push({ severity: "warn", text: `: ${tripWaitText(trip)}` });
    if (hasPendingCorrection(trip)) {
      items.push({ severity: "crit", decision: "correction", text: ": 정밀 정지 보정 승인 대기" });
    }
    items.push(...routeAttention(openTrip(view, robot.robot_id), view.trafficAi, Date.now()));
    const guideRow = (view.guide?.robots || []).find((row) => row.robot_id === robot.robot_id);
    const localization = localizationAttention(robot.localization, staleS === null ? state.localization : null,
      view.guideUnavailable ? null : guideRow, staleS !== null);
    if (localization) items.push(localization);
    if (localization?.severity !== "crit" && state.hitl_requested === true) {
      // 개입 요청은 이름으로 알린다(Law 0). 원격 조종은 이 서버에 없는 능력이다 — 못 하는
      // 조작을 모의 버튼으로 걸면 경보가 거짓말을 한다(D-218, F-20). 진짜 개입은 로봇 화면에서.
      items.push({ severity: "crit", text: ": 개입 필요 — 로봇 화면에서 확인" });
    } else if (localization?.severity !== "crit" && state.capabilities_degraded?.length) {
      items.push({ severity: "warn", text: `: 성능 저하 [${state.capabilities_degraded.join(", ")}]`, snapshotWarn: true });
    }
    const relay = streamEvidence(view.formation, robot.robot_id);
    if (relay && relay.cls) items.push({ severity: relay.cls === "crit" ? "crit" : "warn", text: `: ${relay.text}` });
    const source = motionSource(robot, view);
    if (source.attention) items.push({ severity: "crit", text: `: ${source.text} — ${source.title}` });
    if (state.safety?.estop === true) {
      const auto = state.safety.releases_when_charged === true;
      items.push({ severity: auto ? "warn" : "crit", text: `: ${estopText(state, "비상 정지 걸림")}${auto ? "" : " — 관리자가 해제해야 움직입니다"}` });
    }
    else if (state.safety?.estop !== false) items.push({ severity: "warn", text: ": 정지 상태 미확인" });
    if (state.navigation === "FAILED") items.push({ severity: "warn", text: ": 목표 실패", snapshotWarn: true });
    // D-511 M0: Fleet이 Rosy Cam 지도 자세로 본 차로 여유. 움직이는 로봇만 알린다(D-511 §2).
    // 알리기만 한다(보정·정지는 M1/M2). 여유가 음수면 몸체가 가장자리를 넘은 것이다.
    const lane = robot.lane_compliance;
    if (lane?.moving === true && typeof lane.margin_m === "number" && (lane.level === "WARN" || lane.level === "ACT")) {
      const cm = Math.round(Math.abs(lane.margin_m) * 100);
      const text = lane.margin_m < 0 ? `몸체가 가장자리를 ${cm} cm 넘음` : `여유 ${cm} cm`;
      items.push(lane.level === "ACT"
        ? { severity: "crit", text: `: 차로 이탈 — ${text}` }
        : { severity: "warn", text: `: 차로 가장자리 접근 — ${text}` });
    }
    // D-511 개정 1: Fleet이 본 복귀 상태 한 줄. 같은 판정을 로봇에도 보낸다(lane-cue).
    const back = lane?.return;
    const backText = { OFF_LANE: "차로 밖 — 차로로 복귀 지시", OFF_MAP: "지도 밖 — 정지·확인 필요",
                       WRONG_WAY: "역주행 — 돌아서기 지시", ON_LINE: "차선 위 — 안쪽으로 보정" }[back?.state];
    if (backText) {
      const side = back.side ? ` (${back.side === "left" ? "왼쪽" : "오른쪽"})` : "";
      items.push({ severity: back.state === "ON_LINE" ? "warn" : "crit", text: `: ${backText}${side}` });
    }
    const custody = robot.named_stop_custody;
    if (custody?.reservation_id) {
      items.push({ severity: "crit", decision: "custody",
        text: `: 정밀 정지 점유 보류${custody.missing_proof ? ` (${custody.missing_proof})` : ""}` });
    } else if (custody?.motion_refused_site_wide || custody?.operator_action) {
      items.push({ severity: "warn", text: `: 정밀 정지 점유 보류${custody.missing_proof ? ` (${custody.missing_proof})` : ""}` });
    }
    // D-517 10: 교착·30 s 넘는 위치 불명·긴 합류 대기·고리 수용 초과. 블록 대기 자체는 정상이라 행이 아니다.
    items.push(...trafficAttention(view.traffic, robot.robot_id, view.trafficClock, Date.now()));
    items.push(...guideAttention(view.guide, robot.robot_id));  // D-536 coordinate guides
    // D-550 8 / D-760 3: Fleet started a motion that no TTL or link signal bounds. Shown, not refused.
    const unbounded = ruleMTag(robot.rule_m);
    if (unbounded) items.push({ severity: "warn", text: `: 한도 없는 움직임 — ${unbounded.text}` });
    // D-721 Amendment (S1): a low-battery robot's station recovery request; the row opens on its answer.
    const recovery = (view.stationRecovery?.requests || []).find((r) => r.robot_id === robot.robot_id);
    if (recoveryHeadline(recovery)) items.push({ severity: "warn", decision: "recovery", text: recoveryHeadline(recovery) });
    // D-721 Amendment: 사람 부탁 — a person is asked for something physical; the row opens on the answer buttons.
    for (const ask of requestsFor(view, robot.robot_id))
      items.push({ severity: "warn", decision: "person", key: `${robot.robot_id}|person-${ask.id}`, text: personHeadline(ask) });
    if (robot.queued) items.push({ severity: "warn", text: ": 교통 대기" });
    if (robot.yielding) items.push({ severity: "warn", text: ": 양보 중" });
    // B-1: 스냅샷이 오래되면 그 스냅샷이 낸 주의는 한 행으로 묶는다. crit·판단·Fleet 관측 행은 그대로 둔다.
    if (staleS !== null) {
      const folded = items.filter((item) => item.snapshotWarn);
      const kept = items.filter((item) => !item.snapshotWarn);
      kept.push(folded.length ? {
        severity: "warn", key: `${robot.robot_id}|stale-snapshot`, noGroup: true,
        text: `: 상태 오래됨 — ${evidenceAgeText(staleS).slice(3)} 값 · 지연 경고 ${folded.length}건`,
        foldedDetails: folded.map((item) => item.text.replace(/^:\s*/, "")),
      } : { severity: "warn", text: `: 상태 오래됨 — ${evidenceAgeText(staleS).slice(3)} 값` });
      return kept;
    }
    return items.map(({ snapshotWarn, ...item }) => item);  // fresh rows keep today's exact shape
  }
  // Clock-like digits ("3초 전") are not a new exception. B-1: 묶인 경고 종류가 바뀌면 새 예외다.
  function attentionKey(robot) {
    return view.stateUnavailable ? "" : attentionItems(robot)
      .map((item) => `${item.text.replace(/\d+/g, "#")}${item.foldedDetails ? `:${item.foldedDetails.join(",")}` : ""}`)
      .join("|");
  }
  // D-252 ui-triage head: queue row count and affected robot count (D-540 3).
  function setTriageHead(id, label, rows) {
    const head = el(id);
    if (!head) return;
    const names = new Set(rows.flatMap((row) => row.group || [row.robotId]));
    patchText(head.querySelector("b"), `${label} ${rows.length}건 · ${names.size}대`);
    const small = head.querySelector("small");
    patchText(small, "");
    const title = [...names].join(" · ");
    if (small && small.title !== title) small.title = title;
  }

  // D-540 3 — a row with a decision opens in place, one at a time: the operator's pick, else the most
  // urgent decision row. Rows are kept by key so a 1 s poll never drops focus or a confirm step.
  function syncRows(list, rows, open, robotById = null) {
    const old = new Map([...list.children].map((node) => [node.dataset.key, node]));
    const nodes = rows.map((row, index) => {
      if (row.group) return groupRow(old.get(row.key), row);
      const named = index === 0 || rows[index - 1].robotId !== row.robotId;  // the name once per robot
      if (row.foldedDetails?.length) return foldedRow(old.get(row.key), row, named);
      let li = old.get(row.key);
      if (!li || li.dataset.decision !== (row.decision || "") || li.dataset.folded === "1") {
        li = document.createElement("li");
        li.dataset.key = row.key;
        li.dataset.decision = row.decision || "";
        const line = row.decision ? disclosure("queue-row", false, scope.guard(() => {
          view.queueChoice = { key: row.key, open: line.getAttribute("aria-expanded") !== "true" };
          render();
        })) : li;
        if (row.decision) {
          const body = node("div", "", "queue-decision");
          body.id = `decision-${row.key.replace(/[^A-Za-z0-9_-]/g, "_")}`;
          body.dataset.decisionSlot = row.key;
          line.setAttribute("aria-controls", body.id);
          li.append(line, body);
        }
        const step = node("span", "", "queue-next-step");
        step.hidden = true;
        step.append(node("span", ""), node("a", "", "queue-next-link"));
        line.append(document.createElement("b"), node("span", "", "queue-text"), step);
      }
      const line = row.decision ? li.firstElementChild : li;
      const name = line.querySelector("b");
      patchText(name, row.robotId);
      const cls = named ? "" : "sr-only";
      if (name.className !== cls) name.className = cls;
      const text = line.querySelector(".queue-text");
      patchText(text, queueRowText(row.text, named));
      const next = nextStepFor(robotById?.get(row.robotId), row.text);
      const stepEl = line.querySelector(".queue-next-step");
      if (stepEl) {
        patchHidden(stepEl, !next);
        patchText(stepEl.firstElementChild, next?.text || "");
        const link = stepEl.querySelector(".queue-next-link");
        if (link) {
          patchHidden(link, !next?.href);
          if (next?.href) patchAttr(link, "href", next.href);
          patchText(link, next?.linkText || "");
        }
      }
      if (row.decision) {
        patchAttr(line, "aria-expanded", String(open === row.key));
        patchHidden(li.lastElementChild, open !== row.key);
      }
      return li;
    });
    if (nodes.length !== list.children.length || nodes.some((node, i) => list.children[i] !== node)) {
      list.replaceChildren(...nodes);
    }
  }

  // A grouped row opens (native disclosure, kept by key across polls) to every robot's name.
  function groupRow(li, row) {
    if (!li || li.dataset.group !== "1") {
      li = document.createElement("li");
      li.dataset.key = row.key;
      li.dataset.group = "1";
      const details = document.createElement("details");
      details.className = "queue-group";
      const summary = document.createElement("summary");
      summary.className = "ui-disclosure-row";
      details.append(summary, node("p", "", "hint"));
      li.append(details);
    }
    const summary = li.querySelector("summary"), all = li.querySelector("p");
    const text = groupText(row.text, row.group);
    if (summary.textContent !== text) summary.textContent = text;
    const names = row.group.join(" · ");
    if (all.textContent !== names) all.textContent = names;
    return li;
  }

  // B-1 — one robot's stale rollup opens (native disclosure, kept by key across polls) to the folded
  // causes. Text, name and foldedKind update in place so an open <details> and focus survive 1 Hz polls.
  function foldedRow(li, row, named) {
    if (!li || li.dataset.folded !== "1") {
      li = document.createElement("li");
      li.dataset.key = row.key;
      li.dataset.folded = "1";
      const details = document.createElement("details");
      details.className = "queue-group";
      const summary = document.createElement("summary");
      summary.className = "ui-disclosure-row";
      summary.append(document.createElement("b"), node("span", "", "queue-text"));
      details.append(summary, node("p", "", "hint"));
      li.append(details);
    }
    li.dataset.foldedKind = row.foldedDetails.join("|");
    const summary = li.querySelector("summary");
    const name = summary.querySelector("b");
    name.textContent = row.robotId;
    name.className = named ? "" : "sr-only";
    const text = summary.querySelector(".queue-text");
    const shown = queueRowText(row.text, named);
    if (text.textContent !== shown) text.textContent = shown;
    const hint = li.querySelector(".hint");
    const causes = `이전 스냅샷 경고: ${row.foldedDetails.join(" · ")}`;
    if (hint.textContent !== causes) hint.textContent = causes;
    return li;
  }

  function fillQueues() {
    // ADR-1000: Populate Queues
    const warnList = el("warning-list");
    const critList = el("critical-list");
    const rows = armIncidentAlertRows(view.workcellObs);  // open arm incidents first; each row opens on its clear step
    for (const r of view.stateUnavailable ? [] : view.robots) {
      for (const item of attentionItems(r)) {
        const list = item.severity === "crit" ? rows.crit : rows.warn;
        const key = item.key || `${r.robot_id}|${item.decision || list.length}`;
        list.push({ ...item, robotId: r.robot_id, key });
      }
    }
    rows.crit.sort((a, b) => (Number(Boolean(b.overdue)) - Number(Boolean(a.overdue)))
      || (Number(Boolean(b.decision)) - Number(Boolean(a.decision))));
    rows.warn = groupRows(rows.warn);
    const decisions = [...rows.crit, ...rows.warn].filter((row) => row.decision).map((row) => row.key);
    const open = openDecisionKey(decisions, view.queueChoice);
    const robotById = new Map((view.robots || []).map((r) => [r.robot_id, r]));
    syncRows(critList, rows.crit, open, robotById);
    syncRows(warnList, rows.warn, open, robotById);
    setTriageHead("warning-head", "주의 요망", rows.warn);
    setTriageHead("critical-head", "최우선 개입 요망", rows.crit);

    // ADR-1000 & UX Law 1: Hide empty queues inside the drawer without closing the drawer itself.
    const total = rows.warn.length + rows.crit.length;
    if (warnList.parentElement.hidden !== (rows.warn.length === 0)) warnList.parentElement.hidden = rows.warn.length === 0;
    if (critList.parentElement.hidden !== (rows.crit.length === 0)) critList.parentElement.hidden = rows.crit.length === 0;
    const container = document.querySelector(".queues-container");
    if (container) patchHidden(container, total === 0);
    const empty = el("queues-empty");
    if (empty) patchHidden(empty, total > 0);
    const summary = el("queues-summary");
    if (summary) {
      const parts = [];
      if (rows.crit.length) parts.push(`최우선 ${rows.crit.length}건`);
      if (rows.warn.length) parts.push(`주의 ${rows.warn.length}건`);
      patchText(summary, parts.join(" · "));
    }
  }

  return { attentionItems, attentionKey, fillQueues };
}
