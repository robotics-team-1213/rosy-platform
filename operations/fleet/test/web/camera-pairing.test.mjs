import test from "node:test";
import assert from "node:assert/strict";

import {
  CONFIRM_PROMPT, MESSAGES, PENDING_POLL_MS, UNAVAILABLE, canApprove, credentialActions, credentialText,
  formatClock, formatWhen, freeSources, messageFor, queueHealthText, normalizePairingCode, pairingCodeError, remainingSeconds,
  requestActions, requestText,
} from "../../fleet/server/web/camera-pairing.js";

const REVEALED = {
  request_id: "req-1", device_label: "Galaxy S21", app_version: "1.4.0", state: "revealed",
  requested_at: "2026-10-01T09:00:00Z", expires_in_s: 280, attempts_left: 3,
};

test("the code is the phone's six digits; the console never formats or shows one", () => {
  assert.equal(normalizePairingCode(" 123 456 "), "123456");
  assert.equal(normalizePairingCode("123-456"), "123456");
  assert.equal(pairingCodeError("123456"), null);
  for (const bad of ["", "12345", "1234567", "12a456", "ABCDEF"]) {
    assert.equal(pairingCodeError(bad), MESSAGES.bad_code, bad);
  }
});

test("only paired sources without a credential can be chosen", () => {
  const listing = { paired_sources: [
    { source_id: "ceiling-north", has_credential: true },
    { source_id: "ceiling-south", has_credential: false },
  ] };
  assert.deepEqual(freeSources(listing), ["ceiling-south"]);
  assert.deepEqual(freeSources({}), []);
});

test("remaining time counts down from the fetch and never goes negative", () => {
  assert.equal(remainingSeconds(280, 10_000, 10_000), 280);
  assert.equal(remainingSeconds(280, 10_000, 12_400), 278);
  assert.equal(remainingSeconds(2, 10_000, 20_000), 0);
  assert.equal(formatClock(299), "4:59");
  assert.equal(formatClock(120), "2:00");
  assert.equal(formatClock(5), "0:05");
  assert.equal(formatClock(-3), "0:00");
});

test("request rows say what the phone is doing and how many tries are left", () => {
  const revealed = requestText(REVEALED);
  assert.match(revealed.join(" "), /폰 화면에 코드가 떠 있습니다/);
  assert.match(revealed.join(" "), /앱 1\.4\.0/);
  assert.match(revealed.join(" "), /남은 입력 3회/);
  const pending = requestText({ ...REVEALED, state: "pending" });
  assert.match(pending.join(" "), /폰이 아직 코드를 띄우지 않았습니다/);
  assert.match(requestText({ ...REVEALED, attempts_left: 1 }).join(" "), /남은 입력 1회/);
});

test("approve needs a named operator, a revealed code and a free source; the reason is said", () => {
  const free = ["ceiling-south"];
  assert.deepEqual(requestActions(REVEALED, false, free), []);
  assert.deepEqual(requestActions(REVEALED, true, free),
    [{ action: "approve", reason: null }, { action: "reject", reason: null }]);
  assert.deepEqual(requestActions({ ...REVEALED, state: "pending" }, true, free),
    [{ action: "approve", reason: MESSAGES.not_revealed_reason }, { action: "reject", reason: null }]);
  assert.deepEqual(requestActions(REVEALED, true, []),
    [{ action: "approve", reason: MESSAGES.no_free_source_reason }, { action: "reject", reason: null }]);
});

test("viewers and the shared console token cannot approve", () => {
  assert.equal(canApprove({ role: "viewer", principal_id: "vic" }), false);
  assert.equal(canApprove({ role: "operator", principal_id: "site-console" }), false);
  assert.equal(canApprove({ role: "policy-admin", principal_id: "pam" }), false);
  assert.equal(canApprove({ role: "operator", principal_id: "alice" }), true);
});

