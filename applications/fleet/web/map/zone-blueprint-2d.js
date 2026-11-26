// SVG 2D zone map: the active site map's lanes and places with the zone footprints on them. It reads the same
// model as the 3D view (zone-blueprint-model.js) and uses CSS tokens only.

const SVG_NS = "http://www.w3.org/2000/svg";
const ARROW = "M-6 4L6 0L-6 -4Z";

function svgNode(tag, attrs = {}, text = null) {
  const node = document.createElementNS(SVG_NS, tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value !== null && value !== undefined) node.setAttribute(key, String(value));
  }
  if (text !== null && text !== undefined) node.textContent = String(text);
  return node;
}

/** Point at fraction ``t`` of a polyline's screen length, with its heading in screen degrees. */
function along(points, t) {
  const lengths = points.slice(1).map((point, index) => Math.hypot(point[0] - points[index][0], point[1] - points[index][1]));
  const total = lengths.reduce((sum, value) => sum + value, 0);
  let walked = 0;
  for (let index = 0; index < lengths.length; index += 1) {
    if (walked + lengths[index] >= t * total || index === lengths.length - 1) {
      const fraction = lengths[index] === 0 ? 0 : (t * total - walked) / lengths[index];
      const [a, b] = [points[index], points[index + 1]];
      return {
        x: a[0] + (b[0] - a[0]) * fraction,
        y: a[1] + (b[1] - a[1]) * fraction,
        deg: (Math.atan2(b[1] - a[1], b[0] - a[0]) * 180) / Math.PI,
        total,
      };
    }
    walked += lengths[index];
  }
  return { x: points[0][0], y: points[0][1], deg: 0, total: 0 };
}

const average = (points) => points.reduce(([sx, sy], [x, y]) => [sx + x / points.length, sy + y / points.length], [0, 0]);

/** A body-frame offset (x forward, y left) of a parked robot, in map metres. */
function bodyPoint(footprint, dx, dy) {
  const c = Math.cos(footprint.yaw);
  const s = Math.sin(footprint.yaw);
  return [footprint.pose[0] + dx * c - dy * s, footprint.pose[1] + dx * s + dy * c];
}

