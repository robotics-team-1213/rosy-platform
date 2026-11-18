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
    assert.doesNotMatch(text, /\/\/[^\n]*\b(headers|body):/, name);  // 11-18: a trailing comment swallowed the claim body (422)
  }
});

// 11-18 패널: 실패를 자기 행·구획 글자로 쓰는 모듈은 변경 호출마다 inline을 명시한다(토스트와 이중 알림 금지).
test("modules that write a failed change into their own section mark every change call inline", () => {
  for (const name of ["site-rules-judge.js", "robot/step-nudge.js", "work/control-unit-view.js", "work/work-view.js",
    "work/channel-request-view.js", "work/arm-transfer-view.js", "work/cell-resume-view.js",
    "work/integrated-control-view.js", "work/trip-proposal-view.js", "robot/robot-panel-adapters.js"]) {
    const lines = read(name).split("\n");
    lines.forEach((line, i) => {
      if (!/\bcall\(/.test(line)) return;
      const head = lines.slice(i, i + 4).join(" ");
      if (/method: "(POST|PUT|PATCH|DELETE)"/.test(head)) assert.match(head, /inline: true/, `${name}:${i + 1}`);
    });
  }
});

test("site rules judge shows '판정 중' only while it is judging", () => {
  const text = read("site-rules-judge.js");
  assert.match(text, /setOff\(ask, rule\.busy, "판정 중"\)/);
  assert.doesNotMatch(text, /setAttribute\("reason", "판정 중"\)/);
});
