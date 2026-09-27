const NO_SOURCE = "관제 카메라 인증 후 영상을 불러옵니다.";

export function createVisionView({ el, call, auth }) {
  const select = el("vision-source");
  const image = el("vision-image");
  const status = el("vision-state");
  const message = el("vision-message");
  let lease = null;
  let leaseExpiresAt = 0;
  let objectUrl = null;
  let busy = false;
  let lastSourcesAt = 0;

  function showState(label, kind = "neutral", detail = label) {
    status.textContent = label;
    status.setAttribute("status", kind);
    message.textContent = detail;
    image.hidden = true;
    el("vision-frame").dataset.state = kind;
    if (objectUrl) URL.revokeObjectURL(objectUrl);
    objectUrl = null;
  }

  async function refreshSources() {
    if (auth.locked || !auth.token || busy) {
      showState("인증 대기", "neutral", NO_SOURCE);
      return;
    }
    busy = true;
    try {
      const result = await call("/api/fleet/vision/sources");
      const selected = select.value;
      select.replaceChildren(...result.sources.map((source) => {
        const option = document.createElement("option");
        option.value = source;
        option.textContent = source;
        return option;
      }));
      if (result.sources.includes(selected)) select.value = selected;
      select.disabled = result.sources.length === 0;
      lastSourcesAt = Date.now();
      lease = null;
      if (!result.sources.length) showState("카메라 없음", "warn", "Vision에 등록된 카메라가 없습니다.");
    } catch (error) {
      showState("영상 연결 불가", "warn", error.message);
    } finally {
      busy = false;
    }
  }

  async function refreshFrame() {
    if (busy) return;
    if (auth.locked || !auth.token) {
      showState("인증 대기", "neutral", NO_SOURCE);
      return;
    }
    if (Date.now() - lastSourcesAt > 30000) await refreshSources();
    const source = select.value;
    if (!source) return;
    busy = true;
    try {
      if (!lease || Date.now() >= leaseExpiresAt) {
        const issued = await call("/api/fleet/vision/lease", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ source_id: source }),
        });
        lease = issued;
        leaseExpiresAt = Date.now() + 45000;
      }
      const response = await fetch(lease.frame_path, {
        headers: { Authorization: `Bearer ${lease.lease}` },
        cache: "no-store",
      });
      if (source !== select.value) return;
      if (!response.ok) {
        const stale = response.headers.get("X-Frame-State") === "stale";
        showState(stale ? "영상 정지" : "영상 수신 대기", stale ? "warn" : "neutral",
          stale ? "최신 프레임이 없어 영상 표시를 지웠습니다." : `Vision 응답 ${response.status}`);
        return;
      }
      const blob = await response.blob();
      if (source !== select.value) return;
      const nextUrl = URL.createObjectURL(blob);
      if (objectUrl) URL.revokeObjectURL(objectUrl);
      objectUrl = nextUrl;
      image.src = nextUrl;
      image.hidden = false;
      el("vision-frame").dataset.state = "online";
      status.textContent = "실시간 최신 프레임";
      status.setAttribute("status", "good");
      message.textContent = "";
      el("vision-meta").textContent = `${source} · sequence ${response.headers.get("X-Frame-Seq") || "?"} · age ${response.headers.get("X-Frame-Age-Ms") || "?"} ms`;
    } catch (error) {
      lease = null;
      showState("영상 정지", "warn", error.message || "Vision에 연결할 수 없습니다.");
    } finally {
      busy = false;
    }
  }

  function reset() {
    lease = null;
    leaseExpiresAt = 0;
    lastSourcesAt = 0;
    select.replaceChildren();
    select.disabled = true;
    showState("인증 대기", "neutral", NO_SOURCE);
  }

  select.addEventListener("change", () => {
    lease = null;
    showState("카메라 전환", "neutral", "선택한 영상의 최신 프레임을 기다립니다.");
    refreshFrame();
  });
  el("vision-refresh").addEventListener("click", () => { lease = null; refreshSources().then(refreshFrame); });
  return { refreshSources, refreshFrame, reset };
}
