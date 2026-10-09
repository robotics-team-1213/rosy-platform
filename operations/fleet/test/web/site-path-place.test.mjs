import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const root = new URL("../../fleet/server/web/", import.meta.url);
const html = readFileSync(new URL("index.html", root), "utf8");
const roster = readFileSync(new URL("roster.js", root), "utf8");
const consoleJs = readFileSync(new URL("console.js", root), "utf8");
const vision = readFileSync(new URL("shared/vision-view.js", root), "utf8");

test("the site path block sits in the roster panel above the robot list", () => {
  const panel = html.slice(html.indexOf('aria-labelledby="roster-heading"'), html.indexOf('aria-labelledby="vision-heading"'));
  const pathAt = panel.indexOf('id="site-path"');
  const listAt = panel.indexOf('id="roster"');
  assert.ok(pathAt > 0 && pathAt < listAt);
  assert.equal(html.includes("/api/v1/host/network"), false);
});

test("the page reads link and the calls it already makes", () => {
  assert.match(roster, /linkTag/);
  assert.match(consoleJs, /\/healthz/);
  assert.match(consoleJs, /proxyRow|site-path/);
  assert.match(vision, /onSources/);
  // call() already names this path once so a camera-preview 401 does not lock the page.
  // A second poll in this file would make the split length 3.
  assert.equal(consoleJs.split("/api/fleet/vision/sources").length, 2);
});
