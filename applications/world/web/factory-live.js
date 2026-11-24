import { loadBinaryStl, loadOmxArmMeshes } from "./omx-arm.js";
import { createWorldMonitor } from "./world-monitor.js";
import {
  SIM_NAMES,
  STAGES,
  STAGE_LABELS,
  STAGE_DEFAULTS,
  lerpVec,
  lerpYaw,
  createFactoryLayer,
  interpolateArms,
  interpolatePinkys,
  sampleLocalTimeline,
} from "./factory-actors.js";

const byId = (id) => document.getElementById(id);

export function initFactoryTab({
  manifestRead, readDesignSource, showCad, equipmentUrl, CAD_PATH, REGISTRATION_PATH,
}) {
  const playBtn = byId("factory-play-toggle");
  const restartBtn = byId("factory-restart");
  const speedBtns = [1, 2, 4].map((s) => [s, byId(`factory-speed-${s}`)]);
  const camAutoBtn = byId("factory-cam-auto");
  const camBtns = [
    ["factory_all", byId("factory-cam-all")],
    ["factory_s3", byId("factory-cam-s3")],
    ["factory_omx", byId("factory-cam-omx")],
    ["factory_outbound", byId("factory-cam-outbound")],
    ["d435_top", byId("factory-cam-d435")],
    ["ceiling", byId("factory-cam-ceiling")],
  ];
  const r2sBtns = {
    off: byId("factory-r2s-off"),
    birdview: byId("factory-r2s-birdview"),
    field: byId("factory-r2s-field"),
  };
  const r2sOpacityEl = byId("factory-r2s-opacity");
  const r2sPctEl = byId("factory-r2s-pct");
  const r2sNoteEl = byId("factory-r2s-note");
  const stageBtns = [...byId("factory-stages").querySelectorAll("[data-stage]")];
  const statusEl = byId("factory-stream-status");
  const cadStatusEl = byId("factory-cad-status");
  const scrubber = byId("factory-scrubber");
  const metaEl = byId("factory-meta");
  const canvas = byId("factory-canvas");

  let cadPromise;
  let cadView;
  let layer;
  let r2sCal;
  let r2sSource = "birdview";
  let source;
  let rafId;
  let firstFrameTimer;
  let active = false;
  let playing = true;
  let scrubbing = false;
  let speed = 1;
  let autoCam = true;
  let currentCam = "factory_all";
  let lastStageCam;
  let startTimeS = 0;
  let latest;
  let previous;
  let latestAtMs = 0;
  let localTimeline;
  let timelineCache;
  let localStartMs = 0;
  let activeWorldId = null;
  let activeAdapter = "all";
  const stageStartMap = Object.fromEntries(STAGES.map(([id, , start]) => [id, start]));
  const monitor = createWorldMonitor({
    adaptersBarEl: byId("factory-adapters"),
    worldsStripEl: byId("factory-worlds"),
    parityEl: byId("factory-parity"),
    onSelectWorld({ worldId, adapter }) {
      activeWorldId = worldId;
      activeAdapter = adapter || "all";
      previous = undefined;
      localTimeline = undefined;
      if (active && playing) openStream();
    },
  });

  function setStatus(state, text) {
    if (statusEl.getAttribute("state") !== state) statusEl.setAttribute("state", state);
    if (statusEl.textContent !== text) statusEl.textContent = text;
  }

  function applyCam(focusKey, instant = false) {
    if (!cadView) return;
    currentCam = focusKey;
    layer?.setFocusLabels?.(focusKey);
    if (focusKey === "d435_top" && r2sCal?.cameras?.d435_top?.site_frame) {
      cadView.setExactCamera?.(r2sCal.cameras.d435_top.site_frame);
    } else if (focusKey === "ceiling" && r2sCal?.cameras?.ceiling) {
      cadView.setExactCamera?.(r2sCal.cameras.ceiling);
    } else {
      cadView.select("iso", cadView.focus[focusKey] ?? null, instant);
    }
    for (const [key, btn] of camBtns) btn?.setAttribute("aria-pressed", String(key === focusKey));
  }

  function applyR2sOverlay() {
    if (!cadView?.setR2sPhotoLayer) return;
    const rawPct = Math.max(0, Math.min(100, Number(r2sOpacityEl?.value ?? 55) || 0));
    if (r2sPctEl) r2sPctEl.textContent = `${rawPct}%`;
    for (const [key, btn] of Object.entries(r2sBtns)) {
      btn?.setAttribute("aria-pressed", String(key === r2sSource));
    }
    if (r2sSource === "off" || rawPct <= 0) {
      cadView.setR2sPhotoLayer({ url: null, opacity: 0 });
      return;
    }
    const gp = r2sCal?.ground_photos?.[r2sSource];
    if (gp?.bundle_path && Array.isArray(gp.plane)) {
      cadView.setR2sPhotoLayer({ url: `./${gp.bundle_path}`, plane: gp.plane, opacity: rawPct / 100 });
    } else {
      cadView.setR2sPhotoLayer({ url: null, opacity: 0 });
    }
  }

  function syncStagesMeta(frame) {
    if (!frame?.stage) return;
    if (Array.isArray(frame.stages) && frame.stages.length) {
      const avail = new Set();
      for (const s of frame.stages) {
        if (s?.id) {
          avail.add(s.id);
          if (Number.isFinite(s.start_s)) stageStartMap[s.id] = s.start_s;
        }
      }
      for (const btn of stageBtns) btn.hidden = !avail.has(btn.dataset.stage);
    }
    for (const btn of stageBtns) btn.setAttribute("aria-pressed", String(btn.dataset.stage === frame.stage));
    if (scrubber) {
      if (Number.isFinite(frame.duration_s) && frame.duration_s > 0) scrubber.max = String(frame.duration_s);
      if (!scrubbing && Number.isFinite(frame.sim_time_s)) scrubber.value = String(frame.sim_time_s.toFixed(1));
    }
    if (autoCam && frame.stage !== lastStageCam) {
      lastStageCam = frame.stage;
      const targetCam = STAGE_DEFAULTS[frame.stage]?.cam ?? "factory_all";
      if (targetCam !== currentCam) applyCam(targetCam);
    }
    const simName = SIM_NAMES[frame.adapter ?? frame.simulator] ?? frame.adapter ?? frame.simulator ?? "";
    const stageName = STAGE_LABELS[frame.stage] ?? frame.stage;
    const stacked = frame.cell_ab?.stacked?.length ?? 0;
    const totalSlots = Number.isInteger(frame.cell_ab?.total_slots) && frame.cell_ab.total_slots > 0
      ? frame.cell_ab.total_slots
      : (stacked > 18 ? 27 : stacked > 9 ? 18 : 9);
    const timeText = Number.isFinite(frame.duration_s)
      ? `${frame.sim_time_s.toFixed(1)} / ${frame.duration_s.toFixed(1)}초`
      : `${frame.sim_time_s.toFixed(1)}초`;
    const worldTag = frame.world_id ? `${frame.world_id} · ` : "";
    let trainText = "";
    if (frame.training) {
      let score = "";
      if (Number.isFinite(frame.training.reward)) {
        score = ` R ${frame.training.reward.toFixed(2)}`;
      } else if (Number.isFinite(frame.training.loss)) {
        score = ` Loss ${frame.training.loss.toFixed(3)}`;
      }
      trainText = ` · Ep ${frame.training.episode} Step ${frame.training.step}${score}`;
    }
    const fleetTag = frame.fleet_summary && Number.isFinite(frame.fleet_summary.online)
      ? `ROSY Fleet ${frame.fleet_summary.online}/${frame.fleet_summary.total}대 (rosy_42/45/46 · arm_s/a/b)`
      : "ROSY Fleet 6대 (rosy_42/45/46 · arm_s/a/b)";
    const estopActive = frame.safety?.estop === true;
    const estopTag = estopActive ? " · 비상정지(E-STOP)" : "";
    metaEl.textContent = `${worldTag}${stageName} · ${simName} · ${timeText} · 적재 ${stacked}/${totalSlots}${trainText} · ${fleetTag} · ${frame.run_id}${estopTag}`;
    const modeLabel = frame.stream_mode === "live" ? "실시간 SIM" : "검증 재생";
    setStatus(
      estopActive ? "warning" : "ready",
      estopActive ? `비상정지(E-STOP) 활성 · ${stageName} (${simName})` : `${modeLabel} · ${stageName} (${simName})`,
    );
    monitor.updateFromFrame(frame);
  }

  function interpolateFrame(nowMs) {
    if (localTimeline && playing) {
      const sample = sampleLocalTimeline(localTimeline, startTimeS + ((nowMs - localStartMs) / 1000) * speed);
      latest = sample;
      return sample;
    }
    if (!latest) return null;
    if (!previous || previous === latest || !playing || previous.stage !== latest.stage) return latest;
    const interval = Math.max(16, Math.min(200, (latestAtMs || nowMs) - (previous.receivedAtMs || nowMs)));
    const u = Math.max(0, Math.min(1, (nowMs - latestAtMs) / interval));
    return {
      ...latest,
      pinky: {
        ...latest.pinky,
        pose_m: lerpVec(previous.pinky.pose_m, latest.pinky.pose_m, u),
        yaw_rad: lerpYaw(previous.pinky.yaw_rad, latest.pinky.yaw_rad, u),
      },
      pinkys: interpolatePinkys(previous.pinkys, latest.pinkys, u) ?? latest.pinkys,
      arms: interpolateArms(previous.arms, latest.arms, u) ?? latest.arms,
      cargo: {
        ...latest.cargo,
        pose_m: lerpVec(previous.cargo.pose_m, latest.cargo.pose_m, u),
        yaw_rad: lerpYaw(previous.cargo.yaw_rad ?? 0, latest.cargo.yaw_rad ?? 0, u),
      },
    };
  }

  function frameLoop(nowMs) {
    if (!active || !layer) return;
    const state = interpolateFrame(nowMs);
    if (state) {
      layer.apply(state, nowMs, true);
      syncStagesMeta(state);
    }
    if (playing || localTimeline) rafId = requestAnimationFrame(frameLoop);
  }

  function closeTransport() {
    clearTimeout(firstFrameTimer);
    firstFrameTimer = undefined;
    source?.close();
    source = undefined;
    cancelAnimationFrame(rafId);
    rafId = undefined;
  }

  async function readLocalTimeline() {
    if (timelineCache) return timelineCache;
    const manifest = await manifestRead;
    if (!manifest?.factory_timeline?.bundle_path) return null;
    const res = await fetch(`./${manifest.factory_timeline.bundle_path}`, { cache: "no-store" });
    if (!res.ok) return null;
    timelineCache = await res.json();
    return timelineCache;
  }

  async function fallbackTimeline() {
    try {
      const tl = await readLocalTimeline();
      if (!tl || !active) return setStatus("unavailable", "공장 라이브 스트림 또는 검증 타임라인이 없습니다.");
      localTimeline = tl;
      localStartMs = performance.now();
      setStatus("ready", `오프라인 검증 재생 · ${localTimeline.run_id}`);
      rafId = requestAnimationFrame(frameLoop);
    } catch {
      setStatus("unavailable", "공장 라이브 스트림을 열 수 없습니다.");
    }
  }

  function openStream() {
    closeTransport();
    if (!active || document.hidden || !layer) return;
    localTimeline = undefined;
    let receivedAny = false;
    setStatus("pending", "공장 스트림 연결 중…");
    const params = new URLSearchParams({
      mode: "auto",
      speed: String(speed),
      hz: "25",
      start_s: startTimeS.toFixed(2),
    });
    if (activeWorldId) params.set("world", activeWorldId);
    if (activeAdapter && activeAdapter !== "all") params.set("adapter", activeAdapter);
    const url = `./sim/stream?${params.toString()}`;
    const es = new EventSource(url);
    source = es;
    firstFrameTimer = setTimeout(() => {
      if (source !== es || receivedAny) return;
      if (activeAdapter === "real" || activeWorldId === "real-site") {
        setStatus("empty", "실물 현장 미연결 (Real 어댑터 대기 중)");
        return;
      }
      closeTransport();
      void fallbackTimeline();
    }, 3500);
    es.addEventListener("state", (event) => {
      if (source !== es) return;
      try {
        const frame = JSON.parse(event.data);
        if (frame?.schema !== "rosy.world.factory-state.v1") return;
        receivedAny = true;
        clearTimeout(firstFrameTimer);
        firstFrameTimer = undefined;
        if (latest) previous = { ...latest, receivedAtMs: latestAtMs };
        latest = frame;
        latestAtMs = performance.now();
        if (!rafId) rafId = requestAnimationFrame(frameLoop);
      } catch {
        // Ignore single malformed SSE payload.
      }
    });
    es.addEventListener("idle", (event) => {
      if (source !== es) return;
      try {
        const info = JSON.parse(event.data || "{}");
        const reason = info.reason || (info.adapter === "real" ? "실물 현장 미연결" : "실시간 관측 또는 검증 타임라인 대기 중…");
        setStatus("empty", reason);
      } catch {
        setStatus("empty", "실시간 관측 또는 검증 타임라인을 기다리는 중…");
      }
    });
    es.onerror = () => {
      if (source !== es) return;
      if (!receivedAny) {
        if (activeAdapter === "real" || activeWorldId === "real-site") {
          setStatus("empty", "실물 현장 미연결 (Real 어댑터 대기 중)");
          return;
        }
        closeTransport();
        void fallbackTimeline();
      } else {
        setStatus("warning", "스트림 재연결 중…");
      }
    };
  }

  async function ensureCad() {
    if (cadView) return cadView;
    cadPromise ??= (async () => {
      cadStatusEl.hidden = false;
      cadStatusEl.setAttribute("state", "pending");
      cadStatusEl.textContent = "공장 3D 스튜디오·로봇 관절 CAD를 불러오는 중…";
      const [manifest, r2sResp] = await Promise.all([
        manifestRead,
        fetch("./data/r2s-calibration.json", { cache: "no-store" })
          .then((res) => (res.ok ? res.json() : null))
          .catch(() => null),
      ]);
      r2sCal = r2sResp;
      if (r2sNoteEl) {
        const audit = r2sCal?.geometry_audit;
        const pal = r2sCal?.palette;
        if (audit && pal) {
          const canonicalGap = audit.canonical_plate_inner_gap_mm ?? audit.planned_plate_inner_gap_mm;
          const gateTag = r2sCal?.map_gate?.available
            ? (r2sCal.map_gate.ok ? " · map_gate PASS" : " · map_gate FAIL")
            : "";
          r2sNoteEl.textContent = `매트 ${pal.floor_mat_hex} · 작업대 ${pal.worktable_yellow_hex} · 팔 간격 ${canonicalGap} mm CAD·실물 기준 (사진 참고 ${audit.measured_plate_inner_gap_mm} mm · v25 후보 ${audit.future_v25_candidate_mm ?? 190} mm) · D435 ${audit.d435_fit_rms_px} px RMS${gateTag}`;
        } else {
          r2sNoteEl.textContent = "R2S 사진 보정 파일 없음 · 기본 재질 표시";
        }
      }
      if (!r2sCal?.ground_photos?.birdview?.bundle_path && r2sBtns.birdview) r2sBtns.birdview.hidden = true;
      if (!r2sCal?.ground_photos?.field?.bundle_path && r2sBtns.field) r2sBtns.field.hidden = true;
      if (!r2sCal?.cameras?.d435_top?.site_frame && byId("factory-cam-d435")) byId("factory-cam-d435").hidden = true;
      const cadUrl = manifest?.site_cad?.bundle_path === CAD_PATH ? `./${CAD_PATH}` : null;
      const siteEquip = equipmentUrl(manifest, "site");
      const view = await showCad(canvas, cadUrl, () => {
        setStatus("unavailable", "3D WebGL 컨텍스트가 끊겼습니다.");
      }, siteEquip, { hideStaticRoadPinky: true, studioMode: true, r2sPalette: r2sCal?.palette ?? null });
      const ctx = view.getFactoryContext();
      const armPromise = loadOmxArmMeshes(ctx.three).catch(() => null);
      const trayPromise = loadBinaryStl(ctx.three, "./common/meshes/pinky-tray.stl").catch(() => null);
      const canDesign = !manifest?.site_map_override && !!equipmentUrl(manifest, "cell") &&
        manifest?.equipment?.registration?.bundle_path === REGISTRATION_PATH;
      if (canDesign) {
        try {
          await view.setDesign(true, await readDesignSource());
        } catch {
          // Keep base studio scene if registration is unavailable.
        }
      }
      const [armMeshes, trayGeometry] = await Promise.all([armPromise, trayPromise]);
      cadView = view;
      layer = createFactoryLayer({ ...ctx, armMeshes, trayGeometry, armBases: r2sCal?.arm_bases_site ?? null });
      applyCam("factory_all", true);
      if (!r2sCal?.ground_photos?.birdview) r2sSource = "off";
      applyR2sOverlay();
      cadStatusEl.hidden = true;
      return view;
    })().catch((err) => {
      cadPromise = null;
      cadStatusEl.hidden = false;
      cadStatusEl.setAttribute("state", "unavailable");
      cadStatusEl.textContent = `공장 3D 모델을 열 수 없습니다 (${err?.message || "WebGL 오류"}).`;
      setStatus("unavailable", "공장 3D 초기화 실패");
      return null;
    });
    return cadPromise;
  }

  async function seekTime(tSec) {
    startTimeS = Math.max(0, tSec);
    previous = undefined;
    localStartMs = performance.now();
    if (!cadView) {
      const view = await ensureCad();
      if (!view || !active) return;
    }
    if (playing && !localTimeline) return openStream();
    const tl = localTimeline ?? await readLocalTimeline();
    if (tl && layer) {
      const sample = sampleLocalTimeline(tl, startTimeS);
      latest = sample;
      layer.apply(sample, performance.now(), true);
      syncStagesMeta(sample);
      if (playing && localTimeline && !rafId) rafId = requestAnimationFrame(frameLoop);
    }
  }

  canvas.addEventListener("pointerdown", () => {
    if (!autoCam) return;
    autoCam = false;
    camAutoBtn.setAttribute("aria-pressed", "false");
  });

  camAutoBtn.addEventListener("click", () => {
    autoCam = !autoCam;
    camAutoBtn.setAttribute("aria-pressed", String(autoCam));
    if (autoCam && latest?.stage) {
      lastStageCam = undefined;
      applyCam(STAGE_DEFAULTS[latest.stage]?.cam ?? "factory_all");
    }
  });

  for (const [key, btn] of camBtns) {
    btn?.addEventListener("click", () => {
      autoCam = false;
      camAutoBtn.setAttribute("aria-pressed", "false");
      applyCam(key);
    });
  }

  for (const [key, btn] of Object.entries(r2sBtns)) {
    btn?.addEventListener("click", () => {
      r2sSource = key;
      if (key !== "off" && Number(r2sOpacityEl?.value ?? 0) === 0 && r2sOpacityEl) {
        r2sOpacityEl.value = "55";
      }
      applyR2sOverlay();
    });
  }
  r2sOpacityEl?.addEventListener("input", () => {
    if (Number(r2sOpacityEl.value) > 0 && r2sSource === "off") {
      r2sSource = r2sCal?.ground_photos?.birdview ? "birdview" : "field";
    }
    applyR2sOverlay();
  });

  playBtn.addEventListener("click", () => {
    if (!active) return;
    if (!cadView) {
      void ensureCad().then((view) => { if (view && active && playing) openStream(); });
      return;
    }
    playing = !playing;
    playBtn.setAttribute("aria-pressed", String(playing));
    playBtn.textContent = playing ? "일시 정지" : "계속 재생";
    if (playing) {
      startTimeS = latest?.sim_time_s ?? startTimeS;
      localStartMs = performance.now();
      if (!localTimeline) openStream();
      else rafId = requestAnimationFrame(frameLoop);
    } else {
      startTimeS = latest?.sim_time_s ?? startTimeS;
      closeTransport();
      if (latest) layer?.apply(latest, performance.now(), true);
      setStatus("ready", "일시 정지됨");
    }
  });

  restartBtn.addEventListener("click", () => {
    playing = true;
    playBtn.setAttribute("aria-pressed", "true");
    playBtn.textContent = "일시 정지";
    lastStageCam = undefined;
    void seekTime(0);
  });

  for (const [value, btn] of speedBtns) {
    btn.addEventListener("click", () => {
      if (speed === value) return;
      speed = value;
      for (const [opt, optBtn] of speedBtns) optBtn.setAttribute("aria-pressed", String(opt === value));
      startTimeS = latest?.sim_time_s ?? startTimeS;
      localStartMs = performance.now();
      if (active && playing && !localTimeline) openStream();
    });
  }

  for (const btn of stageBtns) {
    btn.addEventListener("click", () => {
      const stageId = btn.dataset.stage;
      lastStageCam = undefined;
      void seekTime(stageStartMap[stageId] ?? STAGE_DEFAULTS[stageId]?.start ?? 0);
    });
  }

  scrubber?.addEventListener("pointerdown", () => { scrubbing = true; });
  scrubber?.addEventListener("input", async () => {
    scrubbing = true;
    const t = Number(scrubber.value);
    const tl = localTimeline ?? await readLocalTimeline();
    if (tl && layer) {
      const sample = sampleLocalTimeline(tl, t);
      latest = sample;
      lastStageCam = undefined;
      layer.apply(sample, performance.now(), true);
      syncStagesMeta(sample);
    }
  });
  scrubber?.addEventListener("change", () => {
    scrubbing = false;
    lastStageCam = undefined;
    void seekTime(Number(scrubber.value));
  });

  window.addEventListener("keydown", (event) => {
    if (!active || document.hidden || event.altKey || event.ctrlKey || event.metaKey) return;
    if (event.target?.matches?.("input, textarea, select, button, ui-button, [contenteditable]")) return;
    if (event.key === " ") {
      event.preventDefault();
      playBtn.click();
    } else if (event.key >= "1" && event.key <= "9") {
      event.preventDefault();
      const targetBtn = stageBtns[Number(event.key) - 1];
      if (targetBtn && !targetBtn.hidden) targetBtn.click();
    } else if (event.key === "r" || event.key === "R") {
      event.preventDefault();
      restartBtn.click();
    }
  });

  return {
    async activate() {
      active = true;
      monitor.start();
      const view = await ensureCad();
      if (!active || !view) return;
      if (latest) layer?.apply(latest);
      if (playing) openStream();
    },
    deactivate() {
      active = false;
      monitor.stop();
      closeTransport();
    },
  };
}
