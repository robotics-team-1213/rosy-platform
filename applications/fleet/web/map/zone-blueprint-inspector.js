// Interactive 2D/3D Zone Blueprint Inspector overlay (D-371: fixed below ui-topbar so #estop stays live).
import { createZoneBlueprint2d } from "./zone-blueprint-2d.js";
import { createZoneBlueprint3d } from "./zone-blueprint-3d.js";
import {
  buildZoneBlueprintModel,
  formatZoneDetailRows,
  resolveBlueprintTarget,
} from "./zone-blueprint-model.js";

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

export function createZoneBlueprintInspector({ scope, call, log } = {}) {
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
  const statusNote = mk("p", "hint zb-status-note", "열면 최신 YAML·사이트 좌표를 불러옵니다.");
  detailWrap.append(detailTitle, detailDl, statusNote);
  body.append(listEl, stageEl, detailWrap);
  panel.append(head, tabs, body);
  document.body.append(panel);

  let mode = "2d";
  let filterCategory = "all";
  let selectedId = null;
  let model = buildZoneBlueprintModel();
  let view2d = null;
  let view3d = null;
  let returnFocusTo = null;

  const onSelectZone = (id) => {
    selectedId = id;
    paint();
  };

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
      const btn = uiBtn(`${item.label}\n${item.subtitle}`, "quiet", {
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

    if (mode === "3d") {
      view2d?.dispose?.();
      view2d = null;
      view3d ||= createZoneBlueprint3d(stageEl, { onSelect: onSelectZone });
      void view3d.render(model, selectedId, filterCategory);
    } else {
      view3d?.dispose?.();
      view3d = null;
      view2d ||= createZoneBlueprint2d(stageEl, { onSelect: onSelectZone });
      view2d.render(model, selectedId, filterCategory);
    }
  }

  async function loadData(initialQuery = null) {
    const life = scope?.capture?.();
    statusTag.setAttribute("status", "neutral");
    statusTag.textContent = "불러오는 중";
    const opts = life ? { signal: life.signal } : {};
    const [spRes, szRes, ctRes] = await Promise.allSettled([
      call("/api/fleet/site-points", opts),
      call("/api/fleet/pipeline/station-zones", opts),
      call("/api/fleet/pipeline/cell-tasks", opts),
    ]);
    if (panel.hidden) return;
    const sitePoints = spRes.status === "fulfilled" ? spRes.value : null;
    const stationZones = szRes.status === "fulfilled" ? szRes.value : null;
    const cellTasks = ctRes.status === "fulfilled" ? ctRes.value : null;
    model = buildZoneBlueprintModel({ sitePoints, stationZones, cellTasks });

    if (!sitePoints && !stationZones) {
      statusTag.setAttribute("status", "warn");
      statusTag.textContent = "응답 대기";
      statusNote.textContent = "site-points·station-zones 응답을 불러오지 못했습니다. 로그인과 Fleet 연결을 확인하세요.";
      log?.("구역 도면 조회 실패: site-points / station-zones 응답 없음", "warn");
    } else {
      statusTag.setAttribute("status", "active");
      statusTag.textContent = `${model.items.length}개 구역`;
      statusNote.textContent = `정류장 ${model.stops.length} · 대기칸 ${model.stagingBays.length} · 반출대 ${model.exportStations.length} · 팔 셀 ${model.armZones.length}`;
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
