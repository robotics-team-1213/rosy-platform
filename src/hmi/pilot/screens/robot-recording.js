// D-411 A: 로봇 학습 녹화(카메라 유닛 bag) — HUD 토글과 "녹화본" 시트.
// 녹화는 로봇이 하고 CORE 는 요청만 전한다. 받기는 로봇이 멈춰 있는 동안에만 되고(CORE 판정),
// 본문이 Content-Length 보다 짧으면 도중에 끊긴 것이라 저장하지 않는다(이어 받기 없음).
// 서버 글자로 HTML 을 만들지 않는다(textContent 만).

import {api, apiBlob} from "../client.js";
import {el} from "./drive-view.js";
import {RECORDING_POLL_MS, errorText, recordingView, sheetNotice, sheetRows} from "../recording.js";

const NOTICE_POLLS = 5;   // 거부 사유를 HUD 칩에 남겨 두는 폴링 횟수(약 5 s)

export function mountRobotRecording({toggle, detail, openButton, sheetHost, save,
                                     request = api, requestBlob = apiBlob,
                                     schedule = (fn, ms) => { const id = setInterval(fn, ms); return () => clearInterval(id); },
                                    } = {}) {
  let active = null;
  let pending = false;
  let disposed = false;
  let notice = "";
  let noticePolls = 0;
  let sheet = null;
  let fetching = null;
  const rowStatus = new Map();   // id → 마지막 받기 결과(목록을 다시 그려도 남는다)

  function render() {
    const view = recordingView(active);
    toggle.textContent = view.label;
    toggle.disabled = pending || !view.available || view.busy;
    toggle.dataset.state = active?.state ?? "offline";
    toggle.setAttribute("aria-pressed", String(view.recording));
    const text = notice || view.detail || (view.available ? "" : view.reason);
    detail.textContent = text;
    detail.hidden = !text;
    detail.dataset.state = notice ? "refused" : (active?.state ?? "offline");
  }

  async function poll() {
    const response = await request("/api/v1/recordings/active").catch(() => null);
    if (disposed) return;
    active = response?.status === 200 ? (response.body?.active ?? null) : null;
    if (noticePolls > 0 && --noticePolls === 0) notice = "";
    render();
  }

  toggle.addEventListener("click", async () => {
    if (pending) return;
    const stopping = recordingView(active).recording;
    pending = true;
    render();
    const response = await request(stopping ? "/api/v1/recordings/active/stop" : "/api/v1/recordings",
                                   {method: "POST"}).catch(() => null);
    if (disposed) return;
    pending = false;
    if (response?.ok) {
      active = response.body ?? active;
      notice = "";
      noticePolls = 0;
    } else {
      notice = response ? errorText(response.body?.error?.code) : "연결 없음";
      noticePolls = NOTICE_POLLS;
    }
    render();
    poll();
  });

  // --- "녹화본" 시트 ---------------------------------------------------------
  function closeSheet() {
    sheet?.remove();
    sheet = null;
    openButton.setAttribute("aria-pressed", "false");
  }

  function renderRows(listing, failure) {
    if (!sheet) return;
    const rows = sheetRows(listing);
    const message = failure || sheetNotice(listing);
    const noticeNode = sheet.querySelector("[data-recordings-notice]");
    noticeNode.textContent = message;
    noticeNode.hidden = !message;
    const list = sheet.querySelector("[data-recordings-list]");
    list.replaceChildren(...rows.map((row) => {
      const item = el("div", null, {"data-recording-id": row.id});
      const facts = el("div", null, {"data-recording-facts": ""});
      facts.append(el("ui-text", row.title, {scale: "value"}), el("ui-text", row.detail, {scale: "label"}));
      const status = rowStatus.get(row.id) ?? (fetching === row.id ? "받는 중…" : "");
      if (status) facts.append(el("ui-text", status, {scale: "label", "data-recording-status": ""}));
      const fetchButton = el("ui-button", "받기", {type: "button", "data-recording-fetch": ""});
      fetchButton.setAttribute("kind", "quiet");
      fetchButton.disabled = !row.canFetch || fetching !== null;
      fetchButton.reason = fetchButton.disabled && row.reason !== sheetNotice(listing) ? row.reason : "";
      fetchButton.addEventListener("click", () => fetchRecording(row.id));
      item.append(facts, fetchButton);
      return item;
    }));
  }

  async function refreshSheet() {
    const response = await request("/api/v1/recordings").catch(() => null);
    if (disposed || !sheet) return;
    if (response?.status === 200) renderRows(response.body, "");
    else renderRows(null, response ? errorText(response.body?.error?.code) : "");
  }

  async function fetchRecording(id) {
    if (fetching !== null) return;
    fetching = id;
    rowStatus.delete(id);
    await refreshSheet();
    const response = await requestBlob(`/api/v1/recordings/${encodeURIComponent(id)}/archive`).catch(() => null);
    if (disposed) return;
    fetching = null;
    if (response?.ok && response.blob && (response.length == null || response.blob.size === response.length)) {
      save(response.blob, `${id}.tar`);
      rowStatus.set(id, "받음 — 기기의 다운로드 폴더");
    } else if (response && !response.ok) {
      // 409(움직임·녹화 중·다른 받기)는 사유만 보이고 저절로 다시 받지 않는다.
      rowStatus.set(id, errorText(response.body?.error?.code));
    } else {
      rowStatus.set(id, "받기가 끊겼습니다 — 로봇이 멈춘 뒤 처음부터 다시 받으세요");
    }
    refreshSheet();
  }

  openButton.addEventListener("click", () => {
    if (sheet) {
      closeSheet();
      return;
    }
    sheet = el("div", null, {"data-recordings-sheet": "", role: "dialog", "aria-label": "녹화본"});
    const head = el("ui-head", "녹화본");
    const noticeNode = el("ui-text", "", {scale: "label", "data-recordings-notice": ""});
    noticeNode.hidden = true;
    const list = el("div", null, {"data-recordings-list": ""});
    const actions = el("ui-actions");
    const refresh = el("ui-button", "새로고침", {type: "button", "data-recordings-refresh": ""});
    refresh.setAttribute("kind", "quiet");
    refresh.addEventListener("click", () => refreshSheet());
    const close = el("ui-button", "닫기", {type: "button", "data-recordings-close": ""});
    close.setAttribute("kind", "quiet");
    close.addEventListener("click", closeSheet);
    actions.append(refresh, close);
    sheet.append(head, noticeNode, list, actions);
    sheetHost.append(sheet);
    openButton.setAttribute("aria-pressed", "true");
    refreshSheet();
  });

  render();
  poll();
  const stopPolling = schedule(poll, RECORDING_POLL_MS);

  return {
    // 나가기: 이 기기가 시작한 녹화만 멈춘다(남의 녹화는 그대로 — CORE 도 403 으로 막는다).
    async stopIfOwned() {
      const response = await request("/api/v1/recordings/active").catch(() => null);
      const state = response?.body?.active?.state;
      if (response?.status === 200 && response.body?.owned && state === "recording") {
        await request("/api/v1/recordings/active/stop", {method: "POST"}).catch(() => null);
      }
    },
    dispose() {
      disposed = true;
      stopPolling();
      closeSheet();
    },
  };
}
