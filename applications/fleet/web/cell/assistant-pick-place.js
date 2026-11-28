import { setOff } from "/common/cause-line.js";
import { isObjectSnapshotFresh } from "/console/assets/cell-cam-objects.js";
import { DEST_OPTIONS_BY_CELL, buildTargetObjectTaskBody } from "/console/assets/cell-pick-place-staging.js";
import { elOf } from "/console/assets/assistant-command.js";

export function flattenCatalogObjects(cellObjects, nowMs = Date.now()) {
  const out = [];
  if (!cellObjects || typeof cellObjects !== "object") return out;
  const cells = cellObjects.cells && typeof cellObjects.cells === "object" ? cellObjects.cells : {};
  for (const cellId of Object.keys(cells).sort()) {
    const arms = cells[cellId]?.arms || {};
    for (const armId of Object.keys(arms).sort()) {
      const rawSnap = arms[armId];
      if (!rawSnap || typeof rawSnap !== "object") continue;
      const snap = cellObjects.fetchedAtMs !== undefined && rawSnap.fetchedAtMs === undefined
        ? { ...rawSnap, fetchedAtMs: cellObjects.fetchedAtMs } : rawSnap;
      if (!isObjectSnapshotFresh(snap, nowMs)) continue;
      const objs = [...(snap.objects || [])]
        .filter((o) => o && typeof o.catalog_id === "string" && o.catalog_id && o.catalog_id.toLowerCase() !== "unmatched")
        .sort((a, b) => `${a.catalog_id}\0${a.object_ref}`.localeCompare(`${b.catalog_id}\0${b.object_ref}`));
      for (const object of objs) out.push({ cellId, armId: snap.arm_id || armId, snap, object });
    }
  }
  return out;
}

export function createAssistantObjectsBridge({ scope, call, objectHighlight = null, getIdentity = () => null, onChange = () => {} }) {
  let cellObjects = null;
  let panelOpen = false;
  if (objectHighlight?.subscribe) scope?.onDispose?.(objectHighlight.subscribe(() => onChange()));
  async function refresh() {
    const owner = getIdentity();
    if (!owner) return;
    try {
      const data = await call("/api/fleet/pipeline/cell-objects");
      if (getIdentity() !== owner) return;
      cellObjects = { ...(data || {}), fetchedAtMs: Date.now() };
      onChange();
    } catch { /* Cell objects endpoint is optional when no cell vision is attached */ }
  }
  scope?.interval?.(() => { if (panelOpen && !document.hidden) void refresh(); }, 2500);
  return {
    get: () => cellObjects,
    setOpen(open) { panelOpen = Boolean(open); if (panelOpen) void refresh(); },
    refresh,
  };
}

export async function dispatchAssistantPickPlace({ call, dialogue, row, payload, owner = null, log = null, randomUUID, onRender = () => {} }) {
  dialogue.patchNav(row.request_id, { objSubmitting: true, objError: "" });
  onRender();
  try {
    const receipt = await call("/api/fleet/pipeline/cell-tasks", {
      method: "POST",
      headers: { "Content-Type": "application/json", "Idempotency-Key": randomUUID() },
      body: JSON.stringify(payload.buildTaskBody()),
      signals: owner?.signal ? [owner.signal] : [],
    });
    if (owner && !owner.current()) return;
    dialogue.patchNav(row.request_id, { objSubmitting: false, objReceipt: receipt, objError: "" });
    log?.(`관제 AI 1회 집기·놓기 등록: ${payload.object.catalog_id} → ${payload.destSite}`, "good");
  } catch (error) {
    if (error?.name === "AbortError") throw error;
    dialogue.patchNav(row.request_id, { objSubmitting: false, objError: error?.message || "1회 집기·놓기 요청이 거부되었습니다." });
    throw error;
  } finally {
    onRender();
  }
}

