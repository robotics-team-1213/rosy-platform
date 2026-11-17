/**
 * C12 status table: one state -> one tag (icon + tone). Icons come from ui.js actionIcon (D-926 concept, principle 1 and 5).
 *
 *   statusTag(state, text?, {icon, danger}?) -> <ui-tag>
 *     state  "fresh" | "progress" | "delayed" | "disconnected" | "unknown" | "caution" | "danger" | "locked"
 *     text   visible wording; defaults to the shared evidence wording (EVIDENCE_LABEL) or the table's own word
 *     icon   override of the table icon (danger may use "estop"); never for fresh
 *     danger disconnected only: true raises the tag to the crit fill (a real operating risk, 2026-11-14 decision)
 *
 *   fresh shows no icon (a calm normal). unknown is a dashed outline with a minus. Only danger (and a disconnect the
 *   caller raises) is filled with the crit colour, and only the tag, never the card (D-202). The text always stays.
 */
import {actionIcon} from "./ui.js";
import {EVIDENCE_LABEL} from "./core_ui_logic.js";

export const STATUS_TAGS = Object.freeze({
  fresh: {status: "neutral", icon: null, text: EVIDENCE_LABEL.fresh},
  progress: {status: "active", icon: null, text: "진행 중"},
  delayed: {status: "warn", icon: "history", text: EVIDENCE_LABEL.delayed},
  disconnected: {status: "warn", icon: "wifi", text: EVIDENCE_LABEL.disconnected},
  unknown: {status: "neutral", icon: "minus", text: EVIDENCE_LABEL.unavailable},
  caution: {status: "warn", icon: "warn", text: "주의"},
  danger: {status: "crit", icon: "safety", text: "위험"},
  locked: {status: "neutral", icon: "lock", text: "잠김"},
});

export function statusTag(state, text, {icon, danger = false} = {}) {
  const row = STATUS_TAGS[state];
  if (!row) throw new RangeError(`Unknown status tag state: ${state}`);
  const tag = document.createElement("ui-tag");
  tag.setAttribute("status", state === "disconnected" && danger ? "crit" : row.status);
  tag.dataset.state = state;
  tag.textContent = text ?? row.text;
  const name = icon ?? row.icon;
  if (name) actionIcon(tag, name);
  return tag;
}
