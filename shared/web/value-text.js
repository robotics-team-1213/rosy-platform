/**
 * C4 unknown-value text. A missing, empty or non-finite value is never drawn as 0, 100%, 정상 or
 * undefined (D-280): it is EVIDENCE_LABEL.unavailable. The number 0 is a real 0.
 *
 *   valueText(raw, {unit, digits, age, evidence}) -> {text, state}
 *     raw       number | string | null | undefined
 *     unit      suffix such as "%" or " mm", added only to a known value
 *     digits    toFixed digits for a number
 *     age       server-given age in seconds; when set the value is stale: text gets " · N초 전", state "delayed"
 *     evidence  server-judged "fresh" | "delayed" | "disconnected" | "unavailable"; the last two ignore raw
 *   renderValue(el, raw, opts)   sets el.textContent and el.dataset.state from valueText
 */
import { EVIDENCE_LABEL, evidenceAgeText } from "./core_ui_logic.js";

const UNKNOWN = Object.freeze({text: EVIDENCE_LABEL.unavailable, state: "unavailable"});

export function valueText(raw, {unit = "", digits, age, evidence} = {}) {
  if (evidence === "unavailable") return UNKNOWN;
  if (evidence === "disconnected") return {text: EVIDENCE_LABEL.disconnected, state: "disconnected"};
  if (raw === null || raw === undefined || (typeof raw === "string" && !raw.trim())) return UNKNOWN;
  if (typeof raw === "number" && !Number.isFinite(raw)) return UNKNOWN;
  const shown = typeof raw === "number" && Number.isInteger(digits) ? raw.toFixed(digits) : String(raw);
  const aged = evidenceAgeText(age);
  const stale = Boolean(aged) || evidence === "delayed";
  return {text: `${shown}${unit}${aged}`, state: stale ? "delayed" : "fresh"};
}

export function renderValue(el, raw, opts) {
  const {text, state} = valueText(raw, opts);
  el.textContent = text; el.dataset.state = state;
  return {text, state};
}
