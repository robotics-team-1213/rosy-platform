// D-721 Amendment: a person request for this robot - what to do and why.
// A person logged in with an account may answer here; CORE holds the answer until Fleet reads it back and records
// it. The answer moves nothing, releases no stop and passes no check. Other credentials only read the card.
// Unknown is not shown as an ask: a failed read or an expired request hides the card.
import {createNode} from "/assets/dom.js";

const KIND = {unplug_charger: "충전기 분리", plug_charger: "충전기 연결", move_robot: "로봇 옮기기",
  clear_area: "주변 치우기", other: "기타"};

/** Pure: the card's lines for one held request, or null when nothing is held. */
export function personRequestLines(held, canAnswer = false) {
  if (!held || typeof held.text !== "string") return null;
  const seconds = Number.isFinite(held.remaining_s) ? Math.max(0, Math.round(held.remaining_s)) : null;
  const answered = held.answer?.answer === "done" ? "했어요" : held.answer?.answer === "cannot" ? "못 해요" : "";
  const how = answered ? `"${answered}"로 답했습니다. 관제가 기록하면 카드가 사라집니다.`
    : canAnswer ? "아래 버튼이나 관제에서 답해 주세요."
      : "관제에서 답해 주세요. 계정으로 로그인하면 여기서도 답할 수 있습니다.";
  return [`${KIND[held.kind] || "기타"} — ${held.text}`, held.why ? `이유: ${held.why}` : "",
    seconds === null ? "" : `${Math.floor(seconds / 60)}분 ${seconds % 60}초 남음`, how,
    "답은 로봇을 움직이거나 비상 정지를 풀지 않습니다."].filter(Boolean);
}

/** Pure: whether the answer buttons are offered. */
export function personRequestAnswerable(held, canAnswer) {
  return Boolean(canAnswer && held && typeof held.text === "string" && !held.answer);
}

export function mount(el, ctx) {
  const head = createNode("ui-head", "", "사람 부탁");
  const body = createNode("div", "person-request");
  const status = createNode("p", "");
  const done = createNode("ui-button", "", "했어요");
  done.setAttribute("kind", "primary");
  done.type = "button";
  const cannot = createNode("ui-button", "", "못 해요");
  cannot.setAttribute("kind", "quiet");
  cannot.type = "button";
  const actions = createNode("div", "person-request-actions");
  actions.append(done, cannot);
  el.hidden = true;
  el.replaceChildren(head, body, actions, status);
  let shown = null, sending = false;
  const lock = (on) => {
    for (const button of [done, cannot]) {
      button.disabled = on;
      if (on) button.setAttribute("reason", "답을 보내는 중");
      else button.removeAttribute("reason");
    }
  };
  const draw = (data) => {
    const held = data?.person_request;
    const lines = personRequestLines(held, data?.can_answer === true);
    el.hidden = !lines;
    shown = lines ? held : null;
    body.replaceChildren(...(lines || []).map((text) => createNode("p", "", text)));
    actions.hidden = !personRequestAnswerable(held, data?.can_answer === true);
    lock(sending);
  };
  const answer = (value) => async () => {
    if (!shown || sending) return;
    sending = true;
    lock(true);
    status.textContent = "";
    try {
      draw({...(await ctx.api(`/api/v1/person-request/${encodeURIComponent(shown.id)}/answer`,
        {method: "POST", body: JSON.stringify({answer: value})})), can_answer: true});
    } catch (error) {
      status.textContent = `답을 보내지 못했습니다: ${error.message}`;
    } finally {
      sending = false;
      lock(false);
    }
  };
  done.addEventListener("click", answer("done"));
  cannot.addEventListener("click", answer("cannot"));
  const stop = ctx.store.poll("/api/v1/person-request", 2000, draw, () => draw(null));
  return () => stop();
}
