import { cssColor } from "/common/ui.js";
import { node } from "/common/control-dom.js";
import { owns } from "/console/assets/unit-scope.js";

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
  return { cell, label, val };
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

  function setCell(key, text, tone = "neutral", labelText = null) {
    const target = cells?.[key];
    if (!target) return;
    if (labelText && target.label.textContent !== labelText) target.label.textContent = labelText;
    if (target.val.textContent !== text) target.val.textContent = text;
    if (target.cell.dataset.tone !== tone) target.cell.dataset.tone = tone;
  }

  function update(view) {
    const critCount = el("critical-list")?.childElementCount || 0;
    const warnCount = el("warning-list")?.childElementCount || 0;
    const totalAlerts = critCount + warnCount;
    const obs = view.workcellObs;
    const sum = obs?.summary || null;

    if (!owns("drive") && owns("arms")) {
      const unitId = view.controlUnit?.unit_id || "ARM-CELL";
      const critTotal = critCount + (sum?.heldCount || 0) + (sum?.faultArmCount || 0);
      const warnTotal = warnCount + (sum?.warnArmCount || 0);
      setCell("online", view.stateUnavailable ? "연결 끊김" : unitId, view.stateUnavailable ? "crit" : "neutral", "관제 단위");
      setCell("mission", !sum ? "확인 중" : `${sum.armsFresh}/${sum.armsTotal} 실시간`, !sum ? "neutral" : sum.armsFresh > 0 ? "active" : "warn", "팔 피드백");
      setCell("battery", !sum ? "—" : `${sum.camsTotal}대`, sum?.camsTotal ? "neutral" : "warn", "셀 카메라");
      setCell("arms", !sum ? "—" : sum.heldCount > 0 ? `보류 ${sum.heldCount}` : sum.openIncidentCount > 0 ? `사건 ${sum.openIncidentCount}` : "이상 없음", sum?.heldCount > 0 ? "crit" : sum?.openIncidentCount > 0 ? "warn" : "neutral", "보류 · 사건");
      setCell("alerts", critTotal + warnTotal > 0 ? `위험 ${critTotal} · 주의 ${warnTotal}` : "없음", critTotal > 0 ? "crit" : warnTotal > 0 ? "warn" : "neutral", "경보");
      return;
    }

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
    const anchorHeld = anchors.filter(
      (a) => a.held === true || a.cell_status === "HOLD" || a.cell_status === "PAUSED_HUMAN",
    ).length;
    const anchorLive = anchors.filter((a) => a.live === true).length;
    const armTotal = sum?.armsTotal > 0 ? sum.armsTotal : anchors.length;
    const armHeld = sum?.armsTotal > 0 ? sum.heldCount : anchorHeld;
    const armReady = sum?.armsTotal > 0 ? sum.armsFresh : anchorLive;
    const armsText = armTotal === 0
      ? "—"
      : armHeld > 0
        ? `${armHeld}/${armTotal} HOLD`
        : armReady === 0
          ? `0/${armTotal} NO FEED`
          : `${armReady}/${armTotal} LIVE`;

    setCell(
      "online",
      view.stateUnavailable ? "LINK LOST" : `${online}/${total} ON`,
      view.stateUnavailable ? "crit" : online < total ? "warn" : "neutral",
      "FLEET",
    );
    setCell(
      "mission",
      activeCount > 0 ? `${activeCount} RUN` : "0 STBY",
      activeCount > 0 ? "active" : "neutral",
      "MISSION",
    );
    setCell(
      "battery",
      minBatt === null ? "—" : `${minBatt}%`,
      minBatt === null ? "neutral" : minBatt <= 15 ? "crit" : minBatt <= 30 ? "warn" : "neutral",
      "BATT MIN",
    );
    setCell(
      "arms",
      armsText,
      armHeld > 0 ? "crit" : (armTotal > 0 && armReady < armTotal) ? "warn" : "neutral",
      "OMX CELL",
    );
    setCell(
      "alerts",
      estopActive ? "E-STOP" : totalAlerts > 0 ? `${critCount}C · ${warnCount}W` : "0 CLEAR",
      estopActive || critCount > 0 ? "crit" : warnCount > 0 ? "warn" : "neutral",
      "ALERTS",
    );
  }

  return { update };
}

