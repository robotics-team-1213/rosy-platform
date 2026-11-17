// 3D Site Digital Twin (Three.js): live ceiling-camera floor texture + 3D CAD walls/lanes/pads + Pinky & OMX-F rigs.
import { readColour } from "./ui.js";
import {
  ELEV_MAX,
  finite,
  loadThree,
  loadRobotModel,
  siteBoundsCenter,
  rayPlaneIntersection,
  orbitEyePosition,
  twinPresetOrbit,
  inferBounds,
  buildUrdfGroup,
  rebuildFloorMesh,
  updateCameraFloorTexture,
  rebuildSiteGroupMesh,
  localizedMapPose,
  styleRig,
} from "./robot-3d-assets.js";
import { jointAngles, jointsFromList } from "./robot-3d-model.js";

export { siteBoundsCenter, rayPlaneIntersection, orbitEyePosition, twinPresetOrbit };

const OMX_JOINT_NAMES = Object.freeze(["joint1", "joint2", "joint3", "joint4", "joint5", "gripper_joint_1"]);
const CLICK_MAX_DRAG = 5;

function tokenRgb(token, fallback) {
  const rgba = readColour(token);
  if (!Array.isArray(rgba) || rgba.length < 4 || rgba[3] === 0) return fallback;
  return [rgba[0] / 255, rgba[1] / 255, rgba[2] / 255];
}

