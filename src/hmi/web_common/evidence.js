// Rosy Pilot 조종 중 카메라 증거(D-323 T9)와 dashboard 가 함께 쓰는 공용 모듈.
// 원본 camera-capture.js 를 web_common 으로 승격했다(D-323 T9, 바운드 5분/60MB 불변).
// Operator-side evidence from the authenticated, bounded JPEG preview.
// No image, token, request body or device address is sent to a new endpoint.

const OPERATIONS = new Map([
  ["POST /api/v1/mode", "운전 모드 변경"],
  ["POST /api/v1/teleop", "수동 운전"],
  ["POST /api/v1/navigation/goal", "주행 목표 요청"],
  ["POST /api/v1/navigation/cancel", "주행 취소"],
  ["POST /api/v1/docking/dock", "도킹 요청"],
  ["POST /api/v1/docking/undock", "언도크 요청"],
  ["POST /api/v1/docking/cancel", "도킹 취소"],
  ["PUT /api/v1/line-follow/mode", "차선 추종 변경"],
  ["POST /api/v1/safety/stop", "비상 정지"],
  ["POST /api/v1/safety/release", "비상 정지 해제"],
]);
const MAX_DURATION_MS = 5 * 60 * 1000;
const MAX_VIDEO_BYTES = 60 * 1024 * 1024;
const FRAME_FRESH_MS = 2_000;

export async function fetchCameraPair(status, {fetchFrame, previewMode = "raw"}) {
  if (status.raw_available !== true || status.raw_sequence !== status.sequence) {
    throw new Error("표시 없는 원본이 준비되지 않았습니다.");
  }
  async function read(variant) {
    const response = await fetchFrame(`/api/v1/vision/front/frame?sequence=${encodeURIComponent(status.sequence)}&overlay=${variant === "annotated"}`);
    if (!response.ok) throw new Error(`camera ${variant} ${response.status}`);
    const headers = response.headers;
    const sequence = headers.get("X-Rosy-Camera-Sequence");
    const capturedAt = headers.get("X-Rosy-Camera-Captured-At");
    const frameId = headers.get("X-Rosy-Camera-Frame-Id");
    if (headers.get("X-Rosy-Camera-Variant") !== variant || sequence !== String(status.sequence)
        || !capturedAt || !Number.isFinite(Number(capturedAt)) || !frameId) {
      throw new Error("원본·표시본 출처를 확인할 수 없습니다.");
    }
    const blob = await response.blob();
    if (blob.type !== "image/jpeg") throw new Error("JPEG 원본이 아닙니다.");
    return {blob, sequence: Number(sequence), capturedAt: Number(capturedAt), frameId,
      source: headers.get("X-Rosy-Camera-Source") || "front"};
  }
  const raw = await read("raw");
  if (previewMode === "raw") return {...raw, rawBlob: raw.blob, previewMode};
  const annotated = await read("annotated");
  if (annotated.capturedAt !== raw.capturedAt || annotated.frameId !== raw.frameId) {
    throw new Error("원본과 표시본의 촬영 시점이 다릅니다.");
  }
  return {...annotated, rawBlob: raw.blob, previewMode};
}

export function classifyOperation(method, path, status) {
  const action = OPERATIONS.get(`${String(method).toUpperCase()} ${path}`);
  return action ? {action, result: status >= 200 && status < 300 ? "accepted" : "failed"} : null;
}

export function createOperationTimeline({limit = 200} = {}) {
  const events = [];
  return {
    add(event, elapsedMs) {
      if (!event || !Number.isFinite(elapsedMs)) return;
      const previous = events.at(-1);
      if (previous?.action === event.action && previous?.result === event.result
          && elapsedMs - previous.elapsed_ms < 1_000) return;
      events.push({action: event.action, result: event.result,
        elapsed_ms: Math.max(0, Math.round(elapsedMs))});
      if (events.length > limit) events.shift();
    },
    snapshot: () => events.map((event) => ({...event})),
  };
}

function fileStamp(date = new Date()) {
  return date.toISOString().replaceAll(":", "-").replace(/\.\d{3}Z$/, "Z");
}

