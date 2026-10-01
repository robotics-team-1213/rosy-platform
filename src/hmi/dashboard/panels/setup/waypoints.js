import { HeadlessState } from "/common/core_ui_logic.js";
import { poseUnavailableReason } from "./pose-evidence.js";
// D-359 §5.3 — 끌 때 이유를 같이 준다. 켜거나 짧은 요청 중 잠금이면 이유를 지운다.
function setOff(control, off, reason = "") { control.disabled = Boolean(off); if (off && reason) control.setAttribute("reason", reason); else control.removeAttribute("reason"); }
export function mount(el, ctx) {
  const head = document.createElement("ui-head");
  head.textContent = "웨이포인트 준비";
  const help = document.createElement("p");
  help.textContent = "현재 위치를 웨이포인트로 저장합니다. 위치 정보가 들어오면 저장할 수 있습니다.";
  const form = document.createElement("form");
  form.className = "ui-form";
  const input = document.createElement("input");
  input.className = "ui-field";
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
  const saveStatus = document.createElement("p");
  saveStatus.setAttribute("role", "status");
  saveStatus.setAttribute("aria-live", "polite");
  const listStatus = document.createElement("p");
  listStatus.setAttribute("role", "status");
  listStatus.setAttribute("aria-live", "polite");
  const list = document.createElement("ul");
  list.className = "waypoint-list";
  list.hidden = true;
  const emptyNote = document.createElement("ui-empty");
  emptyNote.textContent = "저장된 웨이포인트가 없습니다.";
  emptyNote.hidden = true;
  let latestState = null;
  let pending = false;

  function setStatus(target, text) {
    if (target.textContent !== text) target.textContent = text;
  }

  function poseReady() {
    const pose = latestState?.pose;
    return new HeadlessState(latestState).isFresh("pose") && pose
      && pose.x != null && pose.y != null
      && Number.isFinite(Number(pose.x)) && Number.isFinite(Number(pose.y));
  }
  function syncSave() { setOff(save, pending || !poseReady(), pending ? "" : "위치 증거 확인 필요"); }

  const stopState = ctx.store.poll("/api/v1/robot/state", 1_000, (state) => {
    latestState = state;
    syncSave();
    if (!poseReady()) setStatus(message, new HeadlessState(state).isFresh("pose")
      ? "현재 위치 좌표가 없어 저장을 막았습니다."
      : `${poseUnavailableReason(state)} · 현재 위치 저장을 막았습니다.`);
    else setStatus(message, "현재 위치를 읽었습니다. 이름을 입력해 저장하세요.");
  }, (error) => {
    latestState = null;
    syncSave();
    setStatus(message, `위치 상태를 불러오지 못했습니다: ${error.message}`);
  });
  const stopWaypoints = ctx.store.poll("/api/v1/waypoints", 5_000, ({waypoints = []}) => {
    list.replaceChildren();
    list.hidden = !waypoints.length;
    emptyNote.hidden = waypoints.length > 0;
    setStatus(listStatus, "");
    if (!waypoints.length) return;
    for (const waypoint of waypoints) {
      const row = document.createElement("li");
      row.textContent = `${waypoint.name}: ${Number(waypoint.x).toFixed(2)}, ${Number(waypoint.y).toFixed(2)}`;
      list.append(row);
    }
  }, (error) => {
    list.replaceChildren();
    list.hidden = true;
    emptyNote.hidden = true;
    setStatus(listStatus, `웨이포인트 목록을 읽지 못했습니다: ${error.message}. 다시 확인 중입니다.`);
  });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (pending) return;
    const name = input.value.trim();
    if (!name) { setStatus(saveStatus, "이름을 입력하세요."); input.focus(); return; }
    if (!poseReady()) {
      setStatus(saveStatus, "현재 위치가 최신이 아니어서 저장을 막았습니다.");
      return;
    }
    const pose = latestState.pose;
    const mapId = latestState.map_id || null;
    pending = true;
    save.disabled = true;
    setStatus(saveStatus, "현재 위치를 웨이포인트로 저장하는 중입니다.");
    try {
      await ctx.api("/api/v1/waypoints", {method: "POST", body: JSON.stringify({
        name, x: Number(pose.x), y: Number(pose.y), yaw: Number(pose.yaw) || 0,
        map_id: mapId, metadata: {},
      })});
      input.value = "";
      setStatus(saveStatus, `${name} 웨이포인트를 저장했습니다.${poseReady() ? "" : " 현재 위치 상태는 다시 확인하세요."}`);
    } catch (error) {
      setStatus(saveStatus, `저장하지 못했습니다: ${error.message}`);
    } finally { pending = false; syncSave(); }
  });
  form.append(input, save);
  el.append(head, help, form, message, saveStatus, listStatus, list, emptyNote);
  return () => { stopState(); stopWaypoints(); };
}
