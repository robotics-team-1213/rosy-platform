// D-960 §4 · D-974 — one rule for what this control-unit screen shows. The server's fleet.scope says what the
// instance owns (통합관제 R, a cell, or a standalone Fleet). A block tagged data-unit-scope="drive|arms|children|
// enrollment" stays out of the screen of a unit that does not own it: another unit's screen owns that job.
// The stop controls are never tagged; every unit keeps its E-stop. No scope (an older server) shows everything.
const KEYS = ["drive", "arms", "children", "enrollment"];
const ROLE = {root: "통합관제", cell: "셀 관제", standalone: "단독 관제"};
let current = null;

export function unitScope() { return current; }

// True when the unit owns the job; unknown scope keeps today's screen.
export function owns(need, scope = current) { return !scope || scope[need] === true; }

export function scopeSummary(scope) {
  if (!scope) return "";
  const jobs = [scope.drive && "주행 로봇", scope.arms && "팔 셀", scope.children && "하위 관제"].filter(Boolean);
  return (ROLE[scope.role] || "관제") + " · 맡은 일: " + (jobs.join(", ") || "없음");
}

// Flags on <html> so blocks a view mounts later follow the same CSS rule (fleet-header.css).
export function applyUnitScope(scope, root = globalThis.document?.documentElement) {
  current = scope && typeof scope === "object" ? scope : null;
  if (!root) return;
  root.toggleAttribute("data-unit-scope-ready", current !== null);
  for (const key of KEYS) root.toggleAttribute("data-unit-" + key, owns(key));
}
