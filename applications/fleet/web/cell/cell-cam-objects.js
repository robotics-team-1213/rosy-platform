// Clickable catalog-only detected object SVG overlay for OMX inspector and ARM-CELL stage.
const SVG_NS = "http://www.w3.org/2000/svg";
export const OBJECT_STALE_MS = 5000;

function svgEl(tag, attrs = {}, text = null) {
  const el = document.createElementNS(SVG_NS, tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v !== null && v !== undefined) el.setAttribute(k, String(v));
  }
  if (text !== null && text !== undefined) el.textContent = String(text);
  return el;
}

export function cellIdForCamView(camView) {
  if (!camView) return null;
  const text = [camView.id, camView.source, camView.source_id, camView.role, camView.stream, camView.label]
    .filter(Boolean).join(" ").toLowerCase();
  if (text.includes("wrist") || text.includes("side") || text.includes("depth") || text.includes("front")) return null;
  if (text.includes("arm_s") || text.includes("cell_s") || /\bs3\b/.test(text)) return "cell_s";
  if (
    text.includes("arm_a") || text.includes("arm_b") || text.includes("cell_ab")
    || /\bs5\b/.test(text) || text.includes("overhead") || text.includes("arm_ab_top") || text.includes("top")
  ) {
    return "cell_ab";
  }
  return null;
}

export function armIdForCamView(camView, cellId = null) {
  const resolvedCell = cellId || cellIdForCamView(camView);
  if (!resolvedCell) return null;
  const text = [camView?.id, camView?.source, camView?.source_id, camView?.arm_id, camView?.label]
    .filter(Boolean).join(" ").toLowerCase();
  if (text.includes("arm_s")) return "arm_s";
  if (text.includes("arm_b")) return "arm_b";
  if (text.includes("arm_a")) return "arm_a";
  return resolvedCell === "cell_s" ? "arm_s" : "arm_a";
}

export function isObjectSnapshotFresh(snap, nowMs = Date.now()) {
  if (!snap || snap.stale) return false;
  if (typeof snap.fetchedAtMs === "number" && Number.isFinite(snap.fetchedAtMs)) {
    return (nowMs - snap.fetchedAtMs) <= OBJECT_STALE_MS;
  }
  return true;
}

export function catalogMatchedObjects(snap) {
  const list = Array.isArray(snap?.objects) ? snap.objects : [];
  return list.filter((o) => o && typeof o.catalog_id === "string" && o.catalog_id.trim() && o.catalog_id.toLowerCase() !== "unmatched");
}

export function objectsForCamView(camView, cellObjects) {
  const cellId = cellIdForCamView(camView);
  if (!cellId || !cellObjects) return { cellId: null, armId: null, snap: null, objects: [] };
  const armId = armIdForCamView(camView, cellId);
  const cellArms = cellObjects.cells?.[cellId]?.arms || {};
  let snap = cellObjects.by_arm?.[armId] || cellArms[armId] || null;
  if (!snap && cellId === "cell_ab") {
    snap = cellArms.arm_a || cellArms.arm_b || Object.values(cellArms)[0] || null;
  }
  if (!snap) return { cellId, armId, snap: null, objects: [] };
  if (typeof cellObjects.fetchedAtMs === "number" && snap.fetchedAtMs === undefined) {
    snap = { ...snap, fetchedAtMs: cellObjects.fetchedAtMs };
  }
  return { cellId, armId: snap.arm_id || armId, snap, objects: catalogMatchedObjects(snap) };
}

export function buildCamObjectsSvg(camView, cellObjects, {
  selectedRef = null, aiHighlightRef = null, zoomed = false, nowMs = null, onSelectObject = null,
} = {}) {
  const { cellId, snap, objects } = objectsForCamView(camView, cellObjects);
  if (!snap || !objects.length) return null;
  const renderedAt = Date.now();
  const clickNow = () => (nowMs == null ? Date.now() : nowMs + Math.max(0, Date.now() - renderedAt));
  const fresh = isObjectSnapshotFresh(snap, clickNow());
  const [w, h] = Array.isArray(snap.frame_wh) && snap.frame_wh.length === 2 ? snap.frame_wh : [640, 480];
  const svg = svgEl("svg", {
    class: "omx-cam-objects-overlay",
    viewBox: `0 0 ${w} ${h}`,
    preserveAspectRatio: zoomed ? "xMidYMid meet" : "xMidYMid slice",
    "data-stale": fresh ? "false" : "true",
    "aria-label": "감지된 카탈로그 객체",
  });
  for (const obj of objects) {
    const cx = Array.isArray(obj.centre_px) ? Number(obj.centre_px[0]) : w / 2;
    const cy = Array.isArray(obj.centre_px) ? Number(obj.centre_px[1]) : h / 2;
    const pts = Array.isArray(obj.corners_px) && obj.corners_px.length === 4 ? obj.corners_px.map((p) => `${p[0]},${p[1]}`).join(" ") : null;
    const sel = obj.object_ref === selectedRef;
    const isAi = Boolean(aiHighlightRef && obj.object_ref === aiHighlightRef);
    const shape = pts
      ? svgEl("polygon", { points: pts, class: obj.pickable ? "omx-cam-obj-poly" : "omx-cam-obj-poly-veto" })
      : svgEl("circle", { cx, cy, r: 16, class: obj.pickable ? "omx-cam-obj-poly" : "omx-cam-obj-poly-veto" });
    const badge = `${sel ? "① " : ""}${obj.catalog_id}${!obj.pickable ? ` · ${obj.veto_reason || "제한"}` : (isAi && !sel ? " · AI 후보" : "")}`;
    const label = svgEl("text", { x: cx, y: Math.max(14, cy - 18), "text-anchor": "middle", class: "omx-cam-obj-label" }, badge);
    if (!obj.pickable) {
      const g = svgEl("g", { class: "omx-cam-obj-veto", "aria-disabled": "true", "data-cam-veto": obj.object_ref });
      g.append(svgEl("title", {}, obj.veto_reason || "선택 불가"), shape, label);
      svg.append(g);
      continue;
    }
    const g = svgEl("g", {
      class: `omx-cam-obj-node${isAi ? " ai-highlighted" : ""}`,
      role: "button",
      tabindex: fresh ? "0" : "-1",
      "aria-pressed": sel ? "true" : "false",
      "aria-label": `${obj.catalog_id} (${obj.site}) 선택`,
      "data-cam-object": obj.object_ref,
      "data-catalog-id": obj.catalog_id,
    });
    g.append(svgEl("rect", { x: cx - 22, y: cy - 22, width: 44, height: 44, class: "omx-cam-obj-hit" }));
    if (isAi) g.append(svgEl("circle", { cx, cy, r: 22, class: "omx-cam-obj-ai-ring" }));
    g.append(shape, label);
    const pick = (ev) => {
      ev.stopPropagation();
      if (!isObjectSnapshotFresh(snap, clickNow())) {
        svg.setAttribute("data-stale", "true");
        g.setAttribute("tabindex", "-1");
        return;
      }
      onSelectObject?.(obj, snap, cellId);
    };
    g.addEventListener("click", pick);
    g.addEventListener("keydown", (ev) => {
      if (ev.key === "Enter" || ev.key === " ") {
        ev.preventDefault();
        pick(ev);
      }
    });
    svg.append(g);
  }
  return svg;
}

export function syncCamObjectsOverlay(frameEl, camView, cellObjects, opts = {}) {
  if (!frameEl) return;
  frameEl.querySelector(".omx-cam-objects-overlay")?.remove();
  const svg = buildCamObjectsSvg(camView, cellObjects, opts);
  if (svg) frameEl.append(svg);
}
