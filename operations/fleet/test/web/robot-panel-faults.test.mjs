import test from "node:test";
import assert from "node:assert/strict";

const { register } = await import("node:module");
register("./common-loader.mjs", import.meta.url);
register("./resolve-console-assets.mjs", import.meta.url);
const { createRobotPanel } = await import("../../../../applications/fleet/web/shared/robot-panel.js");
const { robotProfile } = await import("../../../../applications/fleet/web/shared/robot-profile.js");
const { dockEntries } = await import("../../../../applications/fleet/web/shared/robot-dock-model.js");
const { createRobotDock } = await import("../../../../applications/fleet/web/shared/robot-dock.js");
const { armIncidentAlertRows } = await import("../../../../applications/fleet/web/cell/arm-incident-clear.js");

function makeDom(t) {
  const prevDoc = globalThis.document;
  const mkNode = (tag) => {
    const el = {
      tagName: String(tag).toUpperCase(), id: "", className: "", children: [], dataset: {}, hidden: false,
      attributes: new Map(), listeners: {}, tabIndex: 0, scrollTop: 0, text: "", open: false,
      classList: {
        toggle(k, force) { return Boolean(force); },
        contains() { return false; },
        add() {},
        remove() {},
      },
      append(...nodes) {
        for (const n of nodes) {
          if (!n) continue;
          if (typeof n === "string") { el.children.push({ nodeType: 3, textContent: n, parentElement: el, remove() {} }); continue; }
          n.parentElement = el;
          el.children.push(n);
        }
      },
      insertBefore(n, ref) {
        n.parentElement = el;
        const i = el.children.indexOf(n);
        if (i >= 0) el.children.splice(i, 1);
        const r = ref ? el.children.indexOf(ref) : -1;
        if (r >= 0) el.children.splice(r, 0, n); else el.children.push(n);
      },
      replaceChildren(...nodes) { el.children = []; el.append(...nodes); },
      replaceWith(next) {
        const p = el.parentElement;
        if (!p) return;
        const i = p.children.indexOf(el);
        if (i >= 0) { next.parentElement = p; p.children[i] = next; }
      },
      remove() {
        const p = el.parentElement;
        if (p) { const i = p.children.indexOf(el); if (i >= 0) p.children.splice(i, 1); }
        el.parentElement = null;
      },
      get childElementCount() { return el.children.filter((c) => c.nodeType !== 3).length; },
      get firstElementChild() { return el.children.find((c) => c.nodeType !== 3) || null; },
      setAttribute(k, v) { el.attributes.set(k, String(v)); },
      getAttribute(k) { return el.attributes.get(k) ?? null; },
      removeAttribute(k) { el.attributes.delete(k); },
      addEventListener(type, fn) { (el.listeners[type] ??= []).push(fn); },
      matches() { return false; },
      focus() {},
      scrollIntoView() {},
      get textContent() { return el.text + el.children.map((c) => c.textContent).join(""); },
      set textContent(v) { el.children = []; el.text = String(v); },
      querySelector(sel) { return el.querySelectorAll(sel)[0] || null; },
      querySelectorAll(sel) {
        const s = sel.replace(/^:scope\s*>\s*/, "");
        const directOnly = sel.startsWith(":scope >");
        const out = [];
        for (const c of el.children) {
          if (c.nodeType === 3) continue;
          const m = s.match(/^\.([\w-]+)$/) ? c.className.split(/\s+/).includes(s.slice(1))
            : s.match(/^\[data-section="([^"]+)"\]$/) ? c.dataset.section === RegExp.$1
            : false;
          if (m) out.push(c);
          if (!directOnly) out.push(...c.querySelectorAll(s));
        }
        return out;
      },
    };
    return el;
  };
  globalThis.document = { createElement: mkNode, activeElement: null };
  t.after(() => { globalThis.document = prevDoc; });
}

test("robot-panel mounts faults section first when provided and omits when null", (t) => {
  makeDom(t);
  let showFaults = true;
  const panel = createRobotPanel({
    sections: {
      faults: () => (showFaults ? document.createElement("ul") : null),
      status: () => document.createElement("div"),
    },
  });
  const profile = { id: "rosy_46", name: "46", kind: "mobile", kindLabel: "이동로봇", link: { state: "fresh", text: "정상" } };
  panel.setRobot(profile, {});
  const body = panel.root.children.find((c) => c.className === "robot-panel-body");
  assert.equal(body.children[0].dataset.section, "faults");
  assert.equal(body.children[1].dataset.section, "status");
  const jumps = panel.root.children.find((c) => c.className === "robot-panel-jumps");
  assert.equal(jumps.children[0].dataset.jumpSection, "faults");
  assert.equal(jumps.children[0].textContent, "오류");

  showFaults = false;
  panel.setRobot(profile, {});
  assert.equal(body.children[0].dataset.section, "status");
});

test("dockEntries and createRobotDock render multi-fault count badge via robotProfile and cap at 9+", (t) => {
  makeDom(t);
  const plain = robotProfile({ id: "rosy_01", kind: "mobile", online: true, evidence: "fresh", estop: true });
  assert.equal(Object.hasOwn(plain.alarm, "count"), false, "no count key when count is omitted");
  const profiles = [
    robotProfile({ id: "rosy_46", name: "46", kind: "mobile", online: true, evidence: "fresh", estop: true, alarm: { level: "danger", text: "최우선 2건", count: 3 } }),
    robotProfile({ id: "arm_a", name: "ARM_A", kind: "arm", online: true, evidence: "fresh", alarm: { level: "caution", text: "사건 12건", count: 12 } }),
  ];
  const entries = dockEntries(profiles);
  assert.equal(entries[0].marks[0].count, 3);
  assert.equal(entries[1].marks[0].count, 12);
  const dock = createRobotDock({ profiles });
  const counts = dock.root.querySelectorAll(".robot-dock-count").map((n) => n.textContent);
  assert.deepEqual(counts, ["3", "9+"]);
});

test("OMX armIncidentAlertRows retains canonical arm.id and arm.sourceId when label differs", () => {
  const armRows = armIncidentAlertRows({
    arms: [{
      id: "arm_a", sourceId: "omx_arm_a", label: "Arm A",
      openIncidents: [{ incident_id: "inc-1", decision: { hold: true } }],
      homeRecoveries: [],
    }],
  });
  const flat = [...armRows.crit, ...armRows.warn];
  const matched = flat.filter((r) => r.arm?.id === "arm_a" || r.arm?.sourceId === "omx_arm_a");
  assert.equal(matched.length, 1);
  assert.equal(matched[0].robotId, "Arm A");
});
