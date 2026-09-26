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
  const state = () => ({ready: Boolean(ready()), recording: Boolean(active()), uploading,
    saved: Boolean(completed), supported: Boolean(recordingType()), message});
  const notify = () => onChange(state());
  function draw() {
    if (!frame || !context) return;
    context.drawImage(frame.image, 0, 0, canvas.width, canvas.height);
    const last = timeline.snapshot().at(-1);
    if (last && now() - startedAt - last.elapsed_ms < 3_000) {
      const height = Math.max(28, Math.round(canvas.height * 0.13));
      context.fillStyle = "rgba(0, 0, 0, 0.78)";
      context.fillRect(0, canvas.height - height, canvas.width, height);
      context.fillStyle = "white";
      context.font = `${Math.max(14, Math.round(height * 0.48))}px sans-serif`;
      context.fillText(`${(last.elapsed_ms / 1000).toFixed(1)}s  ${last.action} · ${last.result === "accepted" ? "접수" : "실패"}`,
        8, canvas.height - Math.round(height * 0.28), canvas.width - 16);
    }
  }
  function acceptFrame({image, blob, sequence, source, capturedAt}) {
    if (!image?.naturalWidth || !image?.naturalHeight || blob?.type !== "image/jpeg") return;
    frame = {image, blob, sequence, source, capturedAt};
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
    const shot = frame;
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
    if (!ready() || !type || active()) { message = "새 프레임과 브라우저 녹화 지원을 확인하세요."; notify(); return false; }
    completed = null;
    timeline = createOperationTimeline();
    chunks = [];
    bytes = 0;
    frameCount = 1;
    startedAt = now();
    startedWall = new Date();
    canvas = document.createElement("canvas");
    canvas.width = frame.image.naturalWidth;
    canvas.height = frame.image.naturalHeight;
    context = canvas.getContext("2d");
    if (!context || !canvas.captureStream) { message = "이 브라우저는 영상 녹화를 지원하지 않습니다."; notify(); return false; }
    draw();
    try {
      stream = canvas.captureStream(2);
      recorder = new MediaRecorder(stream, {mimeType: type});
      recorder.ondataavailable = (event) => {
        if (event.data?.size) { chunks.push(event.data); bytes += event.data.size; }
        if (bytes > MAX_VIDEO_BYTES && active()) stop("녹화 크기 제한에 도달했습니다.");
      };
      recorder.onerror = () => stop("브라우저 녹화 오류로 중지했습니다.");
      recorder.onstop = () => {
        clearTimeout(timer); timer = null;
        stream?.getTracks().forEach((track) => track.stop());
        stream = null;
        const stamp = fileStamp(startedWall);
        completed = {video: new Blob(chunks, {type}),
          name: `rosy-camera-${stamp}`, extension: type.startsWith("video/mp4") ? "mp4" : "webm",
          manifest: {schema_version: 1, kind: "video", mime_type: type.split(";")[0],
            started_at: startedWall.toISOString(), stopped_at: new Date().toISOString(), frame_count: frameCount,
            operations: timeline.snapshot()}};
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
      recorder.start(1_000);
      timer = setTimeout(() => stop("5분 제한에 도달해 녹화를 중지했습니다."), MAX_DURATION_MS);
      message = "녹화 중 · 화면 미리보기를 기록합니다.";
      notify();
      return true;
    } catch (_error) {
      stream?.getTracks().forEach((track) => track.stop());
      stream = null; recorder = null;
      message = "브라우저가 녹화를 시작하지 못했습니다."; notify();
      return false;
    }
  }
  function stop(reason = "녹화를 중지했습니다.") {
    if (!active()) return false;
    clearTimeout(timer); timer = null;
    message = reason;
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
    if (location === "pc" || location === "both") save(completed.video, `${completed.name}.${completed.extension}`);
    if (location === "robot" || location === "both") {
      if (!storeOnRobot || uploading || completed.video.size > 64 * 1024 * 1024) return false;
      uploading = true; notify();
      try {
        const record = await storeOnRobot(completed.video, completed.manifest);
        message = `영상을 로봇 SD에 저장했습니다 · ${record.file_name}`;
      } catch (error) { message = `로봇 저장 실패: ${error.message}`; return false; }
      finally { uploading = false; notify(); }
    } else { message = "녹화 영상을 PC에 저장했습니다."; notify(); }
    return true;
  }
  function saveOperations() {
    if (!completed) return false;
    save(new Blob([JSON.stringify(completed.manifest, null, 2) + "\n"], {type: "application/json"}),
      `${completed.name}.json`);
    return true;
  }
  function dispose() {
    if (active()) stop("카메라 화면을 닫아 녹화를 중지했습니다.");
    frame = null;
  }
  return {acceptFrame, unavailable, screenshot, start, stop, recordAction,
    saveVideo, saveOperations, dispose, state};
}
