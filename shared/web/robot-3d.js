/**
 * C15 robot 3D view: every robot kind (OMX-AI arm, Pinky Pro mobile robot) drawn the same way from the repo's own models
 * (tools/robot_meshes.py writes meshes/). Pure parts live in robot-3d-model.js; three.js (vendor/, MIT, r183.2) is
 * loaded by dynamic import on the first view, so a page that never creates one never fetches it.
 *
 *   createRobotView(el, {kind, profile, name, selected = false, selection, robotId, joints, pose, skill, preset = "iso"}) -> view
 *     kind     "arm" | "mobile"; profile (robotProfile) gives name and link state, else pass name
 *     joints   {jointName: rad} for an arm (joint1..joint5, gripper_joint_1); unknown ones are not drawn as 0
 *     pose     {x, y, yaw} for a mobile robot (m, rad); yaw turns the robot against a world-fixed +x tick
 *     selection, robotId   optional shared store (selection.js createSelection): selected follows selection.get() === robotId and
 *              every change from another view redraws. The view cannot choose, so it never calls selection.set; dispose() unsubscribes.
 *     skill    optional text for the facts line only (executor and step, from skill-state.js); it never changes the drawing
 *     view.setState({joints, pose, selected, profile, name, skill})   one redraw; view.setPreset("iso"|"front"|"side"|"top")
 *     view.ready   Promise<boolean>: true once drawn, false when WebGL or a model file is unavailable (quiet fallback:
 *                  the facts line stays, the canvas goes)
 *     view.dispose()   releases the GL context; keep at most 6 views per page, never one per list row
 *   el gets <figure class="robot-view">: stage (canvas role=img, keyboard orbit: arrows rotate, +/- zoom, Home resets),
 *   preset buttons, and the facts line (kind, name, selected, joints or pose) that is also the canvas's text alternative.
 *
 * Render policy (D-220): a frame is drawn on state change, resize, theme change or orbit input, never in a loop; poses snap,
 * so prefers-reduced-motion needs no special case. Selected = accent ring on the ground + accent silhouette + accent frame
 * (CSS [data-selected]), all in --selection (D-1030), the same accent as the row's edge and 선택됨 toggle. Colours are read from the CSS
 * custom properties at draw time (dark and light themes); size is set by CSS and renderer.setSize(w, h, false).
 */
import {readColour, toggletip} from "./ui.js";
import {loadThree, loadRobotModel} from "./robot-3d-assets.js";
import {jointAngles, describeRobot, CAMERA_PRESETS, PRESET_LABEL, presetDirection, fitView} from "./robot-3d-model.js";

/** The selection accent token (D-1030), also the CSS frame colour in component-controls.css. */
const SELECTION_TOKEN = "--selection";
const ELEV_MAX = Math.PI / 2 - 0.001; // the top preset sits just under straight down
const OUTLINE_M = {arm: 0.0035, mobile: 0.0018};
let serial = 0;

/** A CSS custom property as a colour: ui.js readColour reads any CSS colour syntax (hex, color-mix) through its probe; [0,0,0,0] = not declared. */
function tokenRgb(token, fallback) {
  const [r, g, b, a] = readColour(token);
  return a === 0 ? fallback : [r / 255, g / 255, b / 255];
}

const el = (tag, className, text) => {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
};

