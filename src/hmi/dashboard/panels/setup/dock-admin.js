import { HeadlessState } from "/common/core_ui_logic.js";

function el(tag, cls, text) { const node = document.createElement(tag); if (cls) node.className = cls; if (text !== undefined) node.textContent = text; return node; }
function input(labelText, name, type = "text") {
  const label = el("label", "ui-field-label", labelText); const control = el("input");
  control.name = name; control.type = type; control.autocomplete = "off"; label.append(control);
  return {label, control};
}

export function mount(root, ctx) {
  const head = el("ui-head", "", "도크 유형 및 위치 관리");
  const status = el("ui-status", "", "pose와 도크 목록을 불러오는 중입니다.");
  const form = el("form", "ui-form");
  const idField = input("새 도크 ID", "dock_id"); idField.control.maxLength = 64;
  const typeField = input("도크 유형 이름 (기존 유형은 재사용)", "dock_type"); typeField.control.maxLength = 64;
  const knownTypes = el("datalist", ""); knownTypes.id = "setup-dock-types"; typeField.control.setAttribute("list", knownTypes.id);
  const detectorLabel = el("label", "ui-field-label", "새 유형의 검출기");
  const detector = el("select"); detector.setAttribute("aria-label", "새 도크 유형 검출기");
  for (const [value, text] of [["", "기존 유형 또는 검출기 선택"], ["simulated", "시뮬레이션"], ["observation", "태그 관측"]]) {
    const option = el("option", "", text); option.value = value; detector.append(option);
  }
  detectorLabel.append(detector);
  const tag = input("태그 ID (태그 관측)", "tag_id", "number"); tag.control.min = "0"; tag.control.step = "1";
  const tagSize = input("태그 크기 m (태그 관측)", "tag_size_m", "number"); tagSize.control.min = "0.001"; tagSize.control.step = "any";
  const add = el("ui-button", "", "현재 위치에 도크 등록"); add.setAttribute("kind", "primary"); add.type = "submit";
  add.disabled = true;
  form.append(idField.label, typeField.label, detectorLabel, tag.label, tagSize.label, add);
  const list = el("ul", "waypoint-list"); list.setAttribute("aria-label", "도크 유형과 등록 위치");
  root.append(head, status, form, knownTypes, list);

  let pose = null;
  let poseFresh = false;
  let types = [];
  let typesLoaded = false;
  let docks = [];
  let pending = false;
  function renderTypes() {
    knownTypes.replaceChildren(...types.map((item) => { const option = el("option", ""); option.value = item.name; option.label = item.detector; return option; }));
  }
  function renderDocks() {
    list.replaceChildren();
    if (!docks.length) list.append(el("li", "", "등록된 도크가 없습니다."));
    for (const item of docks) {
      const row = el("li", ""); row.dataset.dockId = item.id;
      row.append(el("span", "", `${item.id} · ${item.type} · ${item.map_id || "맵 없음"}`));
      const remove = el("ui-button", "", "삭제"); remove.setAttribute("kind", "irreversible"); remove.type = "button";
      remove.addEventListener("click", async () => {
        if (!window.confirm(`${item.id} 도크를 삭제할까요? 되돌릴 수 없습니다.`)) return;
        remove.disabled = true;
        try { await ctx.api(`/api/v1/docking/docks/${encodeURIComponent(item.id)}`, {method: "DELETE"}); status.textContent = `${item.id} 도크를 삭제했습니다.`; }
        catch (error) { status.textContent = `도크 삭제 실패: ${error.message}`; remove.disabled = false; }
      });
      row.append(remove); list.append(row);
    }
  }
  const stopTypes = ctx.store.poll("/api/v1/docking/types", 10_000, ({types: rows = []}) => {
    types = rows; typesLoaded = true; renderTypes();
    add.disabled = pending || !poseFresh;
    updateDetectorFields();
  }, (error) => { typesLoaded = false; add.disabled = true; status.textContent = `도크 유형을 읽지 못해 등록을 막았습니다: ${error.message}`; });
  const stopState = ctx.store.poll("/api/v1/robot/state", 1_000, (state) => {
    poseFresh = new HeadlessState(state).isFresh("pose"); pose = state;
    add.disabled = pending || !poseFresh || !typesLoaded;
    if (!poseFresh) status.textContent = "현재 위치가 최신이 아니어서 도크 등록을 막았습니다.";
    else if (!status.textContent.includes("등록했습니다")) status.textContent = "현재 위치를 읽었습니다. 유형과 ID를 확인한 뒤 등록하세요.";
  }, (error) => { poseFresh = false; pose = null; add.disabled = true; status.textContent = `현재 pose를 읽지 못해 도크 등록을 막았습니다: ${error.message}`; });
  const stopDocks = ctx.store.poll("/api/v1/docking/docks", 10_000, ({docks: rows = []}) => { docks = rows; renderDocks(); }, (error) => { status.textContent = `도크 목록을 읽지 못했습니다: ${error.message}`; });

  function updateDetectorFields() {
    const existingType = types.some((item) => item.name === typeField.control.value.trim());
    detectorLabel.hidden = existingType;
    const needsTag = !existingType && detector.value === "observation";
    tag.control.required = needsTag; tagSize.control.required = needsTag;
    tag.label.hidden = tagSize.label.hidden = !needsTag;
  }
  detector.addEventListener("change", updateDetectorFields);
  typeField.control.addEventListener("input", updateDetectorFields);
  updateDetectorFields();
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!poseFresh || !pose || pending) { status.textContent = "pose 수신이 확인될 때까지 기다리세요."; return; }
    const dockId = idField.control.value.trim(); const typeName = typeField.control.value.trim();
    if (!dockId || !typeName) { status.textContent = "도크 ID와 유형 이름을 입력하세요."; return; }
    const existingType = types.find((item) => item.name === typeName);
    if (!existingType && !detector.value) { status.textContent = "새 유형에는 검출기 종류를 선택하세요."; return; }
    if (detector.value === "observation" && (!tag.control.value || !tagSize.control.value)) { status.textContent = "태그 관측 유형에는 태그 ID와 크기가 필요합니다."; return; }
    if (!window.confirm(`${dockId} 도크를 현재 위치에 등록할까요? 현재 위치가 실제 도크에 정확히 맞는지 확인하세요.`)) return;
    pending = true; add.disabled = true;
    let createdType = false;
    try {
      if (!existingType) {
        const body = {name: typeName, detector: detector.value};
        if (detector.value === "observation") { body.tag_id = Number(tag.control.value); body.tag_size_m = Number(tagSize.control.value); }
        const savedType = await ctx.api("/api/v1/docking/types", {method: "POST", body: JSON.stringify(body)});
        types = [...types, savedType]; renderTypes(); createdType = true;
      }
      await ctx.api("/api/v1/docking/docks", {method: "POST", body: JSON.stringify({
        id: dockId, type: typeName, x: Number(pose.pose.x), y: Number(pose.pose.y), yaw: Number(pose.pose.yaw) || 0, map_id: pose.map_id || null,
      })});
      status.textContent = `${dockId} 도크를 등록했습니다.`; idField.control.value = "";
    } catch (error) { status.textContent = `도크 등록 실패${createdType ? " (유형은 저장됐습니다. 같은 유형으로 다시 시도할 수 있습니다)" : ""}: ${error.message}`; }
    finally { pending = false; add.disabled = !poseFresh || !typesLoaded; }
  });
  return () => { stopTypes(); stopState(); stopDocks(); };
}
