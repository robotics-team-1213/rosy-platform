// D-411 A: 로봇 학습 녹화(카메라 유닛 bag) — HUD 토글과 "녹화본" 시트.
// 녹화는 로봇이 하고 CORE 는 요청만 전한다. 받기는 로봇이 멈춰 있는 동안에만 되고(CORE 판정),
// 본문이 Content-Length 보다 짧으면 도중에 끊긴 것이라 저장하지 않는다(이어 받기 없음).
// 받는 중에 취소하거나 화면을 나가면 요청을 끊는다 — 끝까지 받지 않은 녹화본을 CORE 가
// "받음"으로 표시하지 않게. 서버 글자로 HTML 을 만들지 않는다(textContent 만).

import {createVisionPreview} from "../vision.js";
import {createCameraCapture, saveCameraFile} from "/common/evidence.js";
import {api, apiBlob} from "../client.js";
import {el, actionIcon} from "./drive-view.js";
import {RECORDING_POLL_MS, continueRecording, errorText, recordingView, sheetNotice, sheetRows} from "../recording.js";

const NOTICE_POLLS = 5;            // 거부 사유를 HUD 칩에 남겨 두는 폴링 횟수(약 5 s)
const REQUEST_TIMEOUT_MS = 2000;   // 폴링·시작·정지·목록 한 번의 시한
const SHEET_REFRESH_MS = 3000;     // 열린 시트의 목록 다시 읽기
const FETCH_TIMEOUT_MS = 600_000;  // 받기 한 번의 시한(PILOT_FETCH_MAX_BYTES 를 느린 Wi-Fi 로)

const every = (fn, ms) => { const id = setInterval(fn, ms); return () => clearInterval(id); };

