import assert from "node:assert/strict";
import test from "node:test";
import "./register-console-assets.mjs";

const { workspaceCardKey } = await import("../../../../applications/fleet/web/roster-cards.js");
const card = {
  robot: { robot_id: "rosy_01", online: true },
  view: {},
  state: { pose: { x: 1.004, y: 2, yaw: 0.1 }, pose_frame: "map", map_id: "site" },
  sitePose: "1.00, 2.00",
  power: { battery: "63%", charging: "충전 확인 · 63%", chargingConfirmed: true, voltage: 12.3, note: "값 멈춤 (1분 전)" },
};

test("workspace card identity survives live fact updates", () => {
  assert.equal(workspaceCardKey(card), workspaceCardKey({
    ...card,
    state: { ...card.state, pose: { x: 1.006, y: 2.02, yaw: 0.12 } },
    sitePose: "1.01, 2.02",
    power: { ...card.power, battery: "64%", charging: "충전 확인 · 64%", voltage: 12.31, note: "값 멈춤 (2분 전)" },
  }));
});

test("workspace card identity changes for structure and power status", () => {
  for (const change of [
    { state: { ...card.state, pose: null } },
    { state: { ...card.state, pose_frame: "odom" } },
    { state: { ...card.state, map_id: "other" } },
    { sitePose: null },
    { power: { ...card.power, problem: "배터리 경고" } },
    { power: { ...card.power, chargingConfirmed: false } },
    { power: { ...card.power, note: "" } },
    { power: { ...card.power, safetyRelease: "안전 확인 후 해제" } },
  ]) assert.notEqual(workspaceCardKey(card), workspaceCardKey({ ...card, ...change }));
});
