// D-354 경기장 제안 검토·보정 경기장 뷰·설정 불일치 안내·레이어 토글.
// 제안은 운용자가 수락해야 D-318 브라우저 초안이 된다. 어떤 값도 사이트 설정·sighting·주행에 쓰지 않는다.

import {
  LAYER_KEYS, LAYER_STORAGE_KEY, FIELD_SIZE_PREFIX, parseLayers, normalizeProposal, quadAspect,
  configuredSize, aspectMismatch, parseFieldSize, homography, applyHomography, rectifiedLayout,
  ASPECT_TOLERANCE,
} from "./field-layers.js";

const IDENTITY = [[0, 0], [1, 0], [1, 1], [0, 1]];

function tone(name, fallback) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback;
}

function storageGet(key) {
  try { return localStorage.getItem(key); } catch { return null; }
}
function storageSet(key, value) {
  try { localStorage.setItem(key, value); return true; } catch { return false; }
}

export function createFieldView({ el, view, visionView, onLayersChanged }) {
  const canvas = el("field-canvas");
  const figure = el("field-rectified");
  const caption = el("field-rectified-caption");
  const state = el("field-proposal-state");
  const acceptButton = el("field-accept");
  const dismissButton = el("field-dismiss");
  const notice = el("field-mismatch");
  const widthInput = el("field-width");
  const heightInput = el("field-height");
  const scratch = document.createElement("canvas");
  let proposal = null; // { corners, confidence, aspect, shape, source }
  let lastFrame = null;

  view.layers = parseLayers(storageGet(LAYER_STORAGE_KEY));
  const toggles = [...document.querySelectorAll("[data-layer]")];

  function applyLayers() {
    for (const input of toggles) input.checked = view.layers[input.dataset.layer] !== false;
    el("vision-frame").hidden = !view.layers.raw;
    renderRectified();
    onLayersChanged();
  }

  for (const input of toggles) {
    input.addEventListener("change", () => {
      if (!LAYER_KEYS.includes(input.dataset.layer)) return;
      view.layers = { ...view.layers, [input.dataset.layer]: input.checked };
      if (!storageSet(LAYER_STORAGE_KEY, JSON.stringify(view.layers))) {
        state.textContent = "브라우저 저장을 쓸 수 없어 레이어 설정은 이 화면에서만 유지됩니다.";
      }
      applyLayers();
    });
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
    input.addEventListener("input", () => {
      const source = visionView.currentSource();
      const size = operatorSize();
      if (source && size) storageSet(`${FIELD_SIZE_PREFIX}${source}`, JSON.stringify(size));
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
    const show = view.layers.rectified && frame && frame.source === visionView.currentSource()
      && (frame.rectified || active);
    figure.hidden = !show;
    if (!show) return;
    const size = operatorSize();
    const aspect = size ? size.width / size.height
      : detectedAspect(active, frame.image) || (frame.image.naturalWidth / frame.image.naturalHeight);
    const layout = rectifiedLayout(aspect, 640, 400);
    canvas.width = layout.width;
    canvas.height = layout.height;
    const ctx = canvas.getContext("2d");
    const { field } = layout;
    ctx.fillStyle = tone("--ground-deep", "#000");
    ctx.fillRect(0, 0, layout.width, layout.height);
    if (frame.rectified) {
      // Vision 이 확인한 모서리로 이미 펴서 보냈다(D-318). 바깥은 없다.
      ctx.drawImage(frame.image, field.x, field.y, field.width, field.height);
    } else {
      warp(ctx, frame.image, active.corners, layout);
      // 경기장 밖을 가린다.
      ctx.save();
      ctx.fillStyle = "rgba(0, 0, 0, 0.72)";
      ctx.beginPath();
      ctx.rect(0, 0, layout.width, layout.height);
      ctx.rect(field.x, field.y, field.width, field.height);
      ctx.fill("evenodd");
      ctx.restore();
    }
    ctx.save();
    ctx.strokeStyle = active?.kind === "제안" ? tone("--series-goal", "#fc3") : tone("--series-primary", "#4cf");
    ctx.lineWidth = 2;
    ctx.setLineDash(active?.kind === "제안" ? [6, 4] : []);
    ctx.strokeRect(field.x + 1, field.y + 1, field.width - 2, field.height - 2);
    ctx.restore();
    if (size) drawMetric(ctx, field, size);
    const source = frame.rectified ? "Vision 보정 프레임" : `${active.kind}으로 편 원본`;
    caption.textContent = `위에서 본 경기장 · ${source} · 경기장 밖은 가림`
      + (size ? ` · 표시 축척 ${size.width}×${size.height} m(이 브라우저만)` : " · 축척 미입력")
      + " · 표시 전용, 관측·주행에 쓰지 않음";
    canvas.setAttribute("aria-label", caption.textContent);
  }

  function drawMetric(ctx, field, size) {
    const pxPerM = field.width / size.width;
    const step = [0.05, 0.1, 0.25, 0.5, 1, 2, 5].find((s) => size.width / s <= 16) || 10;
    ctx.save();
    if (view.layers.grid) {
      ctx.strokeStyle = "rgba(255, 255, 255, 0.28)";
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
    ctx.fillStyle = tone("--paper", "#fff");
    ctx.font = `12px ${tone("--mono", "monospace")}`;
    ctx.textBaseline = "bottom";
    ctx.fillText(`${size.width} m`, field.x + field.width / 2 - 16, field.y - 2);
    ctx.fillText(`격자 ${step} m`, field.x + 4, field.y + field.height - 4);
    ctx.restore();
  }

  // 출력 픽셀마다 역변환으로 원본을 표본한다(최근접). 경기장 둘레 여백도 같은 변환으로 채운다.
  function warp(ctx, image, corners, layout) {
    const iw = image.naturalWidth;
    const ih = image.naturalHeight;
    if (!iw || !ih) return;
    scratch.width = iw;
    scratch.height = ih;
    const sctx = scratch.getContext("2d", { willReadFrequently: true });
    sctx.drawImage(image, 0, 0);
    const src = sctx.getImageData(0, 0, iw, ih).data;
    const { field } = layout;
    const dstQuad = [[field.x, field.y], [field.x + field.width, field.y],
      [field.x + field.width, field.y + field.height], [field.x, field.y + field.height]];
    const h = homography(dstQuad, corners.map(([x, y]) => [x * (iw - 1), y * (ih - 1)]));
    if (!h) return;
    const out = ctx.createImageData(layout.width, layout.height);
    for (let y = 0; y < layout.height; y += 1) {
      for (let x = 0; x < layout.width; x += 1) {
        const [u, v] = applyHomography(h, x + 0.5, y + 0.5);
        const sx = Math.round(u);
        const sy = Math.round(v);
        if (sx < 0 || sy < 0 || sx >= iw || sy >= ih) continue;
        const s = (sy * iw + sx) * 4;
        const d = (y * layout.width + x) * 4;
        out.data[d] = src[s]; out.data[d + 1] = src[s + 1]; out.data[d + 2] = src[s + 2]; out.data[d + 3] = 255;
      }
    }
    ctx.putImageData(out, 0, 0);
  }

  function setProposal(next) {
    proposal = next;
    acceptButton.hidden = !next;
    dismissButton.hidden = !next;
    visionView.showProposal(next ? next.corners : null);
    renderRectified();
  }

  el("field-detect").addEventListener("click", async () => {
    state.textContent = "Vision에서 경기장 윤곽을 찾는 중입니다…";
    try {
      const { source, body } = await visionView.fetchFieldProposal();
      const found = normalizeProposal(body);
      if (!found) {
        setProposal(null);
        state.textContent = `제안 없음 — ${body?.reason || "경기장을 찾지 못했습니다"}. 모서리는 손으로 맞추세요.`;
        return;
      }
      setProposal({ ...found, source });
      state.textContent = `제안: 신뢰도 ${found.confidence.toFixed(2)} · 비 ${found.aspect.toFixed(2)} · `
        + `${found.shape === "square" ? "정사각형" : "직사각형"} · 프레임 ${body.frame_seq} `
        + `(${body.detector?.elapsed_ms ?? "?"} ms). 점선 사각형을 확인하고 수락하세요. 자동 적용하지 않습니다.`;
    } catch (error) {
      state.textContent = error.message || "제안을 받지 못했습니다.";
    }
  });
  acceptButton.addEventListener("click", () => {
    if (!proposal) return;
    visionView.acceptCorners(proposal.corners);
    setProposal(null);
    state.textContent = "제안을 이 브라우저의 모서리 조정값으로 옮겼습니다. 손으로 더 고칠 수 있습니다. 관측 좌표와 주행에는 쓰지 않습니다.";
  });
  dismissButton.addEventListener("click", () => {
    setProposal(null);
    state.textContent = "제안을 버렸습니다. 조정값은 그대로입니다.";
  });

  let sizeSource = null;
  visionView.onFrame((frame) => {
    lastFrame = frame;
    if (frame.source !== sizeSource) {
      sizeSource = frame.source;
      loadSize(frame.source);
      if (proposal && proposal.source !== frame.source) setProposal(null);
    }
    renderRectified();
  });

  applyLayers();
  return { render: renderRectified };
}
