import test from "node:test";
import assert from "node:assert/strict";

const { register } = await import("node:module");
register("./common-loader.mjs", import.meta.url);
register("./resolve-console-assets.mjs", import.meta.url);
const {createRobotAppActions} = await import("../../../../applications/fleet/web/devices/device-discovery.js");

const directoryRow = (changes = {}) => ({role: "robot", peer_id: "robot-1", provenance: "approved-directory",
  approval: "approved", freshness: "unavailable", transport: "https", hostname: "robot-a.example.test",
  port: 8443, ...changes});
const mdnsRow = (changes = {}) => ({role: "robot", peer_id: "robot-1", provenance: "mdns",
  approval: "approved", freshness: "fresh", transport: "https", hostname: "robot-a.local",
  address: "192.168.1.10", port: 8443, ...changes});

function renderActions(robotId, peers) {
  const prevDocument = globalThis.document;
  globalThis.document = {
    createElement(tagName) {
      return {
        tagName, children: [], dataset: {}, textContent: "", className: "", href: "", rel: "",
        append(...nodes) { this.children.push(...nodes.filter(Boolean)); },
      };
    },
  };
  try {
    return createRobotAppActions(robotId, peers);
  } finally {
    globalThis.document = prevDocument;
  }
}

const linkHrefs = (robotId, peers) =>
  renderActions(robotId, peers).children.filter(c => c.dataset.robotApp).map(link => link.href);

test("an approved-directory origin keeps building links beside a fresh mDNS observation", () => {
  assert.deepEqual(linkHrefs("robot-1", [mdnsRow(), directoryRow()]),
    ["https://robot-a.example.test:8443/console", "https://robot-a.example.test:8443/pilot"]);
});

test("mDNS-only observations, conflicts and missing approval never build links", () => {
  assert.deepEqual(linkHrefs("robot-1", [mdnsRow()]), []);
  assert.deepEqual(linkHrefs("robot-1", [mdnsRow({freshness: "conflict"}), directoryRow()]), []);
  assert.deepEqual(linkHrefs("robot-1", [directoryRow({approval: "unapproved"})]), []);
  assert.deepEqual(linkHrefs("robot-1", []), []);
  assert.deepEqual(linkHrefs("robot-1", null), []);
  const guidance = renderActions("robot-1", [mdnsRow()]).children.find(c => Object.hasOwn(c.dataset, "robotAppGuidance"));
  assert.ok(guidance);
});

test("two approved origins for one robot stay ambiguous and link-free", () => {
  assert.deepEqual(linkHrefs("robot-1",
    [directoryRow(), directoryRow({hostname: "robot-b.example.test", port: 8444})]), []);
});
