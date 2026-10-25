// Read-only host report interpretation; DOM and control actions stay in host-services.js.
const STATE_LABEL = {
  ok: "정상",
  bad: "나쁨",
  "load-high": "부하 높음",
  unreachable: "응답 없음",
  quiet: "새벽 창",
  error: "확인 실패",
  degraded: "복구 설정 확인 필요",
  unsupported: "하드웨어 미확인·미지원",
  unknown: "미확인",
  missing: "없음",
};

export const HOST_LABEL = {site: "관제 PC", ai: "AI PC", model: "모델 PC"};

export function stateLabel(state) {
  return STATE_LABEL[state] || state || "확인 불가";
}

export function resourceText(resources) {
  if (!resources || typeof resources !== "object") return "여유 수치 없음";
  const parts = [];
  if (Number.isFinite(resources.avail_pct)) parts.push(`메모리 여유 ${resources.avail_pct}%`);
  if (Number.isFinite(resources.swap_pct)) parts.push(`스왑 ${resources.swap_pct}%`);
  if (Number.isFinite(resources.load) && Number.isFinite(resources.cores)) {
    parts.push(`부하 ${resources.load}/${resources.cores}코어`);
  }
  if (Number.isFinite(resources.uptime_s)) parts.push(`가동 ${resources.uptime_s}초`);
  if (Array.isArray(resources.down) && resources.down.length) parts.push(`멈춘 유닛 ${resources.down.join(", ")}`);
  return parts.length ? parts.join(" · ") : "여유 수치 없음";
}

function fresh(report, limit) {
  const age = Date.now() / 1000 - report?.time;
  return Number.isFinite(report?.time) && age >= -60 && age <= limit;
}

export function driftText(drift) {
  if (!drift) return "바라는 상태 확인 불가";
  if (!fresh(drift, 2100)) return "설정 점검 지연 · 마지막 보고를 확인하세요";
  const driftN = (drift.drift || []).length;
  const errorN = (drift.errors || []).length;
  const waitN = (drift.awaiting_approval || []).length;
  if (!driftN && !errorN) {
    return waitN ? `바라는 상태 차이 없음 · 승인 대기 ${waitN}` : "바라는 상태 차이 없음";
  }
  return `바라는 상태 차이 ${driftN} · 오류 ${errorN} · 승인 대기 ${waitN}`;
}

export function gib(value) {
  return Number.isFinite(value) && value >= 0 ? `${(value / 1024 ** 3).toFixed(1)} GiB` : "미확인";
}

export function hostHealth(row) {
  const recovery = row.recovery;
  const current = fresh(row, row.source === "local" ? 2100 : 900);
  const verified = current && fresh(recovery, 2100);
  let label = stateLabel(row.state);
  let healthy = false;
  if (!current) label = row.time ? "점검 지연" : "미확인";
  else if (["unreachable", "quiet", "error"].includes(row.state)) label = stateLabel(row.state);
  else if (!recovery) label = "복구 설정 미확인";
  else if (!verified) label = "점검 지연";
  else if (recovery.state !== "ok" || !["watchdog", "kernel", "ssh", "swap"].every(
    (check) => recovery[check]?.state === "ok")) label = "복구 설정 확인 필요";
  else healthy = row.state === "ok";
  return {current, verified, label, healthy};
}

// D-871 update channels. The same 6 h bound as tools/remote/update_status.py and fleet.host_control.
const UPDATE_STALE_S = 6 * 3600;
const CHANNEL_LABEL = {ok: "정상", off: "꺼짐", stuck: "멈춤", unknown: "미확인"};
const GATE_LABEL = {open: "업데이트 허용", frozen: "업데이트 동결", missing: "동결 관문 없음"};

export function unitName(unit) {
  return String(unit || "").replace(/^rosy-/, "").replace(/(-autoupdate|-update)?\.service$/, "");
}

export function channelState(item, now = Date.now() / 1000) {
  if (item?.state) return item.state;  // /api/fleet/updates already classified it
  if (item?.timer !== "enabled") return "off";
  return Number.isFinite(item?.healthy_at) && now - item.healthy_at <= UPDATE_STALE_S ? "ok" : "stuck";
}

// One line per channel. Reasons (the last step's reason code) only where the caller may see them.
export function updateLines(report, {reasons = false} = {}) {
  if (!report || !Array.isArray(report.updaters ?? report.channels)) return ["업데이트 · 보고 없음"];
  const lines = [`업데이트 · ${GATE_LABEL[report.gate] || "동결 여부 미확인"}`];
  for (const item of report.updaters ?? report.channels) {
    const last = item.last || {};
    const release = item.release ?? last.release;
    const parts = [unitName(item.unit), CHANNEL_LABEL[channelState(item)] || "미확인"];
    if (release) parts.push(release);
    if (reasons && last.step) parts.push(last.reason ? `${last.step} (${last.reason})` : last.step);
    lines.push(parts.join(" · "));
  }
  const stack = report.site_stack;
  if (stack) lines.push(`사이트 스택 · ${stack.current || "미확인"}${reasons && stack.failed ? ` · 실패 기록 ${stack.failed}` : ""}`);
  return lines;
}
