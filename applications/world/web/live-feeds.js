import { showMap } from "./scene.js";
import { initPlay } from "./play.js";

const ISAAC_FRESH_MS = 3000;
const ISAAC_STATES = {
  waiting: "SIM 관측 대기 중",
  running: "SIM 실행 중",
  paused: "SIM 일시정지 또는 시계 정체",
  stopped: "SIM 중지됨",
};
const PINKY_SIM_FRAME = "world_261026_cad";
const PINKY_SIM_FRESH_MS = 3000;
const CAMERA_FRESH_MS = 3000;
const CAMERA_SOURCES = {
  field: { file: "field-live.jpg", label: "Rosy Cam 현장 상단", freshMs: 5000, fleet: true },
  gazebo: { file: "pinky-camera.jpg", label: "Gazebo Pinky 전방" },
  mujoco: { file: "mujoco-top.jpg", label: "MuJoCo OMX 셀 상단" },
  isaac: { file: "isaac-view.json", label: "Isaac Sim", telemetry: true },
};

export const isLayoutSha = (value) => typeof value === "string" && /^[0-9a-f]{64}$/.test(value);
const vector = (values, length) => Array.isArray(values) && values.length === length && values.every(Number.isFinite);

export function initLiveFeeds({
  byId, status, readout, date, text, readJson, mapData, recordingData,
  manifestRead, mapPromise, directRun, getMode, getCadView, getArchiveLayout, getFactoryTab,
}) {
  let isaacSession;
  let simSession;
  let cameraSource = "gazebo";
  let cameraSession;

  function validIsaac(sample) {
    return sample?.schema === "rosy.world.isaac-state.v1" && text(sample.run_id) &&
      (sample.scene === "ab" ? isLayoutSha(sample.layout_sha256)
        : sample.scene === "conformance" && sample.layout_sha256 === null) &&
      Number.isSafeInteger(sample.observed_at_ms) && sample.observed_at_ms > 0 &&
      Number.isFinite(sample.sim_time_s) && sample.sim_time_s >= 0 &&
      Number.isSafeInteger(sample.reset_count) && sample.reset_count >= 0 &&
      typeof sample.state === "string" && Object.hasOwn(ISAAC_STATES, sample.state) &&
      Array.isArray(sample.joints) && sample.joints.every((joint) =>
        text(joint?.name) && Number.isFinite(joint.position_rad)) &&
      Array.isArray(sample.objects) && sample.objects.every((object) =>
        text(object?.id) && text(object.frame_id) &&
        vector(object.position_m, 3) && vector(object.orientation_xyzw, 4));
  }

  function isaacStatus(state, message, summary = message) {
    const node = byId("isaac-status");
    if (node.getAttribute("state") !== state || node.textContent !== message) {
      status("isaac-status", state, message);
    }
    const health = byId("isaac-health");
    const label = `Isaac · ${summary}`;
    if (health.getAttribute("state") !== state || health.textContent !== label) {
      status("isaac-health", state, label);
    }
  }

  function clearIsaacReadout() {
    const list = byId("isaac-readout");
    list.hidden = true;
    list.replaceChildren();
  }

  function showIsaac(session, sample) {
    clearTimeout(session.expiry);
    const age = Date.now() - sample.observed_at_ms;
    if (Math.abs(age) > ISAAC_FRESH_MS) {
      clearIsaacReadout();
      return isaacStatus("unavailable", "연결 안 됨 · SIM 관측 시각이 3초 범위를 벗어났습니다.", "관측 만료");
    }
    if (sample.state === "waiting" || sample.state === "stopped" ||
        !sample.joints.length || !sample.objects.length) {
      clearIsaacReadout();
      return isaacStatus("empty", sample.state === "running" || sample.state === "paused"
        ? "표시할 관절과 물체 관측을 기다리는 중입니다." : ISAAC_STATES[sample.state], "관측 대기");
    }
    isaacStatus("ready", ISAAC_STATES[sample.state],
      sample.state === "running" ? "SIM 관측 수신 중" : "SIM 일시정지 또는 시계 정체");
    const ab = sample.scene === "ab";
    const archiveLayout = getArchiveLayout();
    readout("isaac-readout", [
      ["SIM 장면", ab ? "OMX A/B (ab)" : "적합성 시험 (conformance)"],
      ...(ab ? [
        ["SIM 배치 SHA-256", sample.layout_sha256],
        ["보관 배치 비교", archiveLayout ? (archiveLayout === sample.layout_sha256 ? "SHA-256 일치" : "SHA-256 불일치") : "보관 SHA-256 확인 불가"],
      ] : []),
      ["실행 ID", sample.run_id],
      ["SIM 시간 (s)", sample.sim_time_s],
      ["시계 초기화 횟수", sample.reset_count],
      ...sample.joints.map(({ name, position_rad }) => [`관절 ${name} (rad)`, position_rad]),
      ...sample.objects.flatMap(({ id, frame_id, position_m, orientation_xyzw }) => [
        [`물체 ${id} · 좌표계`, frame_id],
        [`물체 ${id} · 위치 (X, Y, Z m)`, position_m.join(", ")],
        [`물체 ${id} · 자세 (쿼터니언 XYZW)`, orientation_xyzw.join(", ")],
      ]),
    ]);
    session.expiry = setTimeout(() => {
      clearIsaacReadout();
      isaacStatus("unavailable", "연결 안 됨 · 최근 SIM 관측이 없습니다.", "관측 만료");
    }, ISAAC_FRESH_MS - age);
  }

  async function pollIsaac(session) {
    const request = new AbortController();
    session.request = request;
    const deadline = setTimeout(() => request.abort(), 2500);
    try {
      const response = await fetch("./data/isaac-live.json", {
        cache: "no-store", redirect: "error", signal: request.signal,
      });
      if (!response.ok) throw new Error("SIM snapshot unavailable");
      const sample = await response.json();
      if (isaacSession !== session) return;
      if (!validIsaac(sample)) throw new Error("Invalid SIM snapshot");
      showIsaac(session, sample);
    } catch {
      if (isaacSession !== session) return;
      clearTimeout(session.expiry);
      clearIsaacReadout();
      isaacStatus("unavailable", "연결 안 됨 · SIM 관측을 읽을 수 없습니다.", "연결 안 됨");
    } finally {
      clearTimeout(deadline);
      if (isaacSession === session) {
        const delay = byId("isaac-health").getAttribute("state") === "unavailable" ? 2000 : 750;
        session.next = setTimeout(() => pollIsaac(session), delay);
      }
    }
  }

  function stopIsaacStatus() {
    const session = isaacSession;
    isaacSession = undefined;
    if (!session) return;
    session.request?.abort();
    clearTimeout(session.next);
    clearTimeout(session.expiry);
    clearIsaacReadout();
  }

  function startIsaacStatus() {
    if (document.hidden || isaacSession || byId("isaac-status-panel").hidden) return;
    const session = {};
    isaacSession = session;
    isaacStatus("pending", "SIM 관측을 확인하는 중…", "확인 중");
    void pollIsaac(session);
  }

  byId("isaac-status-toggle").addEventListener("click", () => {
    const panel = byId("isaac-status-panel");
    panel.hidden = !panel.hidden;
    byId("isaac-status-toggle").setAttribute("aria-pressed", String(!panel.hidden));
    if (panel.hidden) {
      stopIsaacStatus();
      isaacStatus("empty", "SIM 관측이 꺼져 있습니다 — 스위치로 켤 수 있습니다.", "끔");
    } else startIsaacStatus();
  });

  function validPinkySim(sample, manifest) {
    return sample?.schema === "rosy.world.pinky-sim.v1" && text(sample.run_id) &&
      typeof sample.robot_id === "string" && /^[a-z][a-z0-9_]{0,31}$/.test(sample.robot_id) &&
      sample.frame_id === PINKY_SIM_FRAME && !!manifest?.site_cad?.source_sha256 &&
      sample.site_cad_sha256 === manifest?.site_cad?.source_sha256 &&
      Number.isSafeInteger(sample.observed_at_ms) && sample.observed_at_ms > 0 &&
      Number.isFinite(sample.sim_time_s) && sample.sim_time_s >= 0 &&
      vector(sample.pose_m, 3) && Number.isFinite(sample.yaw_rad);
  }

  function hidePinkySim() {
    getCadView()?.setSim(null);
  }

  function stopPinkySim() {
    const session = simSession;
    simSession = undefined;
    if (!session) return;
    session.request?.abort();
    clearTimeout(session.next);
    clearTimeout(session.expiry);
    hidePinkySim();
  }

  function showPinkySim(session, sample) {
    clearTimeout(session.expiry);
    const age = Date.now() - sample.observed_at_ms;
    if (Math.abs(age) > PINKY_SIM_FRESH_MS) {
      hidePinkySim();
      return status("pinky-sim-status", "unavailable",
        "Pinky SIM 사용 불가 · 관측 시각이 3초 범위를 벗어났습니다.");
    }
    getCadView()?.setSim(sample);
    status("pinky-sim-status", "ready", `Pinky SIM 라이브 · 실행 ${sample.run_id}`);
    session.expiry = setTimeout(() => {
      hidePinkySim();
      status("pinky-sim-status", "unavailable", "Pinky SIM 사용 불가 · 최근 관측이 없습니다.");
    }, PINKY_SIM_FRESH_MS - age);
  }

  async function pollPinkySim(session) {
    const request = new AbortController();
    session.request = request;
    const deadline = setTimeout(() => request.abort(), 2500);
    try {
      const response = await fetch("./data/pinky-sim.json", {
        cache: "no-store", redirect: "error", signal: request.signal,
      });
      if (!response.ok) throw new Error("Pinky SIM snapshot unavailable");
      const sample = await response.json();
      const manifest = await manifestRead;
      if (simSession !== session) return;
      if (!validPinkySim(sample, manifest)) throw new Error("Invalid Pinky SIM snapshot");
      showPinkySim(session, sample);
    } catch {
      if (simSession !== session) return;
      clearTimeout(session.expiry);
      hidePinkySim();
      status("pinky-sim-status", "unavailable", "Pinky SIM 사용 불가 · 관측 파일을 읽을 수 없습니다.");
    } finally {
      clearTimeout(deadline);
      if (simSession === session) {
        const delay = byId("pinky-sim-status").getAttribute("state") === "unavailable" ? 2000 : 750;
        session.next = setTimeout(() => pollPinkySim(session), delay);
      }
    }
  }

  function startPinkySim() {
    if (document.hidden || simSession || getMode() !== "cad" || !getCadView() || byId("panel-map").hidden ||
        byId("pinky-sim-toggle").getAttribute("aria-pressed") !== "true") return;
    const session = {};
    simSession = session;
    status("pinky-sim-status", "pending", "Pinky SIM 관측을 확인하는 중…");
    void pollPinkySim(session);
  }

  byId("pinky-sim-toggle").addEventListener("click", () => {
    const toggle = byId("pinky-sim-toggle");
    const enabled = toggle.getAttribute("aria-pressed") !== "true";
    toggle.setAttribute("aria-pressed", String(enabled));
    if (enabled) startPinkySim();
    else {
      stopPinkySim();
      status("pinky-sim-status", "empty", "Pinky SIM 위치 표시가 꺼져 있습니다 — 스위치로 다시 켤 수 있습니다.");
    }
  });

  function clearCameraFrame(session) {
    clearTimeout(session.expiry);
    const image = byId("pinky-camera-image");
    image.hidden = true;
    image.removeAttribute("src");
    if (session.url) URL.revokeObjectURL(session.url);
    session.url = undefined;
  }

  function stopPinkyCamera() {
    const session = cameraSession;
    cameraSession = undefined;
    if (!session) return;
    session.request?.abort();
    clearTimeout(session.next);
    clearCameraFrame(session);
  }

  // D-136: field camera uses Fleet /api/fleet/vision/sources + lease -> Vision frame bytes.
  const FLEET_VISION_SOURCES = "/api/fleet/vision/sources";
  const FLEET_VISION_LEASE = "/api/fleet/vision/lease";
  const FLEET_LEASE_MARGIN_MS = 15000;
  const FLEET_SOURCES_TTL_MS = 30000;

  function pickCeilingSource(sources) {
    const ids = (Array.isArray(sources) ? sources : []).flatMap((e) => {
      const id = typeof e === "string" ? e : (typeof e?.source_id === "string" ? e.source_id : (typeof e?.id === "string" ? e.id : null));
      return id && id.trim() && e?.enabled !== false ? [id] : [];
    });
    return ids.find((id) => /(^|[_-])(ceiling|top)/.test(id)) || ids[0] || null;
  }

  function haltFieldFeed(session, message) {
    if (cameraSession !== session) return {};
    session.halted = true;
    clearCameraFrame(session);
    status("pinky-camera-status", "unavailable", message);
    return {};
  }

  function haltStatus(session, code) {
    return code === 401 || code === 403 ? `${session.label} · 로그인 필요` : code === 503 ? `${session.label} · 카메라 미리보기 비활성` : null;
  }

  async function issueFieldLease(session, sourceId, signal) {
    const res = await fetch(FLEET_VISION_LEASE, {
      method: "POST", cache: "no-store", redirect: "error", signal,
      headers: { "Content-Type": "application/json" }, body: JSON.stringify({ source_id: sourceId }),
    });
    const haltMsg = haltStatus(session, res.status);
    if (haltMsg) return haltFieldFeed(session, haltMsg);
    if (!res.ok) throw new Error("Vision lease unavailable");
    const issued = await res.json();
    const framePath = typeof issued?.frame_path === "string" ? issued.frame_path.trim() : "";
    if (!framePath || typeof issued?.lease !== "string" || !issued.lease) throw new Error("Invalid vision lease");
    const path = new URL(framePath, location.origin);
    if (path.origin !== location.origin || path.username || path.password) throw new Error("Vision frame path is not same-origin");
    const life = Number(issued.expires_in_s);
    return { source: sourceId, token: issued.lease, path, expiresAt: Date.now() + Math.max(1, Number.isFinite(life) && life > 0 ? life : 60) * 1000 };
  }

  async function fetchFieldFleetFrame(session, signal) {
    if (!session.sourcesAt || Date.now() - session.sourcesAt > FLEET_SOURCES_TTL_MS) {
      const res = await fetch(FLEET_VISION_SOURCES, { cache: "no-store", redirect: "error", signal });
      if (cameraSession !== session) return {};
      if (res.status === 404) return { local: true };
      const haltMsg = haltStatus(session, res.status);
      if (haltMsg) return haltFieldFeed(session, haltMsg);
      if (!res.ok) throw new Error("Vision sources unavailable");
      const listing = await res.json();
      if (cameraSession !== session) return {};
      session.sources = Array.isArray(listing?.sources) ? listing.sources : [];
      session.sourcesAt = Date.now();
    }
    const sourceId = pickCeilingSource(session.sources);
    if (!sourceId) { if (cameraSession === session) status("pinky-camera-status", "unavailable", `${session.label} · 연결된 카메라 없음`); return {}; }
    if (!session.lease || session.lease.source !== sourceId || Date.now() >= session.lease.expiresAt - FLEET_LEASE_MARGIN_MS) {
      const leased = await issueFieldLease(session, sourceId, signal);
      if (cameraSession !== session || session.halted) return {};
      session.lease = leased;
    }
    const res = await fetch(session.lease.path, {
      cache: "no-store", redirect: "error", credentials: "omit", signal,
      headers: { Authorization: `Bearer ${session.lease.token}` },
    });
    if (cameraSession !== session) return {};
    if (res.status === 503) return haltFieldFeed(session, `${session.label} · 카메라 미리보기 비활성`);
    if (res.status === 401 || res.status === 403) { session.lease = undefined; clearCameraFrame(session); status("pinky-camera-status", "unavailable", `${session.label} · 영상 권한 없음`); return {}; }
    if (!res.ok) throw new Error("Vision frame unavailable");
    if (!(res.headers.get("Content-Type")?.split(";")[0] ?? "").startsWith("image/")) throw new Error("Vision frame is not an image");
    const age = Number(res.headers.get("X-Frame-Age-Ms"));
    return { frame: await res.blob(), ageMs: Number.isFinite(age) && age >= 0 ? age : 0 };
  }
  async function pollPinkyCamera(session) {
    const request = new AbortController();
    session.request = request;
    const deadline = setTimeout(() => request.abort(), 2500);
    let nextUrl;
    try {
      let frame;
      let metadata = null;
      let age = 0;
      if (session.fleet && !session.local) {
        const fleet = await fetchFieldFleetFrame(session, request.signal);
        if (cameraSession !== session || session.halted) return;
        if (fleet.local) session.local = true;  // 404: standalone bundle, read the local file from now on.
        else if (fleet.frame) {
          frame = fleet.frame;
          age = fleet.ageMs;
        } else return;  // honest status already shown; keep the slow retry.
      }
      if (!frame) {
        const response = await fetch(`./data/${session.file}`, {
          cache: "no-store", redirect: "error", signal: request.signal,
        });
        const modifiedAt = Date.parse(response.headers.get("Last-Modified"));
        const serverAt = Date.parse(response.headers.get("Date"));
        const type = response.headers.get("Content-Type")?.split(";")[0];
        if (!response.ok || type !== (session.telemetry ? "application/json" : "image/jpeg")) {
          throw new Error("Camera source unavailable");
        }
        metadata = session.telemetry ? await response.json() : null;
        age = (Number.isFinite(serverAt) ? serverAt : Date.now())
          - (metadata ? metadata.observed_at_ms : modifiedAt);
        if (session.telemetry) {
          if (metadata?.schema !== "rosy.world.isaac-view.v1" || !/^sim-[a-z0-9-]{1,80}$/.test(metadata.run_id)
              || !isLayoutSha(metadata.stage_sha256) || !Number.isSafeInteger(metadata.observed_at_ms)
              || !Number.isFinite(metadata.sim_time_s) || metadata.sim_time_s <= 0
              || !Number.isSafeInteger(metadata.sequence) || metadata.sequence < 1
              || !vector(metadata.cargo_xyz_m, 3) || !["scene", "belt"].includes(metadata.scenario)
              || typeof metadata.jpeg !== "string" || metadata.jpeg.length > 682672) {
            throw new Error("Invalid Isaac frame envelope");
          }
          const previous = session.latest;
          if (previous?.run_id === metadata.run_id && (metadata.sequence <= previous.sequence
              || metadata.sim_time_s <= previous.sim_time_s)) return;
          frame = new Blob([Uint8Array.from(atob(metadata.jpeg), (char) => char.charCodeAt(0))], { type: "image/jpeg" });
        } else frame = await response.blob();
      }
      const freshMs = session.freshMs ?? CAMERA_FRESH_MS;
      const remaining = performance.now() + freshMs - age;
      if (!Number.isFinite(age) || age < -1000 || age >= freshMs) {
        throw new Error("No recent camera frame");
      }
      if (cameraSession !== session) return;
      if (frame.size < 4 || frame.size > 512000) throw new Error("Invalid camera frame");
      nextUrl = URL.createObjectURL(frame);
      const decoded = new Image();
      decoded.src = nextUrl;
      await decoded.decode();
      if (cameraSession !== session) return;
      if (performance.now() >= remaining) throw new Error("Camera frame expired in transit");
      clearTimeout(session.expiry);
      const image = byId("pinky-camera-image");
      const previousUrl = session.url;
      image.src = nextUrl;
      session.url = nextUrl;
      nextUrl = undefined;
      image.hidden = false;
      session.latest = metadata;
      if (previousUrl) URL.revokeObjectURL(previousUrl);
      session.expiry = setTimeout(() => {
        status("pinky-camera-status", "warning", `${session.label} · 수신 지연, 마지막 프레임`);
      }, remaining - performance.now());
      status("pinky-camera-status", "ready", metadata
        ? `Isaac Sim · 실시간 ${metadata.sim_time_s.toFixed(2)}초 · ${metadata.run_id} · ${metadata.scenario === "belt" ? "벨트 시험" : "장면 실행"}`
        : `${session.label} · 영상 수신 중`);
    } catch {
      if (cameraSession !== session) return;
      if (!session.url) {
        status("pinky-camera-status", "unavailable", `${session.label} · 최근 영상 없음`);
      }
    } finally {
      if (nextUrl) URL.revokeObjectURL(nextUrl);
      clearTimeout(deadline);
      if (cameraSession === session && !session.halted) {
        const delay = byId("pinky-camera-status").getAttribute("state") === "unavailable" ? 2000 : 400;
        session.next = setTimeout(() => pollPinkyCamera(session), delay);
      }
    }
  }

  function startPinkyCamera() {
    if (document.hidden || cameraSession || byId("panel-map").hidden || byId("pinky-camera-panel").hidden) return;
    const session = { ...CAMERA_SOURCES[cameraSource] };
    cameraSession = session;
    byId("pinky-camera-image").alt = `${session.label} 영상`;
    status("pinky-camera-status", "pending", `${session.label} · 연결 중…`);
    void pollPinkyCamera(session);
  }

  for (const source of Object.keys(CAMERA_SOURCES)) {
    byId(`camera-source-${source}`).addEventListener("click", () => {
      if (source === cameraSource) return;
      stopPinkyCamera();
      cameraSource = source;
      byId("camera-figure").dataset.source = source;
      for (const item of Object.keys(CAMERA_SOURCES)) {
        byId(`camera-source-${item}`).setAttribute("aria-pressed", String(item === source));
      }
      startPinkyCamera();
    });
  }
  manifestRead.then((manifest) => {
    if ((manifest?.field_original || manifest?.field_photo) && byId("pinky-camera-panel").hidden && cameraSource === "gazebo") {
      byId("camera-source-field").click();
    }
  }).catch(() => {});

  byId("pinky-camera-toggle").addEventListener("click", () => {
    const panel = byId("pinky-camera-panel");
    panel.hidden = !panel.hidden;
    byId("pinky-camera-toggle").setAttribute("aria-pressed", String(!panel.hidden));
    if (panel.hidden) stopPinkyCamera();
    else startPinkyCamera();
  });
  if (new URLSearchParams(location.search).get("view") === "isaac") {
    byId("panel-map").prepend(byId("pinky-camera-panel"));
    byId("camera-source-isaac").click();
    byId("pinky-camera-toggle").click();
  }
  if (new URLSearchParams(location.search).get("view") === "play") {
    byId("world-play").after(byId("pinky-camera-panel"));
    byId("camera-source-gazebo").click();
    byId("pinky-camera-toggle").click();
    initPlay();
  }

  document.addEventListener("visibilitychange", () => {
    if (document.hidden && isaacSession) stopIsaacStatus();
    else startIsaacStatus();
    if (document.hidden) stopPinkySim();
    else startPinkySim();
    if (document.hidden) stopPinkyCamera();
    else startPinkyCamera();
    const factoryTab = getFactoryTab();
    if (document.hidden) factoryTab?.deactivate();
    else if (byId("tab-factory").getAttribute("aria-selected") === "true") void factoryTab?.activate();
  });
  startIsaacStatus();

  function recordFallback(message) {
    status("rec-status", "unavailable", message);
    byId("rec-fallback").hidden = false;
    byId("rec-player").hidden = true;
  }

  async function loadRecording() {
    let recording;
    try {
      recording = recordingData(await readJson("recording"));
    } catch {
      return recordFallback("재생할 보관 기록이 없습니다.");
    }
    const { samples, source, captured_at, map_version } = recording;
    readout("rec-readout", [
      ["출처", source], ["기록 시각 (UTC)", date(captured_at)], ["기록 지도 버전", map_version],
    ]);
    let map;
    try {
      const manifest = await manifestRead;
      map = manifest?.recording_map?.bundle_path === "data/recording-map.json"
        ? mapData(await readJson("recording-map")) : await mapPromise;
    } catch {
      return recordFallback("기록에 연결된 지도를 열 수 없습니다.");
    }
    if (!map || map.version !== map_version || !samples.some(({ frame_id }) => frame_id === map.id)) {
      return recordFallback("보관 지도와 지도 ID 및 버전이 일치하는 기록이 없습니다.");
    }
    const duration = samples.at(-1).offset_ms;
    const range = byId("rec-range");
    const play = byId("rec-play");
    let draw;
    let tick;
    let offset = 0;
    let lastSample;
    const stop = () => {
      cancelAnimationFrame(tick);
      tick = undefined;
      play.setAttribute("aria-pressed", "false");
      play.textContent = "재생";
    };
    const unavailable = () => {
      stop();
      recordFallback("기록 위치를 그릴 수 없어 보관 자료를 표시합니다.");
    };
    try {
      draw = await showMap(byId("rec-canvas"), map, unavailable);
    } catch {
      return unavailable();
    }
    function render(value) {
      offset = value;
      const seconds = (ms) => (ms / 1000).toFixed(2);
      range.value = String(value);
      range.setAttribute("aria-valuetext", `${seconds(value)}초`);
      byId("rec-clock").textContent = `${seconds(value)} / ${seconds(duration)}초`;
      let begin = 0;
      let end = samples.length;
      while (begin < end) {
        const midpoint = Math.floor((begin + end) / 2);
        if (samples[midpoint].offset_ms <= value) begin = midpoint + 1;
        else end = midpoint;
      }
      const sample = samples[begin - 1];
      if (sample === lastSample && value !== 0) return;
      lastSample = sample;
      const positions = sample?.frame_id === map.id ? sample.positions : [];
      draw(positions);
      byId("rec-frame-note").textContent = positions.length
        ? [sample.note, ...positions.map(({ id, x_m, y_m }) => `${id} (${x_m.toFixed(3)}, ${y_m.toFixed(3)}) m`)]
          .filter(text).join(" · ")
        : sample && sample.frame_id !== map.id ? "이 시점의 지도 좌표계가 다릅니다." : "이 시점에 표시할 위치가 없습니다.";
    }
    range.max = String(duration);
    play.hidden = range.parentElement.hidden = duration === 0;
    range.addEventListener("input", () => {
      stop();
      render(Number(range.value));
    });
    play.addEventListener("click", () => {
      if (tick !== undefined) return stop();
      const start = performance.now() - (offset >= duration ? 0 : offset);
      play.setAttribute("aria-pressed", "true");
      play.textContent = "일시 정지";
      function advance(now) {
        const elapsed = Math.min(duration, Math.max(0, now - start));
        render(elapsed);
        if (elapsed < duration) tick = requestAnimationFrame(advance);
        else stop();
      }
      tick = requestAnimationFrame(advance);
    });
    document.addEventListener("visibilitychange", () => { if (document.hidden) stop(); });
    const panel = byId("panel-rec");
    new MutationObserver(() => { if (panel.hidden) stop(); }).observe(panel, {
      attributes: true, attributeFilter: ["hidden"],
    });
    render(0);
    status("rec-status", "ready", recording.kind === "simulation" ? "시뮬레이션 실행 재생" : "보관 위치 기록");
    byId("rec-player").hidden = false;
    if (directRun && !panel.hidden && duration > 0) play.click();
  }

  void loadRecording();
  return { startPinkySim, stopPinkySim, startPinkyCamera, stopPinkyCamera };
}
