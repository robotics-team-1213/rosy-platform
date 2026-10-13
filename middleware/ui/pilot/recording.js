// D-411 A: 로봇 학습 녹화(카메라 유닛 bag)의 순수 표시 판정. DOM·fetch·시계 없음.
// 화면 녹화(브라우저 MediaRecorder, evidence.js)와는 다른 것이다 — 이것은 로봇이 쓴다.

export const RECORDING_POLL_MS = 1000;
// Pilot 은 받은 tar 를 통째로 메모리(blob)에 둔다. 이보다 큰 녹화본은 PC 도구로 받는다.
export const PILOT_FETCH_MAX_BYTES = 256e6;
const TOO_BIG_TEXT = "큰 녹화본은 PC에서 받으세요: rosy_ml fetch <로봇> --http";

const BLOCKER_TEXT = Object.freeze({
  RECORDING_BUSY: "녹화 중에는 받을 수 없습니다",
  ROBOT_MOVING: "로봇이 멈춘 뒤에 받을 수 있습니다",
});

const ERROR_TEXT = Object.freeze({
  ...BLOCKER_TEXT,
  RECORDER_UNAVAILABLE: "녹화기 응답 없음",
  RECORDING_QUOTA_FULL: "녹화 공간이 찼습니다 — 녹화본을 받으면 비워집니다",
  RECORDING_DISK_FULL: "로봇 저장 공간이 부족합니다",
  RECORDING_NOT_ACTIVE: "진행 중인 녹화가 없습니다",
  RECORDING_NOT_FOUND: "녹화본이 없습니다",
});

// 녹화기가 스스로 멈춘 이유(last_stop_reason). 'requested'(누가 멈춤)는 따로 말하지 않는다.
const STOP_TEXT = Object.freeze({
  max_duration: "10분 상한에서 멈춤",
  quota: "녹화 공간 한도에서 멈춤",
  disk_full: "저장 공간 부족으로 멈춤",
  recorder_exit: "녹화기가 끝나 멈춤",
  shutdown: "녹화기 종료로 멈춤",
  writer_start_timeout: "녹화기가 시작되지 않아 멈춤",
});

export function formatElapsed(seconds) {
  const total = Math.max(0, Math.floor(Number(seconds) || 0));
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
}

export function formatBytes(bytes) {
  const value = Math.max(0, Number(bytes) || 0);
  if (value < 1e3) return `${Math.round(value)} B`;
  if (value < 1e6) return `${(value / 1e3).toFixed(1)} KB`;
  if (value < 1e9) return `${(value / 1e6).toFixed(1)} MB`;
  return `${(value / 1e9).toFixed(1)} GB`;
}

// action: "start" | "stop" | "fetch". 403 은 정지에서만 "남의 녹화" 이고, 시작·받기에서는 권한 부족이다.
export function errorText(code, action) {
  if (code === "FORBIDDEN") return action === "stop" ? "다른 기기가 시작한 녹화입니다" : "운전자(Operator) 권한이 필요합니다";
  return ERROR_TEXT[code] ?? "요청이 거부되었습니다";
}

// active: GET /api/v1/recordings/active 의 `active`(낡았거나 녹화기가 없으면 null).
// label 은 HUD 버튼 글자(짧게), ariaLabel 은 그 버튼이 하는 일, detail 은 그 옆 칩.
// starting: 로봇의 기록기가 돌지만 아직 첫 파일을 열지 않았다(몇 초) — 켜져 있고 멈출 수 있지만
// 기록은 아직 없으므로 시간을 세지 않는다. 운전은 "로봇 녹화 중지"(= recording)가 보인 뒤에.
// 상태 묶음의 정본은 core_common.protocol.recording 의 ACTIVE_STATES(starting·recording·stopping:
// 진행 중)와 STOPPABLE_STATES(starting·recording: 멈출 수 있음)다.
export function recordingView(active) {
  const off = {recording: false, available: true, busy: false, starting: false,
               label: "로봇 녹화", ariaLabel: "로봇 녹화", detail: "", reason: ""};
  if (!active) return {...off, available: false, reason: "녹화기 응답 없음"};
  if (active.state === "starting") {
    return {...off, recording: true, starting: true, label: "녹화 준비 중…",
            ariaLabel: "로봇 녹화 준비 중, 누르면 취소", detail: "녹화 준비 중 — 아직 기록하지 않습니다"};
  }
  if (active.state === "recording" || active.state === "stopping") {
    const busy = active.state === "stopping";
    const label = busy ? "녹화 정리 중" : "로봇 녹화 중지";
    return {
      ...off, recording: true, busy, label, ariaLabel: label,
      detail: `녹화 ${formatElapsed(active.elapsed_s)} / ${formatElapsed(active.max_duration_s)} · ${formatBytes(active.bytes)}`,
      reason: busy ? "녹화본을 정리하는 중입니다" : "",
    };
  }
  const stopped = STOP_TEXT[active.last_stop_reason];
  return {...off, detail: active.state === "error" ? "녹화기 오류" : stopped ? `지난 녹화: ${stopped}` : ""};
}

// 한 파일은 로봇의 10분 상한(D-411 §3)을 지키고, 사용자가 끄지 않은 녹화는 다음 구간으로 잇는다.
// wanted: 이 기기가 켜고 아직 끄지 않았다. 남이 멈췄거나(requested) 공간 한도면 잇지 않는다.
export function continueRecording(wanted, active) {
  return Boolean(wanted) && active?.state === "idle" && active.last_stop_reason === "max_duration";
}

function formatStarted(iso) {
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return String(iso ?? "");
  const two = (n) => String(n).padStart(2, "0");
  return `${two(at.getMonth() + 1)}-${two(at.getDate())} ${two(at.getHours())}:${two(at.getMinutes())}`;
}

// listing: GET /api/v1/recordings. 받기 가능 여부는 CORE 의 download_allowed 를 따른다
// (받는 도중에도 CORE 가 다시 보고, 움직이면 끊는다).
export function sheetRows(listing) {
  const blocker = listing?.download_allowed ? "" : (BLOCKER_TEXT[listing?.download_blocker] ?? "지금은 받을 수 없습니다");
  return (listing?.items ?? []).map((item) => {
    const complete = item.status === "complete";
    const tooBig = complete && Number(item.bytes) > PILOT_FETCH_MAX_BYTES;
    const duration = item.duration_s == null ? "—" : formatElapsed(item.duration_s);
    return {
      id: item.id,
      title: formatStarted(item.started_at),
      detail: `${duration} · ${formatBytes(item.bytes)}${item.fetched ? " · 받음" : ""}`,
      canFetch: complete && !tooBig && !blocker,
      reason: !complete ? (item.status === "recording" ? "녹화 중입니다" : "끝나지 않은 녹화입니다")
        : tooBig ? TOO_BIG_TEXT : blocker,
    };
  });
}

export function sheetNotice(listing) {
  if (!listing) return "목록을 불러오지 못했습니다";
  if (!listing.download_allowed && listing.items?.length) {
    return BLOCKER_TEXT[listing.download_blocker] ?? "지금은 받을 수 없습니다";
  }
  return listing.items?.length ? "" : "녹화본이 없습니다";
}
