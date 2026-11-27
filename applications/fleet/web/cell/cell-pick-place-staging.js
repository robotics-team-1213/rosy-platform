// 2-click confirmed one-shot target-object staging bar for OMX inspector (/console & /console/cell).
import { setOffBy } from "/common/cause-line.js";
import { node } from "/common/control-dom.js";
import { isObjectSnapshotFresh, objectsForCamView } from "/console/assets/cell-cam-objects.js";

const DEST_OPTIONS_BY_CELL = {
  cell_s: [["belt", "벨트 (belt)"], ["belt-in", "벨트 공급 (belt-in)"]],
  cell_ab: [["stand", "반출대 (stand)"], ["belt", "벨트 (belt)"], ["pallet", "팔레트 (pallet)"]],
};

function buildObjectStagingBar({
  cellId = "cell_ab", snap = null, objects = [], selectedObject = null, selectedDest = null,
  opReason = "", busy = false, statusText = "", nowMs = null,
  onSelectDest = () => {}, onClear = () => {}, onDispatch = () => {},
} = {}) {
  if (!selectedObject && !objects.length && !statusText) return null;
  const wrap = node("div", "", "cell-obj-staging");
  wrap.setAttribute("role", "region");
  wrap.setAttribute("aria-label", "선택 객체 1회 집기·놓기");

  const status = node("p", "", "cell-obj-staging-status");
  status.setAttribute("role", "status");
  status.setAttribute("aria-live", "polite");

  const renderedAt = Date.now();
  const clickNow = () => (nowMs == null ? Date.now() : nowMs + Math.max(0, Date.now() - renderedAt));
  const fresh = isObjectSnapshotFresh(snap, clickNow());
  if (!selectedObject) {
    status.textContent = statusText || `카탈로그 객체 ${objects.length}개 감지됨 — 상단 카메라에서 객체를 클릭해 ① 집기 대상을 선택하세요.`;
    wrap.append(status);
    return wrap;
  }

  const metaTxt = `① ${selectedObject.catalog_id} (${selectedObject.site}) · [${selectedObject.centre_mm?.join(", ")}] mm · tol ${selectedObject.bind_tol_mm ?? 13.5} mm`;
  let lockReason = opReason || "";
  if (!fresh) lockReason = "관측 만료(5초 초과) · 최신 프레임 수신 후 실행 가능";
  else if (!selectedObject.pickable) lockReason = `집기 제한: ${selectedObject.veto_reason || "선택 불가"}`;
  else if (busy) lockReason = "요청 처리 중";

  status.textContent = statusText || (lockReason ? `${metaTxt} — ${lockReason}` : metaTxt);
  wrap.append(status);

  const controls = node("div", "", "cell-obj-staging-controls");
  const field = node("label", "", "omx-inspector-field");
  field.append(node("span", "② 놓을 목적지"));
  const select = node("select");
  select.className = "ui-field";
  select.setAttribute("aria-label", "② 놓을 목적지");
  select.setAttribute("data-obj-dest", "true");
  const opts = DEST_OPTIONS_BY_CELL[cellId] || DEST_OPTIONS_BY_CELL.cell_ab;
  const activeDest = opts.some(([val]) => val === selectedDest) ? selectedDest : opts[0][0];
  for (const [val, label] of opts) {
    const opt = node("option", label);
    opt.value = val;
    if (val === activeDest) opt.selected = true;
    select.append(opt);
  }
  select.addEventListener("change", () => onSelectDest(select.value));
  field.append(select);

  const execBtn = node("ui-button", "1회 집기·놓기 요청");
  execBtn.setAttribute("kind", "primary");
  execBtn.setAttribute("type", "button");
  execBtn.setAttribute("data-obj-dispatch", "true");
  if (lockReason) setOffBy(execBtn, lockReason);
  execBtn.addEventListener("click", () => {
    if (execBtn.disabled || execBtn.hasAttribute("disabled")) return;
    if (!isObjectSnapshotFresh(snap, clickNow())) {
      const msg = "관측 만료(5초 초과) · 최신 프레임 수신 후 실행 가능";
      setOffBy(execBtn, msg);
      status.textContent = `${metaTxt} — ${msg}`;
      return;
    }
    const destSite = select.value || activeDest;
    onDispatch({
      cellId,
      armId: snap?.arm_id || (cellId === "cell_s" ? "arm_s" : "arm_a"),
      snap,
      object: selectedObject,
      destSite,
      button: execBtn,
      buildTaskBody: (robotId = null) => buildTargetObjectTaskBody({
        cellId,
        armId: snap?.arm_id || (cellId === "cell_s" ? "arm_s" : "arm_a"),
        snap,
        object: selectedObject,
        destSite,
        robotId,
      }),
    });
  });

  const clearBtn = node("ui-button", "선택 해제");
  clearBtn.setAttribute("kind", "quiet");
  clearBtn.setAttribute("type", "button");
  clearBtn.setAttribute("data-obj-clear", "true");
  clearBtn.addEventListener("click", () => onClear());

  controls.append(field, execBtn, clearBtn);
  wrap.append(controls);
  return wrap;
}

function buildTargetObjectTaskBody({ cellId, armId, snap, object, destSite, robotId = null }) {
  return {
    cell_id: cellId,
    arm_id: armId,
    src_site: object.site,
    dst_site: destSite,
    propose: false,
    ...(robotId ? { robot_id: robotId } : {}),
    target_object: {
      object_ref: object.object_ref, catalog_id: object.catalog_id, site: object.site,
      centroid_mm: object.centre_mm, observed_at: snap.observed_at,
      ttl_s: snap.ttl_s ?? 15.0, tolerance_mm: object.bind_tol_mm ?? 13.5,
      ...(snap.source_seq != null ? { source_seq: snap.source_seq } : {}),
      ...(snap.cell_state_gen != null ? { expected_cell_state_gen: snap.cell_state_gen } : {}),
    },
  };
}

export function buildInspectorStagingBar(camView, cellObjects, {
  selectedRef = null, selectedDest = null, opReason = "", busy = false, statusText = "",
  nowMs = null, onSelectDest = () => {}, onClear = () => {}, onDispatch = () => {},
} = {}) {
  const views = Array.isArray(camView) ? camView : [camView];
  const resolved = views.map((v) => objectsForCamView(v, cellObjects)).find((r) => r.cellId && r.snap) || objectsForCamView(views[0], cellObjects);
  const { cellId, snap, objects } = resolved;
  if (!cellId || (!objects.length && !statusText)) return null;
  const selectedObject = objects.find((o) => o.object_ref === selectedRef) || null;
  return buildObjectStagingBar({
    cellId, snap, objects, selectedObject, selectedDest, opReason, busy, statusText, nowMs,
    onSelectDest, onClear, onDispatch,
  });
}