export function createTelemetryTrace() {
  const PLOT_HEIGHT = 44;
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
  let plotId = null;
  let plotTone = "primary";
  let currentBounds = null;
  let currentBoundsKey = "";
  let lastSeries = null;
  let disposed = false;
  let rendering = false;
  let pendingRedraw = false;
  let rafSync = 0;

  function colorsForTone(tone) {
    const stroke = cssColor(
      tone === "crit" ? "--status-crit" : tone === "warn" ? "--status-warn" : "--series-primary",
    );
    const fill = cssColor(tone === "crit" ? "--status-crit-a10" : "--surface-sheen");
    const grid = cssColor("--border-subtle");
    const warn = cssColor("--status-warn");
    const crit = cssColor("--status-crit");
    const bg = cssColor("--surface-canvas");
    return { stroke, fill, grid, warn, crit, bg };
  }

  const MAX_SAMPLES = 24;
  const SAMPLE_MIN_MS = 850;
  function ensureSeries(id, value, now = Date.now()) {
    let entry = history.get(id);
    if (!entry) {
      entry = { values: [value], lastAt: now };
      history.set(id, entry);
      return entry.values;
    }
    if (entry.values[entry.values.length - 1] !== value || now - entry.lastAt >= SAMPLE_MIN_MS) {
      entry.values.push(value);
      if (entry.values.length > MAX_SAMPLES) entry.values.shift();
      entry.lastAt = now;
    }
    return entry.values;
  }

  function scheduleSizeSync() {
    if (rafSync || disposed || typeof window.requestAnimationFrame !== "function") return;
    rafSync = window.requestAnimationFrame(() => {
      rafSync = 0;
      if (disposed || !plot || !plotHost.clientWidth) return;
      const w = Math.max(180, Math.floor(plotHost.clientWidth));
      if (Math.abs((plot.width || 0) - w) > 2) {
        plot.setSize({ width: w, height: PLOT_HEIGHT });
      }
    });
  }

  async function drawPlot(id, ys, tone, yBounds) {
    if (disposed) return;
    if (rendering) {
      pendingRedraw = true;
      return;
    }
    rendering = true;
    try {
      const UPlot = await loadUPlot();
      if (disposed) return;
      const latest = lastSeries || { id, ys, tone, yBounds };
      const useYs = latest.ys;
      const useTone = latest.tone;
      const useId = latest.id;
      const useBounds = latest.yBounds;
      const nextBoundsKey = useBounds ? useBounds.join(",") : "auto";
      currentBounds = useBounds;
      const xs = useYs.map((_, idx) => MAX_SAMPLES - useYs.length + idx);
      const { stroke, fill, grid, warn, crit, bg } = colorsForTone(useTone);
      const measured = Math.floor(plotHost.clientWidth || 0);
      const width = Math.max(180, measured || 256);
      if (!plot || plotTone !== useTone || plotId !== useId || currentBoundsKey !== nextBoundsKey) {
        plot?.destroy?.();
        plotHost.replaceChildren();
        plotId = useId;
        plotTone = useTone;
        currentBoundsKey = nextBoundsKey;
        const opts = {
          width,
          height: PLOT_HEIGHT,
          padding: [6, 8, 4, 2],
          pxAlign: 0,
          legend: { show: false },
          cursor: { show: false },
          select: { show: false },
          axes: [{ show: false }, { show: false }],
          scales: {
            x: { time: false, range: () => [0, MAX_SAMPLES - 1] },
            y: {
              range: (_u, dMin, dMax) => {
                if (currentBounds) return currentBounds;
                const pad = Math.max(40, (dMax - dMin) * 0.35, Math.abs(dMax) * 0.25);
                return [Math.max(0, dMin - pad), dMax + pad];
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
                if (currentBounds && currentBounds[0] === 0 && currentBounds[1] === 100) {
                  ctx.setLineDash([4, 4]);
                  ctx.globalAlpha = 0.35;
                  for (const [val, col] of [[25, warn], [15, crit]]) {
                    const py = Math.round(u.valToPos(val, "y", true)) + 0.5;
                    ctx.strokeStyle = col;
                    ctx.beginPath();
                    ctx.moveTo(bbox.left, py);
                    ctx.lineTo(bbox.left + bbox.width, py);
                    ctx.stroke();
                  }
                }
                ctx.restore();
              },
            ],
            draw: [
              (u) => {
                const dxs = u.data?.[0] || [];
                const dys = u.data?.[1] || [];
                const lastIdx = dxs.length - 1;
                const lastY = dys[lastIdx];
                if (lastIdx < 0 || typeof lastY !== "number") return;
                const px = u.valToPos(dxs[lastIdx], "x", true);
                const py = u.valToPos(lastY, "y", true);
                if (!Number.isFinite(px) || !Number.isFinite(py)) return;
                const dpr = window.devicePixelRatio || 1;
                const { ctx } = u;
                ctx.save();
                ctx.fillStyle = stroke;
                ctx.strokeStyle = bg;
                ctx.lineWidth = 1.5 * dpr;
                ctx.beginPath();
                ctx.arc(px, py, 3 * dpr, 0, Math.PI * 2);
                ctx.fill();
                ctx.stroke();
                ctx.restore();
              },
            ],
          },
          series: [{}, { stroke, fill, width: 2, points: { show: false } }],
        };
        plot = new UPlot(opts, [xs, useYs], plotHost);
      } else {
        plot.setData([xs, useYs]);
        if (measured > 0 && Math.abs((plot.width || 0) - width) > 2) {
          plot.setSize({ width, height: PLOT_HEIGHT });
        }
      }
      if (!measured) scheduleSizeSync();
    } finally {
      rendering = false;
      if (pendingRedraw && !disposed && lastSeries) {
        pendingRedraw = false;
        void drawPlot(lastSeries.id, lastSeries.ys, lastSeries.tone, lastSeries.yBounds);
      }
    }
  }

  const onTheme = () => {
    if (!disposed && lastSeries) {
      plot?.destroy?.();
      plot = null;
      void drawPlot(lastSeries.id, lastSeries.ys, lastSeries.tone, lastSeries.yBounds);
    }
  };
  document.addEventListener("rosy:theme", onTheme);

  const resize = typeof ResizeObserver === "function"
    ? new ResizeObserver(() => {
        if (!disposed && plot && plotHost.clientWidth > 0) {
          const w = Math.max(180, Math.floor(plotHost.clientWidth));
          if (Math.abs((plot.width || 0) - w) > 4) plot.setSize({ width: w, height: PLOT_HEIGHT });
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
        pendingRedraw = false;
        plot?.destroy?.();
        plot = null;
        plotId = null;
        plotHost.replaceChildren();
        return;
      }
      const ys = ensureSeries(id, value);
      const lo = Math.min(...ys);
      const hi = Math.max(...ys);
      metaEl.textContent = ys.length < 2
        ? "1 SAMPLE"
        : Math.round(lo) === Math.round(hi) ? "STEADY" : `${Math.round(lo)}–${Math.round(hi)}${unit}`;
      const yBounds = typeof minBound === "number" && typeof maxBound === "number" ? [minBound, maxBound] : null;
      lastSeries = { id, ys: [...ys], tone, yBounds };
      void drawPlot(id, lastSeries.ys, tone, yBounds);
    },
    clear() {
      lastSeries = null;
      pendingRedraw = false;
      plot?.destroy?.();
      plot = null;
      plotId = null;
      plotHost.replaceChildren();
    },
    dispose() {
      disposed = true;
      pendingRedraw = false;
      if (rafSync && typeof window.cancelAnimationFrame === "function") {
        window.cancelAnimationFrame(rafSync);
        rafSync = 0;
      }
      document.removeEventListener("rosy:theme", onTheme);
      resize?.disconnect();
      plot?.destroy?.();
      plot = null;
      plotId = null;
      history.clear();
    },
  };
}
