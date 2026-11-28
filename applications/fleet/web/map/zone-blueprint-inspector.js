// Interactive 2D/3D Zone Blueprint Inspector overlay (D-371: fixed below ui-topbar so #estop stays live).
import { setOffBy } from "/common/cause-line.js";
import { OPERATOR_REASON } from "/console/assets/authorization.js";
import { tripErrorText } from "/console/assets/trip-display.js";
import { createZoneBlueprint2d } from "./zone-blueprint-2d.js";
import { createZoneBlueprint3d } from "./zone-blueprint-3d.js";
import {
  buildZoneBlueprintModel,
  formatZoneDetailRows,
  resolveBlueprintTarget,
} from "./zone-blueprint-model.js";
import {
  SLOT_STATUS_LABEL,
  buildBlueprintSlotOverlays,
  buildCellStagePayload,
} from "./zone-blueprint-staging.js";

const CATEGORIES = [
  { id: "all", label: "전체" },
  { id: "stop", label: "차량 정류장" },
  { id: "staging", label: "임시 대기칸" },
  { id: "export", label: "반출대" },
  { id: "arm_zone", label: "팔 셀 구역" },
];

const PRESET_NAMES = [
  { id: "iso", label: "등각" },
  { id: "top", label: "위" },
  { id: "front", label: "앞" },
  { id: "side", label: "옆" },
];

function mk(tag, className, text) {
  const el = document.createElement(tag);
  if (className) el.className = className;
  if (text !== undefined) el.textContent = text;
  return el;
}

function uiBtn(text, kind, attrs = {}) {
  const b = mk("ui-button", "", text);
  b.setAttribute("kind", kind);
  b.setAttribute("type", "button");
  b.setAttribute("data-work-read", "");
  for (const [k, v] of Object.entries(attrs)) b.setAttribute(k, String(v));
  return b;
}

