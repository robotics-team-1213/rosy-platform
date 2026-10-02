import test from "node:test";
import assert from "node:assert/strict";

import {
  localizationTag, localizationUrgent, untrustedQueuedReason,
} from "../../fleet/server/web/localization-badge.js";

const row = (over) => ({ state: "LOCALIZED", pose_frame: "map", trusted: true, legacy: false,
  needs_human: false, label: "위치 확정", ...over });

test("an offline robot has no localization tag", () => {
  assert.equal(localizationTag(null), null);
  assert.equal(localizationTag(undefined), null);
});

test("a localized robot is a neutral tag with the server's label", () => {
  assert.deepEqual(localizationTag(row()), { text: "위치 확정", cls: "", title: "LOCALIZED · map" });
});

test("an unlocalized robot warns and needs_human is critical", () => {
  assert.equal(localizationTag(row({ state: "CANDIDATES", pose_frame: "odom", trusted: false,
    label: "위치 후보 중재 중" })).cls, "warn");
  const human = localizationTag(row({ state: "CANDIDATES", trusted: false, needs_human: true,
    label: "위치 확인 필요" }));
  assert.equal(human.text, "위치 확인 필요");
  assert.equal(human.cls, "crit");
  assert.equal(localizationUrgent(row({ needs_human: true })), true);
  assert.equal(localizationUrgent(row()), false);
});

test("a robot without D-395 warns 위치 상태 미보고", () => {
  const legacy = localizationTag(row({ state: null, pose_frame: null, legacy: true,
    label: "위치 상태 미보고" }));
  assert.equal(legacy.text, "위치 상태 미보고");
  assert.equal(legacy.cls, "warn");
});

test("a mission held behind an untrusted robot says why", () => {
  assert.match(untrustedQueuedReason("rosy_02"), /^rosy_02 위치를 확인할 수 없어 대기 중/);
});
