import test from "node:test";
import assert from "node:assert/strict";

const { register } = await import("node:module");
register("./common-loader.mjs", import.meta.url);
register("./resolve-console-assets.mjs", import.meta.url);
const { shownRobot, watchFacts } = await import("../../../ui/console/device-watch.js");

const texts = (facts) => facts.tags.map((item) => item.text);

test("the watch follows the open card, then the armed robot, then a sole robot", () => {
  const one = { robot_id: "rosy_26" };
  const two = { robot_id: "rosy_60" };
  assert.equal(shownRobot({ robots: [one, two], focusRobot: "rosy_60", selected: "rosy_26" }).robot_id, "rosy_60");
  assert.equal(shownRobot({ robots: [one, two], focusRobot: null, selected: "rosy_26" }).robot_id, "rosy_26");
  assert.equal(shownRobot({ robots: [one], focusRobot: null, selected: null }).robot_id, "rosy_26");
  assert.equal(shownRobot({ robots: [one, two], focusRobot: "missing", selected: null }), null);
  assert.equal(shownRobot({ robots: [] }), null);
});

test("camera, lidar, line and clearance stay tags, and an older robot stays unknown", () => {
  const ready = watchFacts({
    robot_id: "rosy_26",
    capabilities: { line_follow: { camera: { available: true, age_ms: 120, source: "front" } } },
    state: {
      power: { lidar_ready: true, lidar_spinning: true },
      line_follow: { mode: "CAMERA_LINE", state: "TRACKING", clearance_m: 1.25, body_gap_m: 0.4, clearance_source: "lidar" },
    },
  }, { name: "26" });
  assert.deepEqual(texts(ready), ["26", "전방 카메라", "라이다 준비", "카메라 차선 추종 · 추종 중", "전방 1.25 m", "몸 0.4 m"]);
  assert.equal(ready.tags[1].title, "front · 120 ms");
  assert.equal(ready.tags[4].title, "라이다");
  assert.deepEqual(ready.numbers, [
    { label: "전방 m", value: "1.25" },
    { label: "몸 m", value: "0.4" },
    { label: "거리 출처", value: "라이다" },
  ]);

  const dark = watchFacts({
    robot_id: "rosy_60",
    capabilities: { line_follow: { camera: { available: false } } },
    state: { power: { lidar_ready: false, lidar_spinning: true }, line_follow: { mode: "OFF", state: "OFF" } },
  });
  assert.deepEqual(texts(dark), ["rosy_60", "전방 없음", "라이다 기동"]);
  assert.equal(dark.tags[1].status, "warn");

  const older = watchFacts({ robot_id: "rosy_8", capabilities: { line_follow: {} }, state: { power: {} } });
  assert.deepEqual(texts(older), ["rosy_8", "전방 미확인"]);
});

test("stuck, boundary and AI facts are tags on the robot already in the queue", () => {
  const facts = watchFacts({
    robot_id: "rosy_26",
    capabilities: null,
    state: { power: { lidar_spinning: false, lidar_ready: false } },
    line_stuck: {
      cause: "lane_lost",
      phase: "ASKING",
      inquiry: { lane_boundary: { state: "confirming" } },
      ai: { state: "present", owner_mode: "available" },
      ai_facts: [{ kind: "rear_blocked", confidence: 0.82, source: "analyzer:stuck@ai" }],
    },
  });
  assert.ok(texts(facts).includes("차선을 잃고 멈춤"));
  assert.ok(texts(facts).includes("차선 경계 변화 확인 중"));
  assert.ok(texts(facts).includes("AI 판단 있음"));
  const fact = facts.tags.find((item) => item.text === "뒤 막힘");
  assert.equal(fact.title, "82% · analyzer:stuck@ai");
  assert.equal(facts.tags.find((item) => item.text === "라이다 정지").status, "warn");
});

test("traffic and diagnostics appear only when the snapshot says they matter", () => {
  const quiet = watchFacts({
    robot_id: "rosy_26",
    state: { traffic_policy: { mode: "DISABLED", signal_colour: "green" }, diagnostics_summary: { camera: "OK" } },
  });
  assert.deepEqual(texts(quiet), ["rosy_26", "전방 미확인"]);

  const live = watchFacts({
    robot_id: "rosy_26",
    state: {
      traffic_policy: { mode: "ENFORCED", signal_colour: "red", signal_conflict: true, stop_line_visible: true },
      diagnostics_summary: { lidar: "ERROR", camera: "WARNING" },
    },
  });
  assert.ok(texts(live).includes("교통 적용"));
  assert.ok(texts(live).includes("신호 red"));
  assert.equal(live.tags.find((item) => item.text === "신호 red").status, "crit");
  assert.ok(texts(live).includes("정지선"));
  assert.ok(texts(live).includes("lidar 오류"));
  assert.ok(texts(live).includes("camera 주의"));
});

test("an empty choice and a lost fleet stay one tag", () => {
  assert.deepEqual(texts(watchFacts(null)), ["로봇 미선택"]);
  assert.deepEqual(texts(watchFacts({ robot_id: "rosy_26", state: { power: { lidar_ready: true } } }, { unavailable: true })), ["상태 확인 불가"]);
});