export function createZoneBlueprintInspector({
  scope,
  call,
  log,
  confirmedAction = null,
  isOperator = () => false,
  namedReason = () => "",
} = {}) {
  const panel = mk("section", "panel zone-blueprint-panel");
  panel.id = "zone-blueprint-panel";
  panel.setAttribute("role", "dialog");
  panel.setAttribute("aria-modal", "false");
  panel.setAttribute("aria-labelledby", "zone-blueprint-heading");
  panel.hidden = true;

  const head = mk("div", "zb-panel-head");
  const titleWrap = mk("div", "zb-panel-title");
  const heading = mk("h2", "", "구역 도면 · 2D/3D");
  heading.id = "zone-blueprint-heading";
  const statusTag = mk("ui-tag", "", "대기");
  statusTag.setAttribute("status", "neutral");
  titleWrap.append(heading, statusTag);

  const actions = mk("div", "zb-panel-actions");
  const mode2dBtn = uiBtn("2D 도면", "segment", { "aria-pressed": "true" });
  const mode3dBtn = uiBtn("3D 도면", "segment", { "aria-pressed": "false" });
  const presetBar = mk("div", "zb-presets");
  presetBar.hidden = true;
  for (const p of PRESET_NAMES) {
    const pBtn = uiBtn(p.label, "quiet");
    pBtn.dataset.preset = p.id;
    presetBar.append(pBtn);
  }
  const refreshBtn = uiBtn("새로고침", "quiet");
  const closeBtn = uiBtn("닫기", "quiet");
  actions.append(mode2dBtn, mode3dBtn, presetBar, refreshBtn, closeBtn);
  head.append(titleWrap, actions);

  const tabs = mk("div", "zb-tabs");
  tabs.setAttribute("role", "tablist");
  tabs.setAttribute("aria-label", "구역 종류");
  const tabBtns = CATEGORIES.map((c, idx) => {
    const btn = uiBtn(c.label, "segment", {
      role: "tab",
      "aria-selected": String(idx === 0),
    });
    btn.className = "zb-tab";
    btn.dataset.category = c.id;
    tabs.append(btn);
    return btn;
  });

  const body = mk("div", "zb-body");
  const listEl = mk("ul", "zb-list");
  listEl.setAttribute("aria-label", "구역 목록");
  const stageEl = mk("div", "zb-stage");
  const detailWrap = mk("aside", "zb-detail-wrap");
  const detailTitle = mk("h3", "", "선택 구역 상세");
  const detailDl = mk("dl", "zb-detail");
  const stageBox = mk("div", "zb-stage-box");
  const stageHead = mk("div", "zb-stage-head");
  const stageTitle = mk("h3", "", "셀 작업 지정");
  const stageToggleBtn = mk("ui-button", "", "2클릭 작업 지정");
  stageToggleBtn.setAttribute("kind", "segment");
  stageToggleBtn.setAttribute("type", "button");
  stageToggleBtn.setAttribute("data-work-read", "");
  stageToggleBtn.setAttribute("aria-pressed", "false");
  stageToggleBtn.dataset.zbStageToggle = "";
  stageHead.append(stageTitle, stageToggleBtn);

  const stageControls = mk("div", "zb-stage-controls");
  const tierLabel = mk("label", "ui-field-label zb-stage-tier-label");
  tierLabel.append(mk("span", "", "적재 층"));
  const tierSelect = mk("select", "ui-field");
  tierSelect.setAttribute("aria-label", "적재 층");
  tierSelect.setAttribute("data-work-read", "");
  tierSelect.dataset.zbStageTier = "";
  for (const [val, label] of [["1", "1단"], ["2", "2단"], ["3", "3단"]]) {
    const opt = mk("option", "", label);
    opt.value = val;
    tierSelect.append(opt);
  }
  tierLabel.append(tierSelect);
  const stageResetBtn = mk("ui-button", "", "선택 초기화");
  stageResetBtn.setAttribute("kind", "quiet");
  stageResetBtn.setAttribute("type", "button");
  stageResetBtn.setAttribute("data-work-read", "");
  stageResetBtn.dataset.zbStageReset = "";
  const stageSubmitBtn = mk("ui-button", "", "셀 작업 지시…");
  stageSubmitBtn.setAttribute("kind", "primary");
  stageSubmitBtn.setAttribute("type", "button");
  stageSubmitBtn.dataset.zbStageSubmit = "";
  stageControls.append(tierLabel, stageResetBtn, stageSubmitBtn);
  const stageSummary = mk("p", "zb-stage-summary", "2클릭 작업 지정 버튼을 누른 뒤 도면에서 출발과 도착 슬롯을 순서대로 선택하세요.");
  const stageResult = mk("p", "zb-stage-result");
  stageResult.hidden = true;
  stageBox.append(stageHead, stageControls, stageSummary, stageResult);

  const checkTitle = mk("h3", "", "지도 검사");
  const checkList = mk("ul", "zb-check-list");
  checkList.setAttribute("aria-label", "겹침과 여유 확인");
  const statusNote = mk("p", "hint zb-status-note", "열면 최신 YAML·활성 지도를 불러옵니다.");
  detailWrap.append(detailTitle, detailDl, stageBox, checkTitle, checkList, statusNote);
  body.append(listEl, stageEl, detailWrap);
  panel.append(head, tabs, body);
  document.body.append(panel);

  let mode = "2d";
  let filterCategory = "all";
  let selectedId = null;
  let model = buildZoneBlueprintModel();
  let guideData = null;
  let view2d = null;
  let view3d = null;
  let returnFocusTo = null;
  let stagingMode = false;
  let stagedSrc = null;
  let stagedDst = null;
  let stageBusy = false;
  let stageNotice = null;

  const currentSlots = () => buildBlueprintSlotOverlays(model, guideData).slots;
  const syncSlotSelection = (slot) => {
    if (!slot) return null;
    return currentSlots().find((s) => s.id === slot.id) || slot;
  };

  function paintStaging() {
    stageToggleBtn.setAttribute("aria-pressed", String(stagingMode));
    const src = syncSlotSelection(stagedSrc);
    const dst = syncSlotSelection(stagedDst);
    stagedSrc = src;
    stagedDst = dst;

    const srcName = src ? `${src.label} (${SLOT_STATUS_LABEL[src.status] || "확인 필요"})` : "미선택";
    const dstName = dst ? `${dst.label} (${SLOT_STATUS_LABEL[dst.status] || "확인 필요"})` : "미선택";
    if (!stagingMode && !src && !dst) {
      stageSummary.textContent = "2클릭 작업 지정을 켜고 출발 슬롯과 도착 슬롯을 차례로 클릭하세요.";
    } else {
      const hasUnverified = src?.status === "planned_unverified" || dst?.status === "planned_unverified";
      const suffix = hasUnverified ? " · 계획(실측 대기) 자리 포함" : "";
      stageSummary.textContent = `출발: ${srcName} -> 도착: ${dstName}${suffix}`;
    }

    const { error } = buildCellStagePayload({ src, dst, tier: Number(tierSelect.value || 1) });
    const roleReason = !isOperator() ? OPERATOR_REASON : namedReason();
    const disableWhy = !confirmedAction
      ? "실행 확인 경로를 사용할 수 없습니다."
      : stageBusy
        ? "셀 작업을 등록하는 중입니다."
        : (roleReason || error);
    setOffBy(stageSubmitBtn, disableWhy);
    setOffBy(stageResetBtn, !src && !dst ? "선택된 슬롯이 없습니다." : "");

    if (stageNotice) {
      stageResult.hidden = false;
      stageResult.textContent = stageNotice.text;
      stageResult.dataset.kind = stageNotice.kind;
      stageResult.setAttribute("role", stageNotice.kind === "bad" ? "alert" : "status");
    } else {
      stageResult.hidden = true;
      stageResult.textContent = "";
    }
  }

  const onSelectZone = (id) => {
    selectedId = id;
    paint();
  };

  const onSelectSlot = (slot) => {
    if (slot.zoneId) selectedId = slot.zoneId;
    if (stagingMode) {
      if (!stagedSrc || (stagedSrc && stagedDst)) {
        stagedSrc = slot;
        stagedDst = null;
      } else if (stagedSrc.id === slot.id) {
        stagedSrc = null;
      } else {
        stagedDst = slot;
      }
      stageNotice = null;
    }
    paint();
  };

  async function submitStageTask() {
    const src = syncSlotSelection(stagedSrc);
    const dst = syncSlotSelection(stagedDst);
    const { payload, error } = buildCellStagePayload({ src, dst, tier: Number(tierSelect.value || 1) });
    if (error || !payload || !confirmedAction) return;
    const key = globalThis.crypto.randomUUID();
    await confirmedAction.run({
      message: `도면에서 지정한 셀 작업(${payload.src_site} -> ${payload.dst_site}, ${payload.tier}단)을 큐에 등록할까요?`,
      opener: stageSubmitBtn,
      eligible: () => !stageBusy && isOperator() && !namedReason() && Boolean(buildCellStagePayload({ src: stagedSrc, dst: stagedDst, tier: Number(tierSelect.value || 1) }).payload),
      request: async (owner) => {
        stageBusy = true;
        stageNotice = null;
        paintStaging();
        try {
          const res = await call("/api/fleet/pipeline/cell-tasks", {
            method: "POST",
            signals: [owner.signal],
            headers: { "Content-Type": "application/json", "Idempotency-Key": key },
            body: JSON.stringify(payload),
          });
          owner.check();
          const taskId = res?.task?.task_id || res?.tasks?.[0]?.task_id || "등록됨";
          stageNotice = { text: `셀 작업 등록 완료: ${taskId} (${payload.src_site} -> ${payload.dst_site})`, kind: "good" };
          log?.(stageNotice.text, "good");
          stagedSrc = null;
          stagedDst = null;
          stagingMode = false;
          void loadData(selectedId);
        } finally {
          stageBusy = false;
          paintStaging();
        }
      },
      onError: (err) => {
        if (err?.name === "AbortError") return;
        const code = err?.detail?.code || err?.code;
        const detail = code ? tripErrorText(code, err.detail) : (err?.message || "요청 실패");
        stageNotice = { text: `셀 작업 등록 거절: ${detail}`, kind: "bad" };
        log?.(stageNotice.text, "bad");
        paintStaging();
      },
    });
  }

  function paint() {
    if (panel.hidden) return;
    mode2dBtn.setAttribute("aria-pressed", String(mode === "2d"));
    mode3dBtn.setAttribute("aria-pressed", String(mode === "3d"));
    presetBar.hidden = mode !== "3d";
    for (const btn of tabBtns) {
      btn.setAttribute("aria-selected", String(btn.dataset.category === filterCategory));
    }
    const visibleItems = filterCategory === "all"
      ? model.items
      : model.items.filter((item) => item.category === filterCategory);
    if (!visibleItems.some((item) => item.id === selectedId)) {
      selectedId = visibleItems[0]?.id || model.items[0]?.id || null;
    }

    listEl.replaceChildren(...visibleItems.map((item) => {
      const li = mk("li");
      const flagged = item.footprintId ? model.conflictsOf(item.footprintId).length : 0;
      const btn = uiBtn(`${item.label}\n${item.subtitle}${flagged ? `\n겹침·여유 확인 ${flagged}건` : ""}`, "quiet", {
        "data-selected": String(item.id === selectedId),
      });
      btn.className = "zb-list-btn";
      btn.addEventListener("click", () => onSelectZone(item.id));
      li.append(btn);
      return li;
    }));

    const selectedItem = model.items.find((item) => item.id === selectedId) || null;
    const rows = formatZoneDetailRows(selectedItem, model);
    detailDl.replaceChildren(...rows.flatMap((row) => [mk("dt", "", row.term), mk("dd", "", row.value)]));
    const selectedFootprint = selectedItem?.footprintId || null;
    const ordered = [...model.conflicts].sort((a, b) =>
      Number(b.ids.includes(selectedFootprint)) - Number(a.ids.includes(selectedFootprint)));
    checkList.replaceChildren(...(ordered.length ? ordered : [{ kind: "ok", text: "겹침 없음" }]).map((entry) => {
      const li = mk("li", entry.kind === "overlap" ? "zb-check-crit" : entry.kind === "near" || entry.kind === "stale_yaml" ? "zb-check-warn" : "");
      li.textContent = entry.text;
      return li;
    }));

    if (mode === "3d") {
      view2d?.dispose?.();
      view2d = null;
      view3d ||= createZoneBlueprint3d(stageEl, { onSelect: onSelectZone });
      void view3d.render(model, selectedId, filterCategory);
    } else {
      view3d?.dispose?.();
      view3d = null;
      view2d ||= createZoneBlueprint2d(stageEl, { onSelect: onSelectZone, onSelectSlot });
      view2d.render(model, selectedId, filterCategory, {
        guide: guideData,
        staged: { src: stagedSrc, dst: stagedDst },
      });
    }
    paintStaging();
  }

  async function loadData(initialQuery = null) {
    const life = scope?.capture?.();
    statusTag.setAttribute("status", "neutral");
    statusTag.textContent = "불러오는 중";
    const opts = life ? { signal: life.signal } : {};
    const [spRes, szRes, ctRes, smRes, gdRes] = await Promise.allSettled([
      call("/api/fleet/site-points?view=full", opts),
      call("/api/fleet/pipeline/station-zones", opts),
      call("/api/fleet/pipeline/cell-tasks", opts),
      call("/api/fleet/site-map/active", opts),
      call("/api/fleet/guide", opts),
    ]);
    if (panel.hidden) return;
    const sitePoints = spRes.status === "fulfilled" ? spRes.value : null;
    const stationZones = szRes.status === "fulfilled" ? szRes.value : null;
    const cellTasks = ctRes.status === "fulfilled" ? ctRes.value : null;
    // Without an active map (404/409) the zones are still listed; only the lanes are missing.
    const siteMap = smRes.status === "fulfilled" ? smRes.value : null;
    guideData = gdRes.status === "fulfilled" ? gdRes.value : null;
    model = buildZoneBlueprintModel({ sitePoints, stationZones, cellTasks, siteMap });

    if (!sitePoints && !stationZones) {
      statusTag.setAttribute("status", "warn");
      statusTag.textContent = "응답 대기";
      statusNote.textContent = "site-points·station-zones 응답을 불러오지 못했습니다. 로그인과 Fleet 연결을 확인하세요.";
      log?.("구역 도면 조회 실패: site-points / station-zones 응답 없음", "warn");
    } else {
      const overlaps = model.conflicts.filter((conflict) => conflict.kind === "overlap").length;
      statusTag.setAttribute("status", overlaps ? "warn" : "active");
      statusTag.textContent = `${model.items.length}개 구역${overlaps ? ` · 겹침 ${overlaps}` : ""}`;
      const areaErrors = stationZones?.area_errors || [];
      statusNote.textContent = [
        `정류장 ${model.stops.length} · 대기칸 ${model.stagingBays.length} · 반출대 ${model.exportStations.length} · 팔 셀 ${model.armZones.length}`,
        model.siteMap
          ? `지도 ${model.siteMap.mapId} v${model.siteMap.version ?? "?"}`
          : "활성 사이트 지도 없음 · 차로를 그리지 못함",
        areaErrors.length ? `영역 오류 ${areaErrors.length}건: ${areaErrors.join("; ")}` : "",
      ].filter(Boolean).join(" · ");
    }
    const target = resolveBlueprintTarget(model, initialQuery);
    if (target) selectedId = target.id;
    paint();
  }

  function close() {
    if (panel.hidden) return;
    panel.hidden = true;
    view2d?.dispose?.();
    view2d = null;
    view3d?.dispose?.();
    view3d = null;
    returnFocusTo?.focus?.();
    returnFocusTo = null;
  }

  function open(initialQuery = null) {
    if (panel.hidden) returnFocusTo = document.activeElement;
    panel.hidden = false;
    paint();
    closeBtn.focus?.();
    void loadData(initialQuery);
  }

  mode2dBtn.addEventListener("click", () => { mode = "2d"; paint(); });
  mode3dBtn.addEventListener("click", () => { mode = "3d"; paint(); });
  presetBar.addEventListener("click", (ev) => {
    const preset = ev.target?.closest?.("[data-preset]")?.dataset?.preset;
    if (preset) view3d?.setPreset?.(preset);
  });
  for (const btn of tabBtns) {
    btn.addEventListener("click", () => {
      filterCategory = btn.dataset.category;
      paint();
    });
  }
  refreshBtn.addEventListener("click", () => { void loadData(selectedId); });
  closeBtn.addEventListener("click", close);
  stageToggleBtn.addEventListener("click", () => {
    stagingMode = !stagingMode;
    stageNotice = null;
    paint();
  });
  stageResetBtn.addEventListener("click", () => {
    stagedSrc = null;
    stagedDst = null;
    stageNotice = null;
    paint();
  });
  tierSelect.addEventListener("change", () => paintStaging());
  stageSubmitBtn.addEventListener("click", () => { void submitStageTask(); });

  scope?.listen?.(document, "keydown", (ev) => {
    if (ev.key === "Escape" && !panel.hidden) {
      ev.preventDefault();
      close();
    }
  });
  scope?.listen?.(document, "rosy:theme", () => {
    if (!panel.hidden && mode === "3d") view3d?.redrawTheme?.();
  });
  scope?.onDispose?.(() => {
    close();
    panel.remove();
  });

  return {
    open,
    close,
    isOpen: () => !panel.hidden,
    dispose: () => { close(); panel.remove(); },
  };
}
