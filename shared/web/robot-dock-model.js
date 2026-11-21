/**
 * C23 robot dock model: pure projection from robotProfile objects into dock entries.
 * No DOM, no import of ui.js: node can test it.
 *
 *   dockEntries(profiles, {kinds, ids}?) -> [{id, kind, short, label, marks}]
 *     profiles   array of robotProfile objects (robot-profile.js)
 *     kinds      optional array of allowed kinds ("mobile" | "arm")
 *     ids        optional array of allowed robot ids
 *     order      mobile first, then arm; each group preserves input order
 *     short      mobile trailing digits (rosy_42 -> "42"); arm last "_" segment uppercased (arm_s -> "S"); fallback whole id
 *     marks      only when abnormal: link ("delayed" | "disconnected" | "unknown"), alarm ("caution" | "danger" | "unknown")
 *     label      accessible name: "${name} ${kindLabel}" + " · ${mark.text}" per mark
 */
import {EVIDENCE_LABEL} from "./core_ui_logic.js";
import {ROBOT_KIND_LABEL} from "./robot-profile.js";

const LINK_MARK_STATE = Object.freeze({
  delayed: "delayed",
  disconnected: "disconnected",
  unavailable: "unknown",
});

function shortId(id, kind) {
  const raw = String(id ?? "");
  if (kind === "mobile") return raw.match(/(\d+)$/)?.[1] || raw;
  if (kind === "arm") {
    const idx = raw.lastIndexOf("_");
    const seg = idx >= 0 ? raw.slice(idx + 1) : "";
    return seg ? seg.toUpperCase() : raw;
  }
  return raw;
}

function marksOf(profile) {
  const marks = [];
  const link = profile.link;
  if (link?.state !== "fresh") {
    marks.push({
      kind: "link",
      state: LINK_MARK_STATE[link?.state] || "unknown",
      text: link?.text || EVIDENCE_LABEL.unavailable,
    });
  }
  if (profile.alarm) {
    marks.push({
      kind: "alarm",
      state: profile.alarm.tag || profile.alarm.level || "unknown",
      text: profile.alarm.text || EVIDENCE_LABEL.unavailable,
    });
  }
  return marks;
}

export function dockEntries(profiles = [], {kinds, ids} = {}) {
  const kindSet = Array.isArray(kinds) ? new Set(kinds) : null;
  const idSet = Array.isArray(ids) ? new Set(ids) : null;
  const filtered = profiles.filter((p) => {
    if (!p) return false;
    if (kindSet && !kindSet.has(p.kind)) return false;
    if (idSet && !idSet.has(p.id)) return false;
    return true;
  });
  const ordered = [
    ...filtered.filter((p) => p.kind === "mobile"),
    ...filtered.filter((p) => p.kind === "arm"),
  ];
  return ordered.map((profile) => {
    const id = String(profile.id ?? "");
    const kind = profile.kind;
    const kindLabel = profile.kindLabel || ROBOT_KIND_LABEL[kind] || "";
    const name = profile.name || id;
    const marks = marksOf(profile);
    const label = [`${name} ${kindLabel}`.trim(), ...marks.map((m) => m.text)].join(" · ");
    return {id, kind, short: shortId(id, kind), label, marks};
  });
}
