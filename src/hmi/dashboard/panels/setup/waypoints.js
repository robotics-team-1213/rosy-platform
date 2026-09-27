import { HeadlessState } from "/common/core_ui_logic.js";
import { poseUnavailableReason } from "./pose-evidence.js";
export function mount(el, ctx) {
  const head = document.createElement("ui-head");
  head.textContent = "웨이포인트 준비";
  const help = document.createElement("p");
  help.textContent = "현재 위치를 웨이포인트로 저장합니다. 위치 정보가 들어오면 저장할 수 있습니다.";
  const form = document.createElement("form");
  const input = document.createElement("input");
  input.name = "name";
  input.maxLength = 64;
  input.autocomplete = "off";
  input.setAttribute("aria-label", "웨이포인트 이름");
  input.placeholder = "웨이포인트 이름";
  const save = document.createElement("ui-button");
  save.setAttribute("kind", "primary");
  save.type = "submit";
  save.textContent = "현재 위치 저장";
  save.disabled = true;
  const message = document.createElement("p");
  message.setAttribute("role", "status");
  message.textContent = "현재 위치의 최신 상태를 기다리는 중입니다.";
  const list = document.createElement("ul");
  list.className = "waypoint-list";
  let latestState = null;
  let pending = false;

  function poseReady() {
    const pose = latestState?.pose;
    return new HeadlessState(latestState).isFresh("pose") && pose
      && pose.x != null && pose.y != null
      && Number.isFinite(Number(pose.x)) && Number.isFinite(Number(pose.y));
  }
  function syncSave() { save.disabled = pending || !poseReady(); }

  const stopState = ctx.store.poll("/api/v1/robot/state", 1_000, (state) => {
    latestState = state;
    syncSave();
    if (!poseReady()) message.textContent = new HeadlessState(state).isFresh("pose")
      ? "현재 위치 좌표가 없어 저장을 막았습니다."
      : `${poseUnavailableReason(state)} · 현재 위치 저장을 막았습니다.`;
    else if (!message.textContent.includes("저장했습니다")) message.textContent = "현재 위치를 읽었습니다. 이름을 입력해 저장하세요.";
  }, (error) => {
    latestState = null;
    syncSave();
    message.textContent = `위치 상태를 불러오지 못했습니다: ${error.message}`;
  });
  const stopWaypoints = ctx.store.poll("/api/v1/waypoints", 5_000, ({waypoints = []}) => {
    list.replaceChildren();
    if (!waypoints.length) {
      const empty = document.createElement("ui-empty");
      empty.textContent = "저장된 웨이포인트가 없습니다.";
      list.append(empty);
      return;
    }
    for (const waypoint of waypoints) {
      const row = document.createElement("li");
      row.textContent = `${waypoint.name}: ${Number(waypoint.x).toFixed(2)}, ${Number(waypoint.y).toFixed(2)}`;
      list.append(row);
    }
  }, (error) => { message.textContent = `웨이포인트를 불러오지 못했습니다: ${error.message}`; });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (pending) return;
    const name = input.value.trim();
    if (!name) { message.textContent = "이름을 입력하세요."; return; }
    if (!poseReady()) {
      message.textContent = "현재 위치가 최신이 아니어서 저장을 막았습니다.";
      return;
    }
    const pose = latestState.pose;
    const mapId = latestState.map_id || null;
    pending = true;
    save.disabled = true;
    try {
      await ctx.api("/api/v1/waypoints", {method: "POST", body: JSON.stringify({
        name, x: Number(pose.x), y: Number(pose.y), yaw: Number(pose.yaw) || 0,
        map_id: mapId, metadata: {},
      })});
      input.value = "";
      message.textContent = `${name} 웨이포인트를 저장했습니다.${poseReady() ? "" : " 현재 위치 상태는 다시 확인하세요."}`;
    } catch (error) {
      message.textContent = `저장하지 못했습니다: ${error.message}`;
    } finally { pending = false; syncSave(); }
  });
  form.append(input, save);
  el.append(head, help, form, message, list);
  return () => { stopState(); stopWaypoints(); };
}