export function mountRobotRecording({toggle, detail, openButton, sheetHost, anchor, save,
                                     returnFocus = openButton,
                                     request = api, requestBlob = apiBlob, schedule = every} = {}) {
  let active = null;
  let annotatedReady = false;
  const modeLabel = el("label", "로봇 학습·주행 기록", {class: "ui-field-label"});
  const mode = el("select", null, {class: "ui-field", "data-robot-record-mode": ""});
  mode.className = "ui-field";
  const rawOption = el("option", "원본만 (기본)"); rawOption.value = "raw";
  const annotatedOption = el("option", "원본 + 모델 표시본"); annotatedOption.value = "annotated";
  mode.append(rawOption, annotatedOption); modeLabel.append(mode); toggle.before(modeLabel);
  let pending = null;          // 진행 중인 시작·정지 요청(Promise)
  let epoch = 0;               // 누를 때마다 오른다 — 그 전에 떠난 폴링 응답은 버린다
  let polling = false;
  let disposed = false;
  let notice = "";
  let noticePolls = 0;
  let wanted = false;         // 이 기기가 켜고 아직 끄지 않았다 — 10분 상한 뒤 다음 구간으로 잇는다
  let segment = 1;
  let sheet = null;
  let stopSheetRefresh = null;
  let refreshing = false;
  let download = null;         // {id, controller}
  let lastListing = null;      // 마지막 목록과 실패 글자 — 받기가 끝나면 바로 다시 그린다
  let lastFailure = "";
  let shown = "";              // 지금 그려진 시트 상태; 같으면 다시 만들지 않는다(초점·live region 보존)
  let stopResize = null;
  const rowStatus = new Map(); // id → 마지막 받기 결과(목록을 다시 그려도 남는다)

  function render() {
    const view = recordingView(active);
    annotatedOption.disabled = !annotatedReady;
    mode.title = annotatedReady ? "원본은 항상 보존하며 모델 표시본은 확인용입니다" : "표시본 기록 지원을 확인하지 못했습니다. 원본만 선택할 수 있습니다";
    mode.disabled = Boolean(pending) || view.recording;
    mode.setAttribute("reason", "기록을 종료한 뒤 선택하세요");
    if (!annotatedReady) mode.value = "raw";
    toggle.textContent = view.label;
    toggle.disabled = Boolean(pending) || !view.available || view.busy;
    toggle.reason = pending ? "요청 보내는 중" : toggle.disabled ? view.reason : "";
    toggle.dataset.state = active?.state ?? "offline";
    toggle.setAttribute("aria-pressed", String(view.recording));
    toggle.setAttribute("aria-label", view.ariaLabel);
    const actualMode = active?.preview_mode;
    const format = actualMode === "annotated" ? "원본 + 모델 표시본 · 결과는 확인용" : actualMode === "raw" ? "원본" : "저장 형식 확인 대기";
    const part = view.recording && segment > 1 ? ` · ${segment}번째 구간` : "";
    const text = notice || (view.recording ? `${view.detail} · ${format}${part}` : view.detail);
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
    annotatedReady = response?.body?.preview_modes?.includes("annotated") === true;
    if (noticePolls > 0 && --noticePolls === 0) notice = "";
    if (continueRecording(wanted, active)) {
      segment += 1;
      press(false, `10분 구간이 끝나 ${segment}번째 녹화로 이어 갑니다`);
      return;
    }
    if (active?.state === "idle" || active?.state === "error") { wanted = false; segment = 1; }
    render();
  }

  async function send(stopping) {
    epoch += 1;
    const response = await request(stopping ? "/api/v1/recordings/active/stop" : "/api/v1/recordings",
                                   {method: "POST", timeoutMs: REQUEST_TIMEOUT_MS,
                                    ...(!stopping && annotatedReady ? {body: JSON.stringify({preview_mode: mode.value})} : {})}).catch(() => null);
    if (disposed) return;
    epoch += 1;
    if (response?.ok) {
      active = response.body ?? active;
      notice = "";
      noticePolls = 0;
    } else {
      if (!stopping) wanted = false;
      notice = response ? errorText(response.body?.error?.code, stopping ? "stop" : "start") : "연결 없음";
      noticePolls = NOTICE_POLLS;
    }
  }

  function press(stopping, message = "") {
    if (pending) return;
    wanted = !stopping;
    pending = send(stopping).finally(() => {
      pending = null;
      if (message && !notice) { notice = message; noticePolls = NOTICE_POLLS; }
      if (!disposed) {
        render();
        poll();
      }
    });
    render();
  }

  toggle.addEventListener("click", () => press(recordingView(active).recording));

  // --- "녹화본" 시트 ---------------------------------------------------------
  function placeSheet() {
    // HUD 바로 아래에 붙인다(고정 오프셋 없음). 시트는 sheetHost 기준 absolute 다.
    const below = anchor.getBoundingClientRect().bottom;
    sheet.setAttribute("data-recordings-top", `${Math.round(below - sheetHost.getBoundingClientRect().top)}px`);
    sheet.setAttribute("data-recordings-viewport-top", `${Math.round(below)}px`);
  }

  function onKey(event) {
    if (event.key === "Escape") closeSheet();
  }

  function closeSheet() {
    if (!sheet) return;
    stopSheetRefresh?.();
    stopSheetRefresh = null;
    stopResize?.();
    stopResize = null;
    document.removeEventListener("keydown", onKey);
    // 목록을 다시 그리면 초점 둔 버튼이 바뀌므로 "시트 안"을 따지지 않고 여는 버튼으로 돌려준다.
    sheet.remove();
    sheet = null;
    openButton.setAttribute("aria-pressed", "false");
    if (!disposed) returnFocus.focus();
  }

  function renderRows(listing, failure) {
    if (!sheet) return;
    lastListing = listing;
    lastFailure = failure;
    const rows = sheetRows(listing);
    const message = failure || sheetNotice(listing);
    const state = JSON.stringify([rows, message, download?.id ?? null, [...rowStatus]]);
    if (state === shown) return;   // 3 s 새로 읽기가 같은 목록을 가져왔다: 버튼·초점을 그대로 둔다
    shown = state;
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
        const cancel = el("ui-button", "받기 취소", {type: "button", "data-recording-cancel": ""});
        cancel.setAttribute("kind", "quiet");
        actionIcon(cancel, "close");
        cancel.setAttribute("kind", "quiet");
        cancel.addEventListener("click", () => download?.controller.abort());
        action = cancel;
      } else {
        const receive = el("ui-button", "파일 받기", {type: "button", "data-recording-fetch": ""});
        receive.setAttribute("kind", "quiet");
        actionIcon(receive, "download");
        receive.setAttribute("kind", "quiet");
        receive.disabled = !row.canFetch || download !== null;
        receive.reason = receive.disabled && row.reason !== message ? row.reason : "";
        receive.addEventListener("click", () => fetchRecording(row.id));
        action = receive;
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
    renderRows(lastListing, lastFailure);
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
    renderRows(lastListing, lastFailure);    // "받는 중…/취소" 를 바로 거둔다
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
    const refresh = el("ui-button", "다시 불러오기", {type: "button", "data-recordings-refresh": ""});
    refresh.setAttribute("kind", "quiet");
    actionIcon(refresh, "refresh");
    refresh.setAttribute("kind", "quiet");
    refresh.addEventListener("click", () => refreshSheet());
    const close = el("ui-button", "닫기", {type: "button", "data-recordings-close": ""});
    close.setAttribute("kind", "quiet");
    actionIcon(close, "close");
    close.setAttribute("kind", "quiet");
    close.addEventListener("click", closeSheet);
    actions.append(refresh, close);
    sheet.append(head, el("p", "로봇에 저장된 녹화 파일입니다. 파일 받기는 로봇이 멈춰 있을 때 가능합니다."), noticeNode, list, actions);
    sheetHost.append(sheet);
    shown = "";
    placeSheet();
    // HUD 높이는 줄바꿈·회전으로 바뀐다: 그때마다 시트를 HUD 아래로 다시 붙인다.
    const onResize = () => { if (sheet) placeSheet(); };
    const observer = typeof ResizeObserver === "function" ? new ResizeObserver(onResize) : null;
    observer?.observe(anchor);
    window.addEventListener("resize", onResize);
    stopResize = () => { observer?.disconnect(); window.removeEventListener("resize", onResize); };
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
    closeSheet,
    // 나가기: 받는 중이면 끊고, 막 보낸 시작이 있으면 끝나기를 기다린 뒤, 이 기기가 시작한
    // 녹화만 멈춘다(남의 녹화는 그대로 — CORE 도 403 으로 막는다).
    async stopIfOwned() {
      download?.controller.abort();
      await pending;
      const response = await request("/api/v1/recordings/active", {timeoutMs: REQUEST_TIMEOUT_MS}).catch(() => null);
      const state = response?.body?.active?.state;
      if (response?.status === 200 && response.body?.owned && (state === "recording" || state === "starting")) {
        await request("/api/v1/recordings/active/stop", {method: "POST", timeoutMs: REQUEST_TIMEOUT_MS})
          .catch(() => null);
      }
    },
    dispose() {
      download?.controller.abort();
      disposed = true;
      wanted = false;
      stopPolling();
      closeSheet();
      modeLabel.remove();
    },
  };
}


