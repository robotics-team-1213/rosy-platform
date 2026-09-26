// Operator setup actions use the same capability and API authority as CORE.
function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
}

function field(labelText, name, value = "0") {
  const label = el("label", "ui-field-label", labelText);
  const input = el("input");
  input.type = "number"; input.step = "any"; input.required = true; input.name = name; input.value = value;
  label.append(input);
  return {label, input};
}

export function mount(root, ctx) {
  const head = el("ui-head", "", "위치 설정 및 맵 준비");
  const note = el("p", "surface-message", "기능 지원 여부를 확인하는 중입니다.");
  note.setAttribute("role", "status");

  const poseForm = el("form", "ui-form");
  poseForm.append(el("h3", "", "초기 위치 설정"));
  const x = field("X (m)", "x"); const y = field("Y (m)", "y"); const yaw = field("방향 (rad)", "yaw");
  const setPose = el("ui-button", "", "초기 위치 적용"); setPose.setAttribute("kind", "primary"); setPose.type = "submit";
  poseForm.append(x.label, y.label, yaw.label, setPose);

  const slam = el("section", "surface-readback");
  slam.append(el("h3", "", "SLAM 맵 준비"));
  const mapName = el("input"); mapName.name = "map_name"; mapName.maxLength = 128; mapName.value = "rosy_map";
  mapName.setAttribute("aria-label", "저장할 맵 이름");
  const actions = el("ui-actions", "surface-actions");
  const start = el("ui-button", "", "맵핑 시작"); start.setAttribute("kind", "primary"); start.type = "button";
  const stop = el("ui-button", "", "맵핑 중지"); stop.setAttribute("kind", "quiet"); stop.type = "button";
  const save = el("ui-button", "", "맵 저장"); save.setAttribute("kind", "quiet"); save.type = "button";
  actions.append(start, stop, mapName, save); slam.append(actions);
  root.append(head, note, poseForm, slam);

  let navigationAvailable = false;
  let slamAvailable = false;
  function applyAvailability(caps) {
    navigationAvailable = caps?.navigation?.goal_navigation === true;
    slamAvailable = caps?.slam === true;
    setPose.disabled = !navigationAvailable;
    for (const button of [start, stop, save]) button.disabled = !slamAvailable;
    if (!navigationAvailable || !slamAvailable) {
      note.textContent = `사용할 수 없는 기능: ${[
        !navigationAvailable ? `초기 위치 설정 (${caps?.navigation?.reason || "Navigation capability 미제공"})` : "",
        !slamAvailable ? `SLAM (${caps?.slam_reason || "SLAM capability 미제공"})` : "",
      ].filter(Boolean).join(" · ")}`;
    } else note.textContent = "초기 위치와 SLAM 기능을 사용할 수 있습니다.";
  }
  const stopCaps = ctx.store.poll("/api/v1/system/capabilities", 10_000, applyAvailability, (error) => {
    navigationAvailable = slamAvailable = false;
    setPose.disabled = start.disabled = stop.disabled = save.disabled = true;
    note.textContent = `기능 지원 정보를 받지 못해 작업을 막았습니다: ${error.message}`;
  });

  poseForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const values = [x.input.value, y.input.value, yaw.input.value].map(Number);
    if (!navigationAvailable || !values.every(Number.isFinite)) return;
    setPose.disabled = true;
    try {
      await ctx.api("/api/v1/localization/initialpose", {method: "POST", body: JSON.stringify({x: values[0], y: values[1], yaw: values[2]})});
      note.textContent = "초기 위치 설정 요청을 CORE가 받았습니다.";
    } catch (error) { note.textContent = `초기 위치를 적용하지 못했습니다: ${error.message}`; }
    finally { setPose.disabled = !navigationAvailable; }
  });

  async function run(path, body, prompt, success) {
    if (!slamAvailable || !window.confirm(prompt)) return;
    for (const button of [start, stop, save]) button.disabled = true;
    try {
      const result = await ctx.api(path, {method: "POST", ...(body ? {body: JSON.stringify(body)} : {})});
      note.textContent = result.map_id ? `${success} · 맵 ID ${result.map_id}` : success;
    } catch (error) { note.textContent = `요청을 완료하지 못했습니다: ${error.message}`; }
    finally { for (const button of [start, stop, save]) button.disabled = !slamAvailable; }
  }
  start.addEventListener("click", () => run("/api/v1/slam/start", null, "맵핑을 시작할까요? 세션 중에는 목표 주행이 거부됩니다.", "맵핑 시작 요청을 CORE가 받았습니다."));
  stop.addEventListener("click", () => run("/api/v1/slam/stop", null, "맵핑을 중지할까요?", "맵핑 중지 요청을 CORE가 받았습니다."));
  save.addEventListener("click", () => run("/api/v1/slam/save", {name: mapName.value.trim() || "rosy_map"}, "현재 맵을 저장할까요?", "맵 저장 요청을 CORE가 받았습니다."));

  return () => { stopCaps(); };
}
