import {node, action} from "./control-dom.js";

const STATE_COPY = {pending: "불러오는 중", empty: "아직 자료가 없습니다", forbidden: "권한이 필요합니다",
  error: "조회하지 못했습니다", unavailable: "연결 상태를 확인하세요", ready: "조회한 자료"};

export function createStatePanel({id, onRetry, retryLabel = "다시 조회"} = {}) {
  const element = node("section", "", "ui-state-panel");
  if (id) element.id = id;
  const message = node("ui-status");
  const description = node("p");
  const retry = action(retryLabel, () => onRetry?.());
  element.append(message, description, retry);
  return {element,
    set({state, title = STATE_COPY[state], detail = ""}) {
      if (!Object.hasOwn(STATE_COPY, state)) throw new TypeError(`Unknown state: ${state}`);
      message.setAttribute("state", state); message.textContent = title;
      description.textContent = detail; description.hidden = !detail;
      retry.hidden = !onRetry || !["error", "unavailable"].includes(state);
      element.setAttribute("aria-busy", String(state === "pending"));
    },
  };
}

export function createActionBar(actions) {
  const element = node("ui-actions", "", "ui-action-bar");
  for (const {label, onClick, kind = "quiet", reason = ""} of actions) {
    const button = action(label, onClick, kind);
    if (reason) {button.setAttribute("disabled", ""); button.setAttribute("reason", reason);}
    element.append(button);
  }
  return element;
}

// Labels describe evidence supplied by the caller; elapsed time never becomes success.
export function createOperationResult({id} = {}) {
  const element = node("div", "", "ui-readback"); if (id) element.id = id;
  const status = node("ui-status"); element.append(status);
  const labels = {pending: "요청 중", accepted: "접수 · 실제 완료 미확인", confirmed: "실제 완료 · 다시 조회해 확인",
    failed: "요청 실패", unknown: "결과 미확인"};
  return {element, set({state, detail = ""}) {
    if (!Object.hasOwn(labels, state)) throw new TypeError(`Unknown operation state: ${state}`);
    element.dataset.state = state;
    status.setAttribute("state", state === "pending" ? "pending" : state === "failed" ? "error" : state === "unknown" ? "unavailable" : "ready");
    status.textContent = `${labels[state]}${detail ? ` · ${detail}` : ""}`;
  }};
}

export function createProgress({id, label}) {
  const element = node("div", "", "ui-control-stack"); if (id) element.id = id;
  const text = node("label", label);
  const progress = node("progress"); progress.id = `${id}-bar`; progress.max = 100;
  text.htmlFor = progress.id;
  const status = node("ui-status"); status.setAttribute("state", "pending");
  element.append(text, progress, status);
  return {element, set(value = null) {
    if (value !== null && (!Number.isFinite(value) || value < 0 || value > 100)) throw new RangeError("Progress must be null or 0..100");
    if (value === null) progress.removeAttribute("value"); else progress.value = value;
    status.textContent = value === null ? "전체 진행률 미확인" : `${value}% · 완료 여부는 결과에서 확인하세요`;
  }};
}

export function createTimeline({id, label}) {
  const element = node("section", "", "ui-control-stack"); if (id) element.id = id;
  const heading = node("h3", label);
  const list = node("ol", "", "ui-timeline");
  element.append(heading, list);
  return {element, set(events) {
    list.replaceChildren(...events.map(({label: name, at = null, detail = ""}) => {
      const row = node("li"); row.append(node("strong", name));
      if (at && Number.isFinite(new Date(at).getTime())) {
        const time = node("time", new Date(at).toLocaleString("ko-KR")); time.dateTime = at; row.append(time);
      } else row.append(node("span", "시각 미확인"));
      if (detail) row.append(node("p", detail));
      return row;
    }));
    if (!events.length) list.append(node("li", "기록 없음"));
  }};
}

export function createSteps({id, labels}) {
  const element = node("ol", "", "ui-stage-track"); if (id) element.id = id;
  const rows = labels.map(label => node("li", label, "ui-stage")); element.append(...rows);
  return {element, set(index, {blocked = false} = {}) {
    if (!Number.isInteger(index) || index < 0 || index >= rows.length) throw new RangeError("Unknown step");
    rows.forEach((row, at) => {
      row.dataset.state = at < index ? "done" : at === index ? blocked ? "blocked" : "now" : "todo";
      if (at === index) row.setAttribute("aria-current", "step"); else row.removeAttribute("aria-current");
    });
  }};
}

export function createLogView({label, text = ""}) {
  const element = node("details", "", "ui-log-view");
  const heading = node("summary", label);
  const content = node("pre", text || "기록 없음");
  const result = node("ui-status"); result.setAttribute("state", "ready");
  const copy = action("내용 복사", async () => {
    try {await navigator.clipboard.writeText(content.textContent); result.setAttribute("state", "ready"); result.textContent = "복사했습니다";}
    catch {result.setAttribute("state", "error"); result.textContent = "복사하지 못했습니다. 내용을 선택해 복사하세요";}
  });
  element.append(heading, content, copy, result);
  return {element, set(value) {content.textContent = value || "기록 없음"; result.setAttribute("state", "ready"); result.textContent = "";}};
}
