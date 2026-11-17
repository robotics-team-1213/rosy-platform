/**
 * C21 evidence line: the one line under a proposal or skill that says what the claim rests on, with the source of each
 * piece named in words (plan 2026-11-14-rosy-vla-decision-ai-command.md 6.4). A model's own value never looks like a measurement.
 *
 *   createEvidenceLine(items, {now}?) -> <p class="evidence-line">
 *     items  [{label, value, source, observedAt?, ageS?, staleAfterS?}]
 *       source  "ledger" -> 원장, "measured" -> 측정, "model" -> `모델 자체 값 ... (측정 아님)`;
 *               a missing or unknown source reads `출처 정보 없음`, never 측정 (D-280)
 *       value   missing -> 정보 없음 and the line gets an `unknown` tag
 *       ageS    server-given age in seconds; else observedAt (ms or ISO) against `now` (default Date.now())
 *       staleAfterS  older than this -> `지연 · N초 전` tag; a fresh age is plain text, so a calm line has no tag
 *   Order: ledger, then measured, then model, then unknown source (stable inside a group). Each item is
 *   <span data-source=...><b>출처</b> label value</span>; the line carries one tag per problem kind (delayed, unknown), never one per item.
 *
 * Freshness (fresh/delayed/unknown) and severity are different axes: this line owns freshness only. Styles: component-controls.css.
 */
import {EVIDENCE_LABEL, evidenceAgeText} from "./core_ui_logic.js";
import {statusTag} from "./status-tag.js";

const SOURCE = Object.freeze({ledger: {rank: 0, label: "원장"}, measured: {rank: 1, label: "측정"}, model: {rank: 2, label: "모델 자체 값"}});
const NO_SOURCE = Object.freeze({rank: 3, label: `출처 ${EVIDENCE_LABEL.unavailable}`});
const blank = value => value === undefined || value === null || value === "";

function ageOf(item, now) {
  if (typeof item.ageS === "number" && Number.isFinite(item.ageS)) return item.ageS;
  const at = typeof item.observedAt === "number" ? item.observedAt : Date.parse(item.observedAt ?? "");
  return Number.isFinite(at) ? Math.max(0, Math.round((now - at) / 1000)) : null;
}

export function createEvidenceLine(items = [], {now = Date.now()} = {}) {
  const line = document.createElement("p");
  line.className = "evidence-line";
  const ordered = items.map((item, index) => ({item, index, source: (Object.hasOwn(SOURCE, item.source) ? SOURCE[item.source] : NO_SOURCE)}))
    .sort((a, b) => a.source.rank - b.source.rank || a.index - b.index);
  let delayed = null, unknown = false;
  for (const {item, source} of ordered) {
    const span = document.createElement("span");
    span.dataset.source = Object.hasOwn(SOURCE, item.source) ? item.source : "unknown";
    const name = document.createElement("b");
    name.textContent = source.label;
    const missing = blank(item.value);
    unknown ||= missing;
    const age = ageOf(item, now);
    const stale = age !== null && typeof item.staleAfterS === "number" && age > item.staleAfterS;
    if (stale && (delayed === null || age > delayed)) delayed = age; // the tag names the oldest stale item
    span.append(name, ` ${item.label ?? ""} ${missing ? EVIDENCE_LABEL.unavailable : item.value}${source === SOURCE.model ? "(측정 아님)" : ""}${age === null ? "" : evidenceAgeText(age)}`);
    line.append(span);
  }
  if (!ordered.length) { unknown = true; line.append(EVIDENCE_LABEL.unavailable); }
  if (delayed !== null) line.append(statusTag("delayed", `${EVIDENCE_LABEL.delayed}${evidenceAgeText(delayed)}`));
  if (unknown) line.append(statusTag("unknown"));
  return line;
}
