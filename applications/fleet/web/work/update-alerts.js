// D-871: stalled update channels from /api/fleet/updates as console queue rows.
import {HOST_LABEL, unitName} from "/console/assets/host-health.js";

// The console's once-a-minute read (the site guard rewrites its report every few minutes).
export function createUpdateAlertReader(call, view) {
  let readAt = -Infinity;
  return async function refresh(life) {
    if (Date.now() - readAt < 60_000) return;
    readAt = Date.now();
    try {
      const body = await call("/api/fleet/updates", {signals: [life.signal]});
      if (life.current()) view.updateAlerts = updateAlertRows(body);
    } catch {
      // keep the last rows: a failed read is not a resolved stall
    }
  };
}

// /api/fleet/updates stalls as console queue rows: one per PC and channel (stable key), gone when the server stops saying so.
export function updateAlertRows(body) {
  return (body?.hosts || []).flatMap((host) => (host.channels || []).filter((item) => item.alert).map((item) => {
    const {age_s: age, reason} = item.alert;
    const lasted = !Number.isFinite(age) ? "마지막 정상 기록 없음"
      : age < 3600 ? `${Math.floor(age / 60)}분째 정상 단계 없음` : `${Math.floor(age / 3600)}시간째 정상 단계 없음`;
    return {severity: "warn", noGroup: true, robotId: HOST_LABEL[host.host] || host.host,
      key: `update|${host.host}|${item.unit}`,
      text: [`: 자동 갱신 멈춤 — ${unitName(item.unit)}`, lasted, reason].filter(Boolean).join(" · "),
      next: {text: "PC 상태에서 업데이트 단계 확인", href: "/console/maintenance#host-services", linkText: "PC 정비 열기"}};
  }));
}
