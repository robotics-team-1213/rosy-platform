// Package B UI contracts that need no DOM: the jump slot lives outside the scrolling body,
// manual control keeps its aria names and the external-reason opt-in, and the shared opt-in
// rule + policy link wiring exist. Source-level checks like g6-phrases.test.mjs.
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const ROOT = new URL("../../../../", import.meta.url);
const read = (path) => readFileSync(new URL(path, ROOT), "utf8");

test("robot-panel keeps the jumps nav in a fixed slot between head and body, cleaned up on close", () => {
  const source = read("applications/fleet/web/shared/robot-panel.js");
  assert.match(source, /root\.insertBefore\(jumpsNav, body\)/);
  assert.doesNotMatch(source, /body\.prepend\(jumpsNav\)/);
  assert.doesNotMatch(source, /startOffset/);
  // setRobot(null)와 로봇 교체(sameId 아님) 경로 모두 몸통 밖의 nav를 DOM에서 지운다.
  const removals = source.match(/jumpsNav\?\.remove\(\);/g) ?? [];
  assert.ok(removals.length >= 2, `expected the nav removal in both reset paths, got ${removals.length}`);
});

test("robot-panel mounts common kind tag, persistent place bar, and onCameraCollapse cleanly", () => {
  const source = read("applications/fleet/web/shared/robot-panel.js");
  assert.match(source, /className\s*=\s*"robot-panel-kind"/);
  assert.match(source, /className\s*=\s*"robot-panel-place"/);
  assert.match(source, /className\s*=\s*"robot-panel-place-label"/);
  assert.match(source, /className\s*=\s*"robot-panel-place-text"/);
  assert.match(source, /className\s*=\s*"robot-panel-locate"/);
  assert.match(source, /root\.append\(head,\s*placeBar,\s*body,\s*foot\)/);
  assert.match(source, /onCameraCollapse\?\.\(\)/);
  assert.doesNotMatch(source, /setAttribute\(\s*["']reason["']/);
});

test("roster.css renders the jumps slot as a fixed non-scrolling row with a clean bottom border", () => {
  const css = read("applications/fleet/web/shared/roster.css");
  const block = css.match(/\.robot-panel-jumps \{[^}]*\}/)?.[0] ?? "";
  assert.match(block, /flex: none/);
  assert.match(block, /border-block-end/);
  assert.doesNotMatch(block, /position: sticky|z-index/);
});

test("components.css ships the opt-in external-reason rule without touching the C1 reason contract", () => {
  const css = read("shared/web/components.css");
  const block = css.match(/\[data-reason-display="external"\] ui-button\[reason\] > small\[data-reason\] \{[^}]*\}/)?.[0] ?? "";
  assert.match(block, /position: absolute/);
  assert.match(block, /clip: rect\(0, 0, 0, 0\)/);  // sr-only clip: screen-reader text survives
});

test("manual-control names its buttons and points button reasons at the shared banner only", () => {
  const source = read("applications/fleet/web/manual-control.js");
  assert.match(source, /actions\.dataset\.reasonDisplay = "external"/);
  assert.match(source, /"수동 모드로 전환"/);
  assert.match(source, /"수동 속도 감소"/);
  assert.match(source, /"수동 속도 증가"/);
});

test("work-view polls policy-admission through a gate, pauses requests on 403, and links policy at target height", () => {
  const source = read("applications/fleet/web/work/work-view.js");
  assert.match(source, /createPollGate\(\)/);
  assert.match(source, /policyGate\.fail\(error\.status, error\.code\)/);
  assert.match(source, /policyGate\.reset\(\)/);
  assert.match(source, /requestsPause\(error\.status\)\) requestsPaused = true/);
  assert.match(source, /requestsPaused\) return/);
  assert.match(source, /className: "ui-action-link"/);
});

test("index.html names the trail range select without touching the topbar", () => {
  const page = read("applications/fleet/web/index.html");
  assert.match(page, /id="trail-range" aria-label="지나온 길 범위"/);
});

test("omx-inspector gives its selects explicit names", () => {
  const source = read("applications/fleet/web/shared/omx-inspector.js");
  assert.match(source, /select\.setAttribute\("aria-label", labelText\)/);
});
