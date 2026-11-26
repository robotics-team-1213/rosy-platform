import { mapEvidence, placeText, stamp } from "./common/map-rules.js";

export function activeSiteMap({ canvas, placeSelect, showMap, mapData, onUpdate }) {
  let entries;
  let evidence;
  let draw;
  let sha;
  let timer;
  let expiryTimer;
  let watching = false;
  let request;
  let state = "pending";
  let places = new Map();
  let showPositions;
  const mapLabel = canvas.getAttribute("aria-label");

  function markSelectedPlace() {
    const place = places.get(placeSelect.value);
    showPositions?.(place ? [{ x_m: place.x, y_m: place.y }] : []);
    canvas.setAttribute("aria-label", place ? `Fleet 활성 지도 · ${placeText(place)}` : mapLabel);
  }

  function updatePlaces(locations) {
    const previous = placeSelect.value;
    places = new Map(locations.filter(({ id }) => typeof id === "string" && id).map((place) => [place.id, place]));
    placeSelect.replaceChildren(new Option("전체 위치", ""),
      ...Array.from(places.values(), (place) => new Option(placeText(place), place.id)));
    placeSelect.value = places.has(previous) ? previous : "";
    markSelectedPlace();
  }

  placeSelect.addEventListener("change", markSelectedPlace);
  // Keyboard path on the map itself (#856): arrows step through places, Home/Escape shows all.
  canvas.addEventListener("keydown", (event) => {
    const count = placeSelect.options.length;
    const step = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[event.key];
    if (count < 2 || (!step && !["Home", "Escape"].includes(event.key))) return;
    event.preventDefault();
    placeSelect.selectedIndex = step ? (placeSelect.selectedIndex + step + count) % count : 0;
    markSelectedPlace();
  });

  function unavailable() {
    clearTimeout(expiryTimer);
    entries = undefined;
    state = "unavailable";
    onUpdate();
  }

  async function refresh() {
    if (request) return;
    const controller = new AbortController();
    request = controller;
    const sentAt = performance.now();
    try {
      const signal = AbortSignal.any([controller.signal, AbortSignal.timeout(4000)]);
      const response = await fetch("./api/worlds/real-site/site-map", { signal });
      if (!response.ok) throw new Error("Active map unavailable");
      const { site_map: envelope, fresh_for_ms: freshForMs } = await response.json();
      const map = mapData(envelope);
      if (!Number.isSafeInteger(map.version) || map.version < 1 || !/^[a-f0-9]{64}$/.test(envelope.sha256)
          || !Number.isSafeInteger(envelope.observed_at_ms) || envelope.observed_at_ms <= 0
          || !Number.isSafeInteger(freshForMs) || freshForMs <= 0) {
        throw new Error("Invalid active map revision");
      }
      if (!draw) {
        sha = envelope.sha256;
        draw = showMap(canvas, map, () => {
          draw = undefined;
          showPositions = undefined;
          unavailable();
        }).catch((error) => {
          draw = undefined;
          throw error;
        });
      }
      const renderer = await draw;
      if (request !== controller) return;
      // Charge the entire request to the server's remaining freshness budget.
      const deadline = sentAt + freshForMs;
      if (deadline <= performance.now()) throw new Error("Active map expired in transit");
      const geometryChanged = envelope.sha256 !== sha;
      if (geometryChanged) renderer.setMap(map);
      if (renderer !== showPositions || geometryChanged) {
        showPositions = renderer;
        updatePlaces(map.places);
      }
      sha = envelope.sha256;
      clearTimeout(expiryTimer);
      const remaining = deadline - performance.now();
      if (remaining <= 0) throw new Error("Active map expired while rendering");
      expiryTimer = setTimeout(unavailable, remaining);
      state = "ready";
      entries = [
        ["지도 ID", map.id],
        ["위치", map.places.length],
        ["차로", map.edges.length],
      ];
      evidence = mapEvidence({
        version: map.version, timeLabel: "수신", time: envelope.observed_at_ms / 1000, source: "Fleet 활성 지도",
      });
      const activated = stamp(envelope.activated_at).title;
      if (activated) evidence.title += ` · 활성 ${activated}`;
      onUpdate();
    } catch {
      if (request === controller) unavailable();
    } finally {
      if (request === controller) request = undefined;
    }
  }

  return {
    get entries() { return entries; },
    get evidence() { return evidence; },
    get hasPlaces() { return places.size > 0; },
    get state() { return state; },
    watch(viewing) {
      if (viewing === watching) return;
      watching = viewing;
      clearInterval(timer);
      if (viewing) {
        void refresh();
        timer = setInterval(refresh, 10_000);
      } else {
        clearTimeout(expiryTimer);
        request?.abort();
        request = undefined;
        entries = undefined;
        state = "pending";
        onUpdate();
      }
    },
  };
}
