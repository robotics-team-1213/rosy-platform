// D-375 지도 자동 맞춤: Vision 이 차선 페인트로 제안한 homography 로 사이트 차선을 카메라 위에 겹치고,
// 카메라 영상을 지도 좌표(m) 평면으로 펴서 차선과 함께 보여 준다. 운용자가 수락해야 이 브라우저의
// 표시 초안(localStorage, source 마다)이 된다. 어떤 값도 sighting·CameraMap·주행에 쓰지 않는다.

import {
  MAP_FIT_PREFIX, multiply3, invert3, project, scale3, projectPolyline, projectTriangles,
  normalizeMapProposal, fitSummary, pickLanes, topDownLayout, parseMapDraft, draftFrom,
  retryDelay, MAP_FIT_MAX_TRIES, canAccept, fitUsable, STALE_FIT_TEXT, calibrationRequest,
} from "./map-fit.js";
import { warpImage } from "./field-view.js";

// D-359 §4 — 색·글꼴은 ui.js(window.RosyPalette)가 토큰에서 푼다(테마를 따른다).
const tone = (name) => window.RosyPalette.cssColor(name);
function storageGet(key) {
  try { return localStorage.getItem(key); } catch { return null; }
}
function storageSet(key, value) {
  try { localStorage.setItem(key, value); return true; } catch { return false; }
}
function storageRemove(key) {
  try { localStorage.removeItem(key); } catch { /* 이 화면에서만 지워진다 */ }
}

const KIND_LABEL = {
  proposal: "제안(검토 중)", previous: "이전 결과(최신 결과를 기다리는 중)",
  rejected: "거부된 최선 적합(참고용)", draft: "수락한 맞춤(이 브라우저)",
};

