// 2D 지도 규칙 하나: 화면 방향(D-513 7), 장소 표기, 축척 막대 단위, 근거 줄의 KST 시각·UTC title.
// Fleet 관제·현장 지도와 World 2D 지도가 /common 으로 같이 읽는다(2026-11-26, World 사본 #922 통합).

export const VIEW_TURNS = [0, 90, 180, 270];
export const viewTurnOf = (map) => VIEW_TURNS.includes(map?.view_turn_deg) ? map.view_turn_deg : 0;

// The name, then the ID when it differs; the ID alone without a name.
export function placeText(place) {
  const name = typeof place?.name === "string" ? place.name.trim() : "";
  return name && name !== place.id ? `${name} (${place.id})` : place.id;
}

// Fleet steps (0.5 / 1 / 2 m) first; when that bar overflows maxPx, the largest smaller step that fits
// (World fits small active maps). No bar shorter than 24 px.
export function scaleBar(pxPerM, maxPx = Infinity) {
  if (!Number.isFinite(pxPerM) || pxPerM <= 0) return null;
  let stepM = pxPerM * 0.5 >= 40 ? 0.5 : pxPerM >= 28 ? 1 : 2;
  if (stepM * pxPerM > maxPx) stepM = [1, 0.5, 0.2, 0.1, 0.05].find((s) => s * pxPerM <= maxPx) ?? 0;
  const barPx = stepM * pxPerM;
  return barPx < 24 ? null : { stepM, barPx };
}

const kstParts = new Intl.DateTimeFormat("en-GB", {
  timeZone: "Asia/Seoul", hourCycle: "h23", month: "2-digit", day: "2-digit",
  hour: "2-digit", minute: "2-digit", second: "2-digit",
});
const timestamp = (value) => new Date(typeof value === "number" ? value * 1000 : value);

// Screen time is KST HH:MM:SS (MM-DD first when not today); the UTC original goes to title.
export function stamp(value, now = Date.now()) {
  const at = timestamp(value);
  if ((!Number.isFinite(value) && typeof value !== "string") || !Number.isFinite(at.getTime())) {
    return { text: "확인되지 않음", title: "" };
  }
  const part = (date) => Object.fromEntries(kstParts.formatToParts(date).map(({ type, value: v }) => [type, v]));
  const shown = part(at);
  const today = part(new Date(now));
  const clock = `${shown.hour}:${shown.minute}:${shown.second}`;
  const sameDay = shown.month === today.month && shown.day === today.day;
  return { text: sameDay ? clock : `${shown.month}-${shown.day} ${clock}`, title: `${at.toISOString()} (UTC)` };
}

// Evidence line under a map: "지도 vN · 수신 HH:MM:SS · 출처" (concept.md 근거 줄); the UTC original goes to title.
export function mapEvidence({ version, timeLabel, time, source }, now = Date.now()) {
  const shown = stamp(time, now);
  return {
    text: `지도 v${version ?? "?"} · ${timeLabel} ${shown.text} · ${source}`,
    title: shown.title && `${timeLabel} ${shown.title}`,
  };
}
