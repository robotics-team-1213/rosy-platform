// Interactive N-point camera-to-map calibration workbench (loupe, residuals, before/after compare, freeze & rollback).
import {
  flatMatrix, invert3, project, projectPolyline, projectTriangles, pickLanes, topDownLayout, fitFromCalibration,
} from "/console/assets/map-fit.js";
import { setOffBy } from "/common/cause-line.js";
import { colorForErrorM, drawLoupe, formatRecalStatus, seedPointsFromFit, snapMapPoint, warpTopDownCanvas } from "/console/assets/manual-fit-math.js";
import { isOperator } from "/console/assets/authorization.js";

const tone = (name) => window.RosyPalette.cssColor(name);
const font = (role = "micro", family = "mono") => window.RosyPalette.canvasFont(role, family);

const REASONS_KO = {
  ok: "게이트 통과",
  horizon_inside_track_bounds: "지평선이 트랙 경계 내부로 들어왔습니다",
  collinear_points: "대응점이 일직선에 가깝습니다(넓게 분산 배치하세요)",
  camera_height_out_of_range: "추정 카메라 높이가 허용 범위(0.3~10 m) 밖입니다",
  excessive_shear: "비물리적 전단/왜곡이 과도합니다(대응점 또는 렌즈를 확인하세요)",
  high_reprojection_error: "재투영 오차가 큽니다(잘못 찍힌 점을 확인하세요)",
};

