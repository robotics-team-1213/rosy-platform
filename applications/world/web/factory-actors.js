import { createCorrugatedContainerMaterial } from "./studio-look.js";
import { createArticulatedOmxArm } from "./omx-arm.js";

export const SIM_NAMES = { real: "Real 현장", gazebo: "Gazebo", isaac: "Isaac Sim", mujoco: "MuJoCo" };
export const STAGES = [
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
export const STAGE_LABELS = Object.fromEntries(STAGES.map(([id, label]) => [id, label]));
export const STAGE_DEFAULTS = Object.fromEntries(STAGES.map(([id, , start, cam]) => [id, { start, cam }]));
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

export const lerp = (a, b, u) => a + (b - a) * u;
export const lerpVec = (a, b, u) => a.map((v, idx) => lerp(v, b[idx] ?? v, u));
export function lerpYaw(a, b, u) {
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
  return { group, halo, haloMat, label, ghost: ghostActor(group, 0.30, halo) };
}

function ghostActor(group, opacity, excluded) {
  const meshes = [];
  const ghosts = new Map();
  function ghostMaterial(material) {
    if (!ghosts.has(material)) {
      const ghost = material.clone();
      Object.assign(ghost, { opacity, transparent: true, depthWrite: false });
      ghosts.set(material, ghost);
    }
    return ghosts.get(material);
  }
  group.traverse((mesh) => {
    if (mesh.isMesh && mesh !== excluded) meshes.push([mesh, mesh.material, mesh.castShadow]);
  });
  let dimmed = false;
  return (dim) => {
    if (dimmed === dim) return;
    dimmed = dim;
    for (const [mesh, material, castShadow] of meshes) {
      mesh.material = !dim ? material : Array.isArray(material) ? material.map(ghostMaterial) : ghostMaterial(material);
      mesh.castShadow = !dim && castShadow;
    }
  };
}

export function createFactoryLayer({ three, scene, redraw, addLabel, extractedPinky, armMeshes, trayGeometry, armBases }) {
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
      arms.set(key, { ...arm, ghost: ghostActor(arm.root, 0.35) });
      root.add(arm.root);
    }
  }

  // Shared corrugated materials by color index so each container keeps its identity end-to-end.
  const cargoMats = CONTAINER_PALETTE.map((hex) => createCorrugatedContainerMaterial(three, hex));
  const cargoGeom = new three.BoxGeometry(0.09, 0.03, 0.0324);
  const activeCargo = new three.Mesh(cargoGeom, cargoMats[0]);
  activeCargo.name = "factory-active-cargo";
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
    const hasRoster = Array.isArray(state.pinkys) && state.pinkys.length > 0;
    const activePinkyIds = new Set(list.map((p) => p?.id).filter(Boolean));
    const c = state.cargo;
    const cargoVisible = Boolean(c?.pose_m && c.observed !== false && c.zone !== "unknown");
    for (const p of list) {
      let actor = p?.id ? pinkys.get(p.id) : undefined;
      if (!actor && p?.id && Array.isArray(p?.pose_m)) {
        actor = createPinkyActor(three, p.id, extractedPinky, addLabel, trayGeometry);
        pinkys.set(p.id, actor);
        root.add(actor.group);
      }
      if (!actor || !p?.pose_m) continue;
      actor.group.visible = true;
      actor.group.position.set(p.pose_m[0], p.pose_m[1], Math.max(p.pose_m[2], 0.002));
      actor.group.rotation.z = p.yaw_rad ?? 0;
      actor.ghost(p.observed === false);
      const hasObservedCargo = cargoVisible && c.observed === true && p.has_cargo;
      actor.halo.visible = p.observed !== false && (hasObservedCargo || p.s3_in_bounds || p.observed === undefined);
      const color = p.s3_in_bounds ? 0x3dd68c : hasObservedCargo ? 0xd96b27 : 0x58a6ff;
      actor.haloMat.color.setHex(color);
      actor.haloMat.opacity = p.s3_in_bounds || hasObservedCargo ? pulse : 0.28;
    }
    if (hasRoster) {
      for (const [id, actor] of pinkys) {
        if (!activePinkyIds.has(id)) actor.group.visible = false;
      }
    }

    for (const [key, arm] of arms) {
      arm.setJoints(state.arms?.[key]);
      arm.ghost(state.arms_observed?.[key] === false || state.arms_fresh?.[key] === false);
    }

    const stacked = state.cell_ab?.stacked ?? [];
    if (cargoVisible && (c.zone !== "ship" || stacked.length === 0)) {
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

export function interpolateArms(aArms, bArms, u) {
  if (!aArms) return undefined;
  const out = {};
  for (const [k, qa] of Object.entries(aArms)) {
    const qb = bArms?.[k];
    out[k] = Array.isArray(qb) && qb.length === qa.length ? lerpVec(qa, qb, u) : qa;
  }
  return out;
}

export function interpolatePinkys(aList, bList, u) {
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

export function sampleLocalTimeline(timeline, elapsedS) {
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
