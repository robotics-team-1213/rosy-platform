const NO_SOURCE = "관제 카메라 인증 후 영상을 불러옵니다.";
const DEFAULT_RECTIFICATION = Object.freeze({
  fx: 1, fy: 1, cx: 0.5, cy: 0.5, k1: 0, k2: 0, p1: 0, p2: 0, k3: 0,
  corners: [[0, 0], [1, 0], [1, 1], [0, 1]], output_aspect: 0,
});

export function createVisionView({ el, call, auth }) {
  const select = el("vision-source");
  const image = el("vision-image");
  const status = el("vision-state");
  const message = el("vision-message");
  const profileFields = [...el("vision-adjustments").querySelectorAll("[data-rect]")];
  const cornerFields = [...el("vision-adjustments").querySelectorAll("[data-corner]")];
  const profileFieldsets = [...el("vision-adjustments").querySelectorAll("fieldset")];
  const adjustmentState = el("vision-adjustment-state");
  let lease = null;
  let leaseExpiresAt = 0;
  let objectUrl = null;
  let busy = false;
  let lastSourcesAt = 0;
  let refreshTimer = null;

  function showState(label, kind = "neutral", detail = label) {
    status.textContent = label;
    status.setAttribute("status", kind);
    message.textContent = detail;
    image.hidden = true;
    el("vision-frame").dataset.state = kind;
    if (objectUrl) URL.revokeObjectURL(objectUrl);
    objectUrl = null;
  }

  function readProfile() {
    const profile = { ...DEFAULT_RECTIFICATION };
    for (const field of profileFields) profile[field.dataset.rect] = Number(field.value);
    profile.corners = Array.from({ length: 4 }, (_, index) =>
      Array.from({ length: 2 }, (_, axis) => {
        const input = cornerFields.find((item) => Number(item.dataset.corner) === index
          && Number(item.dataset.axis) === axis);
        return Number(input.value) / 100;
      }));
    return profile;
  }

  function writeProfile(profile) {
    for (const field of profileFields) {
      field.value = String(profile[field.dataset.rect] ?? DEFAULT_RECTIFICATION[field.dataset.rect]);
    }
    for (const field of cornerFields) {
      field.value = String(Math.round(100 * (profile.corners?.[Number(field.dataset.corner)]?.[Number(field.dataset.axis)]
        ?? DEFAULT_RECTIFICATION.corners[Number(field.dataset.corner)][Number(field.dataset.axis)])));
    }
  }

  function loadProfile(source) {
    let profile = DEFAULT_RECTIFICATION;
    try {
      const saved = localStorage.getItem(`rosy-camera-rectification:${source}`);
      if (saved) profile = { ...DEFAULT_RECTIFICATION, ...JSON.parse(saved) };
    } catch {
      adjustmentState.textContent = "저장한 값을 읽지 못해 기본 조정값을 사용합니다.";
    }
    writeProfile(profile);
    profileFieldsets.forEach((fieldset) => { fieldset.disabled = !source; });
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
      else if (result.sources.length) select.value = result.sources[0];
      select.disabled = result.sources.length === 0;
      loadProfile(select.value);
      lastSourcesAt = Date.now();
      lease = null;
      if (!result.sources.length) {
        loadProfile("");
        showState("카메라 없음", "warn", "Vision에 등록된 카메라가 없습니다.");
      }
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
          body: JSON.stringify({ source_id: source, rectification: readProfile() }),
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
        const invalid = response.status === 422;
        showState(stale ? "영상 정지" : "영상 수신 대기", stale || invalid ? "warn" : "neutral",
          invalid ? "보정값을 확인하세요. 모서리는 교차하지 않는 사각형이어야 합니다."
            : stale ? "최신 프레임이 없어 영상 표시를 지웠습니다." : `Vision 응답 ${response.status}`);
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
      const rectified = response.headers.get("X-Frame-Rectified") === "true";
      status.textContent = rectified ? "화면 보정 미리보기" : "원본 최신 프레임";
      status.setAttribute("status", "good");
      message.textContent = "";
      el("vision-meta").textContent = `${source} · sequence ${response.headers.get("X-Frame-Seq") || "?"} · age ${response.headers.get("X-Frame-Age-Ms") || "?"} ms · ${rectified ? "화면 보정" : "원본"}`;
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
    loadProfile("");
    showState("인증 대기", "neutral", NO_SOURCE);
  }

  select.addEventListener("change", () => {
    lease = null;
    loadProfile(select.value);
    showState("카메라 전환", "neutral", "선택한 영상의 최신 프레임을 기다립니다.");
    refreshFrame();
  });
  for (const field of [...profileFields, ...cornerFields]) {
    field.addEventListener("input", () => {
      if (!field.reportValidity()) return;
      const source = select.value;
      if (!source) return;
      const profile = readProfile();
      try {
        localStorage.setItem(`rosy-camera-rectification:${source}`, JSON.stringify(profile));
        adjustmentState.textContent = "조정값을 이 브라우저에 저장했습니다.";
      } catch {
        adjustmentState.textContent = "브라우저 저장을 사용할 수 없습니다. 이 화면에서만 적용됩니다.";
      }
      lease = null;
      if (refreshTimer) clearTimeout(refreshTimer);
      adjustmentState.textContent += " 미리보기를 갱신합니다.";
      refreshTimer = setTimeout(() => refreshFrame(), 450);
    });
  }
  el("vision-reset-adjustments").addEventListener("click", () => {
    const source = select.value;
    if (source) localStorage.removeItem(`rosy-camera-rectification:${source}`);
    loadProfile(source);
    adjustmentState.textContent = "기본 조정값으로 초기화했습니다.";
    lease = null;
    refreshFrame();
  });
  el("vision-refresh").addEventListener("click", () => {
    lease = null;
    refreshSources().then(refreshFrame);
  });
  return { refreshSources, refreshFrame, reset };
}
