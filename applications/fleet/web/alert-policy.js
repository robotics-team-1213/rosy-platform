// Fleet 관제 알림 정책 — 어떤 실패가 토스트 카드가 되는가(SRP: 카드 그리기는 alert-popup.js).
// 호출 실패(GET 관문·폴링 병합)와 로그 실패(같은 사건 병합)를 popup.push로 보낸다. 결과를 누른 행
// 안에 보여 주는 호출은 console.js call({inline})과 log(..., {inline})가 여기까지 오지 않게 한다.
// 화면 런타임 오류는 로봇 상태가 아니므로 토스트가 아니라 기록 줄과 브라우저 개발 도구에만 남는다(11-18).
const POLL_ERROR_KEY = "call|poll|fleet";
const LOG_DEDUPE_WINDOW_MS = 1500;
const ROBOT_RE = /\b(rosy_\d+|arm_[sab])\b/;

export function createFleetAlertPolicy({ push, findItem, clearByKey }) {
  let lastCallError = { at: 0, method: "", message: "", code: "", status: 0, robotId: null, key: "" };
  const pollPaths = new Set();

  function pushLogError(message, meta = {}) {
    if (meta?.silent === true) return;
    const msg = String(message || "오류가 발생했습니다.");
    const match = ROBOT_RE.exec(msg);
    if ((Date.now() - lastCallError.at) < LOG_DEDUPE_WINDOW_MS) {
      const sameMessage = Boolean(lastCallError.message) && msg.includes(lastCallError.message);
      const sameCode = meta?.code !== undefined && meta?.code !== "" && meta.code === lastCallError.code;
      const sameStatus = Boolean(meta?.status) && Number(meta.status) === lastCallError.status;
      const hasExplicitConflict = (
        (meta?.code !== undefined && meta?.code !== "" && Boolean(lastCallError.code) && meta.code !== lastCallError.code)
        || (Boolean(meta?.status) && Boolean(lastCallError.status) && Number(meta.status) !== lastCallError.status)
      );
      const isUnannotatedFollowup = meta?.code === undefined && !meta?.status
        && Boolean(lastCallError.method) && lastCallError.method !== "GET" && Boolean(lastCallError.key);
      if (!hasExplicitConflict && (sameMessage || sameCode || sameStatus || isUnannotatedFollowup)) {
        const existing = lastCallError.key ? findItem(lastCallError.key) : null;
        if (existing) {
          // 같은 사건의 이어지는 로그: 두 번째 카드 없이 같은 key에-message만 갱신(×N은 올라간다).
          const nextRobotId = match?.[1] || meta?.robotId || existing.target?.robotId || null;
          push({key: existing.key, severity: "crit", message: msg, followUp: true,
            target: { kind: "log", robotId: nextRobotId }});
        }
        return;
      }
    }
    push({
      severity: "crit",
      title: meta?.title || "오류 알림",
      message: msg,
      status: meta?.status,
      code: meta?.code,
      path: meta?.path,
      detail: meta?.detail,
      target: { kind: "log", robotId: match?.[1] || meta?.robotId || null },
    });
  }

  function pushCallError(path, options = {}, error = {}, authLocked = false, meta = {}) {
    if (!error || error.name === "AbortError") return;
    if (authLocked || error?.status === 401 || error?.code === "PASSWORD_CHANGE_REQUIRED") return;
    const cleanPath = String(path || "").split("?")[0];
    const method = String(options?.method || "GET").toUpperCase();
    const optionalVision = (cleanPath === "/api/fleet/vision/sources" || cleanPath === "/api/fleet/vision/lease") && error.status === 404;
    if (optionalVision) return;
    if (method === "GET" && error?.status && error.status < 500) return;

    const isPollFailure = method === "GET" && (!error?.status || error.status >= 500);
    if (isPollFailure && meta?.isStaleHoldover) return;
    // Fleet에 닿지 않음(응답 없음·상태 조회 실패)은 머리말 연결 표시(#link-state)가 한 곳에서 말한다. 카드를 만들지 않는다.
    if (isPollFailure && (!error?.status || cleanPath === "/api/fleet/state")) return;

    const match = ROBOT_RE.exec(cleanPath) || ROBOT_RE.exec(String(error.message || ""));
    const robotId = match?.[1] || meta?.robotId || null;
    const key = isPollFailure ? POLL_ERROR_KEY : `call|${cleanPath}`;

    let detail = error.detail;
    if (isPollFailure) {
      if (!findItem(POLL_ERROR_KEY)) pollPaths.clear();
      if (cleanPath) pollPaths.add(cleanPath);
      detail = {
        status: error.status || undefined,
        code: error.code || undefined,
        latestPath: cleanPath || undefined,
        paths: [...pollPaths],
        ...(error.detail !== undefined ? { detail: error.detail } : {}),
      };
    }

    lastCallError = {
      at: Date.now(),
      method,
      message: String(error.message || ""),
      code: error.code ? String(error.code) : "",
      status: error.status ? Number(error.status) : 0,
      robotId,
      key,
    };

    push({
      key,
      severity: "crit",
      title: method !== "GET" ? "명령·요청 오류" : "서버 응답 오류",
      message: error.message || "요청을 처리하지 못했습니다.",
      status: error.status,
      code: error.code,
      path: cleanPath,
      detail,
      target: { kind: "log", robotId },
    });
  }

  function clearCallError(path) {
    const cleanPath = String(path || "").split("?")[0];
    clearByKey(`call|${cleanPath}`);
    if (cleanPath === "/api/fleet/state") clearByKey(POLL_ERROR_KEY);
  }


  function attachWindowErrors(scope, log) {
    scope.listen(window, "error", (event) => {
      if (event.error?.name === "AbortError") return;
      log(`화면 런타임 오류 — ${event.message || event.error?.message || "예상하지 못한 스크립트 오류"}`, "bad", { silent: true });
    });
    scope.listen(window, "unhandledrejection", (event) => {
      const reason = event.reason;
      if (!reason || reason.name === "AbortError") return;
      log(`비동기 처리 오류 — ${reason.message || String(reason)}`, "bad", { silent: true });
    });
  }

  return { pushLogError, pushCallError, clearCallError, attachWindowErrors };
}
