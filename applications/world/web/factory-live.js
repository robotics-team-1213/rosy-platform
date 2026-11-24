import { createCorrugatedContainerMaterial } from "./studio-look.js";
import { loadBinaryStl, loadOmxArmMeshes, createArticulatedOmxArm } from "./omx-arm.js";
import { createWorldMonitor } from "./world-monitor.js";

const SIM_NAMES = { real: "Real 현장", gazebo: "Gazebo", isaac: "Isaac Sim", mujoco: "MuJoCo" };
const STAGES = [
  ["c2_departure", "1. C2 출발", 0.0, "factory_all"],
  ["s1_yield", "2. S1 양보", 5.0, "factory_all"],
  ["s3_stop", "3. S3 정차", 11.0, "factory_s3"],
  ["cell_claim", "4. 셀 점유", 14.0, "factory_s3"],
  ["arm_s_to_belt", "5. 암 S→벨트", 15.5, "factory_s3"],
  ["belt_transit", "6. 벨트 이송", 20.5, "factory_omx"],
  ["ab_stack", "7. A/B 적재", 25.5, "factory_omx"],
  ["ab_rehandle", "8. A↔B 임시대 정리", 36.0, "factory_omx"],
  ["outbound_dispatch", "9. 반출대 접안·출발", 45.0, "factory_outbound"],
];
const STAGE_LABELS = Object.fromEntries(STAGES.map(([id, label]) => [id, label]));
const STAGE_DEFAULTS = Object.fromEntries(STAGES.map(([id, , start, cam]) => [id, { start, cam }]));
const CONTAINER_PALETTE = [0xd96b27, 0x2b6cb0, 0x2f855a, 0xc53030, 0xd69e2e, 0x2c7a7b];
const DEFAULT_ARM_SPECS = {
  arm_s: { pose_m: [0.975, -0.004, 0.072], yaw_rad: Math.PI, accent: 0x58a6ff },
  arm_a: { pose_m: [0.62625, 0.278, 0.084], yaw_rad: 0.0, accent: 0xe796f3 },
  arm_b: { pose_m: [0.96275, 0.278, 0.084], yaw_rad: Math.PI, accent: 0x3dd68c },
};
const DEFAULT_PINKYS = [
  { id: "rosy_42", pose_m: [-0.414, 0.47, 0.0], yaw_rad: -Math.PI / 2 },
  { id: "rosy_45", pose_m: [-0.19, 0.47, 0.0], yaw_rad: -Math.PI / 2 },
  { id: "rosy_46", pose_m: [0.032, 0.47, 0.0], yaw_rad: -Math.PI / 2 },
];
const ROUTE_WAYPOINTS = [
  [-0.19, 0.47], [-0.19, 0.022], [-0.414, 0.022], [-0.687, -0.126],
  [-0.687, -0.246], [0.91, -0.476], [1.041, -0.361], [0.926, -0.246], [0.69, -0.246],
];

const byId = (id) => document.getElementById(id);
const lerp = (a, b, u) => a + (b - a) * u;
const lerpVec = (a, b, u) => a.map((v, idx) => lerp(v, b[idx] ?? v, u));
function lerpYaw(a, b, u) {
  let d = (b - a) % (Math.PI * 2);
  if (d > Math.PI) d -= Math.PI * 2;
  if (d < -Math.PI) d += Math.PI * 2;
  return a + d * u;
}

function createRearTrayGroup(three) {
  // Sculpted J-v3 low-lip rear cargo tray mounted at x_local = -0.095 m, deck z = 0.044 m.
  const group = new three.Group();
  const mat = new three.MeshStandardMaterial({ color: 0x262d38, roughness: 0.48, metalness: 0.34 });
  const deck = new three.Mesh(new three.BoxGeometry(0.042, 0.098, 0.004), mat);
  deck.position.set(-0.095, 0.0, 0.042);
  const back = new three.Mesh(new three.BoxGeometry(0.005, 0.092, 0.044), mat);
  back.position.set(-0.075, 0.0, 0.062);
  for (const sy of [-0.0475, 0.0475]) {
    const lip = new three.Mesh(new three.BoxGeometry(0.042, 0.003, 0.007), mat);
    lip.position.set(-0.095, sy, 0.0465);
    lip.castShadow = lip.receiveShadow = true;
    group.add(lip);
  }
  deck.castShadow = deck.receiveShadow = true;
  back.castShadow = back.receiveShadow = true;
  group.add(deck, back);
  return group;
}

