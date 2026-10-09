// D-457 관제 카메라 추적 층. DOM 없는 순수 계산 — map-view.js 가 그리고 tracking-view.js 가 상태줄을 쓴다.
// 표시·교차확인 전용이다. 목표·교통정리·미션 입력이 아니다.

export const OFFSET_WARN_M = 0.15;
export const TRACKING_STATUS_TEXT = Object.freeze({
  OK: "추적 중",
  LEARNING: "배경 학습 중",
  CALIBRATION_REQUIRED: "보정 필요",
  SCENE_CHANGED: "장면 변화 — 배경 다시 학습",
  STALE: "오래됨",
  NONE: "수신 없음",
});
// Fleet 이 마지막 검출을 거절한 이유(tracking.py last_error). 성공하면 Fleet 이 지운다.
const ERROR_TEXT = Object.freeze({
  CALIBRATION_MISMATCH: "보정 불일치",
  MAP_MISMATCH: "지도 불일치",
  DETECTION_STALE: "검출 지연(거부)",
  DETECTION_FUTURE: "검출 시각 오류(거부)",
  DETECTION_OUT_OF_ORDER: "검출 순서 오류(거부)",
});

const finite = (value) => typeof value === "number" && Number.isFinite(value);

// A current marker measurement wins over the inferred position for that robot.
// Only the one-second server lease counts; delayed display ghosts never block fallback.
export function preferMarkers(tracking, sightings) {
  const measured = new Set((sightings || []).filter(row => row.state === "fresh"
    && finite(row.age_ms) && row.age_ms <= 1000 && finite(row.x) && finite(row.y))
    .map(row => row.robot_id));
  return { ...tracking, robots: tracking.robots.filter(row => !measured.has(row.robotId)) };
}

// GET /api/fleet/tracking → 그릴 것만. MATCHED 만 고리·선을 그리고, 형식이 틀린 행은 버린다.
// 응답이 없으면 빈 층이다 — 지난 값을 남기지 않는다.
export function classifyTracking(body) {
  const robots = [];
  for (const row of body?.robots || []) {
    if (!row || typeof row.robot_id !== "string" || !["MATCHED", "MARKER"].includes(row.status)) continue;
    const camera = row.camera;
    const pose = row.pose;
    if (!camera || ![camera.x, camera.y].every(finite)) continue;
    if (row.status === "MATCHED" && (!pose || ![pose.x, pose.y, row.offset_m].every(finite))) continue;
    robots.push({
      robotId: row.robot_id,
      camera: { x: camera.x, y: camera.y },
      pose: pose && finite(pose.x) && finite(pose.y) ? { x: pose.x, y: pose.y } : null,
      ...(row.status === "MARKER" ? { measured: true } : {}),
      offsetM: row.offset_m,
      warn: row.offset_m > OFFSET_WARN_M,
      verified: row.pose_frame_verified === true,
    });
  }
  const unknown = [];
  for (const item of body?.unknown || []) {
    if (!item || !finite(item.x) || !finite(item.y)) continue;
    // D-575: a seen marker no robot is assigned to keeps its id on the map.
    unknown.push({ x: item.x, y: item.y, ...(Number.isInteger(item.marker_id) ? { markerId: item.marker_id } : {}) });
  }
  robots.sort((a, b) => a.robotId.localeCompare(b.robotId));
  return { robots, unknown };
}

// 상태줄: source 마다 한 조각. Fleet 409(보정·지도 불일치, 검출 거부)가 검출기 상태보다 먼저다.
export function trackingStatusLine(body) {
  const sources = Array.isArray(body?.sources) ? body.sources : [];
  if (!sources.length) return { state: "none", text: "관제 카메라 추적 소스 없음" };
  let state = "ok";
  const parts = sources.map((source) => {
    const error = ERROR_TEXT[source.last_error];
    const label = error || TRACKING_STATUS_TEXT[source.status] || `알 수 없음(${source.status})`;
    if (error || source.status !== "OK") state = "warn";
    const fps = !error && source.status === "OK" && finite(source.fps) ? ` · ${source.fps.toFixed(1)} fps` : "";
    return `${source.source_id} ${label}${fps}`;
  });
  const unverified = (body.robots || [])
    .filter((row) => row?.status === "MATCHED" && row.pose_frame_verified !== true).length;
  const note = unverified ? ` · 위치 상태 미보고 ${unverified}대` : "";
  return { state, text: `관제 카메라 추적: ${parts.join(" / ")}${note}` };
}

export function offsetLabel(row) {
  if (row.measured && !row.pose) return row.robotId;
  return `${row.robotId} · 차이 ${Math.round(row.offsetM * 100)} cm`;
}

