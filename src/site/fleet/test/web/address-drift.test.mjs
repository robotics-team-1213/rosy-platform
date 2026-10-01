import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import {
  RENUMBER_BANNER, addressMap, addressReason, renumberBanner,
} from "../../fleet/server/web/address-drift.js";

const WEB = new URL("../../fleet/server/web/", import.meta.url);

const entry = (over) => ({
  robot_id: "rosy_09", origin: "enrolled", pinned: "192.0.2.10:8080", pinned_is_name: false,
  status: "outside_scanned_subnets", in_subnet: false, seen_addresses: [], movable: false, ...over,
});

test("a pinned address outside every scanned subnet says so instead of a bare offline", () => {
  const reason = addressReason(entry({}));
  assert.equal(reason.action, null);
  assert.match(reason.text, /^고정 주소 192\.0\.2\.10:8080이\(가\) 지금 망에 없습니다/);
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

test("the renumber banner follows the server's all_outside flag only", () => {
  assert.equal(renumberBanner({ all_outside: true, robots: [] }), RENUMBER_BANNER);
  assert.match(RENUMBER_BANNER, /^사이트 망 주소가 바뀐 것 같습니다/);
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
