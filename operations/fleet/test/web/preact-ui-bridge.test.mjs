import test from "node:test";
import assert from "node:assert/strict";

const vendor = await import("/common/vendor/htm-preact.esm.min.js");
const preactUi = await import("/common/preact-ui.js");
const hosts = await import("/console/assets/cockpit-hosts.js");

test("vendored htm/preact, UiButton bridge, and cockpit hosts export clean ESM symbols", () => {
  for (const sym of ["html", "render", "useEffect", "useRef", "useState", "useMemo"]) {
    assert.equal(typeof vendor[sym], "function", `missing vendor export ${sym}`);
  }
  assert.equal(typeof preactUi.UiButton, "function");
  for (const sym of ["Robot3dHost", "TelemetryChartHost", "PanelKvList"]) {
    assert.equal(typeof hosts[sym], "function", `missing host export ${sym}`);
  }
  const kvVnode = hosts.PanelKvList({ rows: [["ID", "rosy_01"], ["연결", undefined]] });
  assert.equal(kvVnode.type, "dl");
  assert.equal(kvVnode.props.class, "robot-panel-kv");
});
