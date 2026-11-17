import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const root = new URL("../../../../applications/fleet/web/", import.meta.url);
const html = readFileSync(new URL("index.html", root), "utf8");
const roster = readFileSync(new URL("robot/roster.js", root), "utf8");
const consoleJs = readFileSync(new URL("console.js", root), "utf8");
// D-798 3.2: the site-path paint and the /healthz read live in console-refresh.js.
const refreshJs = readFileSync(new URL("console-refresh.js", root), "utf8");
const vision = readFileSync(new URL("shared/vision-view.js", root), "utf8");

test("the site path block sits in the roster panel while C14 #roster moves to work-overview", () => {
  const rosterIdx = html.indexOf('aria-labelledby="roster-heading"');
  const panel = html.slice(rosterIdx, html.indexOf('aria-labelledby="vision-heading"'));
  const pathAt = panel.indexOf('id="site-path"');
  const workAt = html.indexOf('id="work-overview"');
  const listAt = html.indexOf('id="roster"');
  assert.ok(pathAt > 0);
  assert.ok(workAt > 0 && listAt > workAt && listAt < rosterIdx);
  assert.equal(html.includes("/api/v1/host/network"), false);
});

test("the page reads link and the calls it already makes", () => {
  assert.match(roster, /linkTag/);
  assert.match(refreshJs, /\/healthz/);
  assert.match(refreshJs, /proxyRow|site-path/);
  assert.match(consoleJs, /createConsoleRefresh\(/);
  assert.match(vision, /onSources/);
  // call() already names this path once so a camera-preview 401 does not lock the page.
  // A second poll in the shell or its refresh module would make the split length 3.
  assert.equal((consoleJs + refreshJs).split("/api/fleet/vision/sources").length, 2);
});
