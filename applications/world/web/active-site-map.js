export function activeSiteMap({ canvas, placeSelect, showMap, mapData, date, onUpdate }) {
  let entries;
  let draw;
  let sha;
  let timer;
  let watching = false;
  let request;
  let state = "pending";
  let places = new Map();
  let showPositions;
  const mapLabel = canvas.getAttribute("aria-label");

  function markSelectedPlace() {
    const place = places.get(placeSelect.value);
    showPositions?.(place ? [{ x_m: place.x, y_m: place.y }] : []);
    canvas.setAttribute("aria-label", place ? `Fleet 활성 지도 · ${place.id}` : mapLabel);
  }

  function updatePlaces(locations) {
    const previous = placeSelect.value;
    places = new Map(locations.filter(({ id }) => typeof id === "string" && id).map((place) => [place.id, place]));
    placeSelect.replaceChildren(new Option("전체 위치", ""),
      ...Array.from(places.keys(), (id) => new Option(id, id)));
    placeSelect.value = places.has(previous) ? previous : "";
    markSelectedPlace();
  }

  placeSelect.addEventListener("change", markSelectedPlace);

  function unavailable() {
    entries = undefined;
    state = "unavailable";
    onUpdate();
  }

  async function refresh() {
    if (request) return;
    const controller = new AbortController();
    request = controller;
    try {
      const signal = AbortSignal.any([controller.signal, AbortSignal.timeout(4000)]);
      const response = await fetch("./api/worlds/real-site/site-map", { signal });
      if (!response.ok) throw new Error("Active map unavailable");
      const { site_map: envelope } = await response.json();
      const map = mapData(envelope);
      if (!Number.isSafeInteger(map.version) || map.version < 1 || !/^[a-f0-9]{64}$/.test(envelope.sha256)
          || !Number.isSafeInteger(envelope.observed_at_ms) || envelope.observed_at_ms <= 0) {
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
      const geometryChanged = envelope.sha256 !== sha;
      if (geometryChanged) renderer.setMap(map);
      if (renderer !== showPositions || geometryChanged) {
        showPositions = renderer;
        updatePlaces(map.places);
      }
      sha = envelope.sha256;
      state = "ready";
      entries = [
        ["출처", "Fleet 활성 지도"],
        ["지도 ID", map.id],
        ["버전", map.version],
        ["활성 시각 (UTC)", date(envelope.activated_at)],
        ["수신 시각 (UTC)", date(envelope.observed_at_ms / 1000)],
        ["위치", map.places.length],
        ["차로", map.edges.length],
      ];
      onUpdate();
    } catch {
      if (request === controller) unavailable();
    } finally {
      if (request === controller) request = undefined;
    }
  }

  return {
    get entries() { return entries; },
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
        request?.abort();
        request = undefined;
        entries = undefined;
        state = "pending";
        onUpdate();
      }
    },
  };
}
