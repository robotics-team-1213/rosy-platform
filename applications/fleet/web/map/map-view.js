// 현장 지도 뷰 (Fleet 분해 4). 격자 paint·좌표 변환·로봇/목표 그리기를 가진다. 대형·중재·관측
// 오버레이는 map-overlays.js, 맵 폴링은 map-polling.js가 가진다(D-798 3.2). 셸은 클릭-목표 지정과 토큰·폴링 주기를 쥔다.
// 좌표계: 로봇 pose 는 CORE 가 TF `map → <ns>base_footprint` 로 읽어 주는 map 프레임
// 값이다(ros_bridge `_map_frame = "map"`). 그래서 N대를 한 격자 위에 그대로 겹쳐
// 그릴 수 있다. 격자는 행 0 이 아래쪽(y 최소)이고 캔버스는 위가 0 이라 y 를 뒤집는다.
// D-257 사이트 층: 천장 카메라가 덮는 사각형과 카메라 관측(sighting)을 같은 map 프레임에
// 그린다. 관측은 속이 빈 점선 고리로, CORE TF pose(채운 삼각형)와 섞지 않는다.

import {
  siteBounds, siteStageHeight, fitTransform, project, gridLines, GRID_STEP_M,
  streamEvidence, quarterTurn,
} from "./site-layer.js";
import { createCameraBackdrop } from "./camera-backdrop.js";
import { createMapOverlays } from "./map-overlays.js";
import { createMapPolling } from "./map-polling.js";
import { drawTrails } from "./trail-view.js";
import { drawSignalLamps, drawTraffic } from "./traffic-view.js";
import { drawGuide } from "/console/assets/guide-layer.js";
import { robotMapPose } from "./localization-badge.js";
import { createChoiceGroup } from "/common/choice-group.js";
import { lockWithMap } from "./map-tool-lock.js";
import { drawLocalizationCandidates } from "/console/assets/localization-view.js";
import { drawMapDatum } from "./map-datum.js";
import { createCadTwinLayer } from "./cad-twin-layer.js";
import { createSiteTwin3d } from "/common/site-twin-3d.js";

// Map label: the short id ("rosy_012" -> "012").
const shortId = (robotId) => String(robotId).replace(/^rosy_/, "");