function createPinkyActor(three, id, extractedPinky, addLabel, trayGeometry) {
  const group = new three.Group();
  if (extractedPinky) {
    group.add(extractedPinky.clone(true));
  } else {
    const body = new three.Mesh(
      new three.BoxGeometry(0.11, 0.095, 0.055),
      new three.MeshStandardMaterial({ color: 0x226899, roughness: 0.38, metalness: 0.25 }),
    );
    body.position.z = 0.042;
    body.castShadow = body.receiveShadow = true;
    group.add(body);
  }
  if (trayGeometry) {
    const trayMat = new three.MeshStandardMaterial({ color: 0xe2e8f0, roughness: 0.45, metalness: 0.12 });
    const trayMesh = new three.Mesh(trayGeometry, trayMat);
    trayMesh.castShadow = trayMesh.receiveShadow = true;
    group.add(trayMesh);
  } else {
    group.add(createRearTrayGroup(three));
  }
  const haloMat = new three.MeshBasicMaterial({ color: 0x58a6ff, transparent: true, opacity: 0.45, side: three.DoubleSide });
  const halo = new three.Mesh(new three.RingGeometry(0.052, 0.068, 28), haloMat);
  halo.position.z = 0.003;
  const ledMat = new three.MeshBasicMaterial({ color: 0xfff6d6 });
  const tailMat = new three.MeshBasicMaterial({ color: 0xff4455 });
  for (const sy of [-0.024, 0.024]) {
    const led = new three.Mesh(new three.BoxGeometry(0.008, 0.012, 0.006), ledMat);
    led.position.set(0.044, sy, 0.036);
    const tail = new three.Mesh(new three.BoxGeometry(0.006, 0.011, 0.006), tailMat);
    tail.position.set(-0.048, sy, 0.036);
    group.add(led, tail);
  }
  group.add(halo);
  const label = addLabel?.(group, id, new three.Vector3(0, 0, 0.17));
  return { group, haloMat, label };
}

