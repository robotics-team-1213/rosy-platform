/**
 * A3/A4 sample-data contract: how a screen treats data that is not real. The gallery and the Fleet dev sample (`arm_ai`
 * scenario) both follow it; the screen adoption (B1-B5) reads this, never a private copy.
 *
 *   SAMPLE_LABEL           "샘플 데이터": the words that appear on screen at the head of every area that shows sample rows
 *   sampleTag() -> <ui-tag status="neutral" data-sample>   the on-screen tag; a test asserts it exists wherever a row has sample: true
 *   isSample(row) -> boolean                                 row.sample === true (anything else is real data, never inferred)
 *   armAiCaseProblems(item) -> string[]                      [] when `item` serves the arm_ai case shape:
 *     {id, sample: true, title, lifecycle, requested_by, evidence: [{label, value, source, ageS?, staleAfterS?}],
 *      candidates: [{id, label, reason}],  and the optional skillState inputs: executor, policyId, version, step {n, of},
 *      guard, measured, ageS, leaseS, blocking, cause (one line for measured_failure/stopped/timed_out)}
 *   approval_attempt {by, result: "refused"|"accepted", reason}: optional. The proposer never approves their own proposal
 *   (AI and Assistant included): by === requested_by with result "accepted" is a problem; a refused self-approval is the sample for the locked button.
 *   Rules the checker enforces: lifecycle is one of the nine SKILL_LIFECYCLES; evidence source is ledger|measured|model;
 *   measured_success names its measurement; a candidate is an id, a label and a reason: no coordinates, joints or executor
 *   choice anywhere in the case (the model never picks a pose or an executor, D-228, D-516 1).
 */
import {SKILL_LIFECYCLES, EXECUTOR_LABEL} from "./skill-state.js";

export const SAMPLE_LABEL = "샘플 데이터";
export const isSample = row => row?.sample === true;

export function sampleTag() {
  const tag = document.createElement("ui-tag");
  tag.setAttribute("status", "neutral");
  tag.dataset.sample = "";
  tag.textContent = SAMPLE_LABEL;
  return tag;
}

const SOURCES = ["ledger", "measured", "model"];
const FORBIDDEN_KEY = /^(x|y|z|yaw|xyz|pose|joint|joints|angles|position|coordinates|target|waypoints|cmd_vel|goal)$/i;

function forbiddenKeys(value, path, out) {
  if (Array.isArray(value)) value.forEach((item, i) => forbiddenKeys(item, `${path}[${i}]`, out));
  else if (value && typeof value === "object") {
    for (const [key, child] of Object.entries(value)) {
      if (FORBIDDEN_KEY.test(key)) out.push(`${path}.${key}: coordinates, joints and targets are not part of the case`);
      forbiddenKeys(child, `${path}.${key}`, out);
    }
  }
}

export function armAiCaseProblems(item) {
  const out = [];
  if (!item || typeof item !== "object") return ["not an object"];
  if (item.sample !== true) out.push("sample must be true");
  for (const key of ["id", "title", "requested_by"]) if (typeof item[key] !== "string" || !item[key]) out.push(`${key} must be a non-empty string`);
  if (!SKILL_LIFECYCLES.includes(item.lifecycle)) out.push(`lifecycle ${item.lifecycle} is not one of ${SKILL_LIFECYCLES.join(", ")}`);
  if (item.executor !== undefined && !Object.hasOwn(EXECUTOR_LABEL, item.executor)) out.push(`executor ${item.executor} is unknown`);
  if (item.lifecycle === "measured_success" && !item.measured) out.push("measured_success needs the measurement source");
  if (!Array.isArray(item.evidence)) out.push("evidence must be a list");
  else item.evidence.forEach((entry, i) => { if (!SOURCES.includes(entry?.source)) out.push(`evidence[${i}].source must be ${SOURCES.join("|")}`); });
  if (!Array.isArray(item.candidates)) out.push("candidates must be a list");
  else item.candidates.forEach((entry, i) => { for (const key of ["id", "label", "reason"]) if (typeof entry?.[key] !== "string") out.push(`candidates[${i}].${key} must be a string`); });
  const tried = item.approval_attempt;
  if (tried && (typeof tried.by !== "string" || !tried.by)) out.push("approval_attempt.by must be a name");
  else if (tried && (tried.by === item.requested_by || tried.by === item.proposed_by) && tried.result !== "refused") out.push("the proposer cannot approve their own proposal");
  if (tried && !["refused", "accepted"].includes(tried.result)) out.push("approval_attempt.result must be refused|accepted");
  forbiddenKeys(item, "case", out);
  return out;
}
