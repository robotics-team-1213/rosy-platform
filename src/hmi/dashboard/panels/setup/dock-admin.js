import { HeadlessState } from "/common/core_ui_logic.js";
import { confirmIrreversible } from "/common/ui.js";
import { poseUnavailableReason } from "./pose-evidence.js";

function el(tag, cls, text) { const node = document.createElement(tag); if (cls) node.className = cls; if (text !== undefined) node.textContent = text; return node; }
function input(labelText, name, type = "text") {
  const label = el("label", "ui-field-label", labelText); const control = el("input", "ui-field");
  control.name = name; control.type = type; control.autocomplete = "off"; label.append(control);
  return {label, control};
}

export function mount(root, ctx) {
  const head = el("ui-head", "", "도크 유형 및 위치 관리");
  const status = el("ui-status", "", "pose와 도크 목록을 불러오는 중입니다.");
  const gate = el("ui-status", "", "");
  gate.id = "dock-registration-gate";
  gate.setAttribute("role", "status");
  gate.setAttribute("aria-live", "polite");
  gate.setAttribute("aria-atomic", "true");
  gate.hidden = true;
  const registrationNotice = el("ui-status", "", "");
  registrationNotice.setAttribute("role", "status");
  registrationNotice.setAttribute("aria-live", "polite");
  registrationNotice.setAttribute("aria-atomic", "true");
  const form = el("form", "ui-form");
  const idField = input("새 도크 ID (필수)", "dock_id"); idField.control.maxLength = 64; idField.control.required = true;
  const typeField = input("도크 유형 이름 (필수 · 기존 유형은 재사용)", "dock_type"); typeField.control.maxLength = 64; typeField.control.required = true;
  const knownTypes = el("datalist", ""); knownTypes.id = "setup-dock-types"; typeField.control.setAttribute("list", knownTypes.id);
  const detectorLabel = el("label", "ui-field-label", "새 유형의 검출기");
  const detector = el("select", "ui-field"); detector.setAttribute("aria-label", "새 도크 유형 검출기");
  for (const [value, text] of [["", "기존 유형 또는 검출기 선택"], ["simulated", "시뮬레이션"], ["observation", "태그 관측"]]) {
    const option = el("option", "", text); option.value = value; detector.append(option);
  }
  detectorLabel.append(detector);
  const tag = input("태그 ID (태그 관측)", "tag_id", "number"); tag.control.min = "0"; tag.control.step = "1";
  const tagSize = input("태그 크기 m (태그 관측)", "tag_size_m", "number"); tagSize.control.min = "0.001"; tagSize.control.step = "any";
  const add = el("ui-button", "", "현재 위치에 도크 등록"); add.setAttribute("kind", "primary"); add.type = "submit";
  add.setAttribute("aria-describedby", gate.id);
  add.disabled = true;
  form.append(idField.label, typeField.label, detectorLabel, tag.label, tagSize.label, add);
  const listStatus = el("ui-status", "", "");
  listStatus.setAttribute("role", "status");
  listStatus.setAttribute("aria-live", "polite");
  const list = el("ul", "waypoint-list"); list.setAttribute("aria-label", "도크 유형과 등록 위치");
  const emptyNote = el("ui-empty", "", "등록된 도크가 없습니다."); emptyNote.hidden = true;
  root.append(head, status, form, gate, registrationNotice, knownTypes, listStatus, list, emptyNote);

  let pose = null;
  let poseFresh = false;
  let types = [];
  let typesLoaded = false;
  let typesError = null;
  let docks = [];
  let pending = false;
  let poseError = null;
  let listError = null;
  let docksLoaded = false;
  let listNotice = "";
  let registrationResult = "";
  const pendingDeletes = new Set();
  function setText(node, value) {
    if (node.textContent !== value) node.textContent = value;
  }
  function updateRegistrationReadiness() {
    const blockers = [];
    if (!poseFresh) {
      blockers.push(poseError
        ? `현재 위치를 읽지 못했습니다: ${poseError}`
        : pose ? poseUnavailableReason(pose).split(" · 마지막 수신")[0] : "현재 위치 정보를 불러오는 중입니다.");
    }
    if (!typesLoaded) {
      blockers.push(typesError
        ? `도크 유형을 읽지 못했습니다: ${typesError}`
        : "도크 유형 목록을 불러오는 중입니다.");
    }
    add.disabled = pending || blockers.length > 0;
    if (pending) {
      setText(gate, "등록 요청을 처리 중입니다. 완료될 때까지 기다려 주세요.");
      gate.hidden = false;
      setText(status, "도크 등록 요청을 처리하고 있습니다.");
    } else if (registrationResult) {
      gate.hidden = blockers.length === 0;
      setText(gate, blockers.length ? `다음 등록은 보류됩니다 · ${blockers.join(" · ")}` : "");
      setText(status, registrationResult);
    } else if (blockers.length) {
      setText(gate, `등록할 수 없습니다 · ${blockers.join(" · ")}`);
      gate.hidden = false;
      setText(status, `${blockers.join(" · ")} · 도크 등록을 막았습니다.`);
    } else {
      gate.hidden = true;
      setText(gate, "");
      setText(status, "현재 위치를 읽었습니다. 유형과 ID를 확인한 뒤 등록하세요.");
    }
  }
  function updateListStatus() {
    setText(listStatus, listError || listNotice);
  }
  function reportRegistrationResult(message) {
    registrationResult = message;
    setText(status, message);
    setText(registrationNotice, message);
  }
  function renderTypes() {
    knownTypes.replaceChildren(...types.map((item) => { const option = el("option", ""); option.value = item.name; option.label = item.detector; return option; }));
  }
  function renderDocks() {
    list.replaceChildren();
    list.hidden = !docksLoaded || !docks.length;
    emptyNote.hidden = !docksLoaded || docks.length > 0;
    if (!docksLoaded) return;
    for (const item of docks) {
      const row = el("li", ""); row.dataset.dockId = item.id;
      row.append(el("span", "", `${item.id} · ${item.type} · ${item.map_id || "맵 없음"}`));
      const deleting = pendingDeletes.has(item.id);
      // D-371 — 목록 행은 조용한 `삭제…`다. 위험 채움은 확인 대화상자의 실행 버튼에만 있다.
      const remove = el("ui-button", "", deleting ? "삭제 중…" : "삭제…"); remove.setAttribute("kind", "quiet"); remove.type = "button";
      remove.disabled = deleting;
      remove.addEventListener("click", async () => {
        if (pendingDeletes.has(item.id) || !docksLoaded) return;
        const confirmed = await confirmIrreversible({message: `"${item.id}" 도크를 삭제할까요? 되돌릴 수 없습니다.`, action: "도크 삭제",
          opener: () => (remove.isConnected ? remove : list.querySelector(`li[data-dock-id="${CSS.escape(String(item.id))}"] ui-button`))});
        if (!confirmed || pendingDeletes.has(item.id) || !docksLoaded) return;
        pendingDeletes.add(item.id);
        listNotice = ""; updateListStatus();
        renderDocks();
        try {
          await ctx.api(`/api/v1/docking/docks/${encodeURIComponent(item.id)}`, {method: "DELETE"});
          listNotice = `${item.id} 도크를 삭제했습니다.`;
          docks = docks.filter((dock) => dock.id !== item.id);
        } catch (error) { listNotice = `도크 삭제 실패: ${error.message}`; }
        finally { pendingDeletes.delete(item.id); renderDocks(); }
        updateListStatus();
      });
      row.append(remove); list.append(row);
    }
  }
  const stopTypes = ctx.store.poll("/api/v1/docking/types", 10_000, ({types: rows = []}) => {
    types = rows; typesLoaded = true; typesError = null; renderTypes();
    updateDetectorFields();
    updateRegistrationReadiness();
  }, (error) => { typesLoaded = false; typesError = error.message; updateRegistrationReadiness(); });
  const stopState = ctx.store.poll("/api/v1/robot/state", 1_000, (state) => {
    poseFresh = new HeadlessState(state).isFresh("pose"); pose = state;
    poseError = null;
    updateRegistrationReadiness();
  }, (error) => { poseFresh = false; pose = null; poseError = error.message; updateRegistrationReadiness(); });
  const stopDocks = ctx.store.poll("/api/v1/docking/docks", 10_000, ({docks: rows = []}) => {
    docks = rows; docksLoaded = true; listError = null; renderDocks(); updateListStatus();
  }, (error) => {
    docks = []; docksLoaded = false;
    listError = `도크 목록을 읽지 못했습니다: ${error.message} · 복구될 때까지 등록 위치와 삭제 조작을 숨겼습니다. 다시 확인 중입니다.`;
    renderDocks(); updateListStatus();
  });

  function updateDetectorFields() {
    const existingType = types.some((item) => item.name === typeField.control.value.trim());
    detectorLabel.hidden = existingType;
    detector.required = !existingType;
    const needsTag = !existingType && detector.value === "observation";
    tag.control.required = needsTag; tagSize.control.required = needsTag;
    tag.label.hidden = tagSize.label.hidden = !needsTag;
  }
  detector.addEventListener("change", updateDetectorFields);
  typeField.control.addEventListener("input", updateDetectorFields);
  for (const control of [idField.control, typeField.control, detector, tag.control, tagSize.control]) {
    control.addEventListener("input", () => {
      registrationResult = "";
      setText(registrationNotice, "");
      updateRegistrationReadiness();
    });
    control.addEventListener("change", () => {
      registrationResult = "";
      setText(registrationNotice, "");
      updateRegistrationReadiness();
    });
  }
  updateDetectorFields();
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!poseFresh || !pose || pending) { status.textContent = "pose 수신이 확인될 때까지 기다리세요."; return; }
    const dockId = idField.control.value.trim(); const typeName = typeField.control.value.trim();
    if (!dockId) { reportRegistrationResult("도크 ID를 입력하세요."); idField.control.focus(); return; }
    if (!typeName) { reportRegistrationResult("도크 유형 이름을 입력하세요."); typeField.control.focus(); return; }
    const existingType = types.find((item) => item.name === typeName);
    if (!existingType && !detector.value) { reportRegistrationResult("새 유형에는 검출기 종류를 선택하세요."); detector.focus(); return; }
    if (!existingType && detector.value === "observation" && !tag.control.value) { reportRegistrationResult("태그 관측 유형에는 태그 ID가 필요합니다."); tag.control.focus(); return; }
    if (!existingType && detector.value === "observation" && !tagSize.control.value) { reportRegistrationResult("태그 관측 유형에는 태그 크기가 필요합니다."); tagSize.control.focus(); return; }
    if (!window.confirm(`${dockId} 도크를 현재 위치에 등록할까요? 현재 위치가 실제 도크에 정확히 맞는지 확인하세요.`)) return;
    pending = true; updateRegistrationReadiness();
    registrationResult = "";
    setText(registrationNotice, "");
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
      reportRegistrationResult(`${dockId} 도크를 등록했습니다.`); idField.control.value = "";
    } catch (error) { reportRegistrationResult(`도크 등록 실패${createdType ? " (유형은 저장됐습니다. 같은 유형으로 다시 시도할 수 있습니다)" : ""}: ${error.message}`); }
    finally { pending = false; updateRegistrationReadiness(); }
  });
  return () => { stopTypes(); stopState(); stopDocks(); };
}
