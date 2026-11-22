import { cssColor } from "/common/ui.js";
import { node } from "/common/control-dom.js";

let uPlotLoader = null;
function loadUPlot() {
  if (!uPlotLoader) {
    uPlotLoader = import("/common/vendor/uPlot.esm.min.js").then((mod) => mod.default || mod);
  }
  return uPlotLoader;
}

function makeHudCell(key, labelText) {
  const cell = document.createElement("div");
  cell.className = "cockpit-hud-cell";
  cell.dataset.hudKey = key;
  cell.dataset.tone = "neutral";
  const label = node("span", labelText, "cockpit-hud-label");
  const val = node("strong", "—", "cockpit-hud-val");
  cell.append(label, val);
  return { cell, val };
}

export function createCockpitHud({ el }) {
  const pathbar = document.querySelector(".fleet-workspace > .ui-pathbar");
  if (!pathbar) return { update() {} };

  let hud = el("cockpit-hud");
  let cells;
  if (!hud) {
    hud = document.createElement("div");
    hud.id = "cockpit-hud";
    hud.className = "cockpit-hud";
    hud.setAttribute("role", "region");
    hud.setAttribute("aria-label", "함대 계기 요약");
    cells = {
      online: makeHudCell("online", "FLEET"),
      mission: makeHudCell("mission", "MISSION"),
      battery: makeHudCell("battery", "BATT MIN"),
      arms: makeHudCell("arms", "OMX CELL"),
      alerts: makeHudCell("alerts", "ALERTS"),
    };
    for (const c of Object.values(cells)) hud.append(c.cell);
    pathbar.append(hud);
  }

  function setCell(key, text, tone = "neutral") {
    const target = cells?.[key];
    if (!target) return;
    if (target.val.textContent !== text) target.val.textContent = text;
    if (target.cell.dataset.tone !== tone) target.cell.dataset.tone = tone;
  }

  function update(view) {
    const robots = view.robots || [];
    const total = robots.length;
    const onlineRobots = robots.filter((r) => r.online);
    const online = onlineRobots.length;
    const estopActive = !view.stateUnavailable && robots.some((r) => r.state?.safety?.estop === true);
    const activeCount = robots.filter(
      (r) => r.online && (r.state?.navigation === "NAVIGATING" || r.goal),
    ).length;

    const pcts = onlineRobots
      .map((r) => {
        const s = r.state || {};
        const p = s.battery?.percent ?? r.power_health?.battery?.percent;
        if (typeof p === "number" && Number.isFinite(p)) return p;
        const frac = s.battery?.percentage;
        if (typeof frac === "number" && Number.isFinite(frac)) return frac <= 1 ? frac * 100 : frac;
        return null;
      })
      .filter((n) => n !== null);
    const minBatt = pcts.length ? Math.round(Math.min(...pcts)) : null;

    const anchors = view.anchors || [];
    const heldArms = anchors.filter(
      (a) => a.held === true || a.cell_status === "HOLD" || a.cell_status === "PAUSED_HUMAN",
    ).length;

    const critCount = el("critical-list")?.childElementCount || 0;
    const warnCount = el("warning-list")?.childElementCount || 0;
    const totalAlerts = critCount + warnCount;

    setCell(
      "online",
      view.stateUnavailable ? "LINK LOST" : `${online}/${total} ON`,
      view.stateUnavailable ? "crit" : online < total ? "warn" : "neutral",
    );
    setCell(
      "mission",
      activeCount > 0 ? `${activeCount} RUN` : "0 IDLE",
      activeCount > 0 ? "active" : "neutral",
    );
    setCell(
      "battery",
      minBatt === null ? "—" : `${minBatt}%`,
      minBatt === null ? "neutral" : minBatt <= 15 ? "crit" : minBatt <= 30 ? "warn" : "neutral",
    );
    setCell(
      "arms",
      anchors.length === 0 ? "—" : heldArms > 0 ? `${heldArms}/${anchors.length} HOLD` : `${anchors.length}/${anchors.length} OK`,
      heldArms > 0 ? "warn" : "neutral",
    );
    setCell(
      "alerts",
      estopActive ? "E-STOP" : totalAlerts > 0 ? `${critCount}C · ${warnCount}W` : "0 CLEAR",
      estopActive || critCount > 0 ? "crit" : warnCount > 0 ? "warn" : "neutral",
    );
  }

  return { update };
}

