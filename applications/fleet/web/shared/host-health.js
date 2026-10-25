// Read-only host report interpretation; DOM and control actions stay in host-services.js.
const STATE_LABEL = {
  ok: "정상",
  bad: "나쁨",
  "load-high": "부하 높음",
  "disk-low": "디스크 부족",
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
  const disk = resources.disk;
  if (disk && Number.isFinite(disk.test_free_gb) && Number.isFinite(disk.root_free_gb)) {
    parts.push(`시험 디스크 여유 ${disk.test_free_gb}GB(${disk.test_use_pct}%) · 루트 ${disk.root_free_gb}GB(${disk.root_use_pct}%)`);
  }
  const gpu = resources.gpu;
  if (gpu && Number.isFinite(gpu.used_mib) && Number.isFinite(gpu.total_mib)) parts.push(`GPU 메모리 ${gpu.used_mib}/${gpu.total_mib}MiB`);
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