test("credential rows show state, approver and expiry; only live ones can be revoked", () => {
  const active = { credential_id: "cred-0a1b2c3d4e5f", source_id: "ceiling-south", state: "active",
    device_label: "Galaxy S21", approved_by: "alice", approved_at: "2026-10-01T09:01:00Z",
    confirmed_at: "2026-10-01T09:01:30Z", expires_at: "2027-03-30T09:01:00Z", expired: false };
  const text = credentialText(active).join(" ");
  assert.match(text, /사용 중/);
  assert.match(text, /alice/);
  assert.match(text, /2027-03-30/);
  assert.match(credentialText({ ...active, state: "pending_confirm" })[0], /폰 확인 대기/);
  assert.match(credentialText({ ...active, state: "revoked" })[0], /폐기됨/);
  assert.match(credentialText({ ...active, expired: true })[0], /만료됨/);
  assert.deepEqual(credentialActions(active, true), ["revoke"]);
  assert.deepEqual(credentialActions({ ...active, state: "pending_confirm" }, true), ["revoke"]);
  assert.deepEqual(credentialActions({ ...active, state: "revoked" }, true), []);
  assert.deepEqual(credentialActions(active, false), []);
});

test("each refusal maps to its operator sentence; a wrong code says the tries left", () => {
  assert.match(messageFor({ code: "CODE_MISMATCH", attempts_left: 2 })[0], /남은 입력 2회/);
  assert.match(messageFor({ code: "CODE_MISMATCH", attempts_left: 0 })[0], /거절로 닫혔습니다/);
  for (const code of ["NOT_REVEALED", "ALREADY_APPROVED", "SOURCE_NOT_PAIRED", "SOURCE_HAS_CREDENTIAL",
    "UNKNOWN_SOURCE", "PAIRING_REQUEST_CLOSED", "UNKNOWN_PAIRING_REQUEST", "UNKNOWN_CREDENTIAL",
    "ALREADY_REVOKED"]) {
    assert.equal(messageFor({ code })[0], MESSAGES[code], code);
  }
  const named = messageFor({ code: "OPERATOR_IDENTITY_REQUIRED", message: "named operator required (site-users.yaml)" });
  assert.match(named[0], /이름 있는 운영자/);
  assert.match(named[0], /site-users\.yaml/);
  assert.match(messageFor({ code: "SOMETHING_NEW" })[0], /SOMETHING_NEW/);
  assert.match(messageFor({ code: "PAIRING_RATE_LIMITED" })[0], /잠시 뒤/);
});

test("fixed copy: absent routes are calm, confirm prompt matches the phone check, polling is 2-3 s", () => {
  assert.equal(UNAVAILABLE, "이 Fleet에는 카메라 연결 승인이 설정되지 않았습니다.");
  assert.equal(CONFIRM_PROMPT, "폰 화면과 이 지문·자격 ID가 같은지 확인하세요");
  assert.ok(PENDING_POLL_MS >= 2000 && PENDING_POLL_MS <= 3000, PENDING_POLL_MS);
});

test("a jammed queue shows as one quiet line of counts since Fleet start; zero says nothing", () => {
  assert.equal(queueHealthText({ refused_requests: 0, commit_mismatches: 0 }), null);
  assert.equal(queueHealthText({}), null);
  const line = queueHealthText({ refused_requests: 4, commit_mismatches: 1, unauthenticated_requests: 9 });
  assert.equal(line, "Fleet 시작 뒤: 한도로 거절된 요청 4건 · 확인값이 맞지 않아 닫힌 요청 1건");
  assert.doesNotMatch(line, /refused|commit|mismatch/i);
});

test("times read as local minutes, and an unreadable time is passed through", () => {
  assert.match(formatWhen("2027-03-30T08:00:00+00:00"), /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$/);
  assert.equal(formatWhen("not a time"), "not a time");
  assert.equal(formatWhen(null), "—");
  const row = { credential_id: "cred-1", source_id: "s", state: "active", device_label: "d",
    approved_by: "alice", approved_at: "2026-10-01T09:01:00Z", expires_at: "2027-03-30T09:01:00Z", expired: false };
  assert.doesNotMatch(credentialText(row).join(" "), /T09:01:00/);
});
