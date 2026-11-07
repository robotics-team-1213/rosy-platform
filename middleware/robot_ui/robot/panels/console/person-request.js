// D-721 Amendment: a person request for this robot - what to do and why. It shows; it does not answer here.
// The answer is recorded on the Fleet console; this card moves nothing, releases no stop and passes no check.
// Unknown is not shown as an ask: a failed read or an expired request hides the card.
import {createNode} from "/assets/dom.js";

const KIND = {unplug_charger: "충전기 분리", plug_charger: "충전기 연결", move_robot: "로봇 옮기기",
  clear_area: "주변 치우기", other: "기타"};

/** Pure: the card's lines for one held request, or null when nothing is held. */
export function personRequestLines(held) {
  if (!held || typeof held.text !== "string") return null;
  const seconds = Number.isFinite(held.remaining_s) ? Math.max(0, Math.round(held.remaining_s)) : null;
  return [`${KIND[held.kind] || "기타"} — ${held.text}`, held.why ? `이유: ${held.why}` : "",
    seconds === null ? "" : `${Math.floor(seconds / 60)}분 ${seconds % 60}초 안에 관제에서 답해 주세요`,
    "관제에서 답해 주세요. 이 카드는 로봇을 움직이거나 비상 정지를 풀지 않습니다."].filter(Boolean);
}

export function mount(el, ctx) {
  const head = createNode("ui-head", "", "사람 부탁");
  const body = createNode("div", "person-request");
  el.hidden = true;
  el.replaceChildren(head, body);
  const draw = (held) => {
    const lines = personRequestLines(held);
    el.hidden = !lines;
    body.replaceChildren(...(lines || []).map((text) => createNode("p", "", text)));
  };
  const stop = ctx.store.poll("/api/v1/person-request", 2000,
    (data) => draw(data?.person_request), () => draw(null));
  return () => stop();
}