export function createSiteTwin3d({
  canvas,
  onSelectRobot = () => {},
  onSelectPlace = () => {},
  onSelectPoint = () => {},
  onSelect = null,
  onHover = null,
  onUnavailable = () => {},
} = {}) {
  let three = null;
  let renderer = null;
  let scene = null;
  let camera = null;
  let raycaster = null;
  let models = null;
  let disposed = false;
  let pending = 0;
  let presetName = "iso";
  let orbited = false;
  let currentTurnDeg = 0;
  let orbit = { az: -Math.PI * 0.35, el: 0.72, dist: 3.5, target: [0, 0, 0] };
  let latestState = {};
  let siteSignature = "";
  let currentBounds = { min_x: -1.5, max_x: 1.5, min_y: -0.75, max_y: 0.75 };

  const colors = {};
  const floorState = { mesh: null, mat: null, geom: null, texture: null, grid: null, seq: -1 };
  const siteGroupState = { group: null, disposables: [], placeRings: new Map() };
  const pinkyRigs = new Map();
  const omxRigs = new Map();
  const pickables = [];

  function readTokenColor(token, fallback) {
    const [r, g, b] = tokenRgb(token, fallback);
    return new three.Color().setRGB(r, g, b, three.SRGBColorSpace);
  }

  function refreshTokens() {
    if (!three) return;
    colors.ground = readTokenColor("--ground-deep", [0.06, 0.07, 0.08]);
    colors.floor = readTokenColor("--surface-canvas", [0.1, 0.11, 0.12]);
    colors.line = readTokenColor("--line-quiet", [0.32, 0.35, 0.4]);
    colors.wall = readTokenColor("--border-strong", [0.55, 0.58, 0.64]);
    colors.primary = readTokenColor("--series-primary", [0.35, 0.65, 1]);
    colors.goal = readTokenColor("--series-goal", [0.24, 0.84, 0.55]);
    colors.warn = readTokenColor("--status-warn", [1, 0.77, 0.24]);
    colors.body = readTokenColor("--ink-quiet", [0.7, 0.72, 0.76]);
    colors.selection = readTokenColor("--selection", [0.22, 0.52, 0.88]);
    renderer?.setClearColor(colors.ground, 1);
  }

  function draw() {
    pending = 0;
    if (disposed || !renderer || !scene || !camera) return;
    const eye = orbitEyePosition(orbit.target, orbit);
    camera.position.set(eye[0], eye[1], eye[2]);
    camera.lookAt(orbit.target[0], orbit.target[1], orbit.target[2]);
    renderer.render(scene, camera);
  }

  const redraw = () => {
    if (!pending && renderer && !disposed) pending = requestAnimationFrame(draw);
  };

  function clearSiteGroup() {
    if (siteGroupState.group && scene) scene.remove(siteGroupState.group);
    for (const item of siteGroupState.disposables) item.dispose?.();
    siteGroupState.disposables = [];
    siteGroupState.placeRings.clear();
    siteGroupState.group = null;
  }

  function rebuildPickables() {
    pickables.length = 0;
    siteGroupState.group?.traverse((obj) => {
      if (obj.isMesh && obj.userData?.entity) pickables.push(obj);
    });
    for (const rig of pinkyRigs.values()) if (rig.root.visible) pickables.push(...rig.pickMeshes);
    for (const rig of omxRigs.values()) if (rig.root.visible) pickables.push(...rig.pickMeshes);
  }

  function applyRobotStates(state) {
    if (!models || !scene) return;
    const focused = state.focusedRobotId || null;
    const stateRobotsById = new Map();
    for (const row of state.robots || []) {
      if (row?.robot_id) stateRobotsById.set(row.robot_id, row);
    }

    // Pinky mobile robots
    const activePinkys = new Set();
    const robotRows = [];
    for (const row of state.guide?.robots || []) {
      if (row?.robot_id && finite(row.pose?.x) && finite(row.pose?.y)) {
        const viewRow = stateRobotsById.get(row.robot_id);
        const offline = row.online === false || viewRow?.online === false;
        const degraded = Boolean(
          row.pose.state !== "LOCALIZED" || row.pose.source === "bridged"
          || row.stale || row.pose.stale || viewRow?.stale || state.guideStale,
        );
        activePinkys.add(row.robot_id);
        robotRows.push({ id: row.robot_id, pose: row.pose, offline, degraded });
      }
    }
    for (const row of state.robots || []) {
      if (!row?.robot_id || activePinkys.has(row.robot_id)) continue;
      const pose = (row.pose && (!row.pose.pose_frame || row.pose.pose_frame === "map"))
        ? row.pose : localizedMapPose(row);
      if (finite(pose?.x) && finite(pose?.y)) {
        const offline = row.online === false;
        const degraded = Boolean(
          row.stale || row.state?.evidence?.pose?.evidence === "delayed"
          || (pose.state && pose.state !== "LOCALIZED") || pose.source === "bridged",
        );
        activePinkys.add(row.robot_id);
        robotRows.push({ id: row.robot_id, pose, offline, degraded });
      }
    }
    for (const [id, rig] of pinkyRigs) if (!activePinkys.has(id)) rig.root.visible = false;
    for (const row of robotRows) {
      let rig = pinkyRigs.get(row.id);
      if (!rig) {
        rig = buildUrdfGroup(three, models.mobile, { kind: "pinky", id: row.id }, colors);
        scene.add(rig.root);
        pinkyRigs.set(row.id, rig);
      }
      rig.root.visible = true;
      rig.root.position.set(row.pose.x, row.pose.y, 0);
      rig.root.rotation.z = finite(row.pose.yaw) ? row.pose.yaw : 0;
      styleRig(rig, colors, focused === row.id, row);
    }

    // OMX-F articulated arms
    const anchors = Array.isArray(state.anchors) ? state.anchors : (Array.isArray(state.guide?.anchors) ? state.guide.anchors : []);
    const liveStates = state.chargeBaysPlan?.arm_live_states || {};
    const activeArms = new Set();
    for (const anc of anchors) {
      if (anc?.kind !== "omx_ai" || !finite(anc.base_x) || !finite(anc.base_y)) continue;
      const id = anc.target_id;
      activeArms.add(id);
      let rig = omxRigs.get(id);
      if (!rig) {
        rig = buildUrdfGroup(three, models.arm, { kind: "omx_ai", id }, colors);
        scene.add(rig.root);
        omxRigs.set(id, rig);
      }
      rig.root.visible = true;
      const live = liveStates?.[id];
      const degs = live?.joints_deg;
      const rads = Array.isArray(degs) ? degs.map((v) => (finite(v) ? (v * Math.PI) / 180 : undefined)) : [];
      const { angles } = jointAngles(models.arm.model, jointsFromList(rads, OMX_JOINT_NAMES));
      for (const [jName, joint] of rig.rotators) {
        joint.node.quaternion.setFromAxisAngle(new three.Vector3(...joint.axis).normalize(), angles[jName] ?? 0);
      }
      let baseYaw = finite(anc.base_yaw) ? anc.base_yaw : null;
      if (baseYaw === null && finite(anc.head_x) && finite(anc.head_y)) {
        const dx = anc.head_x - anc.base_x, dy = anc.head_y - anc.base_y;
        if (Math.hypot(dx, dy) > 1e-4) baseYaw = Math.atan2(dy, dx) - (angles.joint1 ?? 0);
      }
      rig.root.position.set(anc.base_x, anc.base_y, 0);
      rig.root.rotation.z = baseYaw ?? 0;
      const offline = Boolean((live && (live.online === false || live.available === false)) || anc.online === false);
      const degraded = Boolean(live?.stale === true || anc.stale === true);
      styleRig(rig, colors, focused === id, { offline, degraded });
    }
    for (const [id, rig] of omxRigs) if (!activeArms.has(id)) rig.root.visible = false;
  }

  function applyState(state = {}) {
    latestState = state || {};
    if (!renderer || disposed) return;
    const nextBounds = inferBounds(latestState);
    const nextTurn = [90, 180, 270].includes(latestState.turnDeg) ? latestState.turnDeg : 0;
    const turnChanged = nextTurn !== currentTurnDeg;
    currentTurnDeg = nextTurn;
    const sig = JSON.stringify([
      nextBounds.min_x, nextBounds.max_x, nextBounds.min_y, nextBounds.max_y,
      latestState.activeMap?.map_id || "",
      latestState.activeMap?.walls?.length || 0,
      latestState.activeMap?.edges?.length || 0,
      latestState.activeMap?.places?.length || 0,
      latestState.siteLanes?.paintTriangles?.length || 0,
    ]);
    if (sig !== siteSignature) {
      siteSignature = sig;
      currentBounds = nextBounds;
      rebuildFloorMesh(three, scene, floorState, colors, nextBounds);
      rebuildSiteGroupMesh(three, scene, siteGroupState, colors, latestState);
      if (!orbited) orbit = twinPresetOrbit(currentBounds, presetName, currentTurnDeg);
    } else if (turnChanged && !orbited) {
      orbit = twinPresetOrbit(currentBounds, presetName, currentTurnDeg);
    }
    updateCameraFloorTexture(three, floorState, colors, latestState.cameraCanvas);
    for (const [pid, ring] of siteGroupState.placeRings) {
      ring.visible = pid === latestState.selectedPlaceId
        || (latestState.hoveredEntity?.kind === "place" && String(latestState.hoveredEntity.id) === String(pid));
    }
    applyRobotStates(latestState);
    rebuildPickables();
    redraw();
  }

  function raycastPickables(clientX, clientY) {
    if (!renderer || !camera || !raycaster || !canvas) return null;
    const rect = canvas.getBoundingClientRect();
    if (!rect.width || !rect.height) return null;
    const ndc = new three.Vector2(
      ((clientX - rect.left) / rect.width) * 2 - 1,
      -((clientY - rect.top) / rect.height) * 2 + 1,
    );
    raycaster.setFromCamera(ndc, camera);
    const hits = raycaster.intersectObjects(pickables, false);
    return hits.find((item) => item.object?.userData?.entity)?.object.userData.entity || null;
  }

  function pickAt(clientX, clientY) {
    const entity = raycastPickables(clientX, clientY);
    if (entity) {
      if (entity.kind === "place") {
        onSelectPlace(entity.place);
        onSelect?.({ kind: "place", id: entity.id, place: entity.place });
      } else {
        onSelectRobot({ kind: entity.kind, id: entity.id });
        onSelect?.({ kind: entity.kind, id: entity.id });
      }
      return;
    }
    if (!raycaster) return;
    let pt = null;
    if (floorState.mesh) {
      const floorHits = raycaster.intersectObject(floorState.mesh, false);
      if (floorHits.length) pt = floorHits[0].point;
    }
    if (!pt) pt = rayPlaneIntersection(raycaster.ray.origin, raycaster.ray.direction, 0);
    if (pt && finite(pt.x) && finite(pt.y)) {
      const b = currentBounds;
      if (!b || (pt.x >= b.min_x && pt.x <= b.max_x && pt.y >= b.min_y && pt.y <= b.max_y)) {
        const pointEvt = { kind: "point", x: pt.x, y: pt.y };
        onSelectPoint(pointEvt);
        onSelect?.(pointEvt);
      }
    }
  }

  function resize() {
    if (!renderer || !camera || !canvas || disposed) return;
    const width = canvas.clientWidth;
    const height = canvas.clientHeight;
    if (!(width > 0 && height > 0)) return;
    renderer.setSize(width, height, false);
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
    redraw();
  }

  function setPreset(name) {
    presetName = name === "top" ? "top" : "iso";
    orbited = false;
    orbit = twinPresetOrbit(currentBounds, name === "reset" ? "reset" : presetName, currentTurnDeg);
    redraw();
  }

  const onTheme = () => {
    if (!renderer || disposed) return;
    window.RosyPalette?.clear?.();
    refreshTokens();
    siteSignature = "";
    applyState(latestState);
  };

  let drag = null;
  let lastHoverPos = null;
  let lastHoverAt = 0;
  let lastHovered = false;
  const onPointerDown = (e) => {
    if (!renderer || (e.button !== 0 && e.button !== 2)) return;
    drag = { x: e.clientX, y: e.clientY, moved: 0, button: e.button, shift: e.shiftKey };
    canvas?.setPointerCapture?.(e.pointerId);
  };
  const onPointerMove = (e) => {
    if (!renderer) return;
    if (!drag) {
      const dist = lastHoverPos ? Math.hypot(e.clientX - lastHoverPos.x, e.clientY - lastHoverPos.y) : Infinity;
      const now = typeof performance !== "undefined" ? performance.now() : Date.now();
      if (dist > 2 && now - lastHoverAt >= 32) {
        lastHoverPos = { x: e.clientX, y: e.clientY };
        lastHoverAt = now;
        const entity = raycastPickables(e.clientX, e.clientY);
        lastHovered = Boolean(entity);
        canvas?.classList?.toggle?.("clickable-entity", lastHovered);
        onHover?.(entity, e.clientX, e.clientY);
      }
      return;
    }
    const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
    drag.moved += Math.hypot(dx, dy);
    drag.x = e.clientX;
    drag.y = e.clientY;
    if (drag.button === 2 || drag.shift) {
      const panScale = orbit.dist * 0.0016;
      const rx = -Math.sin(orbit.az), ry = Math.cos(orbit.az);
      const fx = -Math.cos(orbit.az), fy = -Math.sin(orbit.az);
      orbit.target = [
        orbit.target[0] - rx * dx * panScale + fx * dy * panScale,
        orbit.target[1] - ry * dx * panScale + fy * dy * panScale,
        0,
      ];
    } else {
      orbit.az -= dx * 0.007;
      orbit.el = Math.max(0.08, Math.min(ELEV_MAX, orbit.el + dy * 0.007));
    }
    orbited = true;
    redraw();
  };
  const onPointerLeave = () => {
    lastHoverPos = null;
    if (lastHovered) {
      lastHovered = false;
      canvas?.classList?.toggle?.("clickable-entity", false);
    }
    onHover?.(null, 0, 0);
  };
  const onPointerUp = (e) => {
    if (!drag) return;
    const wasClick = drag.moved < CLICK_MAX_DRAG && drag.button === 0;
    drag = null;
    if (wasClick) pickAt(e.clientX, e.clientY);
  };
  const onPointerCancel = () => { drag = null; };
  const onWheel = (e) => {
    if (!renderer) return;
    e.preventDefault();
    const radius = Math.max(siteBoundsCenter(currentBounds)?.radius || 1, 0.5);
    const factor = e.deltaY > 0 ? 1.1 : 0.9;
    orbit.dist = Math.max(radius * 0.4, Math.min(radius * 6, orbit.dist * factor));
    orbited = true;
    redraw();
  };
  const onKeyDown = (e) => {
    if (!renderer || disposed || e.ctrlKey || e.metaKey || e.altKey) return;
    const radius = Math.max(siteBoundsCenter(currentBounds)?.radius || 1, 0.5);
    if (e.key === "ArrowLeft" || e.key === "ArrowRight" || e.key === "ArrowUp" || e.key === "ArrowDown") {
      e.preventDefault();
      if (e.shiftKey) {
        const panStep = orbit.dist * 0.08;
        const rx = -Math.sin(orbit.az), ry = Math.cos(orbit.az);
        const fx = -Math.cos(orbit.az), fy = -Math.sin(orbit.az);
        const sx = e.key === "ArrowLeft" ? -1 : e.key === "ArrowRight" ? 1 : 0;
        const sy = e.key === "ArrowUp" ? 1 : e.key === "ArrowDown" ? -1 : 0;
        orbit.target = [
          orbit.target[0] + (rx * sx + fx * sy) * panStep,
          orbit.target[1] + (ry * sx + fy * sy) * panStep,
          0,
        ];
      } else {
        const step = 0.12;
        if (e.key === "ArrowLeft") orbit.az += step;
        else if (e.key === "ArrowRight") orbit.az -= step;
        else if (e.key === "ArrowUp") orbit.el = Math.min(ELEV_MAX, orbit.el + step);
        else orbit.el = Math.max(0.08, orbit.el - step);
      }
      orbited = true;
      redraw();
    } else if (e.key === "+" || e.key === "=") {
      e.preventDefault();
      orbit.dist = Math.max(radius * 0.4, orbit.dist * 0.9);
      orbited = true;
      redraw();
    } else if (e.key === "-" || e.key === "_") {
      e.preventDefault();
      orbit.dist = Math.min(radius * 6, orbit.dist * 1.1);
      orbited = true;
      redraw();
    } else if (e.key === "Home" || e.key === "0") {
      e.preventDefault();
      setPreset("reset");
    }
  };
  const onContextMenu = (e) => e.preventDefault();
  const onContextLost = (e) => {
    e.preventDefault();
    onUnavailable(new Error("WebGL context lost"));
  };

  let resizeObs = null;
  let themeObs = null;
  const schemeQuery = typeof window !== "undefined" ? window.matchMedia?.("(prefers-color-scheme: dark)") : null;

  function detachListeners() {
    resizeObs?.disconnect();
    resizeObs = null;
    themeObs?.disconnect();
    themeObs = null;
    if (typeof document !== "undefined") document.removeEventListener?.("rosy:theme", onTheme);
    schemeQuery?.removeEventListener?.("change", onTheme);
    if (canvas) {
      canvas.removeEventListener?.("pointerdown", onPointerDown);
      canvas.removeEventListener?.("pointermove", onPointerMove);
      canvas.removeEventListener?.("pointerleave", onPointerLeave);
      canvas.removeEventListener?.("pointerup", onPointerUp);
      canvas.removeEventListener?.("pointercancel", onPointerCancel);
      canvas.removeEventListener?.("wheel", onWheel);
      canvas.removeEventListener?.("keydown", onKeyDown);
      canvas.removeEventListener?.("contextmenu", onContextMenu);
      canvas.removeEventListener?.("webglcontextlost", onContextLost);
    }
  }

  const ready = (async () => {
    try {
      if (!canvas) throw new Error("Missing canvas");
      three = await loadThree();
      const [arm, mobile] = await Promise.all([loadRobotModel("arm"), loadRobotModel("mobile")]);
      if (disposed) return false;
      models = { arm, mobile };
      renderer = new three.WebGLRenderer({ canvas, antialias: true, alpha: false });
      renderer.setPixelRatio(Math.min(typeof window !== "undefined" ? window.devicePixelRatio || 1 : 1, 2));
      scene = new three.Scene();
      camera = new three.PerspectiveCamera(38, 1, 0.02, 80);
      camera.up.set(0, 0, 1);
      raycaster = new three.Raycaster();
      const sun = new three.DirectionalLight(0xffffff, 2.2);
      sun.position.set(2.0, -1.5, 4.0);
      scene.add(new three.HemisphereLight(0xffffff, 0x888888, 0.8), sun);
      refreshTokens();

      canvas.tabIndex = 0;
      canvas.addEventListener("pointerdown", onPointerDown);
      canvas.addEventListener("pointermove", onPointerMove);
      canvas.addEventListener("pointerleave", onPointerLeave);
      canvas.addEventListener("pointerup", onPointerUp);
      canvas.addEventListener("pointercancel", onPointerCancel);
      canvas.addEventListener("wheel", onWheel, { passive: false });
      canvas.addEventListener("keydown", onKeyDown);
      canvas.addEventListener("contextmenu", onContextMenu);
      canvas.addEventListener("webglcontextlost", onContextLost);

      if (typeof ResizeObserver === "function") {
        resizeObs = new ResizeObserver(resize);
        resizeObs.observe(canvas.parentElement || canvas);
      }
      if (typeof MutationObserver === "function" && typeof document !== "undefined") {
        themeObs = new MutationObserver(onTheme);
        themeObs.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
        document.addEventListener("rosy:theme", onTheme);
      }
      schemeQuery?.addEventListener?.("change", onTheme);

      resize();
      applyState(latestState);
      return true;
    } catch (err) {
      detachListeners();
      renderer?.dispose();
      renderer = null;
      onUnavailable(err);
      return false;
    }
  })();

  function dispose() {
    disposed = true;
    if (pending) cancelAnimationFrame(pending);
    pending = 0;
    detachListeners();
    clearSiteGroup();
    floorState.geom?.dispose();
    floorState.mat?.dispose();
    floorState.texture?.dispose();
    floorState.grid?.geometry?.dispose();
    floorState.grid?.material?.dispose();
    for (const rig of pinkyRigs.values()) rig.dispose();
    for (const rig of omxRigs.values()) rig.dispose();
    pinkyRigs.clear();
    omxRigs.clear();
    pickables.length = 0;
    scene?.clear?.();
    latestState = {};
    renderer?.dispose();
    renderer?.forceContextLoss?.();
    renderer = null;
  }

  return { ready, render: applyState, setPreset, resize, dispose };
}
