import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import { linkTag } from "../../../../applications/fleet/web/link-tag.js";

test("only a problem link produces a tag", () => {
  assert.equal(linkTag("up"), null);
  assert.equal(linkTag(undefined), null);
  assert.equal(linkTag("other"), null);
  assert.equal(linkTag("unreachable").word, "닿지 않음");
  assert.equal(linkTag("moved").word, "주소 이동");
  assert.equal(linkTag("moved").next, null);
  assert.equal(linkTag("tls-refused").word, "인증 거부");
  assert.equal(linkTag("tls-refused").focus, "console-token");
  assert.equal(linkTag("protocol").word, "프로토콜");
  assert.match(linkTag("protocol").text, /등록된 base URL/);
  assert.equal(linkTag("protocol").focus, null);
  assert.equal(linkTag("degraded").word, "응답 지연");
  assert.equal(linkTag("degraded").kind, "warn");
});

test("new link files do not name transport exceptions", () => {
  const web = new URL("../../../../applications/fleet/web/", import.meta.url);
  for (const name of ["link-tag.js", "site-path.js"]) {
    const text = readFileSync(new URL(name, web), "utf8");
    for (const banned of ["RemoteProtocolError", "ConnectError", "RobotApiError", "SSLError"]) {
      assert.equal(text.includes(banned), false, `${name} names ${banned}`);
    }
  }
});

test("D-550 8: only an unbounded verdict produces the Rule M mark, with its reason in words", async () => {
  const { ruleMTag } = await import("../../../../applications/fleet/web/link-tag.js");
  for (const rule of [undefined, null, {}, { state: "idle" }, { state: "bounded", motion: "goal" }]) {
    assert.equal(ruleMTag(rule), null);
  }
  const mark = ruleMTag({ state: "unbounded", motion: "lane_trip", reason: "hold_back" });
  assert.equal(mark.word, "정지 한도 없음");
  assert.deepEqual(Object.keys(mark), ["word", "kind", "text"]);
  assert.equal(mark.kind, "warn");
  assert.equal(mark.text, "관제가 끊겨도 로봇이 계속 갑니다 (차로 통행권·운행 임대 없음)");
  assert.match(ruleMTag({ state: "unbounded", reason: "no_goal_lease" }).text, /\(목표 임대 없음\)/);
  assert.match(ruleMTag({ state: "unbounded", reason: "toString" }).text, /이유 모름/);
  assert.match(ruleMTag({ state: "unbounded" }).text, /이유 모름/);
});
