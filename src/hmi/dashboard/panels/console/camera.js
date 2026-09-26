import { authHeaders, session } from "/assets/client.js";
import { createVisionPreview } from "/assets/vision.js";
import { createCameraCapture, evidenceBody, saveCameraFile } from "/assets/camera-capture.js";

function el(tag, cls, text) { const node = document.createElement(tag); if (cls) node.className = cls; if (text !== undefined) node.textContent = text; return node; }

export function mount(root, ctx) {
  const head = el("ui-head", "", "전방 카메라");
  const stage = el("div", "surface-camera-stage"); stage.id = "vision-stage"; stage.dataset.state = "waiting";
  const frame = el("img", "surface-camera-frame"); frame.id = "vision-frame"; frame.alt = "전방 카메라 실시간 영상"; frame.hidden = true;
  const empty = el("ui-empty", "surface-camera-empty", "카메라 프레임 수신 대기"); empty.id = "vision-empty";
  stage.append(frame, empty);
  const status = el("p", "surface-message", "WAITING"); status.id = "vision-status";
  const actions = el("ui-actions", "surface-actions surface-camera-actions");
  const storageLabel = el("label", "surface-camera-storage", "저장 위치");
  const storage = el("select"); storage.id = "vision-storage";
  for (const [value, label] of [["pc", "이 PC"], ["robot", "로봇 SD"], ["both", "PC와 로봇 SD"]]) {
    const option = el("option", "", label); option.value = value;
    if (ctx.role === "viewer" && value !== "pc") option.disabled = true;
    storage.append(option);
  }
  storageLabel.append(storage);
  const shot = el("ui-button", "", "스크린샷"); shot.id = "vision-screenshot";
  const start = el("ui-button", "", "녹화 시작"); start.id = "vision-record-start";
  const stop = el("ui-button", "", "녹화 중지"); stop.id = "vision-record-stop";
  const saveVideo = el("ui-button", "", "영상 다시 저장"); saveVideo.id = "vision-record-save";
  const saveLog = el("ui-button", "", "조작 기록 저장"); saveLog.id = "vision-operations-save";
  for (const [button, kind] of [[shot, "quiet"], [start, "primary"], [stop, "quiet"],
    [saveVideo, "quiet"], [saveLog, "quiet"]]) {
    button.type = "button"; button.setAttribute("kind", kind); actions.append(button);
  }
  actions.prepend(storageLabel);
  const captureStatus = el("p", "surface-message", "카메라 프레임 수신 대기");
  captureStatus.id = "vision-capture-status"; captureStatus.setAttribute("role", "status");
  const library = el("details", "surface-camera-library");
  library.hidden = ctx.role === "viewer";
  let refreshLibrary = null;
  if (ctx.role !== "viewer") {
    library.append(el("summary", "", "로봇 SD 저장 파일"));
    const refresh = el("ui-button", "", "목록 새로고침");
    refresh.type = "button"; refresh.setAttribute("kind", "quiet");
    const files = el("ul", "surface-camera-files");
    library.append(refresh, files);
    async function loadLibrary() {
      const records = (await ctx.api("/api/v1/vision/front/evidence")).records || [];
      files.replaceChildren();
      for (const record of records.slice(0, 10)) {
        const row = el("li");
        const button = el("ui-button", "", `${record.file_name} · ${Math.ceil(record.bytes / 1024)} KiB 다운로드`);
        button.type = "button"; button.setAttribute("kind", "quiet");
        button.addEventListener("click", async () => {
          button.disabled = true;
          try {
            const response = await fetch(`/api/v1/vision/front/evidence/${encodeURIComponent(record.id)}`,
              {headers: authHeaders(), cache: "no-store"});
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            saveCameraFile(await response.blob(), record.file_name);
          } catch (error) { captureStatus.textContent = `저장 파일 다운로드 실패: ${error.message}`; }
          finally { button.disabled = false; }
        });
        row.append(button); files.append(row);
      }
      if (!records.length) files.append(el("li", "", "로봇에 저장된 카메라 파일이 없습니다."));
    }
    refreshLibrary = loadLibrary;
    refresh.addEventListener("click", () => loadLibrary().catch((error) => {
      captureStatus.textContent = `로봇 저장 목록을 읽지 못했습니다: ${error.message}`;
    }));
    library.addEventListener("toggle", () => {
      if (library.open) loadLibrary().catch((error) => {
        captureStatus.textContent = `로봇 저장 목록을 읽지 못했습니다: ${error.message}`;
      });
    });
  }
  const facts = el("dl", "ui-readout");
  const source = el("dd", "", "—"); source.id = "vision-source";
  const resolution = el("dd", "", "—"); resolution.id = "vision-resolution";
  const age = el("dd", "", "—"); age.id = "vision-age";
  const captured = el("dd", "", "—"); captured.id = "vision-captured";
  facts.append(el("dt", "", "소스"), source, el("dt", "", "해상도"), resolution,
    el("dt", "", "프레임 나이"), age, el("dt", "", "촬영 시각"), captured);
  root.append(head, stage, status, actions, captureStatus, library, facts);
  const elements = {"vision-stage": stage, "vision-frame": frame, "vision-empty": empty,
    "vision-status": status, "vision-source": source, "vision-resolution": resolution,
    "vision-age": age, "vision-captured": captured};
  async function storeOnRobot(media, metadata) {
    const response = await fetch("/api/v1/vision/front/evidence", {
      method: "POST", cache: "no-store", body: evidenceBody(metadata, media),
      headers: {...authHeaders(), "Content-Type": "application/octet-stream"},
    });
    if (!response.ok) {
      let detail = null;
      try { detail = (await response.json()).error?.message; } catch (_error) { /* HTTP status remains. */ }
      throw new Error(detail || `HTTP ${response.status}`);
    }
    const record = await response.json();
    if (library.open) refreshLibrary?.().catch(() => {});
    return record;
  }
  let capture;
  const updateCapture = (state) => {
    storage.disabled = state.recording || state.uploading;
    shot.disabled = !state.ready || state.uploading;
    start.disabled = !state.ready || !state.supported || state.recording || state.uploading;
    stop.disabled = !state.recording;
    saveVideo.disabled = !state.saved || state.recording || state.uploading;
    saveLog.disabled = !state.saved || state.recording || state.uploading;
    captureStatus.textContent = state.message;
  };
  capture = createCameraCapture({onChange: updateCapture, storeOnRobot,
    onComplete: async () => {
      const location = storage.value;
      if (location !== "robot") capture.saveOperations();
      await capture.saveVideo(location);
    }});
  updateCapture(capture.state());
  shot.addEventListener("click", () => { capture.screenshot(storage.value); });
  start.addEventListener("click", () => { capture.start(); });
  stop.addEventListener("click", () => { capture.stop(); });
  saveVideo.addEventListener("click", () => { capture.saveVideo(storage.value); });
  saveLog.addEventListener("click", () => { capture.saveOperations(); });
  const action = (event) => capture.recordAction(event.detail);
  window.addEventListener("rosy:operator-action", action);
  const preview = createVisionPreview({elements, setText: (id, value) => { elements[id].textContent = value ?? "—"; },
    api: ctx.api, authHeaders, hasToken: () => Boolean(session.token), isHidden: () => document.hidden,
    onFrame: (frame) => capture.acceptFrame(frame), onUnavailable: (message) => capture.unavailable(message)});
  const visibility = () => { if (document.hidden) preview.stop("화면이 숨겨져 카메라를 중지했습니다."); else preview.start(); };
  document.addEventListener("visibilitychange", visibility);
  preview.start();
  return () => { document.removeEventListener("visibilitychange", visibility);
    window.removeEventListener("rosy:operator-action", action);
    preview.stop("카메라 패널을 닫았습니다."); capture.dispose(); };
}
