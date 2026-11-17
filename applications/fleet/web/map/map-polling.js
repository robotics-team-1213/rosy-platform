// 현장 지도 폴링(D-798 3.2, map-view.js에서 나눔): 사이트 사각형·활성 지도·교정, 점유 격자, 교통 표,
// 로봇 상황(guide), 카메라 관측. 주기는 셸(console.js)이 쥐고, 그리기는 map-view.js의 draw가 한다.
import { classifySightings, siteViewTurn } from "./site-layer.js";
import { NO_MAP_RETRY_MS, createPollGate } from "/console/assets/poll-gate.js";
import { noRobotServesGrid } from "./motion-readiness.js";
import { trafficClock } from "/console/assets/site-map-model.js";

export function createMapPolling({ scope, el, view, auth, call, camera, draw, layerOn, onMapChanged, onMapUnavailable,
  onTrafficChanged, onSiteMapLoaded = null }) {
  const MAP_HOLDOVER_MS = 15000;
  const GUIDE_HOLDOVER_MS = 5000;
  const SIGHTINGS_HOLDOVER_MS = 3500;
  let calibrationsAt = 0;
  let mapLostAt = 0;
  let guideLostAt = 0;
  let sightingsLostAt = 0;
  let siteMapInFlight = false;
  let siteMapGen = 0;
  let siteMapAbort = null;
  let mapInFlight = false;
  scope.onDispose(() => {
    siteMapInFlight = false;
    siteMapGen += 1;
    siteMapAbort?.abort();
    siteMapAbort = null;
    mapInFlight = false;
  });
  let prevGuideSig = null;
  let prevTrafficSig = null;

  function clearMapHold() {
    mapLostAt = 0;
    view.mapStaleAt = 0;
    delete el("map-stage").dataset.mapStale;
  }

  function syncLegend(mode) {
    el("map-legend").hidden = mode === "none";
    for (const item of el("map-legend").querySelectorAll("[data-legend=grid]")) {
      item.hidden = mode !== "grid";
    }
    el("legend-sighting").hidden = !view.siteMap && !view.sightings.length;
  }

  function showSiteMap() {
    const canvas = el("map-canvas");
    canvas.removeAttribute("aria-hidden");
    canvas.setAttribute("role", "img");
    canvas.tabIndex = -1;
    canvas.classList.add("idle");
    el("map-stage").dataset.mapState = "site";
    el("map-empty").hidden = true;
    syncLegend("site");
    draw();
    onMapUnavailable();
  }

  function notifySiteMapLoaded(life) {
    if (typeof onSiteMapLoaded !== "function") return;
    Promise.resolve().then(() => {
      if (life.current()) return onSiteMapLoaded(view.siteMap, view.activeSiteMap);
    }).catch(() => {});
  }

  async function refreshCalibrations(life) {
    try {
      const result = await call("/api/fleet/calibrations", { signals: [life.signal] });
      life.check();
      camera.setCalibrations(result.calibrations || []);
      calibrationsAt = Date.now();
    } catch (error) { if (error.name === "AbortError") throw error; camera.setCalibrations([]); }
  }

  async function refreshSiteMap() {
    if (siteMapInFlight) return false;
    const life = scope.capture();
    if (!life.current()) return false;
    const gen = siteMapGen;
    siteMapAbort?.abort();
    siteMapAbort = typeof AbortController === "function" ? new AbortController() : null;
    const signals = [life.signal, siteMapAbort?.signal].filter(Boolean);
    siteMapInFlight = true;
    let showedSite = false;
    try {
      const needCalib = Date.now() - calibrationsAt > 30000;
      const [siteMapRes, activeRes, calibRes] = await Promise.allSettled([
        call("/api/fleet/site-map", { signals }),
        ...(needCalib ? [
          call("/api/fleet/site-map/active", { signals }),
          call("/api/fleet/calibrations", { signals }),
        ] : []),
      ]);
      if (gen !== siteMapGen) return showedSite;
      life.check();
      if (siteMapRes.status === "rejected") throw siteMapRes.reason;
      view.siteMap = siteMapRes.value;
      el("map-stage").dataset.siteMap = "configured";
      if (needCalib) {
        // D-513 7: 활성 현장 지도의 화면 방향. 지도가 없거나(404/409) 읽지 못하면 기본 방향.
        if (activeRes.status === "fulfilled") {
          view.activeSiteMap = activeRes.value;
          view.siteViewTurn = siteViewTurn(view.activeSiteMap);
        } else {
          const error = activeRes.reason;
          if (error?.name === "AbortError" || gen !== siteMapGen) return showedSite;
          if (error?.status === 404 || error?.status === 409) { view.siteViewTurn = 0; view.activeSiteMap = null; } // no active map; else keep the last turn
        }
        if (calibRes.status === "fulfilled") {
          camera.setCalibrations(calibRes.value.calibrations || []);
          calibrationsAt = Date.now();
        } else {
          const error = calibRes.reason;
          if (error?.name === "AbortError" || gen !== siteMapGen) return showedSite;
          if (!calibrationsAt || error?.status === 404 || error?.status === 401 || error?.status === 403) {
            camera.setCalibrations([]);
          }
        }
      }
      notifySiteMapLoaded(life);
      // The first site draw must use the active map turn; drawing at 0° then turning to 90°
      // makes the whole map jump while the camera and robot map requests are still pending.
      if (!view.map && !auth.locked) { showSiteMap(); showedSite = true; }
    } catch (err) {
      if (err.name === "AbortError" || gen !== siteMapGen) return showedSite;
      // NO_SITE_MAP — 카메라 사각형이 설정되지 않은 현장이다. 일시 실패면 직전 사각형을 둔다.
      if (err.status === 404 && err.code === "NO_SITE_MAP") {
        view.siteMap = null;
        el("map-stage").dataset.siteMap = "none";
      }
    } finally {
      if (life.current() && gen === siteMapGen) siteMapInFlight = false;
    }
    return showedSite;
  }

  // NO_MAP(지도를 내는 로봇 없음)은 기능 미설정이 아니라 "아직 없음"이다. 로봇이 나중에
  // 지도를 낼 수 있으니 멈추지 않고 30 s 간격으로만 다시 묻는다. 라우트 없음 404 는
  // resetPolling()(로그인) 전까지 멈춘다. 일시 실패는 다음 5 s 주기에 다시 묻는다.
  const mapGate = createPollGate({ slowCodes: { NO_MAP: NO_MAP_RETRY_MS } });

  // D-517 10: 교통 표(1 s). Fleet 이 그 라우트를 모르면(404) 다음 로그인까지 묻지 않는다.
  // 진행 중 trip 이 있을 때만 /trips 로 계획을 읽는다 — 통행권 끝을 계획 위에 놓는다.
  const trafficGate = createPollGate();
  let trafficInFlight = false;
  scope.onDispose(() => { trafficInFlight = false; });
  // D-536: 로봇 상황(1 s, 교통 표와 같은 주기). 모르는 라우트(404)면 다음 로그인까지 묻지 않는다.
  const guideGate = createPollGate();
  let guideInFlight = false;
  scope.onDispose(() => {
    siteMapInFlight = false;
    mapInFlight = false;
    guideInFlight = false;
    prevGuideSig = null;
    prevTrafficSig = null;
    guideLostAt = 0;
    sightingsLostAt = 0;
    view.guideStale = false;
    clearMapHold();
  });
  async function refreshGuide() {
    const life = scope.capture();
    life.check();
    if (auth.locked || guideInFlight || !guideGate.due()) return;
    guideInFlight = true;
    try {
      view.guide = await call("/api/fleet/guide", { signals: [life.signal] });
      if (Array.isArray(view.guide?.anchors)) view.anchors = view.guide.anchors;
      life.check();
      guideLostAt = 0;
      view.guideStale = false;
      view.guideUnavailable = false;
      guideGate.ok();
    } catch (err) {
      if (err.name === "AbortError") return;
      const failure = guideGate.fail(err.status, err.code);
      if (view.guide && failure === "retry") {
        guideLostAt ||= Date.now();
        if (Date.now() - guideLostAt < GUIDE_HOLDOVER_MS) {
          view.guideStale = true;
          view.guideUnavailable = false;
        } else {
          guideLostAt = 0;
          view.guide = null;
          view.guideStale = false;
          view.guideUnavailable = true;
        }
      } else {
        guideLostAt = 0;
        view.guide = null;
        view.guideStale = false;
        view.guideUnavailable = failure !== "absent";
      }
    } finally {
      if (life.current()) guideInFlight = false;
    }
    const nextSig = JSON.stringify([
      Boolean(view.guideStale),
      Boolean(view.guideUnavailable),
      view.guide ?? null,
    ]);
    if (nextSig !== prevGuideSig) {
      prevGuideSig = nextSig;
      onTrafficChanged();  // the roster's exception queue reads view.guide too
    }
  }
  async function refreshTraffic() {
    const life = scope.capture();
    life.check();
    if (auth.locked || trafficInFlight || !trafficGate.due()) return;
    trafficInFlight = true;
    try {
      const traffic = await call("/api/fleet/traffic", { signals: [life.signal] });
      life.check();
      trafficGate.ok();
      // D-540 (d): one more read after the last trip closes keeps why it ended (view.endedTrips, newest first).
      const fetchedTrips = Boolean(traffic.robots.length || view.trafficTrips?.length);
      const needActiveMap = traffic.map_version !== null && traffic.map_version !== view.activeSiteMap?.version;
      const needAiNow = Boolean(traffic.wait_cycle?.length);
      const [tripsRes, activeRes, aiRes] = await Promise.allSettled([
        fetchedTrips ? call("/api/fleet/trips", { signals: [life.signal] }) : { open: [], trips: view.endedTrips },
        needActiveMap ? call("/api/fleet/site-map/active", { signals: [life.signal] }) : null,
        // D-613: route observations also reach the queue while a trip runs without a wait cycle.
        needAiNow ? call("/api/fleet/ai", { signals: [life.signal] }).catch(() => null) : null,
      ]);
      life.check();
      if (tripsRes.status === "rejected") throw tripsRes.reason;
      if (needActiveMap && activeRes.status === "rejected") throw activeRes.reason;
      const trips = tripsRes.value;
      const tripIdKey = (row) => `${(row?.open || []).map((t) => t.trip_id).join(",")}|${(row?.trips || []).map((t) => t.trip_id).join(",")}`;
      const prevTripKey = tripIdKey(view.trailTrips || { open: view.trafficTrips, trips: view.endedTrips });
      view.trafficTrips = trips.open || [];
      view.endedTrips = trips.trips || [];
      if (fetchedTrips) {
        view.trailTrips = { open: view.trafficTrips, trips: view.endedTrips };
        view.tripsAt = Date.now();
      }
      if (tripIdKey(view.trailTrips || { open: view.trafficTrips, trips: view.endedTrips }) !== prevTripKey) view.pathAt = 0;
      if (needActiveMap) {
        view.activeSiteMap = activeRes.value;
        view.siteViewTurn = siteViewTurn(view.activeSiteMap);
        notifySiteMapLoaded(life);
        await refreshCalibrations(life);
      }
      view.traffic = traffic;
      const ai = needAiNow
        ? (aiRes.status === "fulfilled" ? aiRes.value : null)
        : (view.trafficTrips.length ? await call("/api/fleet/ai", { signals: [life.signal] }).catch(() => null) : null);
      life.check();
      view.trafficAi = ai?.facts || [];
    } catch (err) {
      if (err.name === "AbortError") return;
      if (trafficGate.fail(err.status, err.code) === "absent") view.traffic = null;
    } finally {
      if (life.current()) trafficInFlight = false;
    }
    view.trafficClock = trafficClock(view.trafficClock, view.traffic, Date.now());
    view.trafficLoaded = true;
    const nextSig = JSON.stringify([
      view.traffic ?? null,
      view.trafficTrips ?? null,
      view.endedTrips ?? null,
      view.trafficAi ?? null,
      view.activeSiteMap?.version ?? null,
    ]);
    if (nextSig !== prevTrafficSig) {
      prevTrafficSig = nextSig;
      onTrafficChanged();
    }
  }

  function resetPolling() {
    trafficGate.reset();
    mapGate.reset();
    sightingsUnavailable = false;
    siteMapInFlight = false;
    siteMapGen += 1;
    siteMapAbort?.abort();
    siteMapAbort = null;
    mapInFlight = false;
    prevGuideSig = null;
    prevTrafficSig = null;
    guideLostAt = 0;
    sightingsLostAt = 0;
    view.guideStale = false;
    clearMapHold();
  }

  async function refresh() {
    const life = scope.capture();
    if (!life.current()) return;
    if (auth.locked || siteMapInFlight) return;
    sightingsUnavailable = false;
    const showedSite = await refreshSiteMap();
    if (!life.current()) return;
    // The activated site frame stays the coordinate basis when robots start or stop serving SLAM grids.
    if (!auth.locked && view.siteMap?.maps?.some(map => map.map_id === view.activeSiteMap?.map?.map_id)) {
      clearMapHold();
      view.map = null;
      if (!showedSite) showSiteMap();
      return;
    }
    // Fleet unreachable: say so now, not after a slow NO_MAP retry.
    if (view.stateUnavailable) mapGate.reset();
    if (auth.locked || !mapGate.due()) return;
    if (mapInFlight) return;
    mapInFlight = true;
    let mapFailure = "retry";
    try {
      // The same answer as Fleet's NO_MAP, without a request that can only 404.
      // Fleet itself unreachable: say so (the stale robot list must not blame the robots) instead of asking.
      if (view.stateUnavailable) throw new Error("FLEET_UNREACHABLE");
      if (noRobotServesGrid(view.robots)) throw Object.assign(new Error("NO_MAP"), { status: 404, code: "NO_MAP" });
      const grid = await call("/api/fleet/map", { signals: [life.signal] });
      life.check();
      mapGate.ok();
      clearMapHold();
      view.map = grid;
      el("map-stage").dataset.mapState = "ready";
      el("map-empty").hidden = true;
      el("map-canvas").removeAttribute("aria-hidden");
      syncLegend("grid");
      draw();
      onMapChanged();
    } catch (err) {
      if (err.name === "AbortError") return;
      if (auth.locked) {
        clearMapHold();
        view.map = null;
        return;
      }
      mapFailure = mapGate.fail(err.status, err.code);
      if (view.map && mapFailure === "retry") {
        // 일시 연결 끊김에서는 이전 지도를 일정 시간 유지해 화면이 갑자기 비지 않게 한다.
        mapLostAt ||= Date.now();
        if (Date.now() - mapLostAt < MAP_HOLDOVER_MS) {
          view.mapStaleAt = mapLostAt;
          el("map-stage").dataset.mapStale = "true";
          el("map-stage").dataset.mapState = "ready";
          el("map-empty").hidden = true;
          el("map-canvas").removeAttribute("aria-hidden");
          syncLegend("grid");
          draw();
          return;
        }
      }
      clearMapHold();
      view.map = null;
      if (view.siteMap && !auth.locked) {
        // 점유 격자 없이 카메라 사각형만 있다 — 관측 전용 뷰. 목표 지정은 계속 막힌다.
        showSiteMap();
        return;
      }
      const canvas = el("map-canvas");
      canvas.getContext("2d").clearRect(0, 0, canvas.width, canvas.height);
      canvas.setAttribute("aria-hidden", "true");
      canvas.tabIndex = -1;
      canvas.classList.add("idle");
      el("map-stage").dataset.mapState = "unavailable";
      if (mapFailure === "slow") {
        el("map-empty-title").textContent = "지도를 보내는 로봇이 없습니다";
        el("map-empty-detail").textContent = "로봇이 지도를 내면 30초 안에 표시합니다.";
      } else if (mapFailure === "absent") {
        el("map-empty-title").textContent = "지도 미설정";
        el("map-empty-detail").textContent = "이 Fleet에는 현장 지도 기능이 없습니다.";
      } else if (view.stateUnavailable || err.status === undefined) {
        el("map-empty-title").textContent = "Fleet에 연결할 수 없습니다";
        el("map-empty-detail").textContent = "연결이 돌아오면 지도를 자동으로 다시 표시합니다. 계속되면 관제 PC의 Fleet 서비스를 확인하세요.";
      } else {
        el("map-empty-title").textContent = "지도를 확인할 수 없습니다";
        el("map-empty-detail").textContent = "Fleet이 지도를 주지 못했습니다. 잠시 뒤 다시 표시하며, 계속되면 등록 로봇 상태를 확인하세요.";
      }
      el("map-empty").hidden = false;
      syncLegend("none");
      el("map-tag").textContent = "맵 없음";
      onMapUnavailable();
    } finally {
      if (life.current()) mapInFlight = false;
    }
  }

  // 카메라 관측 폴링(≈1 s). 관측은 표시 전용이다 — 목표·판단 입력으로 넘기지 않는다.
  // 사이트 사각형이 있을 때만 두드린다. 관측 설정이 없으면 라우트가 없어 404 이므로,
  // 404 를 받으면 다음 refresh() 까지 멈춘다.
  let sightingsInFlight = false;
  let sightingsUnavailable = false;
  scope.onDispose(() => { sightingsInFlight = false; });
  async function refreshSightings() {
    const life = scope.capture();
    life.check();
    if (auth.locked || sightingsInFlight || sightingsUnavailable || !view.siteMap) return;
    sightingsInFlight = true;
    let next = [];
    let failed = false;
    try {
      next = classifySightings(await call("/api/fleet/sightings", { signals: [life.signal] }));
      life.check();
      sightingsLostAt = 0;
    } catch (err) {
      if (err.name === "AbortError") return;
      if (err.status === 404) sightingsUnavailable = true;
      failed = true;
    } finally {
      if (life.current()) sightingsInFlight = false;
    }
    if (failed && !sightingsUnavailable && view.sightings?.length) {
      sightingsLostAt ||= Date.now();
      if (Date.now() - sightingsLostAt < SIGHTINGS_HOLDOVER_MS) {
        next = view.sightings;
      }
    }
    if (!next.length && failed) sightingsLostAt = 0;
    const unchanged = JSON.stringify(next) === JSON.stringify(view.sightings);
    view.sightings = next;
    if (unchanged && !next.length) return; // 빈 채로 그대로면 격자를 다시 칠하지 않는다
    el("legend-sighting").hidden = !view.siteMap && !view.sightings.length;
    draw();
  }

  return { refresh, refreshSightings, refreshTraffic, refreshGuide, resetPolling };
}
