import test from "node:test";
import assert from "node:assert/strict";
const {register} = await import("node:module");
register("./common-loader.mjs", import.meta.url);
register("./resolve-console-assets.mjs", import.meta.url);
const {stopControls, childLinks, createIntegratedControlView} =
  await import("../../../../applications/fleet/web/work/integrated-control-view.js");

const unit = (unit_id, parent, changes = {}) => ({unit_id, parent, availability: "AVAILABLE", age_s: 0,
  dispatch: {authority_epoch: 3, generation: 7}, ...changes});

test("stop fences include only fresh descendants of the selected subtree", () => {
  const overview = {units: [unit("R", null), unit("A", "R"), unit("B", "R"),
    unit("A1", "A"), unit("old", "A", {age_s: 8}), unit("offline", "A", {availability: "UNAVAILABLE"})]};
  assert.deepEqual(stopControls(overview, "A"), {A: {authority_epoch: 3, generation: 7},
    A1: {authority_epoch: 3, generation: 7}});
  assert.deepEqual(stopControls(overview, "B"), {B: {authority_epoch: 3, generation: 7}});
  assert.deepEqual(stopControls(overview, "foreign"), {});
  assert.deepEqual(stopControls(overview, "A", 6), {});
});

test("missing observations and invalid dispatch fences cannot become fresh permits", () => {
  for (const changes of [{age_s: null}, {age_s: -1}, {age_s: Infinity}, {availability: "STALE"},
    {dispatch: null}, {dispatch: {authority_epoch: 1, generation: true}},
    {dispatch: {authority_epoch: -1, generation: 2}}, {dispatch: {authority_epoch: 1, generation: 1.5}}]) {
    assert.deepEqual(stopControls({units: [unit("constructor", null, changes)]}, "constructor"), {});
  }
});

test("child links follow verified https origins and never carry credentials", () => {
  const summary = {child_origins: {A: "https://cell-a.example.test:8443", B: "http://plain.invalid:8080"},
    child_arm_units: ["A"]};
  assert.deepEqual(childLinks(summary, "A"), [
    {href: "https://cell-a.example.test:8443/console", label: "관제 화면 열기"},
    {href: "https://cell-a.example.test:8443/console/cell", label: "셀 화면 열기"},
  ]);
  // http origins, unknown targets and missing summaries produce no links.
  assert.deepEqual(childLinks(summary, "B"), []);
  assert.deepEqual(childLinks(summary, "R"), []);
  assert.deepEqual(childLinks(null, "A"), []);
  assert.deepEqual(childLinks({child_origins: {A: "https://a.test"}, child_arm_units: []}, "A"),
    [{href: "https://a.test/console", label: "관제 화면 열기"}]);
});

test("paintUnitLinks renders visible labels and styling on child unit anchors", async () => {
  const prevDocument = globalThis.document;
  const makeEl = (tagName) => {
    const el = {
      tagName, children: [], dataset: {}, attributes: {}, listeners: {},
      textContent: "", className: "", id: "", hidden: false, disabled: false, rel: "", href: "",
      append(...nodes) { this.children.push(...nodes.filter(Boolean)); },
      prepend(...nodes) { this.children.unshift(...nodes.filter(Boolean)); },
      replaceChildren(...nodes) { this.children = nodes.filter(Boolean); },
      before() {}, reset() {},
      setAttribute(k, v) { this.attributes[k] = String(v); },
      removeAttribute(k) { delete this.attributes[k]; },
      getAttribute(k) { return this.attributes[k] ?? null; },
      addEventListener(type, fn) { (this.listeners[type] ??= []).push(fn); },
      querySelector(sel) {
        if (sel === ":scope > ul") return this.children.find(c => c.tagName === "ul") || null;
        if (sel === "ui-button") return this.children.find(c => c.tagName === "ui-button") || null;
        return null;
      },
    };
    return el;
  };
  let panel = null;
  globalThis.document = { createElement: (tag) => makeEl(tag), activeElement: null };
  try {
    const view = createIntegratedControlView({
      scope: { capture: () => ({ current: () => true, check() {} }), listen() {}, onDispose() {} },
      call: async (path) => {
        if (path === "/api/fleet/control-unit/overview") {
          return {
            unit_id: "R", config_revision: "v1",
            units: [
              unit("R", null, { robots_online: 0, robots_total: 0, tasks_active: 0, stop_pending: 0, sampled_at: null }),
              unit("A", "R", { robots_online: 0, robots_total: 0, tasks_active: 0, stop_pending: 0, sampled_at: null }),
            ],
          };
        }
        if (path === "/api/fleet/control-unit") {
          return { unit_id: "R", child_origins: { A: "https://cell-a.example.test:8443" }, child_arm_units: ["A"] };
        }
        if (path === "/api/fleet/control-unit/stops") return { unit_id: "R", config_revision: "v1", stops: [] };
        if (path.startsWith("/api/fleet/control-unit/units/")) {
          return {
            unit_id: path.endsWith("/A") ? "A" : "R", config_revision: "v1",
            availability: "AVAILABLE", age_s: 0, sampled_at: null, robots: [], tasks: [], tasks_truncated: false, map: null,
          };
        }
        throw new Error(`unexpected path: ${path}`);
      },
      anchor: { before(el) { panel = el; } },
      active: () => true,
      approveReason: () => "",
      principal: () => "viewer-1",
      taskStatus: (s) => s,
    });
    await view.refresh();
    const walk = (root, predicate) => {
      const hit = [];
      for (const child of root.children || []) {
        if (predicate(child)) hit.push(child);
        hit.push(...walk(child, predicate));
      }
      return hit;
    };
    const [selectA] = walk(panel, el => el.dataset?.integratedUnit === "A");
    assert.ok(selectA, "child unit button should be rendered");
    for (const handler of selectA.listeners.click || []) await handler();
    const [linksRow] = walk(panel, el => el.className === "integrated-unit-links");
    assert.equal(linksRow.hidden, false);
    assert.equal(linksRow.children.length, 2);
    assert.deepEqual(
      linksRow.children.map(a => ({
        tagName: a.tagName, textContent: a.textContent, className: a.className,
        kind: a.dataset.kind, rel: a.rel, href: a.href,
      })),
      [
        {
          tagName: "a", textContent: "관제 화면 열기", className: "ui-action-link",
          kind: "quiet", rel: "noreferrer", href: "https://cell-a.example.test:8443/console",
        },
        {
          tagName: "a", textContent: "셀 화면 열기", className: "ui-action-link",
          kind: "quiet", rel: "noreferrer", href: "https://cell-a.example.test:8443/console/cell",
        },
      ],
    );
  } finally {
    globalThis.document = prevDocument;
  }
});
