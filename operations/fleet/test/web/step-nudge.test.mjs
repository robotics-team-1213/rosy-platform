import test from "node:test";
import assert from "node:assert/strict";

const { register } = await import("node:module");
register("./common-loader.mjs", import.meta.url);
const { createStepNudge, reportingOff, stepRefusalText } = await import("../../../../applications/fleet/web/robot/step-nudge.js");

function fakeEl(tagName = "div") {
  const attributes = new Map();
  const listeners = new Map();
  const el = {
    tagName: tagName.toUpperCase(),
    localName: tagName.toLowerCase(),
    isConnected: true,
    hidden: false,
    disabled: false,
    textContent: "",
    className: "",
    dataset: {},
    children: [],
    parentNode: null,
    getAttribute: (name) => (attributes.has(name) ? attributes.get(name) : null),
    setAttribute: (name, value) => attributes.set(name, String(value)),
    removeAttribute: (name) => attributes.delete(name),
    hasAttribute: (name) => attributes.has(name),
    append(...items) {
      for (const item of items) {
        if (typeof item === "string") el.textContent += item;
        else { item.parentNode = el; el.children.push(item); }
      }
    },
    addEventListener(type, fn) {
      if (!listeners.has(type)) listeners.set(type, []);
      listeners.get(type).push(fn);
    },
    dispatchEvent(event) {
      for (const fn of listeners.get(event.type) || []) fn(event);
    },
    click() {
      if (el.disabled) return;
      el.dispatchEvent({ type: "click", preventDefault() {}, stopImmediatePropagation() {} });
    },
  };
  return el;
}

function withFakeDom(fn) {
  const prev = globalThis.document;
  globalThis.document = { createElement: (tag) => fakeEl(tag) };
  try { return fn(); }
  finally { globalThis.document = prev; }
}

test("reportingOff detects disabled loc_assist or null localization", () => {
  assert.equal(reportingOff({ robot_id: "r1", localization: null }), true);
  assert.equal(reportingOff({ robot_id: "r1", localization: { reporting: false } }), true);
  assert.equal(reportingOff({ robot_id: "r1", capabilities: { loc_assist: false } }), true);
  assert.equal(reportingOff({ robot_id: "r1", localization: { state: "LOCALIZED" } }), false);
});

test("stepRefusalText maps every server refusal to Korean operator copy", () => {
  assert.match(stepRefusalText({ code: "STEP_ROBOT_BUSY", holder: "trip-9" }), /trip-9/);
  assert.equal(stepRefusalText({ code: "ROBOT_OFFLINE" }), "로봇이 오프라인입니다");
  assert.equal(stepRefusalText({ code: "UNKNOWN_ROBOT" }), "등록되지 않은 로봇입니다");
  assert.equal(stepRefusalText({ message: "path_not_clear" }), "앞/뒤 막힘");
  assert.equal(stepRefusalText({ code: "TRIP_LEASED" }), "주행 임대 중이라 이동할 수 없습니다");
  assert.equal(stepRefusalText({ message: "calibration_lease" }), "보정 임대 중이라 이동할 수 없습니다");
  assert.equal(stepRefusalText({ message: "nav not ready" }), "내비게이션이 준비되지 않았습니다");
  assert.equal(stepRefusalText({ message: "D-395 reporting required" }), "위치 보고가 꺼져 있음");
});