function createFactoryLayer({ three, scene, redraw, addLabel, extractedPinky, armMeshes, trayGeometry, armBases }) {
  const root = new three.Group();
  root.visible = false;

  // S3 precision docking brackets (±4.0 cm x ±2.5 cm).
  const s3Group = new three.Group();
  s3Group.position.set(0.745, -0.207, 0.004);
  const s3PadMat = new three.MeshBasicMaterial({ color: 0x3dd68c, transparent: true, opacity: 0.16, side: three.DoubleSide });
  s3Group.add(new three.Mesh(new three.PlaneGeometry(0.08, 0.05), s3PadMat));
  const s3LineMat = new three.LineBasicMaterial({ color: 0x3dd68c });
  const hw = 0.04, hl = 0.025, leg = 0.014;
  for (const [sx, sy] of [[-1, -1], [1, -1], [1, 1], [-1, 1]]) {
    const pts = [
      new three.Vector3(sx * hw, sy * (hl - leg), 0.001),
      new three.Vector3(sx * hw, sy * hl, 0.001),
      new three.Vector3(sx * (hw - leg), sy * hl, 0.001),
    ];
    s3Group.add(new three.Line(new three.BufferGeometry().setFromPoints(pts), s3LineMat));
  }
  root.add(s3Group);

  const routeLine = new three.Line(
    new three.BufferGeometry().setFromPoints(ROUTE_WAYPOINTS.map(([x, y]) => new three.Vector3(x, y, 0.004))),
    new three.LineBasicMaterial({ color: 0x58a6ff, transparent: true, opacity: 0.35 }),
  );
  root.add(routeLine);

  // 3 ROSY Fleet Pinky Pro AMRs with J-v3 rear cargo trays.
  const pinkys = new Map();
  for (const def of DEFAULT_PINKYS) {
    const actor = createPinkyActor(three, def.id, extractedPinky, addLabel, trayGeometry);
    actor.group.position.set(...def.pose_m);
    actor.group.rotation.z = def.yaw_rad;
    pinkys.set(def.id, actor);
    root.add(actor.group);
  }

  // 3 articulated 6-DOF ROSY Fleet OMX-AI arms (arm_s, arm_a, arm_b).
  const arms = new Map();
  if (armMeshes) {
    for (const [key, spec] of Object.entries(DEFAULT_ARM_SPECS)) {
      const override = armBases?.[key];
      const baseSite = Array.isArray(override?.pose_m) && override.pose_m.length === 3 ? override.pose_m : spec.pose_m;
      const baseYaw = Number.isFinite(override?.yaw_rad) ? override.yaw_rad : spec.yaw_rad;
      const arm = createArticulatedOmxArm(three, armMeshes, {
        name: key, baseSite, baseYaw, accentHex: spec.accent, addLabel,
      });
      arms.set(key, arm);
      root.add(arm.root);
    }
  }

  // Shared corrugated materials by color index so each container keeps its identity end-to-end.
  const cargoMats = CONTAINER_PALETTE.map((hex) => createCorrugatedContainerMaterial(three, hex));
  const cargoGeom = new three.BoxGeometry(0.09, 0.03, 0.0324);
  const activeCargo = new three.Mesh(cargoGeom, cargoMats[0]);
  activeCargo.castShadow = activeCargo.receiveShadow = true;
  root.add(activeCargo);
  const secondaryCargo = new three.Mesh(cargoGeom, cargoMats[1]);
  secondaryCargo.castShadow = secondaryCargo.receiveShadow = true;
  secondaryCargo.visible = false;
  root.add(secondaryCargo);

  const stackPool = Array.from({ length: 27 }, (_, i) => {
    const mesh = new three.Mesh(cargoGeom, cargoMats[i % cargoMats.length]);
    mesh.castShadow = mesh.receiveShadow = true;
    mesh.visible = false;
    root.add(mesh);
    return mesh;
  });

  scene.add(root);

  function setFocusLabels(focusKey) {
    const closeOmx = focusKey === "factory_omx";
    const outOnly = focusKey === "factory_outbound";
    for (const [id, actor] of pinkys.entries()) {
      if (!actor.label) continue;
      actor.label.visible = closeOmx ? false : outOnly ? id === "rosy_46" : true;
    }
  }

  function apply(state, nowMs = performance.now(), immediate = false) {
    const flush = () => (immediate ? redraw() : requestAnimationFrame(redraw));
    if (!state) {
      root.visible = false;
      flush();
      return;
    }
    root.visible = true;
    if (state.s3_box?.center) {
      s3Group.position.set(state.s3_box.center[0], state.s3_box.center[1], 0.004);
      s3Group.rotation.z = state.s3_box.yaw_rad ?? Math.PI;
    }
    const dockColor = state.pinky?.s3_in_bounds ? 0x3dd68c : 0x58a6ff;
    s3PadMat.color.setHex(dockColor);
    s3LineMat.color.setHex(dockColor);

    const pulse = 0.42 + 0.22 * Math.sin(nowMs * 0.006);
    const list = Array.isArray(state.pinkys) && state.pinkys.length ? state.pinkys : (
      state.pinky?.pose_m ? [{ id: state.pinky.id ?? "rosy_45", ...state.pinky }] : []
    );
    for (const p of list) {
      const actor = pinkys.get(p.id);
      if (!actor || !p?.pose_m) continue;
      actor.group.position.set(p.pose_m[0], p.pose_m[1], Math.max(p.pose_m[2], 0.002));
      actor.group.rotation.z = p.yaw_rad ?? 0;
      const color = p.s3_in_bounds ? 0x3dd68c : p.has_cargo ? 0xd96b27 : 0x58a6ff;
      actor.haloMat.color.setHex(color);
      actor.haloMat.opacity = p.s3_in_bounds || p.has_cargo ? pulse : 0.28;
    }

    if (state.arms) {
      for (const [key, q] of Object.entries(state.arms)) {
        arms.get(key)?.setJoints(q);
      }
    }

    const c = state.cargo;
    const stacked = state.cell_ab?.stacked ?? [];
    if (c?.pose_m && (c.zone !== "ship" || stacked.length === 0)) {
      const zLift = c.zone === "belt" ? 0.008 : 0.0;
      const cidx = Number.isInteger(c.color_idx) ? c.color_idx : 0;
      activeCargo.material = cargoMats[((cidx % cargoMats.length) + cargoMats.length) % cargoMats.length];
      activeCargo.visible = true;
      activeCargo.position.set(c.pose_m[0], c.pose_m[1], c.pose_m[2] + zLift);
      activeCargo.rotation.z = c.yaw_rad ?? 0;
      const dualItem = Array.isArray(c.items) && c.items.length > 1 && c.items[1]?.pose_m ? c.items[1] : null;
      const secPose = dualItem ? dualItem.pose_m : c.secondary_pose_m;
      if (Array.isArray(secPose) && secPose.length === 3) {
        const sidx = Number.isInteger(dualItem?.color_idx) ? dualItem.color_idx : (cidx + 1);
        secondaryCargo.material = cargoMats[((sidx % cargoMats.length) + cargoMats.length) % cargoMats.length];
        secondaryCargo.visible = true;
        secondaryCargo.position.set(secPose[0], secPose[1], secPose[2] + zLift);
        secondaryCargo.rotation.z = dualItem?.yaw_rad ?? c.yaw_rad ?? 0;
      } else {
        secondaryCargo.visible = false;
      }
    } else {
      activeCargo.visible = false;
      secondaryCargo.visible = false;
    }

    for (let i = 0; i < stackPool.length; i += 1) {
      const slot = stacked[i];
      const mesh = stackPool[i];
      if (slot?.pose_m) {
        const cidx = Number.isInteger(slot.color_idx) ? slot.color_idx : i;
        mesh.material = cargoMats[((cidx % cargoMats.length) + cargoMats.length) % cargoMats.length];
        mesh.visible = true;
        mesh.position.set(slot.pose_m[0], slot.pose_m[1], slot.pose_m[2]);
        mesh.rotation.z = slot.yaw_rad ?? 0;
      } else {
        mesh.visible = false;
      }
    }
    flush();
  }

  return {
    apply,
    setFocusLabels,
    destroy() { root.visible = false; requestAnimationFrame(redraw); },
  };
}

