export function activeSiteMap({ canvas, showMap, mapData, date, onUpdate }) {
  let entries;
  let draw;
  let sha;
  let timer;
  let watching = false;
  let request;
  let state = "pending";

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
      if (!Number.isSafeInteger(map.version) || map.version < 1 || !/^[a-f0-9]{64}$/.test(envelope.sha256)) {
        throw new Error("Invalid active map revision");
      }
      if (!draw) {
        sha = envelope.sha256;
        draw = showMap(canvas, map, () => {
          draw = undefined;
          unavailable();
        }).catch((error) => {
          draw = undefined;
          throw error;
        });
      }
      const renderer = await draw;
      if (request !== controller) return;
      if (envelope.sha256 !== sha) renderer.setMap(map);
      sha = envelope.sha256;
      state = "ready";
      entries = [
        ["출처", "Fleet 활성 지도"],
        ["지도 ID", map.id],
        ["버전", map.version],
        ["활성 시각 (UTC)", date(envelope.activated_at)],
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
