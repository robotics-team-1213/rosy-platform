import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import { linkTag } from "../../fleet/server/web/link-tag.js";

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
  const web = new URL("../../fleet/server/web/", import.meta.url);
  for (const name of ["link-tag.js", "site-path.js"]) {
    const text = readFileSync(new URL(name, web), "utf8");
    for (const banned of ["RemoteProtocolError", "ConnectError", "RobotApiError", "SSLError"]) {
      assert.equal(text.includes(banned), false, `${name} names ${banned}`);
    }
  }
});
