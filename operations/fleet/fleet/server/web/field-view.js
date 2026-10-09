// D-360 경기장 제안 검토·보정 경기장 뷰·설정 불일치 안내·레이어 토글.
// 제안은 운영자가 수락해야 D-318 브라우저 초안이 된다. 어떤 값도 사이트 설정·sighting·주행에 쓰지 않는다.

import {
  LAYER_KEYS, LAYER_STORAGE_KEY, FIELD_SIZE_PREFIX, parseLayers, normalizeProposal, quadAspect,
  configuredSize, aspectMismatch, parseFieldSize, homography, rectifiedLayout,
  ASPECT_TOLERANCE,
} from "./field-layers.js";
import { multiply3, fieldToMap } from "/console/assets/map-fit.js";
import { warpImage } from "/console/assets/field-warp.js";
import { createPlaneFeed } from "/console/assets/vision-view.js";

export { warpImage };

const IDENTITY = [[0, 0], [1, 0], [1, 1], [0, 1]];

// D-359 §4 — 색·글꼴은 ui.js(window.RosyPalette)가 토큰에서 푼다(테마를 따른다).
const tone = (name) => window.RosyPalette.cssColor(name);

function storageGet(key) {
  try { return localStorage.getItem(key); } catch { return null; }
}
function storageSet(key, value) {
  try { localStorage.setItem(key, value); return true; } catch { return false; }
}

