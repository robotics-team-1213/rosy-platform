// D-411 A: 로봇 학습 녹화(카메라 유닛 bag) — HUD 토글과 "녹화본" 시트.
// 녹화는 로봇이 하고 CORE 는 요청만 전한다. 받기는 로봇이 멈춰 있는 동안에만 되고(CORE 판정),
// 본문이 Content-Length 보다 짧으면 도중에 끊긴 것이라 저장하지 않는다(이어 받기 없음).
// 받는 중에 취소하거나 화면을 나가면 요청을 끊는다 — 끝까지 받지 않은 녹화본을 CORE 가
// "받음"으로 표시하지 않게. 서버 글자로 HTML 을 만들지 않는다(textContent 만).

import {api, apiBlob} from "../client.js";
import {el} from "./drive-view.js";
import {RECORDING_POLL_MS, errorText, recordingView, sheetNotice, sheetRows} from "../recording.js";

const NOTICE_POLLS = 5;            // 거부 사유를 HUD 칩에 남겨 두는 폴링 횟수(약 5 s)
const REQUEST_TIMEOUT_MS = 2000;   // 폴링·시작·정지·목록 한 번의 시한
const SHEET_REFRESH_MS = 3000;     // 열린 시트의 목록 다시 읽기
const FETCH_TIMEOUT_MS = 600_000;  // 받기 한 번의 시한(PILOT_FETCH_MAX_BYTES 를 느린 Wi-Fi 로)

const every = (fn, ms) => { const id = setInterval(fn, ms); return () => clearInterval(id); };

