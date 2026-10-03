// D-204 system.events — 설치·정비 화면. "방금 무슨 일이 있었나"를 최신순 10개로 본다.
// 서버가 붙인 severity만 색이 된다. info는 정상이므로 색이 없다(D-82).

const LIMIT = 10;
const REFRESH_MS = 5_000;

function text(scale, value) {
  const node = document.createElement("ui-text");
  node.setAttribute("scale", scale);
  node.textContent = value;
  return node;
}

function emptyRow(message) {
  const row = document.createElement("li");
  const note = document.createElement("ui-empty");
  note.textContent = message;
  row.append(note);
  return row;
}

function eventRow(event) {
  const row = document.createElement("li");
  const time = document.createElement("time");
  time.className = "event-time";
  time.textContent = event.ts ? new Date(event.ts).toLocaleTimeString("ko-KR") : "—";
  const type = document.createElement("span");
  type.className = "event-type";
  type.textContent = event.type || "unknown.event";
  const severity = document.createElement("span");
  const level = event.severity || "info";
  severity.className = `event-severity ${level}`;
  severity.textContent = level.toUpperCase();
  row.append(time, type, severity);
  return row;
}

export function mount(el, ctx) {
  const head = document.createElement("ui-head");
  head.append(text("label", "최근 이벤트"));
  const list = document.createElement("ol");
  list.className = "event-list";
  list.append(emptyRow("불러오는 중입니다."));
  el.append(head, list);

  function render(payload) {
    const events = [...(payload.events || [])].reverse().slice(0, LIMIT);
    list.replaceChildren(...(events.length ? events.map(eventRow) : [emptyRow("수신된 이벤트가 없습니다.")]));
  }

  function fail(error) {
    list.replaceChildren(emptyRow(`이벤트를 받지 못했습니다: ${error.message}`));
  }

  return ctx.store.poll(`/api/v1/events?limit=${LIMIT}`, REFRESH_MS, render, fail);
}
