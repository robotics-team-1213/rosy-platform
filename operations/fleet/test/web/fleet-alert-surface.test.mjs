import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

// 11-18 Fleet 알림 한 곳(r-A §6 정적 게이트): 알림은 .queues-panel 하나, 토스트는 alert-popup 하나.
const web = new URL("../../../../applications/fleet/web/", import.meta.url);
const read = (name) => readFileSync(new URL(name, web), "utf8");

test("the console has no bell popover, no '알림' tab and no read state", () => {
  const html = read("index.html"), inbox = read("inbox.js");
  assert.doesNotMatch(html, /inbox-popover|context-inbox/);
  assert.doesNotMatch(inbox, /label: "알림"|unread|markAllRead/);
  assert.match(inbox, /#critical-list > li\[data-key\], #warning-list > li\[data-key\]/);  // bell = open queue rows
  assert.doesNotMatch(read("shared/alert-popup.css"), /inbox-popover/);
  assert.doesNotMatch(read("shared/fleet-header.js"), /inbox=1|읽음/);
});

test("polite live regions on the console are only the link word and the AI dialogue", () => {
  const live = [...read("index.html").matchAll(/<[^>]*\baria-live="polite"[^>]*>/g)]
    .map(([tag]) => tag.match(/\bid="([^"]+)"/)?.[1]);
  assert.deepEqual(live.sort(), ["assistant-messages", "link-state"]);
});

test("modules that show a command result in their row never raise a toast for it", () => {
  for (const name of ["line-stuck.js", "person-request.js", "station-recovery.js", "trip-replan.js"]) {
    const text = read(name);
    assert.match(text, /inline: true, method: "POST"/, name);
    assert.match(text, /\{ inline: true \}\);/, name);
  }
});