// Browser confirmation recordings share the existing authenticated preview.
export function mountBrowserRecording({element, apiGet, authHeaders}) {
  const capture = createCameraCapture({
    save: saveCameraFile,
    onComplete: async () => { await capture.saveVideo("pc"); capture.saveOperations(); },
    storeOnRobot: null,          // 로봇 SD 업로드는 dashboard 경로 재사용 예정(후속).
    onChange: (state) => {
      if (!element.frame.hidden) element.empty.textContent = state.message;
      if (element.shotButton) element.shotButton.disabled = !state.ready;
      if (element.recordButton) {
        element.recordButton.disabled = !state.supported || (!state.recording && !state.ready);
        element.recordButton.reason = !state.supported ? "이 브라우저는 녹화를 지원하지 않습니다" : !state.ready ? "표시 없는 원본 수신 대기" : "";
        element.recordButton.textContent = state.recording ? "화면 녹화 중지" : "화면 녹화";
      }
      if (element.browserMode) {
        element.browserMode.disabled = state.recording || state.uploading;
        element.browserMode.setAttribute("reason", state.recording ? "녹화를 종료한 뒤 선택하세요" : "저장 중");
      }
      if (element.saveVideo) {
        element.saveVideo.disabled = !state.saved || state.recording;
        element.saveVideo.reason = state.recording ? "녹화 중" : "저장할 영상이 없습니다";
      }
    },
  });

  // Screens feed both sources (polling and the D-368 driver stream) through
  // this one path so the browser recording capture sees a single pipeline.
  async function acceptPreview(url, meta = {}) {
    element.frame.src = url;
    element.frame.hidden = false;
    element.empty.hidden = true;
    const image = new Image();
    image.src = url;
    try {
      await image.decode();
      let rawImage = image;
      if (meta.previewMode === "annotated") {
        const rawUrl = URL.createObjectURL(meta.rawBlob);
        rawImage = new Image(); rawImage.src = rawUrl;
        try { await rawImage.decode(); } finally { URL.revokeObjectURL(rawUrl); }
      }
      capture.acceptFrame({...meta, image, rawImage});
    } catch (_error) { capture.unavailable("원본 프레임을 읽을 수 없습니다."); }
  }

  const vision = createVisionPreview({
    apiGet,
    previewMode: () => capture.state().previewMode,
    onQuality: (quality) => {
      element.visibility.hidden = !(quality?.valid === false && ["low_light", "overexposed"].includes(quality?.reason));
      element.visibility.textContent = quality?.reason === "overexposed"
        ? "과노출 · 차선 정보 확인 불가" : "조도가 낮아 차선·물체를 판정할 수 없습니다";
    },
    fetchFrame: async (path) => {
      const response = await fetch(path, {headers: authHeaders(), cache: "no-store"});
      // 409·429 본문(JSON)을 이미지로 띄우지 않는다 — 거부하면 다음 틱에 다시 당긴다.
      if (!response.ok) throw new Error(`frame ${response.status}`);
      return response;
    },
    onFrame: async (url, meta) => acceptPreview(url, meta),
    onUnavailable: (message) => {
      element.frame.hidden = true;
      element.empty.hidden = false;
      element.empty.textContent = message;
      capture.unavailable(message);
    },
  });
  vision.start();
  return {capture, vision, acceptPreview};
}
