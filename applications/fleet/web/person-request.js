// D-721 Amendment: 사람 부탁. The system asks a person to do something physical; the person answers here.
// An answer is a statement only: it starts no motion, releases no stop and passes no check. The row says so.
// No import from queues.js: queues.js imports the text helpers below.
import { isRouteAbsent } from "/console/assets/poll-gate.js";

export const KIND_LABEL = Object.freeze({
  unplug_charger: "충전기 분리", plug_charger: "충전기 연결", move_robot: "로봇 옮기기",
  clear_area: "주변 치우기", other: "기타",
});
export const NO_MOTION_LINE = "답은 사람의 말로만 기록됩니다. 로봇을 움직이거나 비상 정지를 풀지 않습니다.";

/** Pure: the attention-queue sentence of one open request. */
export function personHeadline(request) {
  const kind = KIND_LABEL[request.kind] || request.kind;
  return `: 사람 부탁(${kind}) — ${request.text}${request.why ? ` · 이유: ${request.why}` : ""}`;
}

export const SHOWN_FRESH_S = 30;

/** Pure: whether the robot's own screen shows it. "Shown" means Fleet read it back from the robot lately. */
export function deliveryText(request) {
  const age = request.delivery?.age_s;
  switch (request.delivery?.state) {
    case "delivered":
      return Number.isFinite(age) && age <= SHOWN_FRESH_S ? `로봇 화면에도 표시 중 (${Math.round(age)}초 전 확인)`
        : "로봇 화면 표시 확인 불가 — 최근에 로봇에서 읽지 못했습니다";
    case "waiting": return "앞선 부탁이 로봇 화면에 있어 이 부탁은 아직 로봇 화면에 없음 — 관제에서만 보입니다";
    case "not_delivered": return "로봇 화면에 전달하지 못함 — 관제에서만 보입니다";
    case "clear_failed": return "로봇 화면에서 지우지 못함 — 시간이 지나면 사라집니다";
    case "cleared": return "로봇 화면에서 지움";
    case "no_robot": return "로봇 지정 없음";
    default: return "로봇 화면에 보내지 않음";
  }
}

/** Pure: what the opened row shows and why its buttons are locked, if they are. */
export function personView(request, { operator, named = "", busy = false }) {
  const lock = !operator ? "운영자 권한이 필요합니다" : busy ? "답을 보내는 중" : named;
  return { lines: [personHeadline(request).replace(/^:\s*/, ""), deliveryText(request), NO_MOTION_LINE], lock };
}

/** The open requests that belong to one robot, oldest first. */
export function requestsFor(view, robotId) {
  return (view.personRequests || []).filter((r) => r.robot_id === robotId && r.state === "open")
    .sort((a, b) => a.created_at - b.created_at);
}

export function createPersonRequests({ scope, view, call, log, isOperator, namedReason = () => "" }) {
  const busy = new Set(), results = new Map(), signatures = new Map();
  let inFlight = false, unavailable = false;

  async function refresh() {
    const life = scope.capture();
    life.check();
    if (inFlight || unavailable) return;
    inFlight = true;
    try {
      const answer = await call("/api/fleet/person-requests?state=open", { signals: [life.signal] });
      life.check();
      view.personRequests = answer.requests || [];
    } catch (error) {
      if (error.name === "AbortError") return;
      if (isRouteAbsent(error.status, error.code)) unavailable = true;
      view.personRequests = [];  // an unread list is never shown as an empty ask
    } finally {
      inFlight = false;
    }
  }

  async function answer(request, verdict) {
    if (busy.has(request.id)) return;
    const life = scope.capture();
    busy.add(request.id);
    render();
    try {
      await call(`/api/fleet/person-requests/${encodeURIComponent(request.id)}/answer`,
        { method: "POST", body: JSON.stringify({ answer: verdict }) });
      life.check();
      results.set(request.id, { text: `${request.robot_id} 사람 부탁에 "${verdict === "done" ? "했어요" : "못 해요"}"로 답함`, kind: "good" });
    } catch (err) {
      if (err.name === "AbortError") return;
      results.set(request.id, { text: `${request.robot_id} 답을 기록하지 못함 · ${err.code || err.message}`, kind: "bad" });
    } finally {
      if (life.current()) {
        log(results.get(request.id).text, results.get(request.id).kind);
        busy.delete(request.id);
        refresh();
        render();
      }
    }
  }

  function button(label, kind, reason, click) {
    const node = document.createElement("ui-button");
    node.setAttribute("kind", kind);
    node.type = "button";
    node.textContent = label;
    node.disabled = Boolean(reason);
    if (reason) node.setAttribute("reason", reason);
    node.addEventListener("click", scope.guard(click));
    return node;
  }

  function render() {
    const operator = isOperator(), named = namedReason();
    for (const request of view.stateUnavailable ? [] : (view.personRequests || []).filter((r) => r.state === "open")) {
      const key = `${request.robot_id}|person-${request.id}`;
      const slot = document.querySelector(`[data-decision-slot="${CSS.escape(key)}"]`);
      const spec = personView(request, { operator, named, busy: busy.has(request.id) });
      const signature = JSON.stringify([request, spec, results.get(request.id) || null]);
      if (!slot || (slot.firstElementChild && signatures.get(key) === signature)) continue;
      const box = document.createElement("div");
      box.className = "stuck-item";
      for (const text of spec.lines) {
        const line = document.createElement("p");
        line.className = "stuck-resolver";
        line.textContent = text;
        box.append(line);
      }
      const actions = document.createElement("div");
      actions.className = "stuck-actions ui-action-bar";
      actions.setAttribute("role", "group");
      actions.setAttribute("aria-label", `${request.robot_id} 사람 부탁 답`);
      const done = button("했어요", "primary", spec.lock, () => answer(request, "done"));
      done.dataset.personAnswer = "done";
      const cannot = button("못 해요", "quiet", spec.lock, () => answer(request, "cannot"));
      cannot.dataset.personAnswer = "cannot";
      actions.append(done, cannot);
      box.append(actions);
      const last = results.get(request.id);
      if (last) {
        const line = document.createElement("p");
        line.className = "stuck-result";
        line.dataset.kind = last.kind;
        line.setAttribute("role", last.kind === "bad" ? "alert" : "status");
        line.textContent = last.text;
        box.append(line);
      }
      slot.replaceChildren(box);
      signatures.set(key, signature);
    }
  }

  return { refresh, render };
}