// 조감도 카메라 교정 낡음(카메라를 재조준한 뒤 D-457 추적 보정이 어긋난 경우). 한 폴링의
// 큰 차이(offset_m)만으로 낡은 게 아니다 — 움직이는 로봇의 관측 지연도 크다. 정지한 로봇
// (직전 폴링 자세 이동 ≤ STILL_POSE_M)에서 잰 차이가 CALIBRATION_DRIFT_POLLS 폴링 연속
// 한계를 넘어야 낡음이다. 마커 관측(measured)은 보정과 무관한 절대 위치라 세지 않는다.
export const CALIBRATION_DRIFT_M = 0.4;
export const CALIBRATION_DRIFT_POLLS = 3;
export const STILL_POSE_M = 0.05;

// tracking-view 가 폴링마다 한 번 부른다. previousPoses는 직전 rememberTrackingPoses 결과.
// 잴 수 있는 정지 로봇이 없으면 null(낡음 판정의 연속을 끊는다 — 오탐 방지).
export function trackingDriftSample(tracking, previousPoses) {
  let worst = null;
  for (const row of tracking?.robots || []) {
    if (!row.pose || row.measured) continue;
    const previous = previousPoses?.get?.(row.robotId);
    if (!previous || !finite(previous.x) || !finite(previous.y)) continue;
    const moved = Math.hypot(row.pose.x - previous.x, row.pose.y - previous.y);
    if (moved > STILL_POSE_M) continue;
    if (!worst || row.offsetM > worst.distanceM) worst = { robotId: row.robotId, distanceM: row.offsetM };
  }
  return worst;
}

// history: 폴링별 trackingDriftSample 결과(null 허용). 최근 POLLS 표본이 모두 있고 모두
// 한계를 넘어야 낡음이다. null이 하나라도 끼면 연속이 아니므로 낡지 않다.
export function calibrationDriftVerdict(history) {
  const recent = (history || []).slice(-CALIBRATION_DRIFT_POLLS);
  if (recent.length < CALIBRATION_DRIFT_POLLS || recent.some((row) => !row)) return null;
  if (!recent.every((row) => row.distanceM > CALIBRATION_DRIFT_M)) return null;
  return recent.reduce((worst, row) => (!worst || row.distanceM > worst.distanceM ? row : worst));
}

// 서버 자동 검사(Fleet 추적 보정 감시): 로봇 관측 없이 승인 교정과 새 맞춤 제안을 주기
// 비교한 서버 판정이 출처 상태에 실린다. 여러 출처가 낡았으면 가장 많이 어긋난 것 하나.
export function serverCalibrationDrift(sources) {
  let worst = null;
  for (const source of sources || []) {
    const drift = source?.calibration_drift;
    if (!drift || drift.state !== "stale" || !finite(drift.max_move_m)) continue;
    if (!worst || drift.max_move_m > worst.maxMoveM) {
      worst = { sourceId: source.source_id, maxMoveM: drift.max_move_m,
        rotationDeg: finite(drift.rotation_deg) ? drift.rotation_deg : null };
    }
  }
  return worst;
}

// 조감도가 쓸 최종 판정: 로봇 표본 판정(정지 로봇 차이)이 살아 있으면 그것이 먼저다 —
// 로봇이 카메라에 안 보이면(관측 0/0대) 표본 판정은 null이고 서버 판정으로 그린다.
export function effectiveDriftVerdict(robotVerdict, sources) {
  if (robotVerdict) {
    return { origin: "robots", robotId: robotVerdict.robotId, distanceM: robotVerdict.distanceM };
  }
  const server = serverCalibrationDrift(sources);
  return server
    ? { origin: "server", sourceId: server.sourceId, distanceM: server.maxMoveM,
        rotationDeg: server.rotationDeg }
    : null;
}

// 다음 폴링의 정지 판정 재료 — 이번 표본의 MATCHED 자세를 robotId 별로 남긴다.
export function rememberTrackingPoses(tracking) {
  const poses = new Map();
  for (const row of tracking?.robots || []) {
    if (row.pose) poses.set(row.robotId, { x: row.pose.x, y: row.pose.y });
  }
  return poses;
}

// Display resolution is a centimetre; it is not a measured accuracy claim.
export function positionRows(tracking) {
  return [...tracking.robots.map(row => ({ name: row.robotId, x: row.camera.x.toFixed(2),
    y: row.camera.y.toFixed(2), basis: row.measured ? "마커 관측" : "무마커 추론" })),
  ...tracking.unknown.map((row, index) => ({
    name: row.markerId === undefined ? `미확인 ${index + 1}` : `ArUco ${row.markerId}`, x: row.x.toFixed(2),
    y: row.y.toFixed(2), basis: row.markerId === undefined ? "무마커 추론 · 이름 미확정" : "마커 관측 · 미등록" }))];
}

export function displayLeaseMs(body, elapsedMs = 0) {
  const lease = finite(body?.lease_s) ? Math.min(1000, Math.max(0, body.lease_s * 1000)) : 1000;
  const ages = (body?.sources || []).filter(row => row.status === "OK")
    .map(row => finite(row.age_ms) ? Math.max(0, row.age_ms) : 0);
  return Math.max(0, lease - Math.max(0, ...ages) - elapsedMs);
}
