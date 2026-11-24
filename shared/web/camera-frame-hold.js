// Shared camera last-frame hold & elapsed-disconnect formatter (anti-flicker).

export function formatDisconnectDuration(ms) {
  const totalSec = Math.max(0, Math.floor((Number(ms) || 0) / 1000));
  if (totalSec < 60) return `${totalSec}초간 끊어짐`;
  const min = Math.floor(totalSec / 60);
  const sec = totalSec % 60;
  return sec ? `${min}분 ${sec}초간 끊어짐` : `${min}분간 끊어짐`;
}

export function decodeImageUrl(url, { ImageCtor = globalThis.Image } = {}) {
  if (typeof ImageCtor !== "function") return Promise.resolve(true);
  const img = new ImageCtor();
  img.src = url;
  return typeof img.decode === "function"
    ? img.decode().then(() => true, () => false)
    : Promise.resolve(true);
}

export function createCameraFrameHold({
  now = Date.now,
  onRevoke = (url) => { if (typeof URL !== "undefined" && URL.revokeObjectURL) URL.revokeObjectURL(url); },
} = {}) {
  let phase = "waiting";
  let url = null;
  let seq = null;
  let disconnectedAt = null;
  let kind = "neutral";
  let label = "첫 프레임 대기";
  let detail = "스트림 연결 확인";

  function revokeCurrent() {
    if (url) onRevoke(url);
    url = null;
    seq = null;
  }

  return {
    acceptFrame({ url: nextUrl, seq: nextSeq = null, label: nextLabel = "", detail: nextDetail = "", kind: nextKind = "good" }) {
      if (url && url !== nextUrl) onRevoke(url);
      url = nextUrl;
      seq = nextSeq;
      phase = "live";
      disconnectedAt = null;
      kind = nextKind;
      label = nextLabel;
      detail = nextDetail;
    },
    markLive({ label: nextLabel, detail: nextDetail, kind: nextKind = "good" } = {}) {
      if (!url) return;
      phase = "live";
      disconnectedAt = null;
      kind = nextKind;
      if (nextLabel !== undefined) label = nextLabel;
      if (nextDetail !== undefined) detail = nextDetail;
    },
    disconnect({ kind: nextKind = "warn", label: nextLabel = "영상 연결 끊김", detail: nextDetail = "", dropFrame = false } = {}) {
      kind = nextKind;
      label = nextLabel;
      detail = nextDetail;
      if (dropFrame) {
        revokeCurrent();
        disconnectedAt = null;
        phase = "waiting";
        return;
      }
      if (url) {
        phase = "disconnected";
        if (disconnectedAt === null) disconnectedAt = now();
      } else {
        phase = "waiting";
        disconnectedAt = null;
      }
    },
    setPaused(paused) {
      if (paused) {
        phase = "paused";
      } else {
        phase = url ? (disconnectedAt !== null ? "disconnected" : "live") : "waiting";
      }
    },
    snapshot(at = now()) {
      const hasFrame = Boolean(url);
      const disconnectedMs = phase === "disconnected" && disconnectedAt !== null ? Math.max(0, at - disconnectedAt) : 0;
      const stateLine = [label, detail].filter(Boolean).join(" · ");
      let overlayText = stateLine;
      if (phase === "live") overlayText = "";
      else if (phase === "paused") overlayText = hasFrame ? "영상 일시정지 · 마지막 프레임 유지" : "영상 일시정지";
      else if (phase === "disconnected" && hasFrame) {
        overlayText = `끊어짐 · ${formatDisconnectDuration(disconnectedMs)}${label ? ` · ${label}` : ""}`;
      }
      return {
        phase,
        hasFrame,
        url,
        seq,
        kind,
        label,
        detail,
        text: phase === "live" ? stateLine : overlayText,
        disconnectedMs,
        overlayText,
      };
    },
    dispose() {
      revokeCurrent();
      disconnectedAt = null;
      phase = "waiting";
    },
  };
}

export function paintCameraFrameHold(frameEl, imgEl, overlayEl, snap) {
  if (frameEl?.dataset) {
    if (frameEl.dataset.camPhase !== snap.phase) frameEl.dataset.camPhase = snap.phase;
    const nextHas = snap.hasFrame ? "true" : "false";
    if (frameEl.dataset.camHasFrame !== nextHas) frameEl.dataset.camHasFrame = nextHas;
  }
  if (imgEl) {
    const hideImg = !snap.hasFrame;
    if (imgEl.hidden !== hideImg) imgEl.hidden = hideImg;
    if (snap.url) {
      if (imgEl.src !== snap.url) imgEl.src = snap.url;
    } else if (imgEl.src !== "") {
      imgEl.removeAttribute?.("src");
    }
  }
  if (overlayEl) {
    const showOverlay = snap.phase !== "live";
    if (overlayEl.hidden !== !showOverlay) overlayEl.hidden = !showOverlay;
    if (showOverlay && overlayEl.textContent !== snap.overlayText) overlayEl.textContent = snap.overlayText;
  }
}
