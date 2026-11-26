// World 2D map rules shared with the Fleet maps (D-513 7 view turn, place text, N and scale marks).
// Fleet keeps its copies in /console/assets, which World cannot load; keep these rules in step with
// applications/fleet/web/shared/site-map-model.js (viewTurnOf) and map/map-view.js (drawNdOverlay).

const VIEW_TURNS = [0, 90, 180, 270];
export const viewTurnOf = (map) => VIEW_TURNS.includes(map?.view_turn_deg) ? map.view_turn_deg : 0;

// sitemap/site-map.js rule: the name, then the ID when it differs; the ID alone without a name.
export function placeText(place) {
  const name = typeof place?.name === "string" ? place.name.trim() : "";
  return name && name !== place.id ? `${name} (${place.id})` : place.id;
}

// Fleet drawNdOverlay steps (0.5 / 1 / 2 m) first; smaller steps only when the map is too zoomed in for
// them (World fits small active maps). No bar shorter than 24 px.
export function scaleBar(pxPerM, maxPx = Infinity) {
  if (!Number.isFinite(pxPerM) || pxPerM <= 0) return null;
  let stepM = pxPerM * 0.5 >= 40 ? 0.5 : pxPerM >= 28 ? 1 : 2;
  if (stepM * pxPerM > maxPx) stepM = [1, 0.5, 0.2, 0.1, 0.05, 0.02, 0.01].find((s) => s * pxPerM <= maxPx) ?? 0;
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

// Evidence line under a map: "지도 vN · 수신 HH:MM:SS · 출처" (concept.md 근거 줄).
export function mapEvidence({ version, timeLabel, time, source }, now = Date.now()) {
  const shown = stamp(time, now);
  return {
    text: `지도 v${version ?? "?"} · ${timeLabel} ${shown.text} · ${source}`,
    title: shown.title && `${timeLabel} ${shown.title}`,
  };
}

// Server-judged SIM freshness (serve.py age_ms / fresh_for_ms); no browser clock math. Callers charge the
// request time to fresh_for_ms (active-site-map.js way).
export function simFreshness(sample) {
  if (!Number.isSafeInteger(sample?.age_ms) || !Number.isSafeInteger(sample?.fresh_for_ms) || sample.fresh_for_ms < 0) {
    return null;
  }
  return { state: sample.fresh_for_ms > 0 ? "fresh" : "delayed", ageS: Math.round(Math.abs(sample.age_ms) / 1000) };
}