export function createTelemetryTrace() {
  const root = document.createElement("div");
  root.className = "telemetry-chart";

  const head = document.createElement("div");
  head.className = "telemetry-chart-head";
  const titleEl = node("span", "TELEMETRY", "telemetry-chart-title");
  const valueEl = node("strong", "—", "telemetry-chart-value");
  const metaEl = node("span", "—", "telemetry-chart-meta");
  head.append(titleEl, metaEl, valueEl);

  const plotHost = document.createElement("div");
  plotHost.className = "telemetry-chart-plot";
  root.append(head, plotHost);

  const history = new Map();
  let plot = null;
  let plotTone = "primary";
  let lastSeries = null;
  let disposed = false;
  let rendering = false;

  function colorsForTone(tone) {
    const stroke = cssColor(
      tone === "crit" ? "--status-crit" : tone === "warn" ? "--status-warn" : "--series-primary",
    );
    const fill = cssColor(tone === "crit" ? "--status-crit-a10" : "--surface-sheen");
    const grid = cssColor("--border-subtle");
    return { stroke, fill, grid };
  }

  function ensureSeries(id, value) {
    let series = history.get(id);
    if (!series) {
      series = Array.from({ length: 12 }, (_, idx) => (idx === 11 ? value : value));
      history.set(id, series);
      return series;
    }
    if (series[series.length - 1] !== value || series.length < 16) {
      series.push(value);
      if (series.length > 24) series.shift();
    }
    return series;
  }

  async function drawPlot(ys, tone, yBounds) {
    if (disposed || rendering) return;
    rendering = true;
    try {
      const UPlot = await loadUPlot();
      if (disposed) return;
      const xs = ys.map((_, idx) => idx);
      const { stroke, fill, grid } = colorsForTone(tone);
      const width = Math.max(180, Math.floor(plotHost.clientWidth || 256));
      if (!plot || plotTone !== tone) {
        plot?.destroy?.();
        plotHost.replaceChildren();
        plotTone = tone;
        const opts = {
          width,
          height: 64,
          pxAlign: 0,
          legend: { show: false },
          cursor: { show: false },
          select: { show: false },
          axes: [{ show: false }, { show: false }],
          scales: {
            x: { time: false },
            y: {
              range: (_u, dMin, dMax) => {
                if (yBounds) return yBounds;
                const span = Math.max(1, dMax - dMin);
                return [Math.max(0, dMin - span * 0.25), dMax + span * 0.25];
              },
            },
          },
          hooks: {
            drawClear: [
              (u) => {
                const { ctx, bbox } = u;
                if (!bbox.width || !bbox.height) return;
                ctx.save();
                ctx.strokeStyle = grid;
                ctx.lineWidth = 1;
                for (const frac of [0.25, 0.5, 0.75]) {
                  const y = Math.round(bbox.top + bbox.height * frac) + 0.5;
                  ctx.beginPath();
                  ctx.moveTo(bbox.left, y);
                  ctx.lineTo(bbox.left + bbox.width, y);
                  ctx.stroke();
                }
                ctx.restore();
              },
            ],
          },
          series: [{}, { stroke, fill, width: 2, points: { show: false } }],
        };
        plot = new UPlot(opts, [xs, ys], plotHost);
      } else {
        plot.setData([xs, ys]);
        if (Math.abs((plot.width || 0) - width) > 2) {
          plot.setSize({ width, height: 64 });
        }
      }
    } finally {
      rendering = false;
    }
  }

  const onTheme = () => {
    if (!disposed && lastSeries) {
      plot?.destroy?.();
      plot = null;
      drawPlot(lastSeries.ys, lastSeries.tone, lastSeries.yBounds);
    }
  };
  document.addEventListener("rosy:theme", onTheme);

  const resize = typeof ResizeObserver === "function"
    ? new ResizeObserver(() => {
        if (!disposed && plot && plotHost.clientWidth > 0) {
          const w = Math.max(180, Math.floor(plotHost.clientWidth));
          if (Math.abs((plot.width || 0) - w) > 4) plot.setSize({ width: w, height: 64 });
        }
      })
    : null;
  resize?.observe(plotHost);

  return {
    root,
    update({ id, title = "TELEMETRY", readout = "—", value = null, unit = "", minBound = null, maxBound = null, tone = "primary" } = {}) {
      if (disposed) return;
      titleEl.textContent = title;
      valueEl.textContent = readout;
      if (typeof value !== "number" || !Number.isFinite(value) || !id) {
        metaEl.textContent = "NO DATA";
        lastSeries = null;
        plot?.destroy?.();
        plot = null;
        plotHost.replaceChildren();
        return;
      }
      const ys = ensureSeries(id, value);
      const lo = Math.min(...ys);
      const hi = Math.max(...ys);
      metaEl.textContent = `${Math.round(lo)}–${Math.round(hi)}${unit}`;
      const yBounds = typeof minBound === "number" && typeof maxBound === "number" ? [minBound, maxBound] : null;
      lastSeries = { ys: [...ys], tone, yBounds };
      drawPlot(lastSeries.ys, tone, yBounds);
    },
    clear() {
      lastSeries = null;
      plot?.destroy?.();
      plot = null;
      plotHost.replaceChildren();
    },
    dispose() {
      disposed = true;
      document.removeEventListener("rosy:theme", onTheme);
      resize?.disconnect();
      plot?.destroy?.();
      plot = null;
      history.clear();
    },
  };
}