export function createZoneBlueprint2d(host, { onSelect } = {}) {
  const wrap = document.createElement("div");
  wrap.className = "zb-svg-wrap";

  function bindSelect(target, zoneId, label) {
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

  function renderMap(model, selectedId, filterCategory) {
    const W = 960;
    const PAD = 56;
    const b = model.bounds;
    const spanX = Math.max(0.4, b.maxX - b.minX);
    const spanY = Math.max(0.4, b.maxY - b.minY);
    const H = Math.round(Math.min(760, Math.max(340, W * (spanY / spanX))));
    const scale = Math.min((W - PAD * 2) / spanX, (H - PAD * 2) / spanY);
    const ox = PAD + ((W - PAD * 2) - spanX * scale) / 2;
    const oy = H - PAD - ((H - PAD * 2) - spanY * scale) / 2;
    const toPx = (x, y) => {
      const [vx, vy] = model.project(x, y);
      return [ox + (vx - b.minX) * scale, oy - (vy - b.minY) * scale];
    };
    const pointsOf = (polygon) => polygon.map(([x, y]) => toPx(x, y).map((n) => n.toFixed(1)).join(",")).join(" ");

    const svg = svgNode("svg", { class: "zb-svg", viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": "현장 구역 2D 평면도" });

    // Metre grid. Labels are world metres: the view may be quarter-turned like every Fleet map (D-513 7).
    const step = 0.5;
    const turn = model.siteMap?.viewTurnDeg || 0;
    const axisIndex = turn % 180 ? 1 : 0;   // along the screen's horizontal axis lies world y when turned 90 or 270
    const tick = (value) => (Math.round(value * 10) / 10).toFixed(1);
    for (let vx = Math.floor(b.minX / step) * step; vx <= b.maxX; vx += step) {
      const x = ox + (vx - b.minX) * scale;
      svg.append(svgNode("line", { x1: x, y1: PAD - 20, x2: x, y2: H - PAD + 20, class: "zb-grid-line" }));
      svg.append(svgNode("text", { x, y: H - PAD + 34, "text-anchor": "middle", class: "zb-sublabel" },
        tick(model.unproject(vx, 0)[axisIndex])));
    }
    for (let vy = Math.floor(b.minY / step) * step; vy <= b.maxY; vy += step) {
      const y = oy - (vy - b.minY) * scale;
      svg.append(svgNode("line", { x1: PAD - 20, y1: y, x2: W - PAD + 20, y2: y, class: "zb-grid-line" }));
      svg.append(svgNode("text", { x: PAD - 26, y: y + 4, "text-anchor": "end", class: "zb-sublabel" },
        tick(model.unproject(0, vy)[1 - axisIndex])));
    }
    svg.append(svgNode("text", { x: PAD - 40, y: 20, class: "zb-sublabel" },
      model.siteMap ? `지도 ${model.siteMap.mapId} v${model.siteMap.version ?? "?"}` : "활성 사이트 맵 없음"));
    svg.append(svgNode("text", { x: W - PAD + 20, y: H - 8, "text-anchor": "end", class: "zb-sublabel" }, model.axisLabel));

    // Lanes at their real width; an arrow shows the direction of travel.
    for (const lane of model.lanes) {
      const points = lane.points.map(([x, y]) => toPx(x, y));
      const attrs = { points: pointsOf(lane.points) };
      svg.append(svgNode("polyline", { ...attrs, class: "zb-lane-edge", "stroke-width": (lane.widthM * scale + 2).toFixed(1) }));
      svg.append(svgNode("polyline", {
        ...attrs, class: `zb-lane${lane.driveMode === "free" ? " zb-lane-free" : ""}`, "stroke-width": (lane.widthM * scale).toFixed(1),
      }));
      const heads = lane.direction === "two_way" ? [[0.28, 0], [0.72, 180]] : [[0.5, 0]];
      for (const [t, flip] of heads) {
        const at = along(points, t);
        if (at.total < 26) continue;
        svg.append(svgNode("path", { d: ARROW, class: "zb-lane-arrow", transform: `translate(${at.x.toFixed(1)} ${at.y.toFixed(1)}) rotate(${(at.deg + flip).toFixed(1)})` }));
      }
    }

    const flagged = { overlap: new Set(), near: new Set(), stale_yaml: new Set() };
    for (const conflict of model.conflicts) for (const id of conflict.ids) flagged[conflict.kind]?.add(id);
    const flagClass = (id) => (flagged.overlap.has(id) ? " zb-conflict" : flagged.near.has(id) ? " zb-near" : flagged.stale_yaml.has(id) ? " zb-stale" : "");
    const categoryOf = new Map(model.items.map((item) => [item.id, item.category]));
    const isSelected = (footprint) => footprint.itemIds.includes(selectedId);
    const pick = (footprint) => footprint.itemIds.find((id) => categoryOf.get(id) === filterCategory) || footprint.itemIds[0];
    const centreOf = (footprint) => toPx(...average(footprint.polygon));

    // Fixed equipment as context; a cell zone on it is selectable.
    const areaLabels = [];
    for (const area of model.areas) {
      const id = `area:${area.id}`;
      const zone = area.zoneId ? model.footprints.find((footprint) => footprint.id === id) : null;
      const attrs = { points: pointsOf(area.polygon) };
      if (zone) {
        const g = svgNode("g", { class: `zb-node zb-foot zb-foot-cell_zone${flagClass(id)}`, "data-zone-id": area.zoneId, "data-selected": String(isSelected(zone)) });
        g.append(svgNode("polygon", { ...attrs, class: `zb-area zb-area-${area.kind} zb-status-${area.status}` }));
        svg.append(g);
        bindSelect(g, area.zoneId, `팔 셀 구역 ${area.name} 선택`);
      } else {
        const polygon = svgNode("polygon", { ...attrs, class: `zb-area zb-area-${area.kind} zb-status-${area.status}${flagClass(id)}` });
        polygon.append(svgNode("title", {}, `${area.name} · ${area.status}`));
        svg.append(polygon);
      }
      // A name that does not fit across a narrow area (the belt) is set out to its right.
      const px = area.polygon.map(([x, y]) => toPx(x, y));
      const [minX, maxX] = [Math.min(...px.map(([x]) => x)), Math.max(...px.map(([x]) => x))];
      const [minY, maxY] = [Math.min(...px.map(([, y]) => y)), Math.max(...px.map(([, y]) => y))];
      const needed = area.shortName.length * 11 + 6;
      const [cx, cy] = average(px);
      areaLabels.push(svgNode("text", maxX - minX < needed && maxY - minY > needed * 1.6
        ? { x: maxX + 10, y: (minY + maxY) / 2 + 4, "text-anchor": "start", class: "zb-area-label" }
        : { x: cx, y: cy + 4, "text-anchor": "middle", class: "zb-area-label" }, area.shortName));
    }
    // Names go on last, so an area drawn later (the belt's neighbour) cannot cover one.
    svg.append(...areaLabels);

    // Handoffs: the vehicle stop and the cell zone that meet (legend names the dashed line).
    const byPlace = new Map(model.footprints.filter((footprint) => footprint.placeId).map((footprint) => [footprint.placeId, footprint]));
    for (const link of model.links) {
      const from = byPlace.get(link.fromPlaceId);
      const to = model.footprints.find((footprint) => footprint.area?.zoneId === link.toZoneId) || byPlace.get(link.toPlaceId);
      if (!from || !to) continue;
      const [x1, y1] = centreOf(from);
      const [x2, y2] = centreOf(to);
      svg.append(svgNode("line", { x1, y1, x2, y2, class: "zb-handoff-line" }));
    }

    // Junctions are lane ends, not places a robot is sent to.
    const drawn = new Set(model.footprints.map((footprint) => footprint.placeId));
    for (const place of model.siteMap?.places || []) {
      if (drawn.has(place.id)) continue;
      const [cx, cy] = toPx(place.x, place.y);
      svg.append(svgNode("circle", { cx, cy, r: 2.5, class: "zb-junction" }));
      svg.append(svgNode("text", { x: cx + 6, y: cy - 5, class: "zb-sublabel" }, place.id));
    }

    // Where a robot stands at a stop or charge bay: its body at the place pose, the thick edge is the cargo tray.
    for (const footprint of model.footprints) {
      if (footprint.kind === "cell_zone") continue;
      const inFilter = filterCategory === "all" || footprint.itemIds.some((id) => categoryOf.get(id) === filterCategory);
      const zoneId = pick(footprint);
      const g = svgNode("g", {
        class: `zb-node zb-foot zb-foot-${footprint.kind}${isSelected(footprint) ? "" : inFilter ? "" : " zb-dim"}${flagClass(footprint.id)}`,
        "data-zone-id": zoneId,
        "data-selected": String(isSelected(footprint)),
      });
      g.append(svgNode("polygon", { points: pointsOf(footprint.polygon) }));
      if (footprint.anchor === "vehicle_body" && Number.isFinite(footprint.yaw)) {
        const edge = (dx, dy0, dy1) => [toPx(...bodyPoint(footprint, dx, dy0)), toPx(...bodyPoint(footprint, dx, dy1))];
        const [t1, t2] = edge(model.vehicle.rearM, model.vehicle.halfWidthM, -model.vehicle.halfWidthM);
        g.append(svgNode("line", { x1: t1[0], y1: t1[1], x2: t2[0], y2: t2[1], class: "zb-tray" }));
        const nose = toPx(...bodyPoint(footprint, model.vehicle.frontM, 0));
        const ahead = toPx(...bodyPoint(footprint, model.vehicle.frontM + 0.016, 0));
        g.append(svgNode("line", { x1: nose[0], y1: nose[1], x2: ahead[0], y2: ahead[1], class: "zb-nose" }));
      }
      const [cx, cy] = centreOf(footprint);
      g.append(svgNode("text", { x: cx, y: cy + 4, "text-anchor": "middle", class: "zb-label" }, footprint.placeId));
      svg.append(g);
      bindSelect(g, zoneId, `${footprint.kind === "charge" ? "충전 칸" : "정류장"} ${footprint.placeId} 선택`);
    }
    return svg;
  }

  function render(model, selectedId, filterCategory = "all") {
    host.replaceChildren(wrap);
    if (!model?.items?.length) {
      const empty = document.createElement("p");
      empty.className = "hint zb-empty";
      empty.textContent = "표시할 구역 정보가 없습니다.";
      wrap.replaceChildren(empty);
      return;
    }
    const legend = document.createElement("ul");
    legend.className = "zb-legend";
    legend.setAttribute("aria-label", "범례");
    for (const [swatch, text] of [
      ["lane", "차로 (화살표: 진행 방향, 폭: 실제 폭)"],
      ["stop", "정류장 정차 공간 (굵은 선: 짐칸)"],
      ["charge", "충전 칸"],
      ["cell", "팔 셀 구역"],
      ["kit", "작업대·설비 (실선: CAD 등록 후보, 점선: 사진 추정)"],
      ["link", "점선: 하역·반출 연결 (정류장과 팔 셀)"],
      ["conflict", "겹침"],
      ["near", "여유 2 cm 미만"],
    ]) {
      const li = document.createElement("li");
      li.append(Object.assign(document.createElement("span"), { className: `zb-swatch zb-swatch-${swatch}` }), document.createTextNode(text));
      legend.append(li);
    }
    wrap.replaceChildren(renderMap(model, selectedId, filterCategory), legend);
  }

  return {
    render,
    dispose() {
      wrap.replaceChildren();
    },
  };
}
