import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";

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

// 11-18 UI 패널 게이트 ①: console.js가 주입하는 call()의 변경 호출(POST·PUT·PATCH·DELETE)은 inline을 명시한다
// (true = 결과를 행 안에 씀, false = 토스트가 맞음). 명시하지 않은 호출 수는 늘면 실패, 줄면 상한을 같이 내린다.
const UNMARKED_CHANGE_CALLS = 30;
const assets = JSON.parse(read("assets.json")).assets;

function consoleModules() {
  const seen = new Set(), queue = ["console.js"];
  while (queue.length) {
    const name = queue.shift();
    if (seen.has(name)) continue;
    seen.add(name);
    // The browser sees every module flat under /console/assets/, so "./x.js" and "/console/assets/x.js" are both x.js.
    for (const [, spec] of read(name).matchAll(/(?:from|import)\s*\(?\s*["']([^"']+\.js)["']/g)) {
      if (spec.startsWith("/console/assets/") || spec.startsWith(".")) queue.push(assets[spec.slice(spec.lastIndexOf("/") + 1)]?.path);
    }
  }
  return [...seen].filter(Boolean);
}

export function unmarkedChangeCalls(name, text) {
  if (/\b(?:function\s+call\s*\(|(?:const|let)\s+call\s*=)/.test(text)) return [];  // its own request, not console's call()
  const lines = text.split("\n");
  return lines.flatMap((line, i) => {
    if (!/(?<![.\w$])call\(/.test(line)) return [];
    const rest = lines.slice(i, i + 4).join(" ");
    const close = rest.indexOf("})");
    const head = close < 0 ? rest : rest.slice(0, close + 2);  // this call's options only, not the next call's
    return /method: "(POST|PUT|PATCH|DELETE)"/.test(head) && !/\binline:/.test(head) ? [`${name}:${i + 1}`] : [];
  });
}

test("console change calls say whether their result is inline; the unmarked count only goes down", () => {
  const modules = consoleModules();
  assert.ok(modules.includes("work/work-view.js") && modules.includes("robot/roster.js"), modules.join(" "));
  const found = modules.flatMap((name) => unmarkedChangeCalls(name, read(name)));
  assert.ok(found.length <= UNMARKED_CHANGE_CALLS, `${found.length} > ${UNMARKED_CHANGE_CALLS}: mark inline: true|false — ${found.slice(-10).join(" ")}`);
  assert.equal(found.length, UNMARKED_CHANGE_CALLS, `fell to ${found.length}; lower UNMARKED_CHANGE_CALLS to ${found.length}`);
  assert.deepEqual(unmarkedChangeCalls("x.js", 'await call("/a", {method: "POST", body: "{}"});\nawait call("/b", {inline: true, method: "POST"});\nself.call(1, {method: "POST"});'), ["x.js:1"]);
  assert.deepEqual(unmarkedChangeCalls("y.js", 'const call = () => 1;\ncall("/a", {method: "POST"});'), []);
});

test("no request object hides headers or body behind a comment anywhere in the Fleet web", () => {
  const files = readdirSync(web, { recursive: true }).filter((f) => String(f).endsWith(".js")).map((f) => String(f).replaceAll("\\", "/"));
  const hits = files.flatMap((name) => read(name).split("\n").flatMap((line, i) => /(^|[^:])\/\/[^\n]*\b(headers|body):/.test(line) ? [`${name}:${i + 1}`] : []));
  assert.deepEqual(hits, []);
});