function interpolateArms(aArms, bArms, u) {
  if (!aArms) return undefined;
  const out = {};
  for (const [k, qa] of Object.entries(aArms)) {
    const qb = bArms?.[k];
    out[k] = Array.isArray(qb) && qb.length === qa.length ? lerpVec(qa, qb, u) : qa;
  }
  return out;
}

function interpolatePinkys(aList, bList, u) {
  if (!Array.isArray(aList)) return undefined;
  const bMap = new Map(Array.isArray(bList) ? bList.map((p) => [p.id, p]) : []);
  return aList.map((pa) => {
    const pb = bMap.get(pa.id);
    if (!pb?.pose_m || !pa.pose_m) return pa;
    return {
      ...pa,
      pose_m: lerpVec(pa.pose_m, pb.pose_m, u),
      yaw_rad: lerpYaw(pa.yaw_rad, pb.yaw_rad, u),
    };
  });
}

function sampleLocalTimeline(timeline, elapsedS) {
  const frames = timeline.keyframes;
  const duration = timeline.duration_s || 1;
  const t = ((elapsedS % duration) + duration) % duration;
  let lo = 0, hi = frames.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (frames[mid].time_s <= t) lo = mid + 1;
    else hi = mid;
  }
  const idx = Math.max(0, lo - 1);
  const nxt = Math.min(idx + 1, frames.length - 1);
  const a = frames[idx], b = frames[nxt];
  const span = b.time_s - a.time_s;
  const u = span <= 1e-6 || a.stage !== b.stage ? 0 : Math.max(0, Math.min(1, (t - a.time_s) / span));
  return {
    stream_mode: "verified_replay",
    run_id: timeline.run_id,
    sim_time_s: t,
    duration_s: duration,
    stage: a.stage,
    simulator: a.simulator,
    phase: a.phase,
    s3_box: timeline.s3_box,
    stages: timeline.stages,
    pinky: {
      id: a.pinky.id ?? "rosy_45",
      pose_m: lerpVec(a.pinky.pose_m, b.pinky.pose_m, u),
      yaw_rad: lerpYaw(a.pinky.yaw_rad, b.pinky.yaw_rad, u),
      has_cargo: a.pinky.has_cargo,
      s3_in_bounds: a.pinky.s3_in_bounds,
    },
    pinkys: interpolatePinkys(a.pinkys, b.pinkys, u),
    arms: interpolateArms(a.arms, b.arms, u),
    cargo: {
      zone: a.cargo.zone,
      pose_m: lerpVec(a.cargo.pose_m, b.cargo.pose_m, u),
      yaw_rad: lerpYaw(a.cargo.yaw_rad ?? 0, b.cargo.yaw_rad ?? 0, u),
      color_idx: a.cargo.color_idx ?? 0,
    },
    arm_s_ee_m: a.arm_s_ee_m && b.arm_s_ee_m ? lerpVec(a.arm_s_ee_m, b.arm_s_ee_m, u) : a.arm_s_ee_m,
    cell_ab: a.cell_ab,
  };
}

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