export function createRobotView(host, options = {}) {
  const {kind} = options;
  if (kind !== "arm" && kind !== "mobile") throw new RangeError("createRobotView needs kind arm|mobile");
  const state = {name: options.name, profile: options.profile, selected: options.selection ? options.selection.get() === options.robotId : !!options.selected, joints: options.joints, pose: options.pose, skill: options.skill};
  const id = `robot-view-${++serial}`;
  const figure = el("figure", "robot-view");
  figure.dataset.kind = kind;
  figure.dataset.state = "loading";
  const stage = el("div", "robot-view-stage");
  stage.tabIndex = 0;
  stage.setAttribute("role", "group");
  stage.setAttribute("aria-roledescription", "3D 보기");
  const canvas = el("canvas");
  canvas.setAttribute("role", "img");
  canvas.setAttribute("aria-labelledby", `${id}-facts`);
  stage.append(canvas);
  const presets = el("div", "robot-view-presets");
  presets.setAttribute("role", "group");
  presets.setAttribute("aria-label", "3D 시점");
  const presetButtons = CAMERA_PRESETS.map(name => {
    const button = el("ui-button", "", PRESET_LABEL[name]);
    button.setAttribute("kind", "segment");
    button.setAttribute("type", "button");
    button.dataset.preset = name;
    button.addEventListener("click", () => view.setPreset(name));
    return button;
  });
  presets.append(...presetButtons);
  const facts = el("figcaption", "robot-view-facts");
  const summary = el("span", "robot-view-summary");
  summary.id = `${id}-facts`;
  const detail = el("span", "sr-only"); // joints or pose: the accessible description, and the toggletip below for sighted users
  detail.id = `${id}-detail`;
  canvas.setAttribute("aria-describedby", detail.id);
  const more = el("ui-button", "", "값");
  more.setAttribute("kind", "quiet");
  more.setAttribute("type", "button");
  facts.append(summary, more, detail);
  const note = el("p", "robot-view-note");
  note.hidden = true;
  figure.append(stage, presets, note, facts);
  host.replaceChildren(figure);
  toggletip(more, {toString: () => detail.textContent}); // toggletip reads its text when opened, so it shows the current values

  let three, renderer, scene, camera, robot, rig, disposed = false, pending = 0;
  let orbited = false, orbit = {az: 0, el: 0, dist: 1}, frame, presetName = options.preset || "iso";
  const colors = {}, parts = {materials: [], outlines: [], rings: {}, tick: null};

  const syncText = () => {
    const name = state.name || state.profile?.name;
    const text = describeRobot({kind, name, selected: state.selected, joints: state.joints, pose: state.pose, link: state.profile?.link, skill: state.skill});
    summary.textContent = text.summary;
    detail.textContent = text.detail;
    more.setAttribute("aria-label", `${name || kind} ${kind === "arm" ? "관절 값" : "위치·방향 값"}`);
    more.textContent = kind === "arm" ? "관절 값" : "위치·방향";
    stage.setAttribute("aria-label", `${state.name || state.profile?.name || ""} 3D 보기 · 방향키 회전 · +/- 확대 · Home 처음 시점`.trim());
    figure.toggleAttribute("data-selected", state.selected);
  };

  function draw() {
    pending = 0;
    if (disposed || !renderer) return;
    const eye = Math.cos(orbit.el) * orbit.dist;
    camera.position.set(frame.center[0] + eye * Math.cos(orbit.az), frame.center[1] + eye * Math.sin(orbit.az), frame.center[2] + Math.sin(orbit.el) * orbit.dist);
    camera.lookAt(...frame.center);
    renderer.render(scene, camera);
  }
  const redraw = () => { if (!pending && renderer && !disposed) pending = requestAnimationFrame(draw); }; // one frame per change

  // the posed robot's vertices plus its ground ring; the camera distance makes them fill ~75% of the view
  function fit() {
    const {Box3, Vector3} = three;
    robot.updateMatrixWorld(true);
    const box = new Box3().setFromObject(robot), center = box.getCenter(new Vector3()), at = new Vector3(), points = [];
    robot.traverse(node => { // the posed vertices themselves: an axis-aligned box of a diagonal arm is far wider than the arm
      if (!node.isMesh || node.renderOrder < 0) return;
      const p = node.geometry.attributes.position;
      for (let i = 0; i < p.count; i += 2) { at.fromBufferAttribute(p, i).applyMatrix4(node.matrixWorld); points.push([at.x - center.x, at.y - center.y, at.z - center.z]); }
    });
    for (let k = 0; k < 8; k++) points.push([Math.cos(k * Math.PI / 4) * parts.ringR - center.x, Math.sin(k * Math.PI / 4) * parts.ringR - center.y, -center.z]); // the ground ring keeps its margin too
    frame = {center: center.toArray(), points, baseDist: 1};
    const radius = box.getSize(new Vector3()).length() / 2;
    camera.near = radius * 0.05; camera.far = radius * 40; camera.updateProjectionMatrix();
  }
  function setCamera(name) {
    if (stage.clientHeight && stage.clientWidth) camera.aspect = stage.clientWidth / stage.clientHeight; // the stage is measured before the first fit
    fit();
    const dir = presetDirection(name), {distance: dist, shift} = fitView(dir, frame.points, camera.fov, camera.aspect);
    frame.center = frame.center.map((v, i) => v + shift[i]);
    for (const p of frame.points) { p[0] -= shift[0]; p[1] -= shift[1]; p[2] -= shift[2]; }
    orbit = {az: Math.atan2(dir[1], dir[0]), el: Math.asin(dir[2]), dist};
    frame.baseDist = dist;
    orbited = false;
  }

  // a report that is late or lost is drawn faded toward the background (not transparent: that sorts badly), never as live
  const live = () => !state.profile?.link || state.profile.link.state === "fresh";
  function tint() {
    for (const material of parts.materials) material.color.copy(colors.body).multiplyScalar(material.userData.shade ?? 1).lerp(colors.ground, live() ? 0 : 0.35);
  }

  function paintTokens() {
    const read = (token, fallback) => { const [r, g, b] = tokenRgb(token, fallback); return new three.Color().setRGB(r, g, b, three.SRGBColorSpace); };
    colors.ground = read("--surface-canvas", [0.1, 0.1, 0.1]);
    // body tone from tokens: --ink-quiet as is on a dark ground (already light), lifted toward --ground-card-2 on a light one
    const dark = colors.ground.r * 0.2126 + colors.ground.g * 0.7152 + colors.ground.b * 0.0722 < 0.2;
    colors.body = read("--ink-quiet", [0.5, 0.5, 0.5]).lerp(dark ? colors.ground : read("--ground-card-2", [0.85, 0.85, 0.88]), dark ? 0 : 0.4);
    parts.hemi?.groundColor.copy(read("--ground-card-2", [0.5, 0.5, 0.5]));
    colors.line = read("--border-strong", [0.5, 0.5, 0.5]);
    colors.accent = read(SELECTION_TOKEN, [0.35, 0.65, 1]);
    tint();
    for (const material of parts.outlines) material.color.copy(colors.accent);
    parts.rings.quiet?.material.color.copy(colors.line);
    parts.rings.accent?.material.color.copy(colors.accent);
    parts.tick?.material.color.copy(colors.line);
  }

  function applyState() {
    syncText();
    if (!robot) return;
    const {angles} = jointAngles(rig.model, kind === "arm" ? state.joints : {});
    for (const [name, joint] of rig.rotators) joint.node.quaternion.setFromAxisAngle(new three.Vector3(...joint.axis).normalize(), angles[name] ?? 0);
    if (kind === "mobile") robot.rotation.z = Number.isFinite(state.pose?.yaw) ? state.pose.yaw : 0;
    tint();
    if (frame && !orbited && kind !== "mobile") { // grow-only refit: an arm that extends keeps its 75%, small jitter never moves the camera
      fit();
      const {distance} = fitView(presetDirection(presetName), frame.points, camera.fov, camera.aspect);
      if (distance > frame.baseDist * 1.02) setCamera(presetName);
    }
    parts.rings.accent.visible = state.selected;
    parts.rings.quiet.visible = !state.selected;
    for (const mesh of parts.outlineMeshes) mesh.visible = state.selected;
    redraw();
  }

  function smoothOutline(geometry, width) {
    const out = geometry.clone(), p = out.attributes.position, n = out.attributes.normal, sums = new Map();
    const key = i => `${Math.round(p.getX(i) * 1e5)},${Math.round(p.getY(i) * 1e5)},${Math.round(p.getZ(i) * 1e5)}`;
    for (let i = 0; i < p.count; i++) {
      const slot = sums.get(key(i)) ?? sums.set(key(i), [0, 0, 0]).get(key(i));
      slot[0] += n.getX(i); slot[1] += n.getY(i); slot[2] += n.getZ(i);
    }
    for (let i = 0; i < p.count; i++) {
      const s = sums.get(key(i)), length = Math.hypot(...s);
      if (length < 0.85) continue; // faces at this point cancel (thin plate, sliver): no safe outward direction, stay put
      p.setXYZ(i, p.getX(i) + s[0] / length * width, p.getY(i) + s[1] / length * width, p.getZ(i) + s[2] / length * width);
    }
    return out;
  }

  function build(loaded) {
    const {model, meshes} = loaded;
    const {Group, Mesh, BufferGeometry, BufferAttribute, MeshLambertMaterial, MeshBasicMaterial, Euler, Box3, Vector3, RingGeometry, BackSide} = three;
    let shadeIndex = 0; // neighbouring links alternate in lightness so the links read apart
    // drawn first and without depth writes: the body paints over it, so only the rim outside the silhouette stays (a hull
    // that is merely depth-tested shows through where the decimated body has flipped faces)
    const outlineMaterial = new MeshBasicMaterial({color: colors.accent, side: BackSide, depthWrite: false});
    parts.outlines.push(outlineMaterial);
    parts.outlineMeshes = [];
    const geometries = {};
    for (const [name, positions] of Object.entries(meshes)) {
      const geometry = new BufferGeometry();
      geometry.setAttribute("position", new BufferAttribute(positions, 3));
      geometry.computeVertexNormals();
      geometries[name] = geometry;
    }
    const nodes = {}, rotators = new Map(), disposables = Object.values(geometries);
    for (const [name, link] of Object.entries(model.links)) {
      const node = nodes[name] = new Group();
      if (!link.mesh) continue;
      const holder = new Group();
      holder.position.set(...link.xyz);
      holder.rotation.copy(new Euler(link.rpy[0], link.rpy[1], link.rpy[2], "ZYX"));
      const bodyMaterial = new MeshLambertMaterial({color: colors.body});
      bodyMaterial.userData.shade = shadeIndex++ % 2 ? 0.8 : 1;
      parts.materials.push(bodyMaterial);
      holder.add(new Mesh(geometries[link.mesh], bodyMaterial));
      const outline = new Mesh(smoothOutline(geometries[link.mesh], OUTLINE_M[kind]), outlineMaterial);
      outline.visible = false;
      outline.renderOrder = -1;
      disposables.push(outline.geometry);
      parts.outlineMeshes.push(outline);
      holder.add(outline);
      node.add(holder);
    }
    for (const joint of model.joints) {
      const holder = new Group(), turning = new Group();
      holder.position.set(...joint.xyz);
      holder.rotation.copy(new Euler(joint.rpy[0], joint.rpy[1], joint.rpy[2], "ZYX"));
      holder.add(turning);
      turning.add(nodes[joint.child]);
      nodes[joint.parent].add(holder);
      if (joint.type === "revolute" || joint.type === "continuous") rotators.set(joint.name, {node: turning, axis: joint.axis});
    }
    robot = nodes[model.root];
    scene.add(robot);
    rig = {model, rotators, disposables};
    const base = Object.values(model.links).find(link => link.mesh);
    const baseBox = new Box3().setFromBufferAttribute(geometries[base.mesh].attributes.position);
    const ringR = Math.max(baseBox.max.x - baseBox.min.x, baseBox.max.y - baseBox.min.y) * 0.6;
    const ringFor = (width, material) => { const ring = new Mesh(new RingGeometry(ringR, ringR + width, 72), material); ring.position.z = 0.0004; scene.add(ring); disposables.push(ring.geometry); return ring; };
    parts.rings.quiet = ringFor(ringR * 0.025, new MeshBasicMaterial({color: colors.line}));
    parts.rings.accent = ringFor(ringR * 0.07, new MeshBasicMaterial({color: colors.accent}));
    if (kind === "mobile") { // world-fixed +x tick: the robot's heading reads against it
      const line = new three.Line(new BufferGeometry().setFromPoints([new Vector3(ringR * 1.2, 0, 0.0004), new Vector3(ringR * 1.8, 0, 0.0004)]), new three.LineBasicMaterial({color: colors.line}));
      scene.add(line);
      parts.tick = line;
      disposables.push(line.geometry);
    }
    parts.extra = [parts.rings.quiet.material, parts.rings.accent.material, parts.tick?.material].filter(Boolean);
    robot.updateMatrixWorld(true);
    parts.ringR = ringR * 1.07;
  }

  const offSelection = options.selection?.subscribe(picked => view.setState({selected: picked === options.robotId}));
  const view = {
    ready: null,
    setState(next = {}) {
      if (Object.keys(next).every(key => key === "skill")) { state.skill = next.skill; syncText(); return; } // text only: no redraw (D-220)
      for (const key of ["name", "profile", "joints", "pose", "skill"]) if (key in next) state[key] = next[key];
      if ("selected" in next) state.selected = !!next.selected;
      applyState();
    },
    setPreset(name) {
      if (!CAMERA_PRESETS.includes(name)) throw new RangeError(`unknown camera preset ${name}`);
      presetName = name;
      for (const button of presetButtons) button.setAttribute("aria-pressed", String(button.dataset.preset === name));
      if (frame) { setCamera(name); redraw(); }
    },
    dispose() {
      disposed = true;
      offSelection?.();
      cancelAnimationFrame(pending);
      resize?.disconnect();
      themeWatch?.disconnect();
      document.removeEventListener("rosy:theme", onTheme);
      schemeQuery?.removeEventListener?.("change", onTheme);
      rig?.disposables.forEach(item => item.dispose());
      [...parts.materials, ...parts.outlines, ...parts.extra ?? []].forEach(item => item.dispose());
      renderer?.dispose();
      renderer?.forceContextLoss();
      renderer = null;
    },
  };

  const onTheme = () => { if (renderer) { window.RosyPalette?.clear(); paintTokens(); redraw(); } };
  const schemeQuery = window.matchMedia?.("(prefers-color-scheme: dark)");
  let resize, themeWatch;
  syncText();
  for (const button of presetButtons) button.setAttribute("aria-pressed", String(button.dataset.preset === presetName));

  const fallback = reason => {
    figure.dataset.state = "fallback";
    stage.hidden = presets.hidden = true;
    note.hidden = false;
    note.textContent = `3D 보기를 쓸 수 없어 값만 표시합니다 (${reason})`;
    return false;
  };

  view.ready = (async () => {
    try {
      three = await loadThree();
      const loaded = await loadRobotModel(kind);
      if (disposed) return false;
      renderer = new three.WebGLRenderer({canvas, antialias: true, alpha: true});
      renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
      scene = new three.Scene();
      camera = new three.PerspectiveCamera(35, 1, 0.01, 100);
      camera.up.set(0, 0, 1);
      const sun = new three.DirectionalLight(0xffffff, 2.3); // one key light off the camera axis so adjacent faces differ; the hemisphere fills the rest
      sun.position.set(2.2, -0.8, 2.6);
      parts.hemi = new three.HemisphereLight(0xffffff, 0x888888, 0.7);
      scene.add(parts.hemi, sun);
      parts.rings = {};
      paintTokens(); // colours first: build() copies them into its materials
      build(loaded);
      paintTokens();
      view.setPreset(presetName);
      resize = new ResizeObserver(() => {
        const width = stage.clientWidth, height = stage.clientHeight;
        if (!width || !height) return;
        renderer.setSize(width, height, false);
        camera.aspect = width / height;
        camera.updateProjectionMatrix();
        if (robot && !orbited) setCamera(presetName);
        redraw();
      });
      resize.observe(stage);
      themeWatch = new MutationObserver(onTheme);
      themeWatch.observe(document.documentElement, {attributes: true, attributeFilter: ["data-theme"]});
      document.addEventListener("rosy:theme", onTheme);
      schemeQuery?.addEventListener?.("change", onTheme);
      figure.dataset.state = "ready";
      applyState();
      setCamera(presetName); // fit to the pose just applied
      return true;
    } catch (error) {
      console.warn("robot-3d view unavailable:", error);
      renderer?.dispose();
      renderer = null;
      return fallback(/WebGL|context/i.test(error?.message ?? "") ? "WebGL 없음" : "모델 파일을 가져올 수 없음");
    }
  })();

  // pointer orbit (mouse and pen drag; touch drags horizontally, vertical swipes still scroll the page) and the keyboard alternative
  let drag = null;
  stage.addEventListener("pointerdown", event => { if (renderer && event.button === 0) { drag = {x: event.clientX, y: event.clientY}; stage.setPointerCapture(event.pointerId); } });
  stage.addEventListener("pointermove", event => {
    if (!drag || !renderer) return;
    orbit.az -= (event.clientX - drag.x) * 0.008;
    orbit.el = Math.max(-0.2, Math.min(ELEV_MAX, orbit.el + (event.clientY - drag.y) * 0.008));
    drag = {x: event.clientX, y: event.clientY};
    orbited = true;
    redraw();
  });
  for (const type of ["pointerup", "pointercancel"]) stage.addEventListener(type, () => { drag = null; });
  stage.addEventListener("keydown", event => {
    if (!renderer) return;
    const steps = {ArrowLeft: [0.12, 0, 1], ArrowRight: [-0.12, 0, 1], ArrowUp: [0, 0.1, 1], ArrowDown: [0, -0.1, 1], "+": [0, 0, 0.9], "=": [0, 0, 0.9], "-": [0, 0, 1.1]};
    if (event.key === "Home") { setCamera(presetName); }
    else if (steps[event.key]) {
      const [az, elevation, zoom] = steps[event.key];
      orbit.az += az; orbit.el = Math.max(-0.2, Math.min(ELEV_MAX, orbit.el + elevation));
      orbit.dist = Math.max(frame.baseDist * 0.5, Math.min(frame.baseDist * 2.5, orbit.dist * zoom));
    } else return;
    if (event.key !== "Home") orbited = true;
    event.preventDefault();
    redraw();
  });
  return view;
}