export function createManualFitView({ scope, el, call, visionView, auth, onApplied = () => {} }) {
  const root = el("calibration-workbench");
  if (!root) return { refresh: () => {}, reset: () => {}, updateAuthorization: () => {} };
  const camCanvas = el("manual-cam-canvas");
  const mapCanvas = el("manual-map-canvas");
  const cmpCanvas = el("manual-compare-canvas");
  const summaryEl = el("manual-summary");
  const lensSelect = el("manual-lens-mode");
  const lensFile = el("manual-lens-file");
  const blendInput = el("manual-blend");
  const compareMode = el("manual-compare-mode");
  const freezeBtn = el("manual-freeze");
  const applyBtn = el("manual-apply");
  const solveBtn = el("manual-solve");
  const seedBtn = el("manual-seed");
  const delBtn = el("manual-del-point");
  const clearBtn = el("manual-clear");
  const historyList = el("manual-history");
  const recalBanner = el("manual-fit-recal-banner");
  const recalText = el("manual-recal-text");
  const recalPreviewBtn = el("manual-recal-preview");
  const recalAcceptBtn = el("manual-recal-accept");
  const recalDismissBtn = el("manual-recal-dismiss");
  const scratch = document.createElement("canvas");

  let lanes = null;
  let calibrations = [];
  let historyMap = {};
  let recalMap = {};
  let previewCandidate = null;
  let lastFrame = null;
  let pairs = [];       // [{ imagePx: [u,v]|null, mapM: [x,y]|null }]
  let selectedIdx = -1;
  let hoverImg = null;  // [u, v] in raw image pixels
  let drag = null;      // { side: "cam"|"map"|"pan", idx, startX, startY, panX, panY }
  let camView = { zoom: 1, panX: 0, panY: 0 };
  let uploadedLens = null;
  let solved = null;
  let solveTimer = null;
  let busy = false;
  let beforeCache = { key: null, data: null };
  let afterCache = { key: null, data: null };

  const operator = () => isOperator(auth?.role) && !auth?.locked;
  const currentSource = () => visionView.currentSource();
  const currentLaneSet = () => (lanes ? pickLanes(lanes, currentSource()) : null);
  const activeRecord = () => {
    const src = currentSource(), ls = currentLaneSet();
    return calibrations.find((r) => r?.source_id === src && (!ls?.mapId || !r?.map_id || r.map_id === ls.mapId)) || null;
  };
  const activeLensProfile = () => {
    const mode = lensSelect?.value || "active";
    if (mode === "none") return null;
    if (mode === "upload") return uploadedLens;
    return activeRecord()?.lens_profile || uploadedLens || null;
  };

  function camToCanvas(u, v, cw, ch, iw, ih) {
    const baseScale = Math.min(cw / iw, ch / ih);
    const s = baseScale * camView.zoom;
    const ox = (cw - iw * baseScale) * 0.5 + camView.panX;
    const oy = (ch - ih * baseScale) * 0.5 + camView.panY;
    return [ox + u * s, oy + v * s, s, ox, oy];
  }
  function canvasToCam(cx, cy, cw, ch, iw, ih) {
    const baseScale = Math.min(cw / iw, ch / ih);
    const s = baseScale * camView.zoom;
    const ox = (cw - iw * baseScale) * 0.5 + camView.panX;
    const oy = (ch - ih * baseScale) * 0.5 + camView.panY;
    return [(cx - ox) / s, (cy - oy) / s];
  }
  function canvasEventPt(canvas, ev) {
    const r = canvas.getBoundingClientRect();
    return [(ev.clientX - r.left) * (canvas.width / Math.max(1, r.width)),
      (ev.clientY - r.top) * (canvas.height / Math.max(1, r.height))];
  }

  function drawCameraPane() {
    const ctx = camCanvas.getContext("2d");
    const cw = camCanvas.width, ch = camCanvas.height;
    ctx.fillStyle = tone("--ground-deep");
    ctx.fillRect(0, 0, cw, ch);
    const img = lastFrame?.image;
    if (!img?.naturalWidth) {
      ctx.fillStyle = tone("--ink-quiet"); ctx.font = font("label", "body");
      ctx.fillText("카메라 영상 대기 중…", 16, 28);
      return;
    }
    const iw = img.naturalWidth, ih = img.naturalHeight;
    const [, , s, ox, oy] = camToCanvas(0, 0, cw, ch, iw, ih);
    ctx.save();
    ctx.drawImage(img, ox, oy, iw * s, ih * s);
    pairs.forEach((p, idx) => {
      if (!p.imagePx) return;
      const [px, py] = camToCanvas(p.imagePx[0], p.imagePx[1], cw, ch, iw, ih);
      const err = solved?.residuals_m?.[idx]?.err_m;
      const col = tone(idx === selectedIdx ? "--series-primary" : (err != null ? colorForErrorM(err) : "--status-warn"));
      ctx.strokeStyle = col; ctx.fillStyle = col; ctx.lineWidth = 2;
      ctx.beginPath(); ctx.arc(px, py, 6, 0, Math.PI * 2); ctx.stroke();
      ctx.font = font("micro", "mono"); ctx.fillText(String(idx + 1), px + 8, py - 6);
    });
    ctx.restore();
    if (hoverImg) drawLoupe(ctx, img, hoverImg[0], hoverImg[1], cw);
  }

  function drawLanesOn(ctx, h, ls, stroke, lw = 1.5) {
    ctx.save();
    ctx.fillStyle = stroke; ctx.globalAlpha = 0.35;
    for (const [a, b, c] of projectTriangles(ls.triangles, h)) {
      ctx.beginPath(); ctx.moveTo(...a); ctx.lineTo(...b); ctx.lineTo(...c); ctx.closePath(); ctx.fill();
    }
    ctx.globalAlpha = 0.9; ctx.strokeStyle = stroke; ctx.lineWidth = lw;
    for (const line of ls.polylines) {
      for (const run of projectPolyline(line.points, h, line.closed === true)) {
        ctx.beginPath(); run.forEach(([x, y], i) => (i ? ctx.lineTo(x, y) : ctx.moveTo(x, y))); ctx.stroke();
      }
    }
    ctx.restore();
  }

  function drawMapPane() {
    const ctx = mapCanvas.getContext("2d");
    const cw = mapCanvas.width, ch = mapCanvas.height;
    ctx.fillStyle = tone("--ground-deep"); ctx.fillRect(0, 0, cw, ch);
    const ls = currentLaneSet();
    if (!ls) { ctx.fillStyle = tone("--ink-quiet"); ctx.font = font("label", "body"); ctx.fillText("사이트 차선 지도 없음", 16, 28); return; }
    const layout = topDownLayout(ls.bounds, cw, ch, 0.15);
    drawLanesOn(ctx, layout.mapToCanvas, ls, tone("--series-primary"), 1.5);
    pairs.forEach((p, idx) => {
      if (!p.mapM) return;
      const pt = project(layout.mapToCanvas, p.mapM[0], p.mapM[1]);
      if (!pt) return;
      const res = solved?.residuals_m?.[idx];
      const col = tone(idx === selectedIdx ? "--series-primary" : (res ? colorForErrorM(res.err_m) : "--status-warn"));
      if (res) {
        const pred = project(layout.mapToCanvas, p.mapM[0] + res.dx_m, p.mapM[1] + res.dy_m);
        if (pred) {
          ctx.strokeStyle = col; ctx.lineWidth = 2;
          ctx.beginPath(); ctx.moveTo(pt[0], pt[1]); ctx.lineTo(pred[0], pred[1]); ctx.stroke();
        }
      }
      ctx.fillStyle = col; ctx.strokeStyle = tone("--ink"); ctx.lineWidth = 1.5;
      ctx.beginPath(); ctx.arc(pt[0], pt[1], 5, 0, Math.PI * 2); ctx.fill(); ctx.stroke();
      ctx.font = font("micro", "mono"); ctx.fillText(String(idx + 1), pt[0] + 7, pt[1] - 5);
    });
  }

  function drawComparePane() {
    const ctx = cmpCanvas.getContext("2d");
    const cw = cmpCanvas.width, ch = cmpCanvas.height;
    ctx.fillStyle = tone("--ground-deep"); ctx.fillRect(0, 0, cw, ch);
    const ls = currentLaneSet(), img = lastFrame?.image;
    if (!ls || !img?.naturalWidth) return;
    const layout = { ...topDownLayout(ls.bounds, cw, ch, 0.15), bounds: ls.bounds };
    const rec = activeRecord();
    const curFit = rec ? fitFromCalibration(rec, visionView.currentLensInfo()) : null;
    const sx = img.naturalWidth / (curFit?.image?.width || img.naturalWidth);
    const sy = img.naturalHeight / (curFit?.image?.height || img.naturalHeight);
    const scaleM = [sx, 0, 0, 0, sy, 0, 0, 0, 1];
    const mult = (a, b) => [0, 1, 2].flatMap((r) => [0, 1, 2].map((c) => a[r * 3] * b[c] + a[r * 3 + 1] * b[c + 3] + a[r * 3 + 2] * b[c + 6]));
    const mode = compareMode?.value || "after";
    const alpha = mode === "before" ? 0 : mode === "after" ? 1 : (Number(blendInput?.value ?? 50) / 100);
    if (alpha < 1 && curFit?.mapToImage) {
      const m2s = mult(scaleM, curFit.mapToImage);
      const bk = JSON.stringify([lastFrame.seq, rec.calibration_revision, cw, ch]);
      if (beforeCache.key !== bk) beforeCache = { key: bk, data: warpTopDownCanvas(ctx, img, m2s, layout, scratch, curFit.lensProfile) };
      if (beforeCache.data) ctx.putImageData(beforeCache.data, 0, 0);
    }
    const cand = solved?.map_to_image ? solved : previewCandidate;
    if (alpha > 0 && cand?.map_to_image) {
      const ak = JSON.stringify([lastFrame.seq, cand.map_to_image, cand.lens_profile?.D, cw, ch]);
      if (afterCache.key !== ak) afterCache = { key: ak, data: warpTopDownCanvas(ctx, img, cand.map_to_image, layout, scratch, cand.lens_profile) };
      if (afterCache.data) {
        if (alpha >= 1) ctx.putImageData(afterCache.data, 0, 0);
        else {
          const tmp = document.createElement("canvas"); tmp.width = cw; tmp.height = ch;
          tmp.getContext("2d").putImageData(afterCache.data, 0, 0);
          ctx.save(); ctx.globalAlpha = alpha; ctx.drawImage(tmp, 0, 0); ctx.restore();
        }
      }
    }
    drawLanesOn(ctx, layout.mapToCanvas, ls, tone("--status-good"), 1.5);
  }

  function renderHistory() {
    if (!historyList) return;
    const src = currentSource(), cur = activeRecord();
    const rows = historyMap[src] || [];
    if (!rows.length) {
      const empty = document.createElement("li");
      empty.textContent = "저장된 보정 이력이 없습니다.";
      historyList.replaceChildren(empty);
      return;
    }
    historyList.replaceChildren(...rows.map((row) => {
      const li = document.createElement("li");
      const info = document.createElement("span");
      const isCur = cur?.calibration_revision === row.calibration_revision;
      const rms = row.metrics?.rms_m != null ? ` · RMS ${(row.metrics.rms_m * 100).toFixed(1)} cm` : "";
      info.textContent = `${row.calibration_revision}${isCur ? " (현재)" : ""} · ${row.method || "paint"}${rms}${row.has_lens_profile ? " · 렌즈보정" : ""}`;
      li.append(info);
      if (!isCur && operator()) {
        const btn = document.createElement("ui-button");
        btn.setAttribute("kind", "quiet");
        btn.textContent = "복원";
        btn.addEventListener("click", () => rollbackTo(row.calibration_revision));
        li.append(btn);
      }
      return li;
    }));
  }

  function render() {
    drawCameraPane();
    drawMapPane();
    drawComparePane();
    const rec = activeRecord();
    if (freezeBtn) {
      setOffBy(freezeBtn, busy ? "처리 중" : !operator() ? "운영자 권한 필요" : !rec ? "적용된 보정 없음" : "");
      freezeBtn.textContent = rec?.frozen ? "자동 보정 잠금 해제" : "자동 보정 잠금 (Freeze)";
    }
    const complete = pairs.filter((p) => p.imagePx && p.mapM);
    if (solveBtn) setOffBy(solveBtn, busy ? "계산 중" : !operator() ? "운영자 권한 필요" : complete.length < 4 ? "대응점 4개 이상 필요" : "");
    if (applyBtn) setOffBy(applyBtn, busy ? "적용 중" : !operator() ? "운영자 권한 필요" : !solved?.accepted ? "보정 계산을 먼저 통과하세요" : "");
    if (delBtn) setOffBy(delBtn, selectedIdx < 0 ? "선택된 점 없음" : "");
    if (blendInput) setOffBy(blendInput, (compareMode?.value || "after") !== "blend" ? "겹쳐 비교 모드에서 사용" : "");
    renderHistory();
    renderRecalBanner();
  }

  function renderRecalBanner() {
    if (!recalBanner || !recalText) return;
    const row = recalMap[currentSource()];
    const msg = formatRecalStatus(row);
    recalBanner.hidden = !msg;
    if (!msg) return;
    recalText.textContent = msg;
    const hasPend = Boolean(row?.pending_candidate);
    if (recalPreviewBtn) setOffBy(recalPreviewBtn, busy ? "처리 중" : !hasPend ? "대기 후보 없음" : "");
    if (recalAcceptBtn) setOffBy(recalAcceptBtn, busy ? "처리 중" : !operator() ? "운영자 권한 필요" : !hasPend ? "대기 후보 없음" : "");
    if (recalDismissBtn) setOffBy(recalDismissBtn, busy ? "처리 중" : "");
  }

  async function refreshRecords() {
    const life = scope.capture(); life.check();
    try {
      const [lsRes, calRes] = await Promise.all([
        call("/api/fleet/site-lanes", { signals: [life.signal] }),
        call("/api/fleet/calibrations?include_history=true", { signals: [life.signal] }),
      ]);
      life.check();
      lanes = lsRes;
      calibrations = Array.isArray(calRes?.calibrations) ? calRes.calibrations : [];
      historyMap = calRes?.history || {};
      recalMap = calRes?.recalibration || {};
      render();
    } catch (e) { if (e.name !== "AbortError") { /* ignore transient auth/load */ } }
  }

  async function runSolve() {
    const complete = pairs.filter((p) => p.imagePx && p.mapM);
    const ls = currentLaneSet(), img = lastFrame?.image, src = currentSource();
    if (complete.length < 4 || !ls || !img?.naturalWidth || !src) return;
    const life = scope.capture(); life.check();
    busy = true; render();
    try {
      const lens = visionView.currentLensInfo();
      const body = {
        source_id: src,
        ...(ls.mapId ? { map_id: ls.mapId } : {}),
        image: { width: img.naturalWidth, height: img.naturalHeight },
        track_bounds_m: ls.bounds,
        correspondences: complete.map((p) => ({ image_px: p.imagePx, map_m: p.mapM })),
        ...(lens && Number.isFinite(lens.focal_mm) && Number.isFinite(lens.hfov_deg)
          ? { lens: { kind: lens.kind, focal_mm: lens.focal_mm, hfov_deg: lens.hfov_deg } } : {}),
        ...(activeLensProfile() ? { lens_profile: activeLensProfile() } : {}),
      };
      solved = await call("/api/fleet/calibrations/fit", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body), signals: [life.signal],
      });
      life.check();
      const camH = solved.camera_pose_m ? ` · 높이 ${solved.camera_pose_m[2].toFixed(2)} m` : "";
      const warn = solved.warnings?.length ? ` · 주의: ${solved.warnings.join(", ")}` : "";
      summaryEl.textContent = `${REASONS_KO[solved.reason] || solved.reason} · RMS ${(solved.rms_m * 100).toFixed(1)} cm / p95 ${(solved.p95_m * 100).toFixed(1)} cm / 최대 ${(solved.max_m * 100).toFixed(1)} cm${camH} · 사분면 ${solved.quadrant_coverage}/4${warn}`;
    } catch (err) {
      if (err.name === "AbortError") return;
      solved = null;
      summaryEl.textContent = `계산 실패: ${err.message || err}`;
    } finally { busy = false; render(); }
  }

  function scheduleSolve() {
    clearTimeout(solveTimer);
    if (pairs.filter((p) => p.imagePx && p.mapM).length >= 4) {
      solveTimer = setTimeout(() => { void runSolve(); }, 180);
    }
  }

  async function applyManual() {
    const src = currentSource(), ls = currentLaneSet(), img = lastFrame?.image;
    if (!solved?.accepted || !ls || !img?.naturalWidth || !src || busy) return;
    const life = scope.capture(); life.check();
    busy = true; render();
    try {
      const lens = visionView.currentLensInfo();
      const body = {
        source_id: src, ...(ls.mapId ? { map_id: ls.mapId } : {}),
        map_to_image: solved.map_to_image,
        image: { width: img.naturalWidth, height: img.naturalHeight },
        track_bounds_m: ls.bounds,
        fit_score: solved.fit_score,
        lens: lens && Number.isFinite(lens.focal_mm) ? { kind: lens.kind, focal_mm: lens.focal_mm, hfov_deg: lens.hfov_deg } : null,
        frame_seq: lastFrame.seq ?? null,
        ...(solved.lens_profile ? { lens_profile: solved.lens_profile } : {}),
        method: "manual_points",
        metrics: { rms_m: solved.rms_m, p95_m: solved.p95_m, max_m: solved.max_m, point_count: pairs.filter((p) => p.imagePx && p.mapM).length },
      };
      const rec = await call("/api/fleet/calibrations", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body), signals: [life.signal],
      });
      life.check();
      summaryEl.textContent = `수동 보정 적용 완료: ${rec.calibration_revision}`;
      await refreshRecords();
      onApplied(rec);
    } catch (err) {
      if (err.name !== "AbortError") summaryEl.textContent = `적용 실패: ${err.message || err}`;
    } finally { busy = false; render(); }
  }

  async function toggleFreeze() {
    const src = currentSource(), rec = activeRecord();
    if (!src || !rec || busy) return;
    const life = scope.capture(); life.check();
    busy = true; render();
    try {
      const updated = await call(`/api/fleet/calibrations/${encodeURIComponent(src)}/freeze`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ frozen: !rec.frozen }), signals: [life.signal],
      });
      life.check();
      summaryEl.textContent = updated.frozen ? "자동 보정 덮어쓰기를 잠갔습니다(Freeze)." : "자동 보정 잠금을 해제했습니다.";
      await refreshRecords();
      onApplied(updated);
    } catch (err) {
      if (err.name !== "AbortError") summaryEl.textContent = `잠금 변경 실패: ${err.message || err}`;
    } finally { busy = false; render(); }
  }

  async function rollbackTo(targetRevision) {
    const src = currentSource();
    if (!src || busy) return;
    const life = scope.capture(); life.check();
    busy = true; render();
    try {
      const restored = await call(`/api/fleet/calibrations/${encodeURIComponent(src)}/rollback`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ target_revision: targetRevision }), signals: [life.signal],
      });
      life.check();
      summaryEl.textContent = `이전 보정으로 복원했습니다: ${restored.calibration_revision}`;
      await refreshRecords();
      onApplied(restored);
    } catch (err) {
      if (err.name !== "AbortError") summaryEl.textContent = `복원 실패: ${err.message || err}`;
    } finally { busy = false; render(); }
  }

  scope.listen(camCanvas, "wheel", (ev) => {
    ev.preventDefault();
    const img = lastFrame?.image; if (!img?.naturalWidth) return;
    const [cx, cy] = canvasEventPt(camCanvas, ev);
    const [u, v] = canvasToCam(cx, cy, camCanvas.width, camCanvas.height, img.naturalWidth, img.naturalHeight);
    camView.zoom = Math.max(1, Math.min(6, camView.zoom * (ev.deltaY < 0 ? 1.18 : 0.85)));
    if (camView.zoom === 1) { camView.panX = 0; camView.panY = 0; }
    else {
      const [nx, ny] = camToCanvas(u, v, camCanvas.width, camCanvas.height, img.naturalWidth, img.naturalHeight);
      camView.panX += cx - nx; camView.panY += cy - ny;
    }
    drawCameraPane();
  });

  scope.listen(camCanvas, "pointerdown", (ev) => {
    const img = lastFrame?.image; if (!img?.naturalWidth) return;
    const [cx, cy] = canvasEventPt(camCanvas, ev);
    if (ev.shiftKey || ev.button === 1 || ev.button === 2) {
      drag = { side: "pan", startX: cx, startY: cy, panX: camView.panX, panY: camView.panY };
      camCanvas.setPointerCapture(ev.pointerId); return;
    }
    const iw = img.naturalWidth, ih = img.naturalHeight;
    const hit = pairs.findIndex((p) => {
      if (!p.imagePx) return false;
      const [px, py] = camToCanvas(p.imagePx[0], p.imagePx[1], camCanvas.width, camCanvas.height, iw, ih);
      return Math.hypot(px - cx, py - cy) <= 12;
    });
    const [u, v] = canvasToCam(cx, cy, camCanvas.width, camCanvas.height, iw, ih);
    const clamped = [Number(Math.max(0, Math.min(iw - 1, u)).toFixed(2)), Number(Math.max(0, Math.min(ih - 1, v)).toFixed(2))];
    if (hit >= 0) { selectedIdx = hit; pairs[hit].imagePx = clamped; drag = { side: "cam", idx: hit }; }
    else {
      const needIdx = pairs.findIndex((p) => !p.imagePx);
      if (needIdx >= 0) { pairs[needIdx].imagePx = clamped; selectedIdx = needIdx; drag = { side: "cam", idx: needIdx }; }
      else { pairs.push({ imagePx: clamped, mapM: null }); selectedIdx = pairs.length - 1; drag = { side: "cam", idx: selectedIdx }; }
    }
    hoverImg = clamped;
    camCanvas.setPointerCapture(ev.pointerId);
    render(); scheduleSolve();
  });
  scope.listen(camCanvas, "pointermove", (ev) => {
    const img = lastFrame?.image; if (!img?.naturalWidth) return;
    const [cx, cy] = canvasEventPt(camCanvas, ev);
    if (drag?.side === "pan") {
      camView.panX = drag.panX + (cx - drag.startX); camView.panY = drag.panY + (cy - drag.startY);
      drawCameraPane(); return;
    }
    const [u, v] = canvasToCam(cx, cy, camCanvas.width, camCanvas.height, img.naturalWidth, img.naturalHeight);
    hoverImg = [Math.max(0, Math.min(img.naturalWidth - 1, u)), Math.max(0, Math.min(img.naturalHeight - 1, v))];
    if (drag?.side === "cam") {
      pairs[drag.idx].imagePx = [Number(hoverImg[0].toFixed(2)), Number(hoverImg[1].toFixed(2))];
      scheduleSolve();
    }
    drawCameraPane();
  });
  scope.listen(camCanvas, "pointerup", () => { drag = null; });
  scope.listen(camCanvas, "pointerleave", () => { hoverImg = null; drag = null; drawCameraPane(); });

  scope.listen(mapCanvas, "pointerdown", (ev) => {
    const ls = currentLaneSet(); if (!ls) return;
    const layout = topDownLayout(ls.bounds, mapCanvas.width, mapCanvas.height, 0.15);
    const [cx, cy] = canvasEventPt(mapCanvas, ev);
    const hit = pairs.findIndex((p) => {
      if (!p.mapM) return false;
      const pt = project(layout.mapToCanvas, p.mapM[0], p.mapM[1]);
      return pt && Math.hypot(pt[0] - cx, pt[1] - cy) <= 12;
    });
    const rawM = project(layout.canvasToMap, cx, cy); if (!rawM) return;
    const snapped = ev.altKey ? { x: rawM[0], y: rawM[1] } : snapMapPoint(rawM[0], rawM[1], ls);
    const ptM = [Number(snapped.x.toFixed(4)), Number(snapped.y.toFixed(4))];
    if (hit >= 0) { selectedIdx = hit; pairs[hit].mapM = ptM; drag = { side: "map", idx: hit }; }
    else {
      const needIdx = pairs.findIndex((p) => !p.mapM);
      if (needIdx >= 0) { pairs[needIdx].mapM = ptM; selectedIdx = needIdx; drag = { side: "map", idx: needIdx }; }
      else { pairs.push({ imagePx: null, mapM: ptM }); selectedIdx = pairs.length - 1; drag = { side: "map", idx: selectedIdx }; }
    }
    mapCanvas.setPointerCapture(ev.pointerId);
    render(); scheduleSolve();
  });
  scope.listen(mapCanvas, "pointermove", (ev) => {
    if (drag?.side !== "map") return;
    const ls = currentLaneSet(); if (!ls) return;
    const layout = topDownLayout(ls.bounds, mapCanvas.width, mapCanvas.height, 0.15);
    const [cx, cy] = canvasEventPt(mapCanvas, ev);
    const rawM = project(layout.canvasToMap, cx, cy); if (!rawM) return;
    const snapped = ev.altKey ? { x: rawM[0], y: rawM[1] } : snapMapPoint(rawM[0], rawM[1], ls);
    pairs[drag.idx].mapM = [Number(snapped.x.toFixed(4)), Number(snapped.y.toFixed(4))];
    render(); scheduleSolve();
  });
  scope.listen(mapCanvas, "pointerup", () => { drag = null; });

  scope.listen(seedBtn, "click", () => {
    const rec = activeRecord(), ls = currentLaneSet(), img = lastFrame?.image;
    const fit = rec ? fitFromCalibration(rec, visionView.currentLensInfo()) : null;
    if (!fit || !ls || !img?.naturalWidth) { summaryEl.textContent = "초기 핀을 채울 승인 보정 또는 영상이 없습니다."; return; }
    pairs = seedPointsFromFit(fit, ls, img.naturalWidth, img.naturalHeight);
    selectedIdx = pairs.length ? 0 : -1;
    render(); scheduleSolve();
  });
  scope.listen(delBtn, "click", () => {
    if (selectedIdx < 0) return;
    pairs.splice(selectedIdx, 1);
    selectedIdx = pairs.length ? Math.min(selectedIdx, pairs.length - 1) : -1;
    solved = null; render(); scheduleSolve();
  });
  scope.listen(clearBtn, "click", () => { pairs = []; selectedIdx = -1; solved = null; render(); });
  scope.listen(solveBtn, "click", () => { void runSolve(); });
  scope.listen(applyBtn, "click", () => { void applyManual(); });
  scope.listen(freezeBtn, "click", () => { void toggleFreeze(); });
  scope.listen(recalPreviewBtn, "click", () => {
    const cand = recalMap[currentSource()]?.pending_candidate;
    if (!cand) return;
    solved = null; previewCandidate = cand;
    if (compareMode) compareMode.value = "blend";
    drawComparePane();
  });
  scope.listen(recalAcceptBtn, "click", async () => {
    const src = currentSource(); if (!src || busy) return;
    const life = scope.capture(); life.check(); busy = true; render();
    try {
      const res = await call(`/api/fleet/calibrations/${encodeURIComponent(src)}/recalibrate/accept`, { method: "POST", signals: [life.signal] });
      life.check(); previewCandidate = null;
      summaryEl.textContent = `재보정 후보 적용 완료: ${res.record?.calibration_revision || ""}`;
      await refreshRecords(); onApplied(res.record);
    } catch (err) { if (err.name !== "AbortError") summaryEl.textContent = `후보 적용 실패: ${err.message || err}`; }
    finally { busy = false; render(); }
  });
  scope.listen(recalDismissBtn, "click", async () => {
    const src = currentSource(); if (!src || busy) return;
    const life = scope.capture(); life.check(); busy = true; render();
    try {
      await call(`/api/fleet/calibrations/${encodeURIComponent(src)}/recalibrate/dismiss`, { method: "POST", signals: [life.signal] });
      life.check(); previewCandidate = null; await refreshRecords();
    } catch (err) { if (err.name !== "AbortError") summaryEl.textContent = `무시 실패: ${err.message || err}`; }
    finally { busy = false; render(); }
  });
  scope.listen(compareMode, "change", render);
  scope.listen(blendInput, "input", render);
  scope.listen(lensSelect, "change", () => {
    if (lensSelect.value === "upload" && lensFile) lensFile.click();
    render(); scheduleSolve();
  });
  if (lensFile) {
    scope.listen(lensFile, "change", async () => {
      const f = lensFile.files?.[0]; if (!f) return;
      try {
        const doc = JSON.parse(await f.text());
        const lp = doc.lens?.K ? doc.lens : doc;
        if (!Array.isArray(lp.K) || !Array.isArray(lp.D) || !Array.isArray(lp.image_size)) throw new Error("K/D/image_size 필요");
        uploadedLens = { model: lp.model || "pinhole", K: lp.K, D: lp.D, image_size: lp.image_size, source: "measured", revision: lp.revision };
        summaryEl.textContent = `렌즈 프로파일 불러옴 (${uploadedLens.model} ${uploadedLens.image_size.join("x")})`;
        render(); scheduleSolve();
      } catch (err) { summaryEl.textContent = `렌즈 JSON 오류: ${err.message || err}`; }
    });
  }
  scope.subscribe(() => visionView.onFrame(scope.guard((frame) => {
    if (lastFrame?.source !== frame.source) { pairs = []; selectedIdx = -1; solved = null; camView = { zoom: 1, panX: 0, panY: 0 }; }
    lastFrame = frame;
    if (!lanes) void refreshRecords();
    else render();
  })));
  function reset() { pairs = []; selectedIdx = -1; solved = null; lastFrame = null; camView = { zoom: 1, panX: 0, panY: 0 }; render(); }
  return { refresh: refreshRecords, reset, updateAuthorization: render };
}
