import test from "node:test";
import assert from "node:assert/strict";

const { register } = await import("node:module");
register("./common-loader.mjs", import.meta.url);
register("./resolve-console-assets.mjs", import.meta.url);
const {robotAppLinks} = await import("../../../../applications/fleet/web/devices/device-discovery.js");

const directoryRow = (changes = {}) => ({role: "robot", peer_id: "robot-1", provenance: "approved-directory",
  approval: "approved", freshness: "unavailable", transport: "https", hostname: "robot-a.example.test",
  port: 8443, ...changes});
const mdnsRow = (changes = {}) => ({role: "robot", peer_id: "robot-1", provenance: "mdns",
  approval: "approved", freshness: "fresh", transport: "https", hostname: "robot-a.local",
  address: "192.168.1.10", port: 8443, ...changes});

test("an approved-directory origin keeps building links beside a fresh mDNS observation", () => {
  const links = robotAppLinks("robot-1", [mdnsRow(), directoryRow()]);
  assert.deepEqual(links.map(link => link.href),
    ["https://robot-a.example.test:8443/console", "https://robot-a.example.test:8443/pilot"]);
});

test("mDNS-only observations, conflicts and missing approval never build links", () => {
  assert.deepEqual(robotAppLinks("robot-1", [mdnsRow()]), []);
  assert.deepEqual(robotAppLinks("robot-1", [mdnsRow({freshness: "conflict"}), directoryRow()]), []);
  assert.deepEqual(robotAppLinks("robot-1", [directoryRow({approval: "unapproved"})]), []);
  assert.deepEqual(robotAppLinks("robot-1", []), []);
  assert.deepEqual(robotAppLinks("robot-1", null), []);
});

test("two approved origins for one robot stay ambiguous and link-free", () => {
  assert.deepEqual(robotAppLinks("robot-1",
    [directoryRow(), directoryRow({hostname: "robot-b.example.test", port: 8444})]), []);
});
