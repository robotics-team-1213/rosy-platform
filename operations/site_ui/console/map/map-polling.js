// 현장 지도 폴링(D-798 3.2, map-view.js에서 나눔): 사이트 사각형·활성 지도·교정, 점유 격자, 교통 표,
// 로봇 상황(guide), 카메라 관측. 주기는 셸(console.js)이 쥐고, 그리기는 map-view.js의 draw가 한다.
import { classifySightings, siteViewTurn } from "./site-layer.js";
import { NO_MAP_RETRY_MS, createPollGate } from "/console/assets/poll-gate.js";
import { noRobotServesGrid } from "./motion-readiness.js";
import { trafficClock } from "/console/assets/site-map-model.js";

export function createMapPolling({ scope, el, view, auth, call, camera, draw, layerOn, onMapChanged, onMapUnavailable,
  onTrafficChanged }) {
  let calibrationsAt = 0;

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

  async function refreshSiteMap() {
    const life = scope.capture();
    life.check();
    try {
      const siteMap = await call("/api/fleet/site-map");
      life.check();
      view.siteMap = siteMap;
      el("map-stage").dataset.siteMap = "configured";
      if (Date.now() - calibrationsAt > 30000) {
        // D-513 7: 활성 현장 지도의 화면 방향. 지도가 없거나(404/409) 읽지 못하면 기본 방향.
        try {
          view.activeSiteMap = await call("/api/fleet/site-map/active", { signals: [life.signal] });
          view.siteViewTurn = siteViewTurn(view.activeSiteMap);
          life.check();
        } catch (error) {
          if (error.name === "AbortError") return;
          if (error.status === 404 || error.status === 409) { view.siteViewTurn = 0; view.activeSiteMap = null; } // no active map; else keep the last turn
        }
        // The first site draw must use the active map turn; drawing at 0° then turning to 90°
        // makes the whole map jump while the camera and robot map requests are still pending.
        if (!view.map && !auth.locked) showSiteMap();
        try {
          const result = await call("/api/fleet/calibrations", { signals: [life.signal] });
          life.check();
          camera.setCalibrations(result.calibrations || []);
          calibrationsAt = Date.now();
        } catch (error) { if (error.name === "AbortError") return; camera.setCalibrations([]); }
      } else if (!view.map && !auth.locked) {
        showSiteMap();
      }
    } catch (err) {
      if (err.name === "AbortError") return;
      // NO_SITE_MAP — 카메라 사각형이 설정되지 않은 현장이다. 일시 실패면 직전 사각형을 둔다.
      if (err.status === 404 && err.code === "NO_SITE_MAP") {
        view.siteMap = null;
        el("map-stage").dataset.siteMap = "none";
      }
    }
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
  scope.onDispose(() => { guideInFlight = false; });
  async function refreshGuide() {
    const life = scope.capture();
    life.check();
    if (auth.locked || guideInFlight || !guideGate.due()) return;
    guideInFlight = true;
    try {
      view.guide = await call("/api/fleet/guide", { signals: [life.signal] });
      life.check();
      view.guideUnavailable = false;
      guideGate.ok();
    } catch (err) {
      if (err.name === "AbortError") return;
      view.guide = null;
      view.guideUnavailable = guideGate.fail(err.status, err.code) !== "absent";
    } finally {
      if (life.current()) guideInFlight = false;
    }
    onTrafficChanged();  // the roster's exception queue reads view.guide too
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
      const trips = traffic.robots.length || view.trafficTrips?.length
        ? await call("/api/fleet/trips", { signals: [life.signal] }) : { open: [], trips: view.endedTrips };
      view.trafficTrips = trips.open || [];
      view.endedTrips = trips.trips || [];
      life.check();
      if (traffic.map_version !== null && traffic.map_version !== view.activeSiteMap?.version) {
        view.activeSiteMap = await call("/api/fleet/site-map/active", { signals: [life.signal] });
        life.check();
      }
      view.traffic = traffic;
      // D-613: route observations also reach the queue while a trip runs without a wait cycle.
      const ai = traffic.wait_cycle?.length || view.trafficTrips.length
        ? await call("/api/fleet/ai", { signals: [life.signal] }).catch(() => null) : null;
      life.check();
      view.trafficAi = ai?.facts || [];
    } catch (err) {
      if (err.name === "AbortError") return;
      if (trafficGate.fail(err.status, err.code) === "absent") view.traffic = null;
    } finally {
      if (life.current()) trafficInFlight = false;
    }
    view.trafficClock = trafficClock(view.trafficClock, view.traffic, Date.now());
    el("traffic-toggle").hidden = !view.traffic?.units?.length;
    onTrafficChanged();
  }
  scope.listen(el("traffic-toggle"), "click", () => {
    const on = !layerOn("traffic");
    view.layers = { ...view.layers, traffic: on };
    el("traffic-toggle").setAttribute("aria-pressed", String(on));
    el("traffic-toggle").textContent = on ? "교통 켬" : "교통 끔";  // the quiet button has no pressed look
    draw();
  });

  function resetPolling() {
    trafficGate.reset();
    mapGate.reset();
    sightingsUnavailable = false;
  }

  async function refresh() {
    const life = scope.capture();
    life.check();
    if (auth.locked) return;
    sightingsUnavailable = false;
    await refreshSiteMap();
    life.check();
    // The activated site frame stays the coordinate basis when robots start or stop serving SLAM grids.
    if (!auth.locked && view.siteMap?.maps?.some(map => map.map_id === view.activeSiteMap?.map?.map_id)) {
      view.map = null;
      showSiteMap();
      return;
    }
    if (auth.locked || !mapGate.due()) return;
    let mapFailure = "retry";
    try {
      // The same answer as Fleet's NO_MAP, without a request that can only 404.
      if (noRobotServesGrid(view.robots)) throw Object.assign(new Error("NO_MAP"), { status: 404, code: "NO_MAP" });
      const grid = await call("/api/fleet/map");
      life.check();
      mapGate.ok();
      view.map = grid;
      el("map-stage").dataset.mapState = "ready";
      el("map-empty").hidden = true;
      el("map-canvas").removeAttribute("aria-hidden");
      el("map-canvas").setAttribute("role", "button");
      syncLegend("grid");
      draw();
      onMapChanged();
    } catch (err) {
      if (err.name === "AbortError") return;
      view.map = null;
      if (auth.locked) return;
      if (!auth.locked) mapFailure = mapGate.fail(err.status, err.code);
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
      } else {
        el("map-empty-title").textContent = "지도를 확인할 수 없습니다";
        el("map-empty-detail").textContent = "Fleet 지도 연결과 등록 로봇 상태를 확인하세요.";
      }
      el("map-empty").hidden = false;
      syncLegend("none");
      el("map-tag").textContent = "맵 없음";
      onMapUnavailable();
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
    try {
      next = classifySightings(await call("/api/fleet/sightings"));
      life.check();
    } catch (err) {
      if (err.name === "AbortError") return;
      // 일시 실패도 옛 관측을 남기지 않는다.
      if (err.status === 404) sightingsUnavailable = true;
    } finally {
      if (life.current()) sightingsInFlight = false;
    }
    const unchanged = JSON.stringify(next) === JSON.stringify(view.sightings);
    view.sightings = next;
    if (unchanged && !next.length) return; // 빈 채로 그대로면 격자를 다시 칠하지 않는다
    el("legend-sighting").hidden = !view.siteMap && !view.sightings.length;
    draw();
  }

  return { refresh, refreshSightings, refreshTraffic, refreshGuide, resetPolling };
}