export function createFieldView({ scope, el, view, visionView, onLayersChanged }) {
  const canvas = el("field-canvas");
  const figure = el("field-rectified");
  const caption = el("field-rectified-caption");
  const state = el("field-proposal-state");
  const acceptButton = el("field-accept");
  const dismissButton = el("field-dismiss");
  const notice = el("field-mismatch");
  const widthInput = el("field-width");
  const heightInput = el("field-height");
  const storageState = el("field-storage-state");
  const layerHint = el("map-layer-hint");
  const scratch = document.createElement("canvas");
  let proposal = null; // { corners, confidence, aspect, shape, source }
  let lastFrame = null;
  let warped = null; // { key, data } — 같은 프레임·모서리·크기면 다시 펴지 않는다.
  // D-560 4: 승인 보정이 있으면 Vision 지도 평면 영상을 그대로 보여 준다. 없으면 아래 예전 경로다.
  const planes = createPlaneFeed({ scope, visionView, onChange: () => renderRectified() });

  view.layers = parseLayers(storageGet(LAYER_STORAGE_KEY));
  const toggles = [...document.querySelectorAll("[data-layer]")];

  function applyLayers() {
    for (const input of toggles) input.checked = view.layers[input.dataset.layer] !== false;
    el("vision-frame").hidden = !view.layers.raw;
    const off = LAYER_KEYS.filter((key) => view.layers[key] === false).length;
    layerHint.hidden = off === 0;
    layerHint.textContent = off ? `숨긴 레이어 ${off}개` : "";
    renderRectified();
    onLayersChanged();
  }

  for (const input of toggles) {
    scope.listen(input, "change", () => {
      if (!LAYER_KEYS.includes(input.dataset.layer)) return;
      view.layers = { ...view.layers, [input.dataset.layer]: input.checked };
      storageNotice(storageSet(LAYER_STORAGE_KEY, JSON.stringify(view.layers)));
      applyLayers();
    });
  }

  // 저장 실패는 제안 상태 줄과 따로 알린다(제안 안내를 덮지 않는다).
  function storageNotice(saved) {
    storageState.hidden = saved;
    storageState.textContent = saved ? "" : "브라우저 저장을 쓸 수 없어 레이어·크기 설정은 이 화면에서만 유지됩니다.";
  }

  function operatorSize() {
    return parseFieldSize(widthInput.value, heightInput.value);
  }

  function loadSize(source) {
    let saved = null;
    try { saved = JSON.parse(storageGet(`${FIELD_SIZE_PREFIX}${source}`) || "null"); } catch { saved = null; }
    widthInput.value = saved?.width ?? "";
    heightInput.value = saved?.height ?? "";
  }

  for (const input of [widthInput, heightInput]) {
    scope.listen(input, "input", () => {
      const source = visionView.currentSource();
      const size = operatorSize();
      if (source && size) storageNotice(storageSet(`${FIELD_SIZE_PREFIX}${source}`, JSON.stringify(size)));
      renderRectified();
    });
  }

  // 확인했거나 제안된 모서리(정규 좌표). 조정값이 항등이면 쓸 모서리가 없다.
  function activeCorners() {
    if (proposal && proposal.source === visionView.currentSource()) return { corners: proposal.corners, kind: "제안" };
    const corners = visionView.currentCorners();
    const identity = corners.every(([x, y], i) => Math.abs(x - IDENTITY[i][0]) < 1e-6 && Math.abs(y - IDENTITY[i][1]) < 1e-6);
    return identity ? null : { corners, kind: "확인한 모서리" };
  }

  function detectedAspect(active, image) {
    if (!active) return null;
    if (active.kind === "제안") return proposal.aspect;
    const w = image?.naturalWidth || 1;
    const h = image?.naturalHeight || 1;
    return quadAspect(active.corners.map(([x, y]) => [x * w, y * h]));
  }

  function updateMismatch(active) {
    const aspect = detectedAspect(active, lastFrame?.image);
    const configured = configuredSize(view.siteMap, visionView.currentSource());
    const verdict = aspectMismatch(configured, aspect);
    if (verdict.state === "mismatch") {
      notice.textContent = `설정 ${configured.width.toFixed(2)}×${configured.height.toFixed(2)} m(비 ${verdict.expected.toFixed(2)})와 `
        + `카메라에 보이는 경기장(비 ${verdict.detected.toFixed(2)})이 ${Math.round(verdict.relative * 100)}% 다릅니다. `
        + `허용 ${Math.round(ASPECT_TOLERANCE * 100)}%. 관제는 설정을 고치지 않습니다 — 현장 치수를 확인하세요.`;
      notice.hidden = false;
    } else if (verdict.state === "unconfigured") {
      notice.textContent = `사이트 설정에 경기장 W×H가 없습니다. 카메라에 보이는 경기장 비는 ${verdict.detected.toFixed(2)}입니다.`;
      notice.hidden = false;
    } else {
      notice.hidden = true;
    }
    notice.dataset.state = verdict.state;
  }

  function renderRectified() {
    const active = activeCorners();
    updateMismatch(active);
    const frame = lastFrame;
    const shot = planes.current();
    const plane = shot?.source === visionView.currentSource() && view.hasFleetCalibration?.(shot.source) ? shot : null;
    // D-375 대체 경로: 경기장 모서리가 없고 운영자가 지도 맞춤을 수락했으면 지도 사각형을 그 homography 로 편다.
    const byMap = !plane && !active && frame && !frame.rectified ? view.mapFieldFallback?.(frame) ?? null : null;
    const show = view.layers.rectified && (plane || (frame && frame.source === visionView.currentSource()
      && (frame.rectified || active || byMap)));
    figure.hidden = !show;
    if (!show) return;
    const mapSize = plane ? {
      width: Math.round(plane.image.naturalWidth / plane.plane.ppm * 1000) / 1000,
      height: Math.round(plane.image.naturalHeight / plane.plane.ppm * 1000) / 1000,
    } : byMap ? {
      width: Math.round((byMap.bounds.max_x - byMap.bounds.min_x) * 1000) / 1000,
      height: Math.round((byMap.bounds.max_y - byMap.bounds.min_y) * 1000) / 1000,
    } : null;
    const size = mapSize || operatorSize();
    const aspect = size ? size.width / size.height
      : detectedAspect(active, frame.image) || (frame.image.naturalWidth / frame.image.naturalHeight);
    const layout = rectifiedLayout(aspect, 640, 400);
    canvas.width = layout.width;
    canvas.height = layout.height;
    const ctx = canvas.getContext("2d");
    const { field } = layout;
    ctx.fillStyle = tone("--ground-deep");
    ctx.fillRect(0, 0, layout.width, layout.height);
    if (plane) {
      ctx.drawImage(plane.image, field.x, field.y, field.width, field.height);
    } else if (frame.rectified) {
      // Vision 이 확인한 모서리로 이미 펴서 보냈다(D-318). 바깥은 없다.
      ctx.drawImage(frame.image, field.x, field.y, field.width, field.height);
    } else {
      // 지도 경로는 전체 homography 라 0–100% 로 잘리는 모서리 조정값을 거치지 않는다.
      const h = byMap ? multiply3(byMap.mapToShown, fieldToMap(byMap.bounds, field)) : null;
      const key = JSON.stringify([frame.source, frame.url ?? frame.seq, h || active.corners, layout.width, layout.height]);
      if (warped?.key !== key) {
        warped = { key, data: h ? warpImage(ctx, frame.image, h, layout.width, layout.height, scratch)
          : warp(ctx, frame.image, active.corners, layout) };
      } else if (warped.data) ctx.putImageData(warped.data, 0, 0);
      // 경기장 밖을 가린다.
      ctx.save();
      ctx.fillStyle = tone("--scrim");
      ctx.beginPath();
      ctx.rect(0, 0, layout.width, layout.height);
      ctx.rect(field.x, field.y, field.width, field.height);
      ctx.fill("evenodd");
      ctx.restore();
    }
    ctx.save();
    ctx.strokeStyle = active?.kind === "제안" ? tone("--series-goal") : tone("--series-primary");
    ctx.lineWidth = 2;
    ctx.setLineDash(active?.kind === "제안" ? [6, 4] : []);
    ctx.strokeRect(field.x + 1, field.y + 1, field.width - 2, field.height - 2);
    ctx.restore();
    if (size) drawMetric(ctx, field, size);
    const source = plane ? `Rosy Cam 평면 영상(보정 ${plane.calibrationRevision})`
      : frame.rectified ? "Vision 보정 프레임"
      : byMap ? "수락한 지도 맞춤으로 편 원본(모서리가 화면 밖이어도 됨)"
        : `${active.kind === "제안" ? "제안으로" : "확인한 모서리로"} 편 원본`;
    caption.textContent = `위에서 본 경기장 · ${source} · 경기장 밖은 가림`
      + (mapSize ? ` · 지도 ${size.width}×${size.height} m`
        : size ? ` · 표시 축척 ${size.width}×${size.height} m(이 브라우저만)` : " · 축척 미입력")
      + " · 표시 전용, 관측·주행에 쓰지 않음";
    canvas.setAttribute("aria-label", caption.textContent);
  }

  function drawMetric(ctx, field, size) {
    const pxPerM = field.width / size.width;
    const step = [0.05, 0.1, 0.25, 0.5, 1, 2, 5].find((s) => size.width / s <= 16) || 10;
    ctx.save();
    if (view.layers.grid) {
      ctx.strokeStyle = tone("--line-30");
      ctx.lineWidth = 1;
      for (let x = step; x < size.width - 1e-9; x += step) {
        const px = field.x + x * pxPerM;
        ctx.beginPath(); ctx.moveTo(px, field.y); ctx.lineTo(px, field.y + field.height); ctx.stroke();
      }
      for (let y = step; y < size.height - 1e-9; y += step) {
        const py = field.y + y * (field.height / size.height);
        ctx.beginPath(); ctx.moveTo(field.x, py); ctx.lineTo(field.x + field.width, py); ctx.stroke();
      }
    }
    ctx.fillStyle = tone("--ink");
    ctx.font = window.RosyPalette.canvasFont(12, "mono");
    ctx.textBaseline = "bottom";
    ctx.fillText(`${size.width} m`, field.x + field.width / 2 - 16, field.y - 2);
    ctx.fillText(`격자 ${step} m`, field.x + 4, field.y + field.height - 4);
    ctx.restore();
  }

  // 경기장 사각형 → 원본 모서리 호모그래피로 편다. 경기장 둘레 여백도 같은 변환으로 채운다.
  function warp(ctx, image, corners, layout) {
    const iw = image.naturalWidth;
    const ih = image.naturalHeight;
    if (!iw || !ih) return null;
    const { field } = layout;
    const dstQuad = [[field.x, field.y], [field.x + field.width, field.y],
      [field.x + field.width, field.y + field.height], [field.x, field.y + field.height]];
    const h = homography(dstQuad, corners.map(([x, y]) => [x * (iw - 1), y * (ih - 1)]));
    return h ? warpImage(ctx, image, h, layout.width, layout.height, scratch) : null;
  }

  function setProposal(next) {
    proposal = next;
    acceptButton.hidden = !next;
    dismissButton.hidden = !next;
    visionView.showProposal(next ? next.corners : null);
    renderRectified();
  }

  scope.listen(el("field-detect"), "click", async () => {
    const life = scope.capture();
    life.check();
    state.textContent = "Vision에서 경기장 윤곽을 찾는 중입니다…";
    try {
      const { source, body } = await visionView.fetchFieldProposal();
      life.check();
      const found = normalizeProposal(body);
      if (!found) {
        setProposal(null);
        state.textContent = `제안 없음 — ${body?.reason || "경기장을 찾지 못했습니다"}. `
          + (view.mapFieldFallback?.(lastFrame)
            ? "수락한 지도 맞춤으로 경기장 뷰를 그립니다."
            : "모서리는 손으로 맞추거나 '맵 자동 맞춤'을 수락하세요.");
        return;
      }
      setProposal({ ...found, source });
      state.textContent = `제안: 신뢰도 ${found.confidence.toFixed(2)} · 비 ${found.aspect.toFixed(2)} · `
        + `${found.shape === "square" ? "정사각형" : "직사각형"} · 프레임 ${body.frame_seq} `
        + `(${body.detector?.elapsed_ms ?? "?"} ms). 점선 사각형을 확인하고 수락하세요. 자동 적용하지 않습니다.`;
    } catch (error) {
      if (error.name === "AbortError") return;
      state.textContent = error.message || "제안을 받지 못했습니다.";
    }
  });
  scope.listen(acceptButton, "click", () => {
    if (!proposal) return;
    visionView.acceptCorners(proposal.corners);
    setProposal(null);
    state.textContent = "제안을 이 브라우저의 모서리 조정값으로 옮겼습니다. 손으로 더 고칠 수 있습니다. 관측 좌표와 주행에는 쓰지 않습니다.";
  });
  scope.listen(dismissButton, "click", () => {
    setProposal(null);
    state.textContent = "제안을 버렸습니다. 조정값은 그대로입니다.";
  });

  let sizeSource = null;
  scope.subscribe(() => visionView.onFrame(scope.guard((frame) => {
    lastFrame = frame;
    planes.refresh(Boolean(view.layers.rectified && view.hasFleetCalibration?.(frame.source)));
    if (frame.source !== sizeSource) {
      sizeSource = frame.source;
      loadSize(frame.source);
      if (proposal && proposal.source !== frame.source) setProposal(null);
    }
    renderRectified();
  })));
  scope.onDispose(() => {
    proposal = null;
    lastFrame = null;
    sizeSource = null;
    acceptButton.hidden = true;
    dismissButton.hidden = true;
  });

  applyLayers();
  return { render: renderRectified };
}
