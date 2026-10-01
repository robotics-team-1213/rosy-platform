import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import {
  RENUMBER_BANNER, addressMap, addressReason, movableRobots, renumberBanner,
} from "../../fleet/server/web/address-drift.js";
import { MESSAGES, moveDoneLines } from "../../fleet/server/web/enrollment.js";

const WEB = new URL("../../fleet/server/web/", import.meta.url);

const entry = (over) => ({
  robot_id: "rosy_09", origin: "enrolled", pinned: "192.0.2.10:8080", pinned_is_name: false,
  status: "outside_scanned_subnets", in_subnet: false, seen_addresses: [], movable: false, ...over,
});

test("a pinned address outside every scanned subnet says so instead of a bare offline", () => {
  const reason = addressReason(entry({}));
  assert.equal(reason.action, null);
  assert.match(reason.text, /^고정 주소 192\.0\.2\.10:8080이\(가\) 지금 망에 없을 수 있습니다/);
  const file = addressReason(entry({ origin: "static" }));
  assert.match(file.text, /robots\.yaml/);
});

test("the same robot at a new address offers the existing per-robot move", () => {
  const reason = addressReason(entry({ status: "seen_at_other_address",
    seen_addresses: ["10.16.36.20:8080"], movable: true }));
  assert.equal(reason.text, "같은 로봇이 10.16.36.20:8080에 보입니다 — 새 주소로 옮기기…");
  assert.equal(reason.action, "move");
  const notYet = addressReason(entry({ status: "seen_at_other_address",
    seen_addresses: ["10.16.36.20:8080"], movable: false }));
  assert.equal(notYet.action, null);
});

test("several addresses for one name are a conflict and never a move", () => {
  const reason = addressReason(entry({ status: "seen_at_other_address", movable: true,
    seen_addresses: ["10.16.36.20:8080", "10.16.36.21:8080"] }));
  assert.equal(reason.action, null);
  assert.match(reason.text, /신원 충돌/);
});

test("a robots.yaml .local name is a suggestion for the operator, not a move", () => {
  const reason = addressReason(entry({ origin: "static", pinned: "rosy-a.local:8080", pinned_is_name: true,
    in_subnet: null, status: "seen_at_other_address", seen_addresses: ["10.16.36.20:8080"] }));
  assert.equal(reason.action, null);
  assert.match(reason.text, /따라가지 않습니다/);
  assert.match(reason.text, /10\.16\.36\.20:8080/);
  assert.match(reason.text, /robots\.yaml/);
});

test("in-subnet and unknown robots get no address line", () => {
  assert.equal(addressReason(entry({ status: "in_scanned_subnet", in_subnet: true })), null);
  assert.equal(addressReason(entry({ status: "unknown", in_subnet: null })), null);
  assert.equal(addressReason(undefined), null);
});

test("the renumber hint follows all_outside unless a name-pinned robot is online", () => {
  assert.equal(renumberBanner({ all_outside: true, robots: [] }), RENUMBER_BANNER);
  assert.match(RENUMBER_BANNER, /^사이트 망 주소가 바뀌었을 수 있습니다/);
  const payload = { all_outside: true, robots: [entry({}),
    entry({ robot_id: "rosy_01", origin: "static", pinned: "rosy-a.local:8080", pinned_is_name: true,
      status: "unknown", in_subnet: null })] };
  assert.equal(renumberBanner(payload, [{ robot_id: "rosy_01", online: false }]), RENUMBER_BANNER);
  assert.equal(renumberBanner(payload, [{ robot_id: "rosy_01", online: true }]), null);
  assert.equal(renumberBanner(payload, [{ robot_id: "rosy_09", online: true }]), RENUMBER_BANNER);
  assert.equal(renumberBanner({ all_outside: false }), null);
  assert.equal(renumberBanner(null), null);
  assert.deepEqual(Object.keys(addressMap({ robots: [entry({}), entry({ robot_id: "rosy_01" })] })),
    ["rosy_09", "rosy_01"]);
});

test("no console text shows a 192.168.1.x example address", () => {
  for (const name of ["index.html", "enrollment.js", "address-drift.js", "console.js", "roster.js"]) {
    const text = readFileSync(new URL(name, WEB), "utf8");
    assert.doesNotMatch(text, /192\.168\.1\.\d/, name);
  }
});

const moved = (robot_id, seen, over = {}) => entry({ robot_id, status: "seen_at_other_address",
  seen_addresses: [seen], movable: true, ...over });

test("the banner lists only enrolled robots the server marked movable", () => {
  const payload = { robots: [
    moved("rosy_09", "10.16.36.20:8080"),
    moved("rosy_10", "10.16.36.21:8080", { movable: false }),
    moved("rosy_01", "10.16.36.22:8080", { origin: "static", movable: false }),
    entry({ robot_id: "rosy_11" }),
  ] };
  assert.deepEqual(movableRobots(payload).map((e) => e.robot_id), ["rosy_09"]);
  assert.deepEqual(movableRobots(null), []);
});

test("there is no bulk move: every move asks for that robot's screen code", () => {
  for (const name of ["index.html", "console.js", "address-drift.js", "enrollment.js"]) {
    const text = readFileSync(new URL(name, WEB), "utf8");
    assert.doesNotMatch(text, /\(전체\)|runBulkMove|address-move-all/, name);
  }
  const panel = readFileSync(new URL("enrollment.js", WEB), "utf8");
  assert.doesNotMatch(panel, /window\.confirm/);
  assert.match(panel, /move-address`;[\s\S]{0,120}method: "POST", body: \{ code: input\.value \}/);
});

test("a finished move says whether the old site token was revoked", () => {
  const row = { robot_id: "rosy_09", address: "10.16.36.20:8080", old_token_revoked: true };
  assert.deepEqual(moveDoneLines(row), ["rosy_09: 10.16.36.20:8080(으)로 옮김 — 새 토큰으로 다시 묶었습니다."]);
  const left = moveDoneLines({ ...row, old_token_revoked: false });
  assert.equal(left.length, 2);
  assert.match(left[1], /이전 사이트 토큰을 회수하지 못했습니다 — 로봇 대시보드/);
});

test("a different device at the new address is reported without implying a leak", () => {
  assert.match(MESSAGES.identity_mismatch, /등록된 토큰은 보내지 않았습니다/);
  assert.doesNotMatch(MESSAGES.identity_mismatch, /다른 기기에 갔을 수/);
});
