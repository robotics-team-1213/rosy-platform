import { html, render } from "/common/vendor/htm-preact.esm.min.js";
import { cssColor } from "/common/ui.js";
import { node, patchText } from "/common/control-dom.js";
import { owns } from "/console/assets/unit-scope.js";
import { powerHealthView } from "/console/assets/power-health-view.js";

let uPlotLoader = null;
function loadUPlot() {
  if (!uPlotLoader) {
    uPlotLoader = import("/common/vendor/uPlot.esm.min.js").then((mod) => mod.default || mod);
  }
  return uPlotLoader;
}

function CockpitHudCells({ items }) {
  return html`${items.map((item) => html`
    <div
      class="cockpit-hud-cell"
      key=${item.key}
      data-hud-key=${item.key}
      data-tone=${item.tone}
      title=${item.title || undefined}
    >
      <span class="cockpit-hud-label">${item.label}</span>
      <strong class="cockpit-hud-val">${item.text}</strong>
    </div>
  `)}`;
}

export function createCockpitHud({ el }) {
  const pathbar = document.querySelector(".fleet-workspace > .ui-pathbar");
  if (!pathbar) return { update() {} };

  let hud = el("cockpit-hud");
  if (!hud) {
    hud = document.createElement("div");
    hud.id = "cockpit-hud";
    hud.className = "cockpit-hud";
    hud.setAttribute("role", "region");
    hud.setAttribute("aria-label", "함대 계기 요약");
    pathbar.append(hud);
  }

  let lastHudSig = "";
  function renderItems(items) {
    const sig = JSON.stringify(items);
    if (sig === lastHudSig) return;
    lastHudSig = sig;
    render(html`<${CockpitHudCells} items=${items} />`, hud);
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
      renderItems([
        { key: "online", label: "관제 단위", text: view.stateUnavailable ? "연결 끊김" : unitId, tone: view.stateUnavailable ? "crit" : "neutral" },
        { key: "mission", label: "팔 피드백", text: !sum ? "확인 중" : `${sum.armsFresh}/${sum.armsTotal} 실시간`, tone: !sum ? "neutral" : sum.armsFresh > 0 ? "active" : "warn" },
        { key: "battery", label: "셀 카메라", text: !sum ? "—" : view.cellCamChecked ? `${view.cellLiveCamCount ?? 0}/${sum.camsTotal} 실시간` : `${sum.camsTotal}대`, tone: view.cellCamChecked ? ((view.cellLiveCamCount ?? 0) > 0 ? "active" : "warn") : (sum?.camsTotal ? "neutral" : "warn") },
        { key: "arms", label: "보류 · 사건", text: !sum ? "—" : sum.heldCount > 0 ? `보류 ${sum.heldCount}` : sum.openIncidentCount > 0 ? `사건 ${sum.openIncidentCount}` : "이상 없음", tone: sum?.heldCount > 0 ? "crit" : sum?.openIncidentCount > 0 ? "warn" : "neutral" },
        { key: "alerts", label: "경보", text: critTotal + warnTotal > 0 ? `위험 ${critTotal} · 주의 ${warnTotal}` : "없음", tone: critTotal > 0 ? "crit" : warnTotal > 0 ? "warn" : "neutral" },
      ]);
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

    const nowMs = Date.now();
    const validPcts = view.stateUnavailable ? [] : onlineRobots
      .map((r) => powerHealthView(r, view.receivedAtMs, nowMs).percent)
      .filter((n) => n !== null);
    const minBatt = validPcts.length ? Math.min(...validPcts) : null;
    const battText = online === 0 || view.stateUnavailable ? "—"
      : minBatt === null ? "확인 불가"
      : validPcts.length < online ? `${minBatt}% (${validPcts.length}/${online})`
      : `${minBatt}%`;
    const battTone = online === 0 || view.stateUnavailable ? "neutral"
      : minBatt === null ? (view.stateLoaded ? "warn" : "neutral")
      : minBatt <= 15 ? "crit" : minBatt <= 30 ? "warn" : "neutral";
    const battTitle = online === 0 || view.stateUnavailable ? ""
      : minBatt === null ? "유효 배터리 근거 없음"
      : validPcts.length < online ? `유효 배터리 근거 ${validPcts.length}/${online}대 기준 최저값`
      : "";

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

    renderItems([
      { key: "online", label: "로봇", text: view.stateUnavailable ? "연결 끊김" : `${online}/${total} ON`, tone: view.stateUnavailable ? "crit" : online < total ? "warn" : "neutral" },
      { key: "mission", label: "운행", text: activeCount > 0 ? `${activeCount} RUN` : "0 STBY", tone: activeCount > 0 ? "active" : "neutral" },
      { key: "battery", label: "최저 배터리", text: battText, tone: battTone, title: battTitle },
      { key: "arms", label: "셀 팔", text: armsText, tone: armHeld > 0 ? "crit" : (armTotal > 0 && armReady < armTotal) ? "warn" : "neutral" },
      { key: "alerts", label: "경보", text: estopActive ? "E-STOP" : totalAlerts > 0 ? `위험 ${critCount} · 주의 ${warnCount}` : "이상 없음", tone: estopActive || critCount > 0 ? "crit" : warnCount > 0 ? "warn" : "neutral" },
    ]);
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
  const SAMPLE_MIN_MS = 5000;
  function ensureSeries(id, value, now = Date.now()) {
    let entry = history.get(id);
    if (!entry) {
      entry = { values: [value], lastAt: now };
      history.set(id, entry);
      return { values: entry.values, changed: true };
    }
    if (entry.values[entry.values.length - 1] !== value || now - entry.lastAt >= SAMPLE_MIN_MS) {
      entry.values.push(value);
      if (entry.values.length > MAX_SAMPLES) entry.values.shift();
      entry.lastAt = now;
      return { values: entry.values, changed: true };
    }
    return { values: entry.values, changed: false };
  }

  function measurePlotWidth() {
    return Math.floor(plotHost.clientWidth || head.clientWidth || root.clientWidth || 0);
  }

  function scheduleSizeSync() {
    if (rafSync || disposed || typeof window.requestAnimationFrame !== "function") return;
    rafSync = window.requestAnimationFrame(() => {
      rafSync = 0;
      const w = measurePlotWidth();
      if (disposed || !plot || !w) return;
      const clamped = Math.max(180, w);
      if (Math.abs((plot.width || 0) - clamped) > 2) {
        plot.setSize({ width: clamped, height: PLOT_HEIGHT });
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
      const measured = measurePlotWidth();
      if (!measured && typeof ResizeObserver === "function") return;
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
        const measured = measurePlotWidth();
        if (disposed || !measured) return;
        if (!plot && lastSeries && !rendering) {
          void drawPlot(lastSeries.id, lastSeries.ys, lastSeries.tone, lastSeries.yBounds);
          return;
        }
        if (plot) {
          const w = Math.max(180, measured);
          if (Math.abs((plot.width || 0) - w) > 2) plot.setSize({ width: w, height: PLOT_HEIGHT });
        }
      })
    : null;
  resize?.observe(root);
  resize?.observe(plotHost);

  return {
    root,
    update({ id, title = "TELEMETRY", readout = "—", value = null, unit = "", minBound = null, maxBound = null, tone = "primary" } = {}) {
      if (disposed) return;
      patchText(titleEl, title);
      patchText(valueEl, readout);
      if (typeof value !== "number" || !Number.isFinite(value) || !id) {
        patchText(metaEl, "NO DATA");
        if (lastSeries || plot || plotHost.childElementCount) {
          lastSeries = null;
          pendingRedraw = false;
          plot?.destroy?.();
          plot = null;
          plotId = null;
          plotHost.replaceChildren();
        }
        return;
      }
      const { values: ys, changed } = ensureSeries(id, value);
      const lo = Math.min(...ys);
      const hi = Math.max(...ys);
      const nextMeta = ys.length < 2
        ? "1 SAMPLE"
        : Math.round(lo) === Math.round(hi) ? "STEADY" : `${Math.round(lo)}–${Math.round(hi)}${unit}`;
      patchText(metaEl, nextMeta);
      const yBounds = typeof minBound === "number" && typeof maxBound === "number" ? [minBound, maxBound] : null;
      const nextBoundsKey = yBounds ? yBounds.join(",") : "auto";
      if (!changed && plot && plotId === id && plotTone === tone && currentBoundsKey === nextBoundsKey) return;
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