export function mountRobotRecording({toggle, detail, openButton, sheetHost, anchor, save,
                                     request = api, requestBlob = apiBlob, schedule = every} = {}) {
  let active = null;
  let pending = null;          // 진행 중인 시작·정지 요청(Promise)
  let epoch = 0;               // 누를 때마다 오른다 — 그 전에 떠난 폴링 응답은 버린다
  let polling = false;
  let disposed = false;
  let notice = "";
  let noticePolls = 0;
  let sheet = null;
  let stopSheetRefresh = null;
  let refreshing = false;
  let download = null;         // {id, controller}
  const rowStatus = new Map(); // id → 마지막 받기 결과(목록을 다시 그려도 남는다)

  function render() {
    const view = recordingView(active);
    toggle.textContent = view.label;
    toggle.disabled = Boolean(pending) || !view.available || view.busy;
    toggle.reason = pending ? "요청 보내는 중" : toggle.disabled ? view.reason : "";
    toggle.dataset.state = active?.state ?? "offline";
    toggle.setAttribute("aria-pressed", String(view.recording));
    const text = notice || view.detail;
    detail.textContent = text;
    detail.hidden = !text;
    detail.dataset.state = notice ? "refused" : (active?.state ?? "offline");
  }

  async function poll() {
    if (polling || pending || disposed) return;
    polling = true;
    const mine = epoch;
    const response = await request("/api/v1/recordings/active", {timeoutMs: REQUEST_TIMEOUT_MS}).catch(() => null);
    polling = false;
    if (disposed || mine !== epoch || pending) return;      // 그사이 누른 결과가 이긴다
    active = response?.status === 200 ? (response.body?.active ?? null) : null;
    if (noticePolls > 0 && --noticePolls === 0) notice = "";
    render();
  }

  async function send(stopping) {
    epoch += 1;
    const response = await request(stopping ? "/api/v1/recordings/active/stop" : "/api/v1/recordings",
                                   {method: "POST", timeoutMs: REQUEST_TIMEOUT_MS}).catch(() => null);
    if (disposed) return;
    epoch += 1;
    if (response?.ok) {
      active = response.body ?? active;
      notice = "";
      noticePolls = 0;
    } else {
      notice = response ? errorText(response.body?.error?.code, stopping ? "stop" : "start") : "연결 없음";
      noticePolls = NOTICE_POLLS;
    }
  }

  toggle.addEventListener("click", () => {
    if (pending) return;
    pending = send(recordingView(active).recording).finally(() => {
      pending = null;
      if (!disposed) {
        render();
        poll();
      }
    });
    render();
  });

  // --- "녹화본" 시트 ---------------------------------------------------------
  function placeSheet() {
    // HUD 바로 아래에 붙인다(고정 오프셋 없음). 시트는 sheetHost 기준 absolute 다.
    const below = anchor.getBoundingClientRect().bottom;
    sheet.style.setProperty("--recordings-top", `${Math.round(below - sheetHost.getBoundingClientRect().top)}px`);
    sheet.style.setProperty("--recordings-viewport-top", `${Math.round(below)}px`);
  }

  function onKey(event) {
    if (event.key === "Escape") closeSheet();
  }

  function closeSheet() {
    if (!sheet) return;
    stopSheetRefresh?.();
    stopSheetRefresh = null;
    document.removeEventListener("keydown", onKey);
    // 목록을 다시 그리면 초점 둔 버튼이 바뀌므로 "시트 안"을 따지지 않고 여는 버튼으로 돌려준다.
    sheet.remove();
    sheet = null;
    openButton.setAttribute("aria-pressed", "false");
    if (!disposed) openButton.focus();
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
      const busy = download?.id === row.id;
      const status = busy ? "받는 중…" : (rowStatus.get(row.id) ?? "");
      facts.append(el("ui-text", status, {scale: "label", "data-recording-status": "", role: "status",
                                          "aria-live": "polite"}));
      let action;
      if (busy) {
        action = el("ui-button", "취소", {type: "button", "data-recording-cancel": ""});
        action.addEventListener("click", () => download?.controller.abort());
      } else {
        action = el("ui-button", "받기", {type: "button", "data-recording-fetch": ""});
        action.disabled = !row.canFetch || download !== null;
        action.reason = action.disabled && row.reason !== message ? row.reason : "";
        action.addEventListener("click", () => fetchRecording(row.id));
      }
      action.setAttribute("kind", "quiet");
      item.append(facts, action);
      return item;
    }));
  }

  async function refreshSheet() {
    if (refreshing || !sheet) return;
    refreshing = true;
    const response = await request("/api/v1/recordings", {timeoutMs: REQUEST_TIMEOUT_MS}).catch(() => null);
    refreshing = false;
    if (disposed || !sheet) return;
    placeSheet();
    if (response?.status === 200) renderRows(response.body, "");
    else renderRows(null, response ? errorText(response.body?.error?.code, "fetch") : "");
  }

  async function fetchRecording(id) {
    if (download !== null) return;
    const controller = new AbortController();
    download = {id, controller};
    rowStatus.delete(id);
    await refreshSheet();
    const response = await requestBlob(`/api/v1/recordings/${encodeURIComponent(id)}/archive`,
                                       {signal: controller.signal, timeoutMs: FETCH_TIMEOUT_MS}).catch(() => null);
    download = null;
    if (disposed) return;
    if (controller.signal.aborted) {
      rowStatus.set(id, "받기를 취소했습니다");
    } else if (response?.ok && response.blob && (response.length == null || response.blob.size === response.length)) {
      save(response.blob, `${id}.tar`);
      rowStatus.set(id, "받음 — 기기의 다운로드 폴더");
    } else if (response && !response.ok) {
      // 409(움직임·녹화 중·다른 받기)는 사유만 보이고 저절로 다시 받지 않는다.
      rowStatus.set(id, errorText(response.body?.error?.code, "fetch"));
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
    sheet = el("div", null, {"data-recordings-sheet": "", role: "dialog", "aria-label": "녹화본",
                             tabindex: "-1"});
    const head = el("ui-head", "녹화본");
    const noticeNode = el("ui-text", "", {scale: "label", "data-recordings-notice": "", role: "status",
                                          "aria-live": "polite"});
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
    placeSheet();
    openButton.setAttribute("aria-pressed", "true");
    document.addEventListener("keydown", onKey);
    sheet.focus();
    stopSheetRefresh = schedule(refreshSheet, SHEET_REFRESH_MS);
    refreshSheet();
  });

  render();
  poll();
  const stopPolling = schedule(poll, RECORDING_POLL_MS);

  return {
    // 나가기: 받는 중이면 끊고, 막 보낸 시작이 있으면 끝나기를 기다린 뒤, 이 기기가 시작한
    // 녹화만 멈춘다(남의 녹화는 그대로 — CORE 도 403 으로 막는다).
    async stopIfOwned() {
      download?.controller.abort();
      await pending;
      const response = await request("/api/v1/recordings/active", {timeoutMs: REQUEST_TIMEOUT_MS}).catch(() => null);
      const state = response?.body?.active?.state;
      if (response?.status === 200 && response.body?.owned && state === "recording") {
        await request("/api/v1/recordings/active/stop", {method: "POST", timeoutMs: REQUEST_TIMEOUT_MS})
          .catch(() => null);
      }
    },
    dispose() {
      download?.controller.abort();
      disposed = true;
      stopPolling();
      closeSheet();
    },
  };
}
