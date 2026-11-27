// Shared top-camera pixel ROI SVG overlay helpers for OMX inspector and ARM-CELL stage.
const SVG_NS = "http://www.w3.org/2000/svg";

function svgEl(tag, attrs = {}, text = null) {
  const el = document.createElementNS(SVG_NS, tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v !== null && v !== undefined) el.setAttribute(k, String(v));
  }
  if (text !== null && text !== undefined) el.textContent = String(text);
  return el;
}

/** Resolve pixel ROI rects/points for a camera view against site-points full `cameras`. */
export function cameraRoiEntries(camView, cameraRois) {
  const cams = cameraRois?.arm_s_top || cameraRois?.arm_ab_top ? cameraRois : cameraRois?.cameras;
  if (!cams || !camView) return { size: [640, 480], entries: [] };
  const text = [camView.id, camView.source, camView.source_id, camView.role, camView.label]
    .filter(Boolean).join(" ").toLowerCase();
  if (text.includes("wrist") || text.includes("side") || text.includes("depth") || text.includes("front")) {
    return { size: [640, 480], entries: [] };
  }
  let key = "";
  if (text.includes("arm_s") || text.includes("cell_s") || /\bs3\b/.test(text)) key = "arm_s_top";
  else if (
    text.includes("arm_a") || text.includes("arm_b") || text.includes("cell_ab")
    || /\bs5\b/.test(text) || text.includes("overhead") || text.includes("arm_ab_top") || text.includes("top")
  ) {
    key = "arm_ab_top";
  }
  const group = key ? cams[key] : null;
  if (!group || typeof group !== "object") return { size: [640, 480], entries: [] };
  const size = Array.isArray(cameraRois?.image_size_px) && cameraRois.image_size_px.length === 2
    ? cameraRois.image_size_px
    : [640, 480];
  const entries = Object.entries(group).map(([roiKey, spec]) => ({
    key: roiKey,
    label: spec?.label || roiKey,
    rect: Array.isArray(spec?.top_roi_px) && spec.top_roi_px.length === 4 ? spec.top_roi_px : null,
    point: Array.isArray(spec?.top_px) && spec.top_px.length === 2 ? spec.top_px : null,
  })).filter((entry) => entry.rect || entry.point);
  return { size, entries };
}

export function buildCamRoiSvg(camView, cameraRois) {
  const { size, entries } = cameraRoiEntries(camView, cameraRois);
  if (!entries.length) return null;
  const svg = svgEl("svg", {
    class: "omx-cam-roi-overlay",
    viewBox: `0 0 ${size[0]} ${size[1]}`,
    preserveAspectRatio: "xMidYMid slice",
    "aria-hidden": "true",
  });
  for (const entry of entries) {
    if (entry.rect) {
      const [x0, y0, x1, y1] = entry.rect;
      svg.append(svgEl("rect", {
        x: x0, y: y0, width: Math.max(1, x1 - x0), height: Math.max(1, y1 - y0),
        class: "omx-cam-roi-rect", "data-roi-key": entry.key,
      }));
      svg.append(svgEl("text", { x: x0 + 6, y: y0 + 16, class: "omx-cam-roi-label" }, entry.label));
    } else if (entry.point) {
      const [px, py] = entry.point;
      svg.append(svgEl("circle", { cx: px, cy: py, r: 7, class: "omx-cam-roi-point", "data-roi-key": entry.key }));
      svg.append(svgEl("text", { x: px + 10, y: py + 4, class: "omx-cam-roi-label" }, entry.label));
    }
  }
  return svg;
}

export function syncCamRoiOverlay(frameEl, camView, cameraRois, showRoi = true) {
  if (!frameEl) return;
  frameEl.querySelector(".omx-cam-roi-overlay")?.remove();
  if (!showRoi || !cameraRois) return;
  const svg = buildCamRoiSvg(camView, cameraRois);
  if (!svg) return;
  const standby = frameEl.querySelector(".omx-inspector-cam-standby");
  if (standby) frameEl.insertBefore(svg, standby);
  else frameEl.append(svg);
}