export function renderObjectPickPlaceCard({
  row, cellObjects = null, highlightedRef = null, executionEnabled = false, available = false,
  identity = null, receipt = null, errorText = "", submitting = false, draft = null, nowMs = null,
  onHighlightObject = null, onDraftChange = null, onSubmit = null,
} = {}) {
  const hasObjFacts = Boolean(row?.facts?.some((f) => String(f?.ref || "").startsWith("cell_objects:")));
  if (!row || row.state !== "ANSWERED" || (!receipt && row.kind !== "CONTROL" && row.kind !== "CLARIFY" && !hasObjFacts)) return null;
  const card = elOf("div", "assistant-command-card assistant-obj-card");
  if (receipt) {
    const box = elOf("div", "assistant-receipt"), link = elOf("a", "ui-action-link", "셀 작업 화면에서 확인");
    box.setAttribute("role", "status");
    link.href = "/console/cell";
    box.append(
      elOf("strong", "", "1회 집기·놓기 작업이 큐에 등록되었습니다."),
      elOf("small", "", `작업 ${receipt?.task?.task_id || "—"} · 대상 ${receipt?.task?.arm_id || receipt?.task?.cell_id || "—"} · 상태 ${receipt?.task?.status || "QUEUED"}`),
      link,
    );
    card.append(box);
    return card;
  }

  const renderedAt = Date.now();
  const clickNow = () => (nowMs == null ? Date.now() : nowMs + Math.max(0, Date.now() - renderedAt));
  const entries = flattenCatalogObjects(cellObjects, clickNow());
  if (!entries.length) return null;

  const active = entries.find((e) => highlightedRef && e.object.object_ref === highlightedRef)
    || entries.find((e) => draft?.objectRef && e.object.object_ref === draft.objectRef)
    || entries.find((e) => e.object.pickable) || entries[0];

  const head = elOf("div", "assistant-command-head");
  const tag = elOf("ui-tag", active.object.pickable ? "선택 가능" : "선택 제한");
  tag.setAttribute("variant", "inline");
  tag.setAttribute("status", active.object.pickable && isObjectSnapshotFresh(active.snap, clickNow()) ? "active" : "warn");
  head.append(elOf("strong", "", `셀 카탈로그 객체 (${active.cellId} · ${active.armId})`), tag);
  const meta = elOf("p", "assistant-obj-meta",
    `${active.object.catalog_id} · ${active.object.site} · [${active.object.centre_mm?.join(", ")}] mm · tol ${active.object.bind_tol_mm ?? 13.5} mm`);

  const chips = elOf("div", "assistant-obj-chips");
  for (const entry of entries) {
    const o = entry.object;
    const chip = elOf("button", "assistant-obj-chip", `${o.catalog_id} (${o.site})${o.pickable ? "" : ` · ${o.veto_reason || "제한"}`}`);
    chip.type = "button";
    chip.dataset.assistantObjChip = o.object_ref;
    chip.setAttribute("aria-pressed", String(entry === active && o.pickable));
    if (!o.pickable) setOff(chip, true, o.veto_reason || "제한");
    chip.addEventListener("click", () => {
      if (!o.pickable || !isObjectSnapshotFresh(entry.snap, clickNow())) return;
      onHighlightObject?.(o.object_ref);
      onDraftChange?.({ ...(draft || {}), objectRef: o.object_ref });
    });
    chips.append(chip);
  }

  const opts = DEST_OPTIONS_BY_CELL[active.cellId] || DEST_OPTIONS_BY_CELL.cell_ab;
  const activeDest = opts.some(([val]) => val === draft?.destSite) ? draft.destSite : opts[0][0];
  const destField = elOf("label", "assistant-nav-field"), select = elOf("select", "ui-field");
  select.dataset.assistantObjDest = "true";
  for (const [val, label] of opts) {
    const opt = elOf("option", "", label);
    opt.value = val;
    if (val === activeDest) opt.selected = true;
    select.append(opt);
  }
  select.addEventListener("change", () => onDraftChange?.({ ...(draft || {}), objectRef: active.object.object_ref, destSite: select.value }));
  destField.append(elOf("span", "", "놓을 목적지"), select);

  const actions = elOf("div", "assistant-command-actions"), submitBtn = document.createElement("ui-button");
  submitBtn.textContent = submitting ? "요청 중…" : "1회 집기·놓기 요청";
  submitBtn.setAttribute("kind", "primary");
  submitBtn.setAttribute("type", "button");
  submitBtn.dataset.assistantObjSubmit = "true";
  const reasonFor = () => (!identity ? "기명 운영자로 로그인해 주세요." : !available ? "관제 AI 연결이 필요합니다."
    : !executionEnabled ? "현재 관제 AI는 조회 전용 모드입니다." : !active.object.pickable ? "선택한 객체는 현재 집기 제한 상태입니다."
    : submitting ? "1회 집기·놓기 요청을 등록 중입니다."
    : !isObjectSnapshotFresh(active.snap, clickNow()) ? "관측 만료(5초 초과) · 최신 프레임 수신 후 실행 가능" : "");
  const initialReason = reasonFor();
  setOff(submitBtn, Boolean(initialReason), initialReason);
  submitBtn.addEventListener("click", () => {
    const locked = reasonFor();
    if (locked) {
      setOff(submitBtn, true, locked);
      return;
    }
    const destSite = select.value || activeDest;
    onSubmit?.({
      cellId: active.cellId, armId: active.armId, snap: active.snap, object: active.object, destSite,
      buildTaskBody: () => buildTargetObjectTaskBody({
        cellId: active.cellId, armId: active.armId, snap: active.snap, object: active.object, destSite,
      }),
    }, submitBtn);
  });
  actions.append(submitBtn);
  card.append(head, meta, chips, destField, actions);
  if (errorText) {
    const err = elOf("p", "hint assistant-nav-error", errorText);
    err.setAttribute("role", "alert");
    card.append(err);
  }
  return card;
}
