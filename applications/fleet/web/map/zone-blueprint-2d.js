// SVG-only 2D site-floor & arm-cell slot/tier blueprint renderer using CSS tokens only.

import { placeText } from "/common/map-rules.js";

const SVG_NS = "http://www.w3.org/2000/svg";

function svgNode(tag, attrs = {}, text = null) {
  const node = document.createElementNS(SVG_NS, tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value !== null && value !== undefined) node.setAttribute(key, String(value));
  }
  if (text !== null && text !== undefined) node.textContent = String(text);
  return node;
}

function htmlBtn(text, className, attrs = {}) {
  const btn = document.createElement("ui-button");
  btn.setAttribute("kind", "quiet");
  btn.setAttribute("type", "button");
  btn.setAttribute("data-work-read", "");
  if (className) btn.className = className;
  for (const [k, v] of Object.entries(attrs)) btn.setAttribute(k, String(v));
  btn.textContent = text;
  return btn;
}

export function createZoneBlueprint2d(host, { onSelect } = {}) {
  const wrap = document.createElement("div");
  wrap.className = "zb-svg-wrap";

  function bindSelect(target, zoneId, label = zoneId) {
    target.setAttribute("tabindex", "0");
    target.setAttribute("role", "button");
    target.setAttribute("aria-label", label);
    target.addEventListener("click", () => onSelect?.(zoneId));
    target.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        onSelect?.(zoneId);
      }
    });
  }

  function renderArmCell(model, activeZone) {
    const toolbar = document.createElement("div");
    toolbar.className = "zb-arm-tabs";
    toolbar.append(htmlBtn("현장 평면도 (m)", "zb-arm-tab", { "data-selected": "false" }));
    toolbar.firstElementChild.addEventListener("click", () => {
      const floorItem = model.items.find((item) => item.category !== "arm_zone");
      if (floorItem) onSelect?.(floorItem.id);
    });
    for (const z of model.armZones) {
      const btn = htmlBtn(`${z.label} (${z.id})`, "zb-arm-tab", {
        "data-selected": String(z.id === activeZone.id),
        "aria-pressed": String(z.id === activeZone.id),
      });
      btn.addEventListener("click", () => onSelect?.(z.id));
      toolbar.append(btn);
    }

    const gridWrap = document.createElement("div");
    gridWrap.className = "zb-arm-grid";
    if (!(activeZone.slots && activeZone.slots.length)) {
      const empty = document.createElement("p");
      empty.className = "hint zb-empty";
      empty.textContent = "등록된 슬롯이 없습니다 · 실측 대기";
      gridWrap.append(empty);
      wrap.replaceChildren(toolbar, gridWrap);
      return;
    }
    const cols = Math.max(1, activeZone.grid?.columns || 3);
    const rows = Math.max(1, activeZone.grid?.rows || 1);
    const cellW = 110;
    const rowH = 128;
    const padX = 36;
    const padY = 44;
    const vw = padX * 2 + cols * cellW;
    const vh = padY * 2 + rows * rowH;

    const svg = svgNode("svg", {
      class: "zb-svg",
      viewBox: `0 0 ${vw} ${vh}`,
      role: "img",
      "aria-label": `${activeZone.label} ${rows}행 ${cols}열 슬롯 도면`,
    });
    svg.append(svgNode("text", { x: padX, y: 24, class: "zb-label" },
      `${activeZone.label} (${activeZone.id}) · ${rows}행 × ${cols}열 × ${activeZone.grid?.tiers || 1}단 · 층고 ${model.tierHeightMm} mm`));

    for (let c = 1; c <= cols; c++) {
      const cx = padX + (c - 0.5) * cellW;
      svg.append(svgNode("text", { x: cx, y: vh - 12, "text-anchor": "middle", class: "zb-sublabel" }, `${c}열`));
    }
    if (activeZone.holdBoundary?.columns?.length === 2) {
      const bx = padX + activeZone.holdBoundary.columns[0] * cellW;
      svg.append(svgNode("line", { x1: bx, y1: padY - 8, x2: bx, y2: vh - padY + 8, class: "zb-hold-line" }));
    }

    for (const slot of activeZone.slots || []) {
      const [cStart, cEnd] = slot.columns?.length >= 2 ? slot.columns : [1, cols];
      const span = Math.max(1, cEnd - cStart + 1);
      const sx = padX + (cStart - 1) * cellW + 6;
      const sy = padY + (slot.row - 1) * rowH + 6;
      const sw = span * cellW - 12;
      const sh = rowH - 14;
      const g = svgNode("g", { class: "zb-node zb-node-arm", "data-zone-id": activeZone.id, "data-selected": "true" });
      g.append(svgNode("rect", { x: sx, y: sy, width: sw, height: sh, rx: 6, class: "zb-slot-rect" }));
      g.append(svgNode("text", { x: sx + 10, y: sy + 20, class: "zb-label" }, `${slot.label} · ${slot.id}`));
      g.append(svgNode("text", { x: sx + 10, y: sy + 36, class: "zb-sublabel" },
        `팔 ${(slot.arms || []).join(", ") || "—"}${slot.hold ? ` · Hold ${slot.hold}` : ""}`));
      const tiers = slot.tiers || [];
      tiers.forEach((tier, idx) => {
        const ty = sy + 46 + idx * 22;
        g.append(svgNode("rect", { x: sx + 10, y: ty, width: sw - 20, height: 18, rx: 4, class: "zb-tier-chip" }));
        g.append(svgNode("text", { x: sx + 16, y: ty + 13, class: "zb-sublabel" },
          `T${tier.tier} · ${tier.item || tier.id}`));
      });
      svg.append(g);
    }
    gridWrap.append(svg);
    wrap.replaceChildren(toolbar, gridWrap);
  }

  function renderFloorPlan(model, selectedId, filterCategory) {
    const W = 760;
    const H = 480;
    const PAD = 48;
    const b = model.worldBounds;
    const spanX = Math.max(0.4, b.maxX - b.minX);
    const spanY = Math.max(0.4, b.maxY - b.minY);
    const scale = Math.min((W - PAD * 2) / spanX, (H - PAD * 2) / spanY);
    const px = (x) => PAD + (x - b.minX) * scale;
    const py = (y) => H - PAD - (y - b.minY) * scale;

    const svg = svgNode("svg", {
      class: "zb-svg",
      viewBox: `0 0 ${W} ${H}`,
      role: "img",
      "aria-label": "현장 구역 2D 평면도",
    });

    const x0 = Math.floor(b.minX * 2) / 2;
    const y0 = Math.floor(b.minY * 2) / 2;
    for (let gx = x0; gx <= b.maxX; gx += 0.5) {
      const sx = px(gx);
      svg.append(svgNode("line", { x1: sx, y1: PAD, x2: sx, y2: H - PAD, class: "zb-grid-line" }));
      svg.append(svgNode("text", { x: sx, y: H - PAD + 16, "text-anchor": "middle", class: "zb-sublabel" }, gx.toFixed(1)));
    }
    for (let gy = y0; gy <= b.maxY; gy += 0.5) {
      const sy = py(gy);
      svg.append(svgNode("line", { x1: PAD, y1: sy, x2: W - PAD, y2: sy, class: "zb-grid-line" }));
      svg.append(svgNode("text", { x: PAD - 8, y: sy + 4, "text-anchor": "end", class: "zb-sublabel" }, gy.toFixed(1)));
    }
    svg.append(svgNode("line", { x1: PAD, y1: H - PAD, x2: W - PAD, y2: H - PAD, class: "zb-axis" }));
    svg.append(svgNode("line", { x1: PAD, y1: PAD, x2: PAD, y2: H - PAD, class: "zb-axis" }));
    svg.append(svgNode("text", { x: W - PAD, y: H - PAD + 32, "text-anchor": "end", class: "zb-sublabel" }, "+X (m) → · +Y (m) ↑"));

    const showCat = (cat) => filterCategory === "all" || filterCategory === cat;
    const stopById = new Map(model.stops.map((s) => [s.id, s]));

    if (showCat("stop")) {
      for (const h of model.handoffs || []) {
        const fromStop = stopById.get(h.vehicle_stop_id);
        const toStop = stopById.get(h.vehicle_exit_stop_id);
        if (fromStop && toStop && Number.isFinite(fromStop.x) && Number.isFinite(toStop.x)) {
          svg.append(svgNode("line", {
            x1: px(fromStop.x), y1: py(fromStop.y),
            x2: px(toStop.x), y2: py(toStop.y),
            class: "zb-handoff-line",
          }));
        }
      }
      for (const s of model.stops) {
        if (!Number.isFinite(s.x) || !Number.isFinite(s.y)) continue;
        if (Array.isArray(s.stopZone) && s.stopZone.length >= 3) {
          const pts = s.stopZone.map((pt) => `${px(Number(pt[0])).toFixed(1)},${py(Number(pt[1])).toFixed(1)}`).join(" ");
          svg.append(svgNode("polygon", { points: pts, class: "zb-stop-zone" }));
        }
        const g = svgNode("g", { class: "zb-node zb-node-stop", "data-zone-id": s.id, "data-selected": String(s.id === selectedId) });
        g.append(svgNode("circle", { cx: px(s.x), cy: py(s.y), r: 11 }));
        g.append(svgNode("text", { x: px(s.x) + 14, y: py(s.y) + 4, class: "zb-label" }, s.id));
        bindSelect(g, s.id, `정류장 ${placeText(s)} 선택`);
        svg.append(g);
      }
    }

    if (showCat("staging")) {
      for (const bay of model.stagingBays) {
        if (!Number.isFinite(bay.x) || !Number.isFinite(bay.y)) continue;
        const cx = px(bay.x), cy = py(bay.y);
        const g = svgNode("g", { class: "zb-node zb-node-staging", "data-zone-id": bay.id, "data-selected": String(bay.id === selectedId) });
        g.append(svgNode("rect", { x: cx - 12, y: cy - 9, width: 24, height: 18, rx: 3 }));
        g.append(svgNode("text", { x: cx + 16, y: cy + 4, class: "zb-label" }, bay.id));
        bindSelect(g, bay.id, `임시 대기칸 ${placeText(bay)} 선택`);
        svg.append(g);
      }
    }

    if (showCat("export")) {
      for (const st of model.exportStations) {
        if (!Number.isFinite(st.x) || !Number.isFinite(st.y)) continue;
        const cx = px(st.x), cy = py(st.y);
        const g = svgNode("g", { class: "zb-node zb-node-export", "data-zone-id": st.id, "data-selected": String(st.id === selectedId) });
        g.append(svgNode("polygon", { points: `${cx},${cy - 12} ${cx + 12},${cy} ${cx},${cy + 12} ${cx - 12},${cy}` }));
        g.append(svgNode("text", { x: cx + 15, y: cy + 4, class: "zb-label" }, st.id));
        bindSelect(g, st.id, `반출대 ${placeText(st)} 선택`);
        svg.append(g);
      }
    }

    if (model.armZones.length) {
      const strip = document.createElement("div");
      strip.className = "zb-arm-tabs";
      for (const z of model.armZones) {
        const btn = htmlBtn(`셀 구역: ${z.label} (${z.grid.rows}×${z.grid.columns}×${z.grid.tiers})`, "zb-arm-tab", {
          "data-selected": String(z.id === selectedId),
        });
        btn.addEventListener("click", () => onSelect?.(z.id));
        strip.append(btn);
      }
      wrap.replaceChildren(strip, svg);
    } else {
      wrap.replaceChildren(svg);
    }
  }

  return {
    render(model, selectedId, filterCategory = "all") {
      host.replaceChildren(wrap);
      if (!model?.items?.length) {
        const empty = document.createElement("p");
        empty.className = "hint zb-empty";
        empty.textContent = "표시할 구역 정보가 없습니다.";
        wrap.replaceChildren(empty);
        return;
      }
      const armZone = model.armZones.find((z) => z.id === selectedId);
      if (armZone || filterCategory === "arm_zone") {
        const target = armZone || model.armZones[0];
        if (target) { renderArmCell(model, target); return; }
      }
      renderFloorPlan(model, selectedId, filterCategory);
    },
    dispose() {
      wrap.replaceChildren();
    },
  };
}