export function createMapView({ scope, el, view, auth, call, onMapChanged, onMapUnavailable, onTrafficChanged = () => {},
  onSelectRobotFromMap = null, onSelectPlaceFromMap = null, onSelectPoint = null, onHoverEntity = null }) {
  view.twinUnavailableNotice = view.twinUnavailableNotice || "";
  view.twinFailed = Boolean(view.twinFailed);
  const camera = createCameraBackdrop({ scope, el, view, draw });
  const setDisplayMode = (mode) => {
    camera.setMode(mode);
    const stage = el("map-stage");
    if (stage) {
      stage.dataset.displayMode = view.displayMode;
      stage.dataset.view = view.displayMode === "camera" ? "camera" : view.displayMode === "twin3d" ? "twin3d" : "map";
    }
  };
  view.setDisplayMode = setDisplayMode;
  // D-359 §4 — 색·글꼴은 ui.js(window.RosyPalette)가 어떤 CSS 색이든 풀어 캐시한다.
  const css = (name) => window.RosyPalette.cssColor(name);
  const font = (role, displayScale = 1) => window.RosyPalette.canvasFont(role, "mono", displayScale);
  const cadTwin = createCadTwinLayer({ scope, call, css, view, onLoaded: () => draw() });
  let twin3d = null;
  let twinFailed = false;
  scope.onDispose(() => { twin3d?.dispose?.(); twin3d = null; });
  const GRID = { UNKNOWN: -1, FREE_MAX: 25, OCCUPIED_MIN: 65 };
  // D-360 레이어 토글. 기본은 모두 켜고, 상단 #map-overlay-toggles 버튼으로 전체 또는 개별 층을 즉시 켜고 끈다.
  if (!view.layers) {
    view.layers = { poses: true, omx: true, lanes: true, traffic: true, labels: true, cad: true, site: true, grid: true, sightings: true, tracking: true };
  }
  const layerOn = (key) => view.layers?.[key] !== false;
  const toggleSlot = el("map-overlay-slot");
  if (toggleSlot) {
    const layerItems = [
      { value: "poses", label: "로봇·경로" },
      { value: "omx", label: "OMX-AI" },
      { value: "lanes", label: "도로·장소" },
      { value: "cad", label: "CAD 모델" },
      { value: "traffic", label: "교통·점유" },
      { value: "labels", label: "라벨" },
    ];
    const layerGroup = createChoiceGroup({
      id: "map-overlay-toggles",
      label: "지도 오버레이 표시",
      mode: "toggle",
      master: { label: "전체" },
      items: layerItems,
      value: layerItems.map(item => item.value).filter(key => view.layers[key] !== false),
      onChange: (values) => {
        const anyOn = values.length > 0;
        for (const item of layerItems) view.layers[item.value] = values.includes(item.value);
        view.layers.site = anyOn;
        view.layers.grid = anyOn;
        view.layers.sightings = view.layers.poses;
        view.layers.tracking = view.layers.poses;
        draw();
      },
    });
    toggleSlot.replaceWith(layerGroup.element);
    lockWithMap({ stage: el("map-stage"), group: layerGroup, items: layerItems, scope });
    scope.onDispose(() => layerGroup.dispose());
  }
  const {
    CHIP_GAP, chipFontSize, drawChip, flushChips, resetChips, addMarker, cellOf, activeCall, labelImportant,
    drawFormationOverlay, drawMediation, drawSighting, drawCameraTracking, sitePolygons, tracePolygon, drawCrosswalks,
    drawSiteOverlay, datumBottomInset, paintPlaceLabels, drawSiteLanesAndPlaces,
  } = createMapOverlays({ view, css, font, layerOn, worldToCell, colorOf, el });

  let gridRasterCache = { grid: null, themeKey: "", canvas: null };
  let lastPlaceListSig = "";
  function paintGrid(grid) {
    const canvas = el("map-canvas");
    const { width, height } = grid;
    // Occupancy cells stay pixelated, while map labels need enough backing pixels
    // to remain legible when a small grid is stretched across the console.
    const displaySize = Math.min(canvas.clientWidth || 1600, canvas.clientHeight || 1600) * (window.devicePixelRatio || 1);
    const scale = Math.min(10, Math.max(1, Math.round(displaySize / Math.max(width, height))));
    const nextW = width * scale, nextH = height * scale;
    if (canvas.width !== nextW) canvas.width = nextW;
    if (canvas.height !== nextH) canvas.height = nextH;
    const ctx = canvas.getContext("2d");
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.imageSmoothingEnabled = false;
    // 로봇 지도(dashboard map.js)와 같은 raster 토큰이다 — 두 화면의 지형 색이 같다.
    const tone = window.RosyPalette.readPalette({
      unknown: "--raster-unknown", free: "--raster-free",
      uncertain: "--raster-uncertain", occupied: "--raster-occupied",
    });
    const themeKey = `${tone.unknown.join(",")}|${tone.free.join(",")}|${tone.uncertain.join(",")}|${tone.occupied.join(",")}`;
    if (gridRasterCache.grid !== grid || gridRasterCache.themeKey !== themeKey || !gridRasterCache.canvas) {
      const image = ctx.createImageData(width, height);
      for (let row = 0; row < height; row += 1) {
        for (let col = 0; col < width; col += 1) {
          const value = grid.data[row * width + col];
          const rgb = value === GRID.UNKNOWN || value < 0 ? tone.unknown
            : value >= GRID.OCCUPIED_MIN ? tone.occupied
              : value <= GRID.FREE_MAX ? tone.free : tone.uncertain;
          const pixel = ((height - 1 - row) * width + col) * 4;
          image.data[pixel] = rgb[0];
          image.data[pixel + 1] = rgb[1];
          image.data[pixel + 2] = rgb[2];
          image.data[pixel + 3] = 255;
        }
      }
      const cells = gridRasterCache.canvas || document.createElement("canvas");
      cells.width = width;
      cells.height = height;
      cells.getContext("2d").putImageData(image, 0, 0);
      gridRasterCache = { grid, themeKey, canvas: cells };
    }
    ctx.drawImage(gridRasterCache.canvas, 0, 0, canvas.width, canvas.height);
    ctx.scale(scale, scale); // following geometry keeps using map-cell coordinates
  }

  function worldToCell(grid, x, y) {
    return { col: (x - grid.origin.x) / grid.resolution, row: (y - grid.origin.y) / grid.resolution };
  }

  function toWorld(grid, col, row) {
    return { x: grid.origin.x + (col + 0.5) * grid.resolution, y: grid.origin.y + (row + 0.5) * grid.resolution };
  }

  function colorOf(robotId) {
    const index = view.robots.findIndex((r) => r.robot_id === robotId);
    return view.colors[(index >= 0 ? index : 0) % view.colors.length];
  }

  // 사이트 뷰 스테이지 높이는 CSS(styles.css 사이트 스코프)가 min/max-block-size 로 정하고,
  // 이 그림은 그 경계 안에서 폭×사이트 비율로 비트맵 높이를 계산해 고유 비율을 맞춘다.
  // 계산값이 없는 환경(node 시험)은 데스크톱 기본(바닥 12.5rem, 상한 46rem)을 쓴다.
  function stageSizeLimits(stage) {
    const win = stage?.ownerDocument?.defaultView;
    if (!win?.getComputedStyle) return { minPx: 200, maxPx: 736 };
    const cs = win.getComputedStyle(stage);
    const px = (value, fallback) => { const n = parseFloat(value); return Number.isFinite(n) ? n : fallback; };
    return { minPx: px(cs.minBlockSize, 200), maxPx: px(cs.maxBlockSize, Infinity) };
  }

  // D-540: 지도 열(.console-primary)은 스크롤하지 않는다. 열 높이에서 스테이지 밖 블록·간격을 뺀
  // 남은 높이를 읽는다(읽기만 — 스타일 주입 없음). 고정 프레임(데스크톱)이 아니면 제한 없음.
  function stageAvailPx(stage) {
    const win = stage?.ownerDocument?.defaultView;
    const col = stage?.closest?.(".console-primary");
    if (!col || !win?.matchMedia?.("(width >= 64rem) and (height >= 40rem)").matches || !col.clientHeight) return Infinity;
    const kids = [...col.children].map((c) => c.getBoundingClientRect()).filter((r) => r.height > 0);
    if (!kids.length) return Infinity;
    const cs = win.getComputedStyle(col);
    const used = Math.max(...kids.map((r) => r.bottom)) - Math.min(...kids.map((r) => r.top));
    const other = used - stage.getBoundingClientRect().height;
    return col.clientHeight - (parseFloat(cs.paddingTop) || 0) - (parseFloat(cs.paddingBottom) || 0) - other;
  }

  // 점유 격자가 없을 때: 사이트 사각형에 맞춘 미터 축척 뷰. 목표 지정은 받지 않는다.
  function drawSiteView() {
    const bounds = siteBounds(view.siteMap);
    if (!bounds) return;
    const stage = el("map-stage");
    const canvas = el("map-canvas");
    const calibration = camera.calibration();
    // 교정 낡음(카메라 재조준): 정지 로봇의 관측 차이가 계속 클 때(tracking-view). D-595: 이것은
    // 진단 경고일 뿐이다 — 그림은 수락된 보정으로 그대로 두고(폴링마다 바뀌지 않게) 경고만 얹는다.
    // 보정을 바꾸는 것은 설치의 맵 고정(맞춤 → 추적 보정 적용)뿐이다.
    const cameraOn = view.displayMode === "overlay" && Boolean(calibration);
    // 비트맵 크기(D-593 개정): 폭은 스테이지 폭(=열 폭), 높이는 폭×사이트 비율+여백(siteStageHeight).
    // 스테이지 높이를 읽지 않아 순환이 없다. 스테이지를 아직 모르면(숨김 등) 기본 높이로 대신한다.
    // D-515: 실영상도 지도 미터 뷰(+y 위) 위에 위에서 본 직사각형으로 편다. 지도 방향이 화면
    // 방향이라 따로 돌리지 않고(D-513 7의 mapUpTurn 불필요), 클릭도 미터 뷰를 그대로 거꾸로 푼다.
    const rect = stage.getBoundingClientRect();
    const width = rect.width > 0 ? rect.width : (canvas.clientWidth || 800);
    const rot = view.siteViewTurn || 0;
    const { minPx, maxPx } = stageSizeLimits(stage);
    const height = siteStageHeight(width, bounds, rot, 32, minPx, maxPx, stageAvailPx(stage));
    const dpr = window.devicePixelRatio || 1;
    const targetW = Math.round(width * dpr);
    const targetH = Math.round(height * dpr);
    if (canvas.width !== targetW) canvas.width = targetW;
    if (canvas.height !== targetH) canvas.height = targetH;
    const ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    // D-515 + D-513 7: 사이트 지도의 화면 방향(view_turn_deg, 시계 방향 quarter turn)만큼 미터 뷰를
    // 돌린다. 돌린 상자 크기에 맞춰 넣고, 모든 점(영상 삼각형·차로·로봇·글자 자리)을 toPx 하나로
    // 돌리므로 글자는 똑바로 선다.
    const side = rot === 90 || rot === 270;
    const fw = side ? height : width, fh = side ? width : height;
    const t = fitTransform(bounds, fw, fh, 32);
    const turn = quarterTurn(rot, fw, fh);
    const toPx = (x, y) => { const p = project(t, x, y); return turn.point(p.px, p.py); };
    // D-593 pin on the site view (a motor-mode robot has no grid): canvas CSS px → map m.
    view.siteToWorld = (x, y) => { const p = turn.unpoint(x, y); return { x: (p.x - t.ox) / t.scale, y: (t.oy - p.y) / t.scale }; };
    ctx.fillStyle = css("--ground-deep");
    ctx.fillRect(0, 0, width, height);
    if (cameraOn) camera.drawTopDown(ctx, calibration, bounds, toPx, width, height, dpr, rot);
    const labelFont = font("micro");

    // 0.5 m 격자
    ctx.save();
    ctx.lineWidth = 1;
    ctx.strokeStyle = css("--line-quiet");
    ctx.globalAlpha = 0.5;
    for (const gx of layerOn("grid") ? gridLines(bounds.min_x, bounds.max_x, GRID_STEP_M) : []) {
      const a = toPx(gx, bounds.min_y);
      const b = toPx(gx, bounds.max_y);
      ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke();
    }
    for (const gy of layerOn("grid") ? gridLines(bounds.min_y, bounds.max_y, GRID_STEP_M) : []) {
      const a = toPx(bounds.min_x, gy);
      const b = toPx(bounds.max_x, gy);
      ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke();
    }
    ctx.restore();

    // 사각형 + 치수 + 출처(source_id)
    ctx.save();
    ctx.font = labelFont;
    for (const entry of layerOn("site") ? sitePolygons() : []) {
      tracePolygon(ctx, entry.polygon_m, toPx);
      ctx.globalAlpha = 0.08;
      ctx.fillStyle = css("--series-primary");
      ctx.fill();
      ctx.globalAlpha = 1;
      ctx.lineWidth = 2;
      ctx.strokeStyle = css("--series-primary");
      ctx.stroke();
    }
    ctx.restore();

    const placeLabels = [];
    const activeMap = view.activeSiteMap?.map;
    if (layerOn("cad")) {
      cadTwin.drawFloorCad(ctx, toPx, activeMap, { overlayMode: cameraOn });
    }
    drawSiteLanesAndPlaces(ctx, toPx, activeMap, placeLabels);
    drawCrosswalks(ctx, toPx, 1.5);
    if (layerOn("poses")) drawTrails(ctx, view, toPx, 1.5, call);
    traffic(ctx, toPx, t.scale);
    drawCameraTracking(ctx, toPx, Math.max(14, t.scale * 0.09), 2);
    guide(ctx, toPx);
    if (layerOn("cad")) {
      cadTwin.drawRobotCadModels(ctx, toPx, {
        guide: view.guide,
        anchors: view.anchors,
        chargeBaysPlan: view.chargeBaysPlan,
        overlayMode: cameraOn,
        focusedRobotId: view.robotSelection?.get?.() || view.focusAnchorId || null,
      });
    }
    if (layerOn("sightings")) {
      for (const s of view.sightings) drawSighting(ctx, s, toPx, Math.max(14, t.scale * 0.09), 2);
    }
    paintPlaceLabels(ctx, placeLabels);
    if (layerOn("site") && layerOn("labels")) {
      drawMapDatum(ctx, toPx, bounds, {css, insetBottom: datumBottomInset(), hoverWorld: view.hoverWorld});
    }
    flushChips(ctx);
  }

  const traffic = (ctx, toPoint, pxPerM) =>
    drawTraffic(ctx, toPoint, pxPerM, { view, el, css, colorOf, drawChip, on: layerOn("traffic") });
  // D-536: 로봇 몸체 원·방향·불확실성 고리와 안내 목표. "로봇" 층을 따른다.
  const guide = (ctx, toPoint) => {
    // Guide chips start with the robot id ("rosy_01 · ±0.05 m"): exceptions and the selected robot always show.
    const focusedRobotId = (typeof view.robotSelection?.get === "function" ? view.robotSelection.get() : null) || view.selected || null;
    const chip = (c, g, x, y, text, tone) => drawChip(c, g, x, y, text, tone,
      Boolean(focusedRobotId && String(text).includes(focusedRobotId)) || labelImportant(String(text).split(" · ")[0]));
    drawGuide(ctx, toPoint, { guide: view.guide, css, colorOf, drawChip: chip, on: layerOn("poses"), focusedRobotId, view });

    drawSignalLamps(ctx, toPoint, { view, css, on: layerOn("traffic") });  // D-525 rev 3: above the robots
  };

  function describeSightings() {
    const observed = new Set(view.sightings.filter((s) => s.state === "fresh").map((s) => s.robot_id));
    for (const row of view.cameraTracking?.robots || []) observed.add(row.robotId);
    return `카메라 관측 ${observed.size}/${Math.max(view.robots.length, observed.size)}대`;
  }

  function draw() {
    const activeMap = view.activeSiteMap?.map;
    const places = layerOn("lanes") && view.siteMap?.maps.some(row => row.map_id === activeMap?.map_id) ? activeMap.places || [] : [];
    const placeList = el("map-places");
    if (placeList) {
      const placeSig = places.map((place) => `${place.name} · ${place.x.toFixed(2)}, ${place.y.toFixed(2)} m`).join("\n");
      placeList.hidden = !places.length;
      if (placeSig !== lastPlaceListSig) {
        lastPlaceListSig = placeSig;
        placeList.replaceChildren(...places.map(place => {
          const row = document.createElement("li");
          row.textContent = `${place.name} · ${place.x.toFixed(2)}, ${place.y.toFixed(2)} m`;
          return row;
        }));
      }
    }
    const calibrationStatus = el("map-calibration-status");
    if (calibrationStatus) {
      const drift = camera.calibration() && view.trackingDrift;
      const health = !drift && view.calibrationHealth;   // D-1006: 거부된 맞춤·범위 부족도 알린다
      calibrationStatus.hidden = !drift && !health;
      calibrationStatus.textContent = health ? `카메라 교정 확인(${health.sourceId}) — ${health.text}`
        : !drift ? "" : drift.origin === "server"
        ? `카메라 교정 어긋남(자동 검사) — 승인 교정과 새 맞춤 제안이 최대 ${Math.round(drift.distanceM * 100)} cm 어긋남(${drift.sourceId}). 맵 고정을 다시 하세요(맞춤 → 추적 보정 적용).`
        : `카메라 교정 어긋남 — 정지 로봇 관측 차이 최대 ${Math.round(drift.distanceM * 100)} cm(${drift.robotId}). 맵 고정을 다시 하세요(맞춤 → 추적 보정 적용).`;
    }
    if (view.call && Date.now() >= view.call.until) view.call = null;
    const callLabel = view.call ? ` · 호출 ${view.call.robot_id}` : "";
    const staleMapLabel = view.mapStaleAt
      ? `이전 지도 유지 (${Math.max(1, Math.round((Date.now() - view.mapStaleAt) / 1000))}초 전)`
      : "";
    const holdParts = [];
    if (view.stateStale) holdParts.push("연결 지연");
    if (staleMapLabel) holdParts.push(staleMapLabel);
    else if (view.guideStale) holdParts.push("경로 안내 지연");
    const holdLabel = holdParts.length ? ` · ${holdParts.join(" · ")}` : "";
    const twinCanvas = el("map-twin-canvas");
    const twinTools = el("map-twin-tools");
    if (view.siteMap && view.twinUnavailableNotice === "사이트 지도가 없어 2D 지도로 표시합니다") {
      view.twinUnavailableNotice = "";
    }
    if (view.displayMode === "twin3d" && !view.siteMap) {
      (view.setDisplayMode || setDisplayMode)("coordinates");
    }
    const wantTwin = view.displayMode === "twin3d" && !twinFailed && Boolean(view.siteMap);
    const wasTwinHidden = Boolean(twinCanvas?.hidden);
    if (twinCanvas) twinCanvas.hidden = !wantTwin;
    if (twinTools) twinTools.hidden = !wantTwin;
    if (wantTwin && twinCanvas && view.siteMap) {
      const bounds = siteBounds(view.siteMap);
      if (bounds) {
        const enrichHoverEntity = (entity) => {
          if (!entity) return null;
          if (entity.kind === "pinky" && !entity.guideRow) {
            const guideRow = (view.guide?.robots || []).find((r) => r.robot_id === entity.id)
              || (view.robots || []).find((r) => r.robot_id === entity.id) || null;
            return { ...entity, guideRow };
          }
          if (entity.kind === "omx_ai" && !entity.anchor) {
            const anchors = Array.isArray(view.anchors) ? view.anchors : (view.guide?.anchors || []);
            const anchor = anchors.find((a) => a.target_id === entity.id) || null;
            return { ...entity, anchor };
          }
          return entity;
        };
        if (!twin3d) {
          const instance = createSiteTwin3d({
            canvas: twinCanvas,
            onSelectRobot: ({ id }) => {
              view.mapSelection = null;
              if (onSelectRobotFromMap) onSelectRobotFromMap(id);
              else { view.robotSelection?.set?.(id, { source: "map" }); onTrafficChanged(); draw(); }
            },
            onSelectPlace: (place) => {
              view.mapSelection = { kind: "place", id: String(place.id), place };
              if (onSelectPlaceFromMap) onSelectPlaceFromMap(place);
              else { onTrafficChanged(); draw(); }
            },
            onSelectPoint: (pt) => {
              if (!pt) return;
              const same = view.mapSelection?.kind === "point"
                && Math.hypot(view.mapSelection.x - pt.x, view.mapSelection.y - pt.y) < 0.08;
              view.mapSelection = same ? null : { kind: "point", x: pt.x, y: pt.y };
              if (onSelectPoint) onSelectPoint(pt);
              else { onTrafficChanged(); draw(); }
            },
            onHover: (entity, clientX, clientY) => {
              const enriched = enrichHoverEntity(entity);
              const prevKey = view.hoverEntity ? `${view.hoverEntity.kind}:${view.hoverEntity.id}` : "";
              const nextKey = enriched ? `${enriched.kind}:${enriched.id}` : "";
              view.hoverEntity = enriched;
              if (onHoverEntity) onHoverEntity(enriched, clientX, clientY);
              else if (prevKey !== nextKey) { onTrafficChanged(); draw(); }
            },
            onUnavailable: () => {
              twinFailed = true;
              view.twinFailed = true;
              view.twinUnavailableNotice = "3D 보기를 열 수 없어 CAD + 실영상으로 전환했습니다";
              const activeTwin = twin3d;
              twin3d = null;
              activeTwin?.dispose?.();
              if (twinCanvas) twinCanvas.hidden = true;
              if (twinTools) twinTools.hidden = true;
              if (view.displayMode === "twin3d") (view.setDisplayMode || setDisplayMode)("overlay");
              const status = el("map-display-status");
              if (status) status.textContent = view.twinUnavailableNotice;
              draw();
            },
          });
          if (twinFailed) instance.dispose?.();
          else twin3d = instance;
        }
        if (twin3d) {
          if (wasTwinHidden) twin3d.resize?.();
          const activeMap = view.activeSiteMap?.map || null;
          void cadTwin.ensureSiteLanes(activeMap?.map_id ?? null);
          const twinRobots = (view.robots || []).map((row) => {
            const pose = (row.pose && (!row.pose.pose_frame || row.pose.pose_frame === "map"))
              ? row.pose : robotMapPose(row);
            const stale = Boolean(row.stale || row.state?.evidence?.pose?.evidence === "delayed");
            return { ...row, pose, state: pose ? row.state : null, stale };
          });
          twin3d.render({
            bounds,
            turnDeg: view.siteViewTurn || 0,
            activeMap,
            siteLanes: cadTwin.getSiteLanes(),
            guide: view.guide,
            guideStale: Boolean(view.guideStale),
            robots: twinRobots,
            anchors: view.anchors,
            chargeBaysPlan: view.chargeBaysPlan,
            cameraCanvas: camera.renderFloorCanvas(bounds),
            focusedRobotId: view.robotSelection?.get?.() || view.focusAnchorId || null,
            selectedPlaceId: view.mapSelection?.kind === "place" ? String(view.mapSelection.id) : null,
            hoveredEntity: view.hoverEntity || null,
          });
        }
      }
    }
    const grid = view.map;
    if (!grid && !view.siteMap) drawTraffic(null, null, 0, {view: {}, el, on: true});
    resetChips();
    if (!grid) {
      if (view.siteMap) {
        drawSiteView();
        const b = siteBounds(view.siteMap, 0);
        el("map-tag").textContent =
          `사이트 ${(b.max_x - b.min_x).toFixed(1)}×${(b.max_y - b.min_y).toFixed(1)} m · ${describeSightings()}`
          + (camera.calibration()
            ? ` · ${camera.usesPlane() ? "Rosy Cam 평면 영상" : "브라우저 보정(대체)"} · ${camera.calibration().calibration_revision}`
              + (view.trackingDrift ? " · 카메라 교정 어긋남 — 맵 고정 다시 필요" : "") : "")
          + holdLabel + callLabel;
        el("map-canvas").setAttribute("aria-label",
          `천장 카메라 사이트 지도 — ${describeSightings()}${holdLabel}${callLabel}. 로봇 선택 후 지도를 클릭하여 목표를 지정하세요.`
          + (view.trackingDrift ? " 카메라 교정이 어긋난 것 같습니다. 그림은 수락된 보정 그대로이며 맵 고정을 다시 하세요." : ""));
      }
      return;
    }
    const canvas = el("map-canvas");
    const ctx = canvas.getContext("2d");
    const paintGridDatum = (hoverWorld) => drawMapDatum(ctx, (x, y) => {
      const cell = cellOf(grid, x, y);
      return {x: cell.cx, y: cell.cy};
    }, {
      min_x: grid.origin.x, min_y: grid.origin.y,
      max_x: grid.origin.x + grid.width * grid.resolution,
      max_y: grid.origin.y + grid.height * grid.resolution,
    }, {
      css,
      insetBottom: datumBottomInset(),
      hoverWorld,
    });
    paintGrid(grid);
    if (view.stateUnavailable) {
      drawSiteOverlay(ctx, grid);
      paintGridDatum(view.hoverWorld);
      flushChips(ctx);
      const staleNote = staleMapLabel ? ` · ${staleMapLabel}` : "";
      el("map-tag").textContent = `로봇 위치 확인 불가${staleNote}${callLabel}`;
      canvas.setAttribute("aria-label", `로봇 위치 확인 불가${staleNote}${callLabel} — Fleet 상태 연결을 확인하세요`);
      return;
    }
    el("map-tag").textContent = `${grid.width}×${grid.height} · ${grid.map_id || "map"}${holdLabel}${callLabel}`;
    canvas.setAttribute("aria-label", view.call
      ? `지도에서 로봇 목표 위치 선택. 호출 ${view.call.robot_id}`
      : "지도에서 로봇 목표 위치 선택");
    // 격자 픽셀 위에 그리므로 선 굵기도 격자 칸 단위다. 0.6칸이면 3 cm 남짓이다.
    drawTrails(ctx, view, (x, y) => { const c = cellOf(grid, x, y); return { x: c.cx, y: c.cy }; }, 0.4, call);
    ctx.lineWidth = 0.6;
    const labels = [];  // id labels go after every marker box exists, so a label never covers a marker
    view.robots.forEach((robot, index) => {
      // Only the robot's LOCALIZED map pose draws the triangle; otherwise Fleet's map pose (guide circle)
      // and Rosy Cam tracking (ring) show where it is, each in its own layer.
      const pose = robotMapPose(robot);
      if (!pose || !layerOn("poses")) return;
      const color = view.colors[index % view.colors.length];
      const cell = worldToCell(grid, pose.x, pose.y);
      const cx = cell.col;
      const cy = grid.height - cell.row;
      const pxPerCell = Math.max(canvas.clientWidth / grid.width, canvas.clientHeight / grid.height) || 1;
      const size = Math.min(3, 18 / pxPerCell);
      // Chips use screen-sized type; keep their half-height clear of the marker at every grid scale.
      const labelOffset = Math.max(size * 2.2, size + (chipFontSize(ctx) * 0.9 + CHIP_GAP) / ctx.getTransform().d);
      ctx.save();
      ctx.translate(cx, cy);
      ctx.rotate(-pose.yaw); // 캔버스 y 가 아래로 자라므로 회전도 뒤집는다
      ctx.beginPath();
      ctx.moveTo(size, 0);
      ctx.lineTo(-size * 0.6, size * 0.62);
      ctx.lineTo(-size * 0.6, -size * 0.62);
      ctx.closePath();
      ctx.fillStyle = color;
      ctx.globalAlpha = robot.online ? 1 : 0.35;
      ctx.fill();
      if (activeCall(robot.robot_id)) {
        ctx.globalAlpha = 1;
        ctx.beginPath();
        ctx.arc(0, 0, size * 1.7, 0, Math.PI * 2);
        ctx.lineWidth = 0.35;
        ctx.strokeStyle = css("--status-warn");
        ctx.stroke();
      }
      if (view.robotSelection?.get?.() === robot.robot_id) {
        ctx.globalAlpha = 1;
        ctx.beginPath();
        ctx.arc(0, 0, size * 1.55, 0, Math.PI * 2);
        ctx.lineWidth = 0.45;
        ctx.strokeStyle = css("--selection") || css("--series-primary");
        ctx.stroke();
      }
      ctx.restore();
      if (activeCall(robot.robot_id)) {
        drawChip(ctx, grid, cx, cy - labelOffset, `호출 ${robot.robot_id}`, "warn");
      }
      const [a, b] = [-size, size].map((d) => ctx.getTransform().transformPoint({ x: cx + d, y: cy + d }));
      addMarker({ x: a.x, y: a.y, w: b.x - a.x, h: b.y - a.y, robot: robot.robot_id });
      labels.push([cx, cy + labelOffset, robot.robot_id]);

      // 목표는 Fleet 이 기억하는 값이다(로봇 상태에는 없다) — "내가 무엇을 시켰는가".
      // 대기 중인 미션도 그린다 — 어디로 갈 예정인지가 보여야 순서를 판단한다.
      const goal = robot.goal || robot.queued;
      if (goal && typeof goal.x === "number") {
        const gcell = worldToCell(grid, goal.x, goal.y);
        ctx.beginPath();
        ctx.arc(gcell.col, grid.height - gcell.row, size * 0.5, 0, Math.PI * 2);
        ctx.strokeStyle = css("--series-goal");
        ctx.globalAlpha = 1;
        ctx.stroke();
      }
    });
    for (const [x, y, robotId] of labels) drawChip(ctx, grid, x, y, shortId(robotId), undefined, labelImportant(robotId));
    traffic(ctx, (x, y) => { const c = cellOf(grid, x, y); return { x: c.cx, y: c.cy }; }, 1 / grid.resolution);
    guide(ctx, (x, y) => { const c = cellOf(grid, x, y); return { x: c.cx, y: c.cy }; });
    drawLocalizationCandidates({ ctx, view, toPoint: (x, y) => { const c = cellOf(grid, x, y); return { x: c.cx, y: c.cy }; }, css });
    drawFormationOverlay(ctx, grid);
    drawMediation(ctx, grid);
    drawSiteOverlay(ctx, grid);
    // US-009 — 원점 글자(x·y·0,0)도 글자다. 선을 다 그린 뒤, 칩 바로 앞에 칠해 선이 글자를 지나지 않는다.
    paintGridDatum(view.selected && view.cursor ? toWorld(grid, view.cursor.col, view.cursor.row) : view.hoverWorld);
    flushChips(ctx);
    if (view.selected && view.cursor) {
      const { col, row } = view.cursor;
      const cx = col + 0.5;
      const cy = grid.height - row - 0.5;
      ctx.save();
      ctx.beginPath();
      ctx.arc(cx, cy, 1.8, 0, Math.PI * 2);
      ctx.lineWidth = 0.5;
      ctx.strokeStyle = css("--series-goal");
      ctx.stroke();
      ctx.restore();
      const world = toWorld(grid, col, row);
      const metres = `${world.x.toFixed(2)}, ${world.y.toFixed(2)} m`;
      drawChip(ctx, null, cx + 2, cy, metres);
      canvas.setAttribute("aria-label", `${canvas.getAttribute("aria-label")}. ${metres}`);
      flushChips(ctx);
    }
  }

  const presetIso = el("twin-preset-iso");
  const presetTop = el("twin-preset-top");
  const presetReset = el("twin-preset-reset");
  if (presetIso) scope.listen(presetIso, "click", () => twin3d?.setPreset?.("iso"));
  if (presetTop) scope.listen(presetTop, "click", () => twin3d?.setPreset?.("top"));
  if (presetReset) scope.listen(presetReset, "click", () => twin3d?.setPreset?.("reset"));

  // 사이트 사각형·격자·교통·상황·관측 폴링은 map-polling.js가 가진다. 이 뷰를 다시 그리게 draw를 건넨다.
  const { refresh, refreshSightings, refreshTraffic, refreshGuide, resetPolling } = createMapPolling({ scope, el, view,
    auth, call, camera, draw, layerOn, onMapChanged, onMapUnavailable, onTrafficChanged,
    onSiteMapLoaded: (siteMap) => {
      const mapId = view.activeSiteMap?.map?.map_id ?? siteMap?.maps?.[0]?.map_id ?? null;
      void cadTwin.preload(mapId);
    } });

  return { draw, refresh, refreshSightings, refreshTraffic, refreshGuide, resetPolling, toWorld, streamEvidence,
    setCameraFrame: camera.setCameraFrame, bindCamera: camera.bindCamera, setDisplayMode,
    twinPreset: (name) => twin3d?.setPreset?.(name) };
}