test("createStepNudge sends one POST while running, ignores repeat keydown, and locks when reporting is off", async () => {
  await withFakeDom(async () => {
    const calls = [];
    let locMission = { kind: "nudge_forward", state: "running" };
    const nudge = createStepNudge({
      pollMs: 5,
      call: async (path, opts) => {
        calls.push({ path, opts });
        if (path.endsWith("/localization")) return { mission: locMission };
        return { accepted: true };
      },
    });

    const offPanel = nudge.renderPanel({ robot: { robot_id: "rosy_01", online: true, localization: null } });
    const [offFwd, offBwd] = offPanel.element.children[0].children;
    const offCause = offPanel.element.children[2];
    assert.equal(offFwd.disabled, true);
    assert.equal(offBwd.disabled, true);
    assert.equal(offCause.textContent, "위치 보고가 꺼져 있음");
    assert.equal(offFwd.getAttribute("aria-describedby"), offCause.id);

    const onPanel = nudge.renderPanel({ robot: { robot_id: "rosy_02", online: true, localization: { state: "LOCALIZED" } } });
    const [fwd, bwd] = onPanel.element.children[0].children;
    assert.equal(fwd.disabled, false);

    // Repeat keydown must not trigger a step
    let prevented = false;
    fwd.dispatchEvent({
      type: "keydown", key: "Enter", repeat: true,
      preventDefault() { prevented = true; }, stopImmediatePropagation() {},
    });
    assert.equal(prevented, true);
    assert.equal(calls.length, 0);

    // First click sends one POST and disables both buttons until localization mission is done
    fwd.click();
    assert.equal(fwd.disabled, true);
    assert.equal(bwd.disabled, true);
    fwd.click();
    bwd.click();
    await new Promise((r) => setTimeout(r, 20));
    const stepPosts = calls.filter((c) => c.path.endsWith("/step"));
    assert.equal(stepPosts.length, 1);
    assert.deepEqual(JSON.parse(stepPosts[0].opts.body), { direction: "forward", distance_m: 0.1 });

    // Once localization reports done, buttons re-enable
    locMission = { kind: "nudge_forward", state: "done" };
    await new Promise((r) => setTimeout(r, 25));
    assert.equal(fwd.disabled, false);
    assert.equal(bwd.disabled, false);
  });
});

test("createStepNudge stops polling after repeated localization errors and aborts cleanly on scope dispose", async () => {
  await withFakeDom(async () => {
    let locCalls = 0;
    const disposeHandlers = [];
    const ac = new AbortController();
    const nudge = createStepNudge({
      pollMs: 2,
      maxPollErrors: 3,
      scope: { signal: ac.signal, onDispose(fn) { disposeHandlers.push(fn); } },
      call: async (path) => {
        if (path.endsWith("/localization")) {
          locCalls += 1;
          throw new Error("LOC_UNAVAILABLE");
        }
        return { accepted: true };
      },
    });

    const panel = nudge.renderPanel({ robot: { robot_id: "rosy_03", online: true, localization: { state: "LOCALIZED" } } });
    const [fwd] = panel.element.children[0].children;
    fwd.click();
    assert.equal(fwd.disabled, true);
    await new Promise((r) => setTimeout(r, 35));
    assert.equal(locCalls, 3);
    assert.equal(fwd.disabled, false);

    // Trigger again and dispose scope mid-flight: no background polling continues.
    fwd.click();
    const callsAtDispose = locCalls;
    ac.abort();
    for (const fn of disposeHandlers) fn();
    await new Promise((r) => setTimeout(r, 20));
    assert.ok(locCalls <= callsAtDispose + 1);
  });
});

test("createStepNudge clears errors and stays usable after pageScope.invalidate()", async () => {
  const { createPageScope } = await import("../../../../shared/web/scope.js");
  await withFakeDom(async () => {
    const events = { addEventListener() {}, removeEventListener() {} };
    const scope = createPageScope({ events });
    let failStep = true;
    let stepCalls = 0;
    const nudge = createStepNudge({
      pollMs: 2,
      scope,
      call: async (path) => {
        if (path.endsWith("/step")) {
          stepCalls += 1;
          if (failStep) throw new Error("PATH_NOT_CLEAR");
          return { accepted: true };
        }
        return { mission: { kind: "nudge_forward", state: "done" } };
      },
    });
    const panel = nudge.renderPanel({ robot: { robot_id: "rosy_03", online: true, localization: { state: "LOCALIZED" } } });
    const [fwd] = panel.element.children[0].children;
    const status = panel.element.children[1];
    fwd.click();
    await new Promise((r) => setTimeout(r, 10));
    assert.equal(stepCalls, 1);
    assert.equal(status.hidden, false);

    // Account/page invalidation clears prior error and lets subsequent clicks work cleanly.
    scope.invalidate();
    failStep = false;
    panel.sync();
    assert.equal(status.hidden, true);
    fwd.click();
    await new Promise((r) => setTimeout(r, 15));
    assert.equal(stepCalls, 2);
    assert.equal(nudge.isRunning("rosy_03"), false);
    scope.dispose();
  });
});