export function evidenceBody(metadata, media) {
  const encoded = new TextEncoder().encode(JSON.stringify(metadata));
  if (encoded.length > 32_768) throw new Error("조작 기록이 너무 큽니다.");
  const prefix = new Uint8Array(4);
  new DataView(prefix.buffer).setUint32(0, encoded.length, true);
  return new Blob([prefix, encoded, media], {type: "application/octet-stream"});
}

export function saveCameraFile(blob, filename) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  setTimeout(() => URL.revokeObjectURL(url), 30_000);
}

function recordingType() {
  if (typeof MediaRecorder === "undefined") return null;
  for (const type of ["video/webm;codecs=vp9", "video/webm;codecs=vp8", "video/webm", "video/mp4"]) {
    if (MediaRecorder.isTypeSupported(type)) return type;
  }
  return null;
}

export function createCameraCapture({onChange = () => {}, onComplete = () => {}, save = saveCameraFile,
  storeOnRobot = null,
  now = () => performance.now()} = {}) {
  let frame = null;
  let frameAt = -Infinity;
  let recorder = null;
  let derivative = null;
  let derivativeStream = null;
  let derivativeCanvas = null;
  let derivativeContext = null;
  let derivativeChunks = [];
  let previewMode = "raw";
  let pairGroup = null;
  let finalizing = false;
  let disposed = false;
  let stream = null;
  let canvas = null;
  let context = null;
  let chunks = [];
  let bytes = 0;
  let startedAt = 0;
  let startedWall = null;
  let frameCount = 0;
  let timeline = createOperationTimeline();
  let completed = null;
  let timer = null;
  let message = "프레임을 기다립니다.";
  let uploading = false;

  const active = () => recorder && recorder.state === "recording";
  const ready = () => frame && now() - frameAt <= FRAME_FRESH_MS;
  const state = () => ({ready: Boolean(ready()), recording: Boolean(active()) || finalizing, uploading,
    saved: Boolean(completed), supported: Boolean(recordingType()), previewMode, message});
  const notify = () => onChange(state());
  // D-359 §4 — 색·글꼴은 ui.js(window.RosyPalette)가 푼다. 녹화 중에는 프레임마다
  // 다시 그리므로 테마가 바뀌면 다음 프레임부터 새 색이다.
  const tokenColor = (name) => window.RosyPalette.cssColor(name);
  function draw() {
    if (!frame || !context) return;
    context.drawImage(frame.rawImage || frame.image, 0, 0, canvas.width, canvas.height);
    if (!derivativeContext) return;
    derivativeContext.drawImage(frame.image, 0, 0, derivativeCanvas.width, derivativeCanvas.height);
    const last = timeline.snapshot().at(-1);
    if (last && now() - startedAt - last.elapsed_ms < 3_000) {
      const height = Math.max(28, Math.round(derivativeCanvas.height * 0.13));
      derivativeContext.fillStyle = tokenColor("--scrim");
      derivativeContext.fillRect(0, derivativeCanvas.height - height, derivativeCanvas.width, height);
      derivativeContext.fillStyle = tokenColor("--ink");
      derivativeContext.font = window.RosyPalette.canvasFont(Math.max(14, Math.round(height * 0.48)), "body");
      derivativeContext.fillText(`${(last.elapsed_ms / 1000).toFixed(1)}s  ${last.action} · ${last.result === "accepted" ? "접수" : "실패"}`,
        8, derivativeCanvas.height - Math.round(height * 0.28), derivativeCanvas.width - 16);
    }
  }
  function acceptFrame({image, blob, sequence, source, capturedAt, rawImage, rawBlob, previewMode: incomingMode}) {
    if (disposed) return;
    if (incomingMode && incomingMode !== previewMode) return;
    if (!image?.naturalWidth || !image?.naturalHeight || blob?.type !== "image/jpeg") return;
    if (previewMode === "annotated" && (!rawImage?.naturalWidth || rawBlob?.type !== "image/jpeg")) {
      unavailable("같은 촬영 시점의 원본이 없어 표시본 녹화를 중지합니다."); return;
    }
    frame = {image, blob, sequence, source, capturedAt, rawImage, rawBlob};
    frameAt = now();
    if (active()) { frameCount += 1; draw(); }
    message = active() ? "녹화 중 · 화면 미리보기를 기록합니다." : "스크린샷 또는 녹화를 시작할 수 있습니다.";
    notify();
  }
  function unavailable(reason = "카메라 프레임을 기다립니다.") {
    frame = null;
    frameAt = -Infinity;
    if (active()) stop("카메라 프레임이 끊겨 녹화를 중지했습니다.");
    else { message = reason; notify(); }
  }
  async function screenshot(location = "pc") {
    if (!ready()) { message = "새 카메라 프레임이 없어 저장할 수 없습니다."; notify(); return false; }
    const shot = {...frame, blob: frame.rawBlob || frame.blob};
    if (location === "pc" || location === "both") save(shot.blob, `rosy-camera-${fileStamp()}.jpg`);
    if (location === "robot" || location === "both") {
      if (!storeOnRobot || uploading) return false;
      uploading = true; notify();
      try {
        const record = await storeOnRobot(shot.blob, {schema_version: 1, kind: "screenshot",
          mime_type: "image/jpeg", saved_at: new Date().toISOString(),
          sequence: shot.sequence, source: shot.source || "UNKNOWN"});
        message = `스크린샷을 로봇 SD에 저장했습니다 · ${record.file_name}`;
      } catch (error) { message = `로봇 저장 실패: ${error.message}`; return false; }
      finally { uploading = false; notify(); }
    } else { message = "스크린샷 JPEG를 PC에 저장했습니다."; notify(); }
    return true;
  }
  function start() {
    const type = recordingType();
    if (disposed || !ready() || !type || active() || finalizing) { message = "새 프레임과 브라우저 녹화 지원을 확인하세요."; notify(); return false; }
    completed = null;
    timeline = createOperationTimeline();
    chunks = [];
    bytes = 0;
    frameCount = 1;
    pairGroup = Array.from(crypto.getRandomValues(new Uint8Array(16)),
      value => value.toString(16).padStart(2, "0")).join("");
    derivativeChunks = [];
    startedAt = now();
    startedWall = new Date();
    canvas = document.createElement("canvas");
    canvas.width = (frame.rawImage || frame.image).naturalWidth;
    canvas.height = (frame.rawImage || frame.image).naturalHeight;
    context = canvas.getContext("2d");
    if (!context || !canvas.captureStream) { message = "이 브라우저는 영상 녹화를 지원하지 않습니다."; notify(); return false; }
    try {
      if (previewMode === "annotated") {
        derivativeCanvas = document.createElement("canvas");
        derivativeCanvas.width = frame.image.naturalWidth; derivativeCanvas.height = frame.image.naturalHeight;
        derivativeContext = derivativeCanvas.getContext("2d");
        derivativeStream = derivativeCanvas.captureStream(2);
        derivative = new MediaRecorder(derivativeStream, {mimeType: type});
        derivative.ondataavailable = (event) => {
          if (event.data?.size) { derivativeChunks.push(event.data); bytes += event.data.size; }
          if (bytes > MAX_VIDEO_BYTES && active()) stop("녹화 크기 제한에 도달했습니다.");
        };
        derivative.onerror = () => stop("표시본 녹화 오류로 원본과 함께 중지했습니다.");
      }
      draw();
      stream = canvas.captureStream(2);
      recorder = new MediaRecorder(stream, {mimeType: type});
      recorder.ondataavailable = (event) => {
        if (event.data?.size) { chunks.push(event.data); bytes += event.data.size; }
        if (bytes > MAX_VIDEO_BYTES && active()) stop("녹화 크기 제한에 도달했습니다.");
      };
      recorder.onerror = () => stop("브라우저 녹화 오류로 중지했습니다.");
      const finish = () => {
        finalizing = false;
        clearTimeout(timer); timer = null;
        stream?.getTracks().forEach((track) => track.stop());
        stream = null;
        derivativeStream?.getTracks().forEach((track) => track.stop()); derivativeStream = null;
        const stamp = fileStamp(startedWall);
        completed = {video: new Blob(chunks, {type}),
          name: `rosy-camera-${stamp}-raw`, extension: type.startsWith("video/mp4") ? "mp4" : "webm",
          manifest: {schema_version: 1, kind: "video", mime_type: type.split(";")[0],
            preview_mode: "raw", pair_group_id: pairGroup,
            started_at: startedWall.toISOString(), stopped_at: new Date().toISOString(), frame_count: frameCount,
            operations: timeline.snapshot()}};
        if (completed.video.size && derivativeChunks.length) {
          completed.derivative = {video: new Blob(derivativeChunks, {type}),
            name: `rosy-camera-${stamp}-annotated`, extension: completed.extension,
            manifest: {...completed.manifest, preview_mode: "annotated"}};
        }
        derivativeChunks = []; derivative = null; derivativeContext = null; derivativeCanvas = null;
        chunks = [];
        if (!completed.video.size) completed = null;
        message = completed
          ? `${frameCount}개 프레임 기록 완료 · 영상과 조작 기록을 저장하세요.`
          : "녹화 데이터가 없어 저장할 수 없습니다.";
        notify();
        if (completed) Promise.resolve().then(onComplete).catch((error) => {
          message = `저장 실패: ${error.message}`;
          notify();
        });
      };
      let rawStopped = false, derivativeStopped = !derivative;
      recorder.onstop = () => { rawStopped = true; if (derivativeStopped) finish(); };
      if (derivative) derivative.onstop = () => { derivativeStopped = true; if (rawStopped) finish(); };
      derivative?.start(1_000);
      recorder.start(1_000);
      timer = setTimeout(() => stop("5분 제한에 도달해 녹화를 중지했습니다."), MAX_DURATION_MS);
      message = "녹화 중 · 화면 미리보기를 기록합니다.";
      notify();
      return true;
    } catch (_error) {
      stream?.getTracks().forEach((track) => track.stop());
      if (derivative?.state === "recording") derivative.stop();
      derivativeStream?.getTracks().forEach((track) => track.stop());
      derivative = null; derivativeStream = null; derivativeContext = null;
      stream = null; recorder = null;
      message = "브라우저가 녹화를 시작하지 못했습니다."; notify();
      return false;
    }
  }
  function stop(reason = "녹화를 중지했습니다.") {
    if (!active() || finalizing) return false;
    clearTimeout(timer); timer = null;
    message = reason;
    finalizing = true;
    if (derivative?.state === "recording") derivative.stop();
    recorder.stop();
    notify();
    return true;
  }
  function recordAction(event) {
    if (!active()) return;
    timeline.add(event, now() - startedAt);
    draw();
  }
  async function saveVideo(location = "pc") {
    if (!completed?.video.size) return false;
    const files = [completed, completed.derivative].filter(Boolean);
    if (location === "pc" || location === "both") {
      for (const file of files) save(file.video, `${file.name}.${file.extension}`);
    }
    if (location === "robot" || location === "both") {
      if (!storeOnRobot || uploading || completed.video.size > 64 * 1024 * 1024) return false;
      uploading = true; notify();
      try {
        let record;
        for (const file of files) record = await storeOnRobot(file.video, file.manifest);
        message = `영상을 로봇 SD에 저장했습니다 · ${record.file_name}`;
      } catch (error) { message = `로봇 저장 실패: ${error.message}`; return false; }
      finally { uploading = false; notify(); }
    } else { message = "녹화 영상을 PC에 저장했습니다."; notify(); }
    return true;
  }
  function saveOperations() {
    if (!completed) return false;
    const manifest = {...completed.manifest, annotation_origin: "none",
      derivative: completed.derivative ? {file_name: `${completed.derivative.name}.${completed.derivative.extension}`,
        preview_mode: "annotated", annotation_origin: "model_unreviewed"} : null};
    save(new Blob([JSON.stringify(manifest, null, 2) + "\n"], {type: "application/json"}),
      `${completed.name}.json`);
    return true;
  }
  function dispose() {
    disposed = true;
    if (active()) stop("카메라 화면을 닫아 녹화를 중지했습니다.");
    frame = null;
  }
  function setPreviewMode(value) {
    if (disposed || active() || finalizing || uploading || !["raw", "annotated"].includes(value)) return false;
    previewMode = value; frame = null; frameAt = -Infinity;
    message = value === "raw" ? "표시 없는 원본 수신 대기" : "원본 + 모델 표시본 수신 대기 · 결과는 확인용입니다.";
    notify(); return true;
  }
  return {acceptFrame, unavailable, screenshot, start, stop, recordAction,
    saveVideo, saveOperations, dispose, state, setPreviewMode};
}
