import test from "node:test";
import assert from "node:assert/strict";

import {
  AVAHI_HINT, DISCOVERY_LABELS, MESSAGES, canManage, codeError, discoveryActions, formatCode,
  messageFor, normalizeCode, parseAddress, retryUntil, rowActions, rowText,
} from "../../fleet/server/web/enrollment.js";

const CODE = "7KXM" + "P3QA";

test("codes are normalized and format-checked before anything is sent", () => {
  assert.equal(normalizeCode(" 7kxm-p3qa "), CODE);
  assert.equal(formatCode("7kxmp3qa"), "7KXM-P3QA");
  assert.equal(codeError("7kxm p3qa"), null);
  for (const bad of ["", "7KXM-P3Q", "7KXM-P3QA1", "7KXM-P3Q0", "ILO1-ABCD"]) {
    assert.equal(codeError(bad), MESSAGES.bad_format, bad);
  }
});

test("manual addresses are private IPv4 with port 8080 by default", () => {
  assert.equal(parseAddress("192.168.1.202"), "192.168.1.202:8080");
  assert.equal(parseAddress("10.0.0.5:9000"), "10.0.0.5:9000");
  assert.equal(parseAddress("172.16.3.4"), "172.16.3.4:8080");
  for (const bad of ["rosy-pinky-8kcn.local", "8.8.8.8", "127.0.0.1", "192.168.1.300",
    "192.168.1.2:0", "172.32.0.1", "example.com"]) {
    assert.equal(parseAddress(bad), null, bad);
  }
});

test("each classification maps to its operator sentence", () => {
  assert.match(messageFor({ code: "code_rejected" })[0], /틀렸거나, 이미 쓰였거나, 만료/);
  assert.match(messageFor({ code: "code_burned" })[0], /폐기/);
  assert.match(messageFor({ code: "lan_forbidden" })[0], /LAN 밖/);
  assert.match(messageFor({ code: "unreachable" })[0], /닿지 않습니다/);
  assert.match(messageFor({ code: "rate_limited", retry_after: 17 })[0], /17초/);
  const consumed = messageFor({ code: "code_consumed", reason: "admin_code_refused" });
  assert.match(consumed[0], /소모/);
  assert.match(consumed[1], /관리자/);
  const wrong = messageFor({ code: "code_consumed", reason: "wrong_robot" });
  assert.equal(wrong.at(-1), AVAHI_HINT);
  assert.match(wrong.at(-1), /-2\.local/);
  assert.match(messageFor({ code: "something_new" })[0], /something_new/);
});

test("a 429 keeps the button off for Retry-After seconds", () => {
  const until = retryUntil({ code: "rate_limited", retry_after: 30 }, 1000);
  assert.equal(until, 31000);
  const device = { name: "rosy-pinky-8kcn", enrollable: true };
  assert.deepEqual(discoveryActions(device, true, until, 30999), []);
  assert.deepEqual(discoveryActions(device, true, until, 31000), ["enroll"]);
  assert.equal(retryUntil({ code: "code_rejected" }, 1000), 0);
});

test("viewers and the shared console token see no enrollment buttons", () => {
  const row = { robot_id: "rosy_09", state: "address_changed" };
  assert.equal(canManage({ role: "viewer", principal_id: "vic" }), false);
  assert.equal(canManage({ role: "operator", principal_id: "site-console" }), false);
  assert.equal(canManage({ role: "operator", principal_id: "alice" }), true);
  assert.deepEqual(rowActions(row, false), []);
  assert.deepEqual(rowActions(row, true), ["move", "unenroll"]);
  assert.deepEqual(rowActions({ ...row, state: "active" }, true), ["unenroll"]);
  assert.deepEqual(rowActions({ ...row, state: "pending_logout" }, true), []);
  assert.deepEqual(rowActions({ ...row, state: "active", hub_linkable: true }, true), ["hub-link", "unenroll"]);
  assert.deepEqual(rowActions({ ...row, state: "active", hub_linked: true }, true), ["hub-unlink", "unenroll"]);
  assert.deepEqual(discoveryActions({ enrollable: true }, false, 0, 1), []);
  assert.deepEqual(discoveryActions({ enrollable: false }, true, 0, 1), []);
});

test("row text follows the register state", () => {
  assert.equal(rowText({ state: "needs_new_code" })[0], "새 코드 필요");
  assert.equal(rowText({ state: "address_changed" })[0], "주소 바뀜 — 확인 필요");
  assert.match(rowText({ state: "pending_logout", expires_at: "2026-10-06" })[1],
    /로봇에 토큰이 남아 있음\(만료 2026-10-06\) — 로봇 대시보드에서 회수 가능/);
  assert.ok(rowText({ state: "active", legacy_lifetime: true }).some((l) => /7일 뒤 새 코드/.test(l)));
  assert.ok(rowText({ state: "active", lifetime_shortened: true }).some((l) => /관리자 세션의 만료/.test(l)));
  assert.ok(rowText({ state: "active", hold: "conflict" }).some((l) => /신원 충돌/.test(l)));
  assert.ok(rowText({ state: "active" }).includes("수집: REST"));
  assert.ok(rowText({ state: "active", hub_linked: true, hub_host: "site.local", hub_online: true })
    .includes("허브 연결됨(site.local) · 수집: 허브"));
});

test("discovery labels include enrolled and the renamed event-link state", () => {
  assert.equal(DISCOVERY_LABELS.enrolled, "등록됨");
  assert.equal(DISCOVERY_LABELS.pairing_pending, "이벤트 연결 대기");
});

test("review codes have operator sentences, and the address rule is RFC 1918 only", () => {
  for (const code of ["not_enrollable", "identity_mismatch", "no_new_address", "ROBOT_BUSY",
    "ACTIVE_TASKS", "FORMATION_ACTIVE"]) {
    assert.equal(messageFor({ code })[0], MESSAGES[code], code);
  }
  for (const bad of ["192.0.2.5", "100.64.0.1", "169.254.1.1"]) {
    assert.equal(parseAddress(bad), null, bad);
  }
});
