import { authHeaders, session } from "/assets/client.js";
import { createVisionPreview } from "/assets/vision.js";
import { createCameraCapture, evidenceBody, saveCameraFile } from "/assets/camera-capture.js";
// D-359 §5.3 — 끌 때 이유를 같이 준다. 켜거나 짧은 요청 중 잠금이면 이유를 지운다.
function setOff(control, off, reason = "") { control.disabled = Boolean(off); if (off && reason) control.setAttribute("reason", reason); else control.removeAttribute("reason"); }

function el(tag, cls, text) { const node = document.createElement(tag); if (cls) node.className = cls; if (text !== undefined) node.textContent = text; return node; }

export function mount(root, ctx) {
  let disposed = false; let expanding = false; let generation = 0; let closeRequested = false;
  const head = el("ui-head", "", "전방 카메라");
  const stage = el("div", "surface-camera-stage"); stage.id = "vision-stage"; stage.dataset.state = "waiting";
  const frame = el("img", "surface-camera-frame"); frame.id = "vision-frame"; frame.alt = "전방 카메라 실시간 영상"; frame.hidden = true;
  const empty = el("ui-empty", "surface-camera-empty", "카메라 프레임 수신 대기"); empty.id = "vision-empty";
  const closeExpanded = el("ui-button", "surface-camera-close", "확대 닫기");
  closeExpanded.type = "button"; closeExpanded.setAttribute("kind", "quiet");
  const toolbar = el("div", "surface-camera-toolbar");
  toolbar.append(closeExpanded); stage.append(frame, empty, toolbar);
  const status = el("ui-tag", "", "수신 대기"); status.id = "vision-status";
  status.dataset.evidence = "unavailable"; status.title = "WAITING"; status.setAttribute("status", "neutral");
  const qualityIndicator = el("ui-status", "", "조도가 낮아 차선·물체를 판정할 수 없습니다");
  qualityIndicator.id = "vision-quality"; qualityIndicator.hidden = true; qualityIndicator.setAttribute("state", "warning");
  qualityIndicator.setAttribute("role", "status"); qualityIndicator.setAttribute("aria-live", "polite");
  const actions = el("ui-actions", "surface-actions surface-camera-actions");
  const expand = el("ui-button", "", "영상 확대"); expand.id = "vision-expand";
  expand.type = "button"; expand.setAttribute("kind", "quiet"); actions.append(expand);
  const storageLabel = el("label", "ui-field-label surface-camera-storage", "저장 위치");
  const storage = el("select", "ui-field"); storage.id = "vision-storage";
  for (const [value, label] of [["pc", "이 PC"], ["robot", "로봇 SD"], ["both", "PC와 로봇 SD"]]) {
    const option = el("option", "", label); option.value = value;
    if (ctx.role === "viewer" && value !== "pc") option.disabled = true;
    storage.append(option);
  }
  storageLabel.append(storage);
  const browserLabel = el("label", "ui-field-label", "브라우저 확인 영상");
  const browserMode = el("select", "ui-field"); browserMode.id = "vision-record-mode";
  for (const [value, label] of [["raw", "표시 없는 원본"], ["annotated", "원본 + 모델 표시본"]]) {
    const option = el("option", "", label); option.value = value; browserMode.append(option);
  }
  browserLabel.append(browserMode);
  const shot = el("ui-button", "", "스크린샷"); shot.id = "vision-screenshot";
  shot.type = "button"; shot.setAttribute("kind", "quiet"); actions.append(shot);
  const start = el("ui-button", "", "녹화 시작"); start.id = "vision-record-start";
  start.type = "button"; start.setAttribute("kind", "primary"); actions.append(start);
  const stop = el("ui-button", "", "녹화 중지"); stop.id = "vision-record-stop";
  stop.type = "button"; stop.setAttribute("kind", "quiet"); actions.append(stop);
  const saveVideo = el("ui-button", "", "영상 다시 저장"); saveVideo.id = "vision-record-save";
  saveVideo.type = "button"; saveVideo.setAttribute("kind", "quiet"); actions.append(saveVideo);
  const saveLog = el("ui-button", "", "조작 기록 저장"); saveLog.id = "vision-operations-save";
  saveLog.type = "button"; saveLog.setAttribute("kind", "quiet"); actions.append(saveLog);
  const primaryActions = el("ui-actions", "surface-actions"); primaryActions.append(expand, stop);
  actions.prepend(storageLabel, browserLabel);
  const tools = el("details", "surface-camera-tools");
  tools.append(el("summary", "", "사진·녹화 저장 도구"), actions);
  const captureStatus = el("ui-status", "", "카메라 프레임 수신 대기");
  captureStatus.id = "vision-capture-status";
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
          } catch (error) { captureStatus.hidden = false; captureStatus.textContent = `저장 파일 다운로드 실패: ${error.message}`; }
          finally { button.disabled = false; }
        });
        row.append(button); files.append(row);
      }
      if (!records.length) files.append(el("li", "", "로봇에 저장된 카메라 파일이 없습니다."));
    }
    refreshLibrary = loadLibrary;
    const refreshWithFeedback = () => loadLibrary().catch((error) => {
      captureStatus.hidden = false; captureStatus.textContent = `로봇 저장 목록을 읽지 못했습니다: ${error.message}`;
    });
    refresh.addEventListener("click", refreshWithFeedback);
    library.addEventListener("toggle", () => { if (library.open) refreshWithFeedback(); });
  }
  const facts = el("dl", "ui-readout");
  const source = el("dd", "", "—"); source.id = "vision-source";
  const resolution = el("dd", "", "—"); resolution.id = "vision-resolution";
  const age = el("dd", "", "—"); age.id = "vision-age";
  const captured = el("dd", "", "—"); captured.id = "vision-captured";
  facts.append(el("dt", "", "소스"), source, el("dt", "", "해상도"), resolution,
    el("dt", "", "프레임 나이"), age, el("dt", "", "촬영 시각"), captured);
  const legend = el("details", "surface-camera-legend");
  legend.append(el("summary", "", "차선·객체 표시 읽는 법"));
  for (const text of [
    "LEFT LANE · RIGHT LANE: 추종에 선택한 왼쪽·오른쪽 경계. UNSEEN은 선택한 경계가 없음.",
    "FOLLOW PATH: 따라갈 목표 방향. 점선은 주행 궤적이나 객체의 미래 이동이 아님.",
    "CURRENT LANE: 선택한 차로. CANDIDATE: 추가 차로 후보이며 자동 차선 변경 대상이 아님.",
    "REGION UNCLASSIFIED · DARK: 바닥 색과 다른 미분류 영역이며 벽·차선 페인트도 포함될 수 있음. 장애물 종류를 알아본 결과가 아님. DET는 객체 모델 검출. NEAR는 가까운 중앙 경로 영역에 걸침. 0.42m L은 카메라 앞 거리(L LiDAR, G 바닥 평면 추정). unranged는 거리 미확인.",
    "TAG: 영상에서 식별한 표식 번호. PRED STOP은 도로 예측 표시 중단.",
  ]) legend.append(el("p", "", text));
  root.append(head, stage, status, qualityIndicator, primaryActions, tools, legend, captureStatus, library, facts);
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
    setOff(expand, expanding || !state.ready || !stage.requestFullscreen,
      !state.ready ? "영상 수신 후 확대할 수 있습니다" : "이 브라우저는 전체 화면 확대 불가");
    storage.disabled = state.recording || state.uploading;
    setOff(browserMode, state.recording || state.uploading, "녹화·저장이 끝난 뒤 선택하세요");
    // 올리는 중(uploading)은 짧은 잠금이라 사유 없이 끈다.
    const waiting = state.uploading ? "" : !state.ready ? "카메라 대기" : "";
    setOff(shot, !state.ready || state.uploading, waiting);
    setOff(start, !state.ready || !state.supported || state.recording || state.uploading,
      waiting || (state.uploading ? "" : !state.supported ? "이 브라우저는 녹화 불가" : state.recording ? "녹화 중" : ""));
    setOff(stop, !state.recording, "녹화 중 아님");
    const saveReason = state.uploading ? "" : state.recording ? "녹화 중" : "저장할 녹화 없음";
    setOff(saveVideo, !state.saved || state.recording || state.uploading, saveReason);
    setOff(saveLog, !state.saved || state.recording || state.uploading, saveReason);
    captureStatus.textContent = state.message;
    captureStatus.setAttribute("state", state.uploading ? "pending" : state.ready || state.saved ? "ready" : "unavailable");
    // D-359 US-009 — 프레임이 없을 때의 대기 문장은 무대(ui-empty)와 상태 태그가 이미 말한다.
    captureStatus.hidden = !state.ready && !state.recording && !state.saved && !state.uploading;
  };
  capture = createCameraCapture({onChange: updateCapture, storeOnRobot,
    onComplete: async () => {
      const location = storage.value;
      await capture.saveVideo(location);
      if (location !== "robot") capture.saveOperations();
    }});
  updateCapture(capture.state());
  let homes = [];
  function relocate() {
    if (homes.length) return;
    for (const node of [document.getElementById("shell-estop"), document.getElementById("shell-notice"), stop, captureStatus, qualityIndicator].filter(Boolean)) {
      const anchor = document.createComment("camera-fullscreen-home");
      node.before(anchor); homes.push({node, anchor}); toolbar.append(node);
    }
  }
  function restore(focus = true) {
    const active = document.activeElement;
    const returnFocus = closeRequested || active === document.body || active === closeExpanded || active === stage;
    closeRequested = false;
    for (const {node, anchor} of homes) { if (anchor.parentNode) anchor.replaceWith(node); }
    homes = []; expanding = false;
    if (!disposed) updateCapture(capture.state());
    if (focus && returnFocus && expand.isConnected && expand.getClientRects().length && !expand.closest("[inert]")) expand.focus();
  }
  expand.addEventListener("click", async () => {
    if (disposed || expanding || expand.disabled) return;
    const attempt = ++generation;
    expanding = true; updateCapture(capture.state());
    try {
      await stage.requestFullscreen();
      if (disposed) {
        if (document.fullscreenElement === stage) await document.exitFullscreen().catch(() => {});
        restore(false);
      }
    } catch (_error) {
      if (!disposed && attempt !== generation) return;
      restore();
      if (!disposed) { captureStatus.hidden = false; captureStatus.setAttribute("state", "error"); captureStatus.textContent = "영상 확대를 열지 못했습니다."; }
    }
  });
  closeExpanded.addEventListener("click", () => { closeRequested = true; document.exitFullscreen().catch(() => { closeRequested = false; }); });
  let cameraExpanded = false;
  const fullscreenChanged = () => {
    if (document.fullscreenElement === stage) { cameraExpanded = true; relocate(); closeExpanded.focus(); }
    else if (cameraExpanded) { cameraExpanded = false; generation++; restore(); }
  };
  document.addEventListener("fullscreenchange", fullscreenChanged);
  shot.addEventListener("click", () => { capture.screenshot(storage.value); });
  start.addEventListener("click", () => { capture.start(); });
  stop.addEventListener("click", () => { capture.stop(); });
  saveVideo.addEventListener("click", () => { capture.saveVideo(storage.value); });
  saveLog.addEventListener("click", () => { capture.saveOperations(); });
  const action = (event) => capture.recordAction(event.detail);
  window.addEventListener("rosy:operator-action", action);
  const preview = createVisionPreview({elements, setText: (id, value) => { elements[id].textContent = value ?? "—"; },
    previewMode: () => capture.state().previewMode,
    api: ctx.api, authHeaders, hasToken: () => Boolean(session.token), isHidden: () => document.hidden,
    onQuality: (quality) => {
      qualityIndicator.hidden = !(quality?.valid === false && ["low_light", "overexposed"].includes(quality?.reason));
      qualityIndicator.textContent = quality?.reason === "overexposed"
        ? "과노출 · 차선 정보 확인 불가" : "조도가 낮아 차선·물체를 판정할 수 없습니다";
    },
    onFrame: (frame) => capture.acceptFrame(frame), onUnavailable: (message) => capture.unavailable(message)});
  browserMode.addEventListener("change", () => {
    if (!capture.setPreviewMode(browserMode.value)) browserMode.value = capture.state().previewMode;
    else preview.start();
  });
  const visibility = () => { if (document.hidden) preview.stop("화면이 숨겨져 카메라를 중지했습니다."); else preview.start(); };
  document.addEventListener("visibilitychange", visibility);
  preview.start();
  return () => { disposed = true; generation++; restore(false); document.removeEventListener("visibilitychange", visibility);
    document.removeEventListener("fullscreenchange", fullscreenChanged);
    if (document.fullscreenElement === stage) document.exitFullscreen().catch(() => {});
    window.removeEventListener("rosy:operator-action", action);
    preview.stop("카메라 패널을 닫았습니다."); capture.dispose(); };
}