export function createMapFitView({ scope, el, view, call, visionView, onChanged = () => {} }) {
  const overlay = el("vision-lane-overlay");
  const figure = el("map-fit-figure");
  const canvas = el("map-fit-canvas");
  const caption = el("map-fit-caption");
  const state = el("map-fit-state");
  const guidance = el("map-fit-guidance");
  const acceptButton = el("map-fit-accept");
  const dismissButton = el("map-fit-dismiss");
  const clearButton = el("map-fit-clear");
  const applyButton = el("map-fit-apply");
  let applying = false;      // "추적 보정 적용" 요청 진행 중 — 두 번 보내지 않는다
  const scratch = document.createElement("canvas");
  let lanes = null;          // /api/fleet/site-lanes 응답
  let lanesError = null;     // 마지막 읽기 실패 안내
  let lanesAt = 0;
  let pending = null;        // { source, norm } 검토 중인 Vision 응답
  let lastFrame = null;
  let warped = null;         // { key, data }

  async function ensureLanes({ force = false } = {}) {
    const life = scope.capture();
    life.check();
    if (lanes && !force) return lanes;
    if (!force && Date.now() - lanesAt < 30000) return null; // 실패 뒤 30 s 는 다시 묻지 않는다
    lanesAt = Date.now();
    try {
      const result = await call("/api/fleet/site-lanes");
      life.check();
      lanes = result;
      lanesError = null;
    } catch (error) {
      if (error.name === "AbortError") throw error;
      lanes = null;
      lanesError = error.status === 404
        ? "Fleet에 사이트 차선 지도가 설정되지 않았습니다(fleet console --site-lane-graph / --site-lane-paint)."
        : `사이트 차선을 읽지 못했습니다: ${error.message || error}`;
    }
    return lanes;
  }

  function draftFor(source) {
    return source ? parseMapDraft(storageGet(`${MAP_FIT_PREFIX}${source}`)) : null;
  }

  // 지금 그릴 맞춤: 검토 중 제안 → 수락한 초안 순서.
  function active() {
    const source = visionView.currentSource();
    const fit = pending?.source === source ? pending.norm.fit : null;
    if (fit?.mapToImage) { // 행렬 없는 거부(coverage·잘린 쪽만)는 그리지 않는다
      const kind = pending.norm.previous ? "previous" : pending.norm.accepted ? "proposal" : "rejected";
      return { kind, mapToImage: fit.mapToImage, imageToMap: fit.imageToMap, image: pending.norm.image,
        stamp: pending.stamp };
    }
    const draft = draftFor(source);
    return draft ? { kind: "draft", ...draft } : null;
  }

  // 해상도 비·지도가 바뀐 맞춤은 늘여 맞추지 않고 버린다(fitUsable). 안내는 한 번만 붙인다.
  function usableFit(fit, frame, laneSet) {
    if (!fit || !frame?.image?.naturalWidth) return null;
    const verdict = fitUsable(fit, frame.image.naturalWidth, frame.image.naturalHeight, laneSet);
    if (verdict.ok) return fit;
    if (!guidance.textContent.includes(STALE_FIT_TEXT)) {
      guidance.textContent = STALE_FIT_TEXT;
      guidance.hidden = false;
    }
    return null;
  }

  function colour(kind) {
    if (kind === "proposal") return tone("--series-goal");
    if (kind === "previous") return tone("--ink-quiet");
    if (kind === "rejected") return tone("--status-warn");
    return tone("--series-primary");
  }

  // 지도 → 화면에 디코드된 원본 픽셀. Vision 응답의 image 크기와 디코드 크기가 다르면 비례로 맞춘다.
  function displayMatrices(fit, image) {
    const sx = image.naturalWidth / fit.image.width;
    const sy = image.naturalHeight / fit.image.height;
    return { mapToShown: multiply3(scale3(sx, sy), fit.mapToImage),
      shownToMap: multiply3(fit.imageToMap, scale3(1 / sx, 1 / sy)) };
  }

  function drawLanes(ctx, h, laneSet, stroke, lineWidth) {
    ctx.save();
    ctx.fillStyle = stroke;
    ctx.globalAlpha = 0.5;
    for (const [a, b, c] of projectTriangles(laneSet.triangles, h)) {
      ctx.beginPath(); ctx.moveTo(...a); ctx.lineTo(...b); ctx.lineTo(...c); ctx.closePath(); ctx.fill();
    }
    ctx.globalAlpha = 0.95;
    ctx.strokeStyle = stroke;
    ctx.lineWidth = lineWidth;
    ctx.setLineDash([lineWidth * 4, lineWidth * 3]);
    for (const line of laneSet.polylines) {
      for (const run of projectPolyline(line.points, h, line.closed === true)) {
        ctx.beginPath();
        run.forEach(([x, y], i) => (i ? ctx.lineTo(x, y) : ctx.moveTo(x, y)));
        ctx.stroke();
      }
    }
    ctx.restore();
  }

  function renderOverlay(fit, laneSet, frame) {
    const image = frame?.image;
    const show = Boolean(view.layers.lanes && fit && laneSet && frame && !frame.rectified
      && frame.source === visionView.currentSource() && image?.naturalWidth);
    overlay.hidden = !show;
    if (!show) return;
    overlay.width = image.naturalWidth;
    overlay.height = image.naturalHeight;
    const ctx = overlay.getContext("2d");
    ctx.clearRect(0, 0, overlay.width, overlay.height);
    const { mapToShown } = displayMatrices(fit, image);
    drawLanes(ctx, mapToShown, laneSet, colour(fit.kind), Math.max(1.5, image.naturalWidth / 640));
  }

  function renderTopDown(fit, laneSet, frame) {
    const image = frame?.image;
    const show = Boolean(view.layers.maptop && fit && laneSet && frame && !frame.rectified
      && frame.source === visionView.currentSource() && image?.naturalWidth);
    figure.hidden = !show;
    if (!show) return;
    const layout = topDownLayout(laneSet.bounds, 640, 400, 0.1);
    canvas.width = layout.width;
    canvas.height = layout.height;
    const ctx = canvas.getContext("2d");
    ctx.fillStyle = tone("--ground-deep");
    ctx.fillRect(0, 0, layout.width, layout.height);
    const { mapToShown, shownToMap } = displayMatrices(fit, image);
    const canvasToShown = multiply3(mapToShown, layout.canvasToMap);
    const key = JSON.stringify([frame.source, frame.url ?? frame.seq, canvasToShown, layout.width, layout.height]);
    if (view.layers.raw !== false) {
      if (warped?.key !== key) warped = { key, data: warpImage(ctx, image, canvasToShown, layout.width, layout.height, scratch) };
      else if (warped.data) ctx.putImageData(warped.data, 0, 0);
    }
    const stroke = colour(fit.kind);
    drawLanes(ctx, layout.mapToCanvas, laneSet, stroke, 1.5);
    // 카메라 시야(원본 네 모서리)를 지도 위에 그린다. 지평선 너머 모서리는 뺀다.
    const w = image.naturalWidth - 1;
    const h = image.naturalHeight - 1;
    const footprint = [[0, 0], [w, 0], [w, h], [0, h]]
      .map(([x, y]) => project(shownToMap, x, y)).filter(Boolean)
      .map(([x, y]) => project(layout.mapToCanvas, x, y)).filter(Boolean);
    ctx.save();
    ctx.strokeStyle = tone("--ink");
    ctx.lineWidth = 1;
    ctx.setLineDash([3, 3]);
    if (footprint.length === 4) {
      ctx.beginPath();
      footprint.forEach(([x, y], i) => (i ? ctx.lineTo(x, y) : ctx.moveTo(x, y)));
      ctx.closePath();
      ctx.stroke();
    }
    ctx.setLineDash([]);
    ctx.fillStyle = tone("--ink");
    ctx.font = window.RosyPalette.canvasFont(12, "mono");
    ctx.textBaseline = "top";
    ctx.fillText("북 +y ↑   동 +x →", 6, 6);
    ctx.restore();
    caption.textContent = `위에서 본 지도 좌표(m) · ${KIND_LABEL[fit.kind]} · 카메라 영상을 지도 평면으로 편 위에 `
      + "차선 페인트(채움)와 중심선(점선), 카메라 시야(가는 점선) · 페인트가 겹치면 맞음 · 표시 전용, 관측·주행에 쓰지 않음";
    canvas.setAttribute("aria-label", caption.textContent);
  }

  function render() {
    const source = visionView.currentSource();
    const laneSet = lanes ? pickLanes(lanes, source) : null;
    const fit = usableFit(active(), lastFrame, laneSet);
    acceptButton.hidden = !canAccept(pending, source) || !fit || fit.kind !== "proposal";
    applyButton.hidden = acceptButton.hidden;
    dismissButton.hidden = !(pending?.source === source);
    clearButton.hidden = !draftFor(source);
    renderOverlay(fit, laneSet, lastFrame);
    renderTopDown(fit, laneSet, lastFrame);
  }

  function showSummary(summary) {
    state.textContent = summary.headline;
    state.dataset.tone = summary.tone;
    guidance.hidden = !summary.guidance;
    guidance.textContent = summary.guidance || "";
  }

  // 한 번 맞추는 데 1–10 s 라 Vision 이 429(계산 중·초당 1회)나 "previous"(지난 결과)를 줄 수 있다.
  // 둘 다 오류가 아니라 "맞추는 중"이다. previous 는 보여 주되 수락은 못 하게 하고 최신 결과까지 다시 묻는다.
  const sleep = (ms) => scope.sleep(ms);
  async function fetchUntilCurrent(generation) {
    const life = scope.capture();
    life.check();
    for (let attempt = 0; ; attempt += 1) {
      let reply;
      try {
        reply = await visionView.fetchMapProposal();
        life.check();
      } catch (error) {
        if (error.name === "AbortError") throw error;
        const wait = retryDelay(error, attempt);
        if (wait == null) {
          if (error.busy) error.message = "Vision이 아직 맞추는 중입니다. 잠시 뒤 다시 누르세요.";
          throw error;
        }
        if (generation !== fitGeneration) return null;
        state.textContent = `맞추는 중… (${attempt + 1}/${MAP_FIT_MAX_TRIES})`;
        await sleep(wait);
        life.check();
        continue;
      }
      if (reply.proposalState !== "previous" || attempt + 1 >= MAP_FIT_MAX_TRIES) return reply;
      if (generation !== fitGeneration) return null;
      showPending(reply, generation); // 이전 결과를 표시만 한다
      await sleep(1000);
      life.check();
    }
  }

  function showPending({ source, body, proposalState }, generation) {
    if (generation !== fitGeneration) return; // reset·새 요청 뒤에 도착한 늦은 결과
    const norm = normalizeMapProposal(body, { proposalState });
    const laneSet = lanes ? pickLanes(lanes, source) : null;
    pending = norm ? { source, norm, stamp: laneSet
      ? { mapId: laneSet.mapId, laneSha: laneSet.laneSha, paintSha: laneSet.paintSha } : null } : null;
    showSummary(fitSummary(norm));
    if (!lanes && lanesError) state.textContent += ` ${lanesError}`;
    render();
  }

  const detectButton = el("map-fit-detect");
  let fitGeneration = 0;
  scope.listen(detectButton, "click", async () => {
    const life = scope.capture();
    life.check();
    const generation = ++fitGeneration;
    pending = null; // 지난 제안이 실패한 새 맞춤 뒤에 남지 않게
    detectButton.setAttribute("disabled", "");
    detectButton.setAttribute("reason", "맞추는 중");
    state.textContent = "Vision에서 차선 페인트를 사이트 지도에 맞추는 중입니다…";
    state.dataset.tone = "neutral";
    guidance.hidden = true;
    render();
    visionView.showRaw();
    try {
      const [reply] = await Promise.all([fetchUntilCurrent(generation), ensureLanes({ force: !lanes })]);
      life.check();
      if (reply) showPending(reply, generation);
    } catch (error) {
      if (error.name === "AbortError") return;
      if (generation === fitGeneration) {
        state.textContent = error.message || "맞춤 제안을 받지 못했습니다.";
        state.dataset.tone = "warn";
      }
    } finally {
      if (life.current() && generation === fitGeneration) {
        detectButton.removeAttribute("disabled");
        detectButton.removeAttribute("reason");
      }
    }
    render();
  });
  scope.listen(acceptButton, "click", () => {
    const source = visionView.currentSource();
    if (!canAccept(pending, source)) return;
    const saved = storageSet(`${MAP_FIT_PREFIX}${source}`, draftFrom(pending.norm, pending.stamp));
    pending = null;
    showSummary({ tone: "good", guidance: null, headline: saved
      ? "맞춤을 이 브라우저의 표시 초안으로 저장했습니다. 관측 좌표·CameraMap·주행에는 쓰지 않습니다."
      : "브라우저 저장을 쓸 수 없어 수락한 맞춤을 보관하지 못했습니다." });
    render();
    onChanged();
  });
  // D-457 1항: 같은 최신 제안을 Fleet 추적 보정 기록으로 승인한다(운용자). 관제 카메라 추적 표시에만 쓰인다.
  // 위의 "맞춤 수락"(이 브라우저의 표시 초안)과 별개다 — 하나가 다른 하나를 대신하지 않는다.
  scope.listen(applyButton, "click", async () => {
    const life = scope.capture();
    life.check();
    const source = visionView.currentSource();
    const laneSet = lanes ? pickLanes(lanes, source) : null;
    const body = calibrationRequest(pending, source, laneSet, visionView.currentLensInfo());
    if (!body) {
      showSummary({ tone: "warn", guidance: null,
        headline: "추적 보정을 적용할 수 없습니다 — 이 카메라의 최신 통과 제안과 사이트 차선 지도가 필요합니다." });
      return;
    }
    if (applying) return;
    applying = true;
    try {
      const record = await call("/api/fleet/calibrations", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body), signals: [life.signal],
      });
      life.check();
      const lensNote = body.lens ? "" : " 렌즈 정보가 없어 렌즈 검사 없이 적용했습니다.";
      showSummary({ tone: "good", guidance: null, headline: `추적 보정 ${record.calibration_revision} 적용 — `
        + `관제 카메라 추적 표시에만 씁니다(관측·주행 아님). 렌즈를 바꾸면 다시 맞추세요.${lensNote}` });
    } catch (error) {
      if (error.name === "AbortError") return;
      showSummary({ tone: "warn", guidance: null, headline: `추적 보정 적용 실패: ${error.message || error}` });
    } finally {
      applying = false;
    }
  });

  scope.listen(dismissButton, "click", () => {
    pending = null;
    showSummary({ tone: "neutral", guidance: null, headline: "제안을 버렸습니다. 저장한 맞춤은 그대로입니다." });
    render();
  });
  scope.listen(clearButton, "click", () => {
    storageRemove(`${MAP_FIT_PREFIX}${visionView.currentSource()}`);
    showSummary({ tone: "neutral", guidance: null, headline: "이 카메라의 저장한 맞춤을 지웠습니다." });
    render();
    onChanged();
  });

  scope.subscribe(() => visionView.onFrame(scope.guard((frame) => {
    if (lastFrame?.source !== frame.source && pending && pending.source !== frame.source) pending = null;
    lastFrame = frame;
    if (!lanes && draftFor(frame.source)) {
      const life = scope.capture();
      ensureLanes().then(() => {
      life.check();
        render();
        onChanged();
      }).catch(error => { if (error.name !== "AbortError") throw error; });
    }
    render();
  })));

  // D-360 경기장 뷰 대체 경로: 운용자가 수락한 지도 맞춤이 있을 때만, 지도 사각형을 그 homography 로 편다.
  view.mapFieldFallback = (frame) => {
    const draft = frame && !frame.rectified ? draftFor(frame.source) : null;
    const laneSet = draft && lanes ? pickLanes(lanes, frame.source) : null;
    if (!laneSet || !frame.image?.naturalWidth
        || !fitUsable(draft, frame.image.naturalWidth, frame.image.naturalHeight, laneSet).ok) return null;
    return { mapToShown: displayMatrices(draft, frame.image).mapToShown, bounds: laneSet.bounds };
  };

  function reset() {
    fitGeneration += 1; // 진행 중인 맞춤의 늦은 결과가 초기화를 덮지 않게
    detectButton.removeAttribute("disabled");
    detectButton.removeAttribute("reason");
    lanes = null;
    lanesAt = 0;
    pending = null;
    lastFrame = null;
    warped = null;
    render();
  }
  scope.onDispose(() => {
    fitGeneration++;
    lanesAt = 0;
    pending = null;
    lastFrame = null;
    warped = null;
    detectButton.removeAttribute("disabled");
    detectButton.removeAttribute("reason");
  });

  return { render, reset };
}
