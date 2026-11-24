// DOM-free blueprint model normalizing site-points, station-zones, and cell-tasks.

const CATEGORY_LABEL = Object.freeze({
  stop: "차량 정류장",
  staging: "임시 대기칸",
  export: "반출대",
  arm_zone: "팔 셀 구역",
});

const ROLE_LABEL = Object.freeze({
  load: "상차",
  unload: "하역",
  intake_dropoff: "반입 하역",
  outbound_pickup: "반출 상차",
  outbound_exit: "반출 출구",
  charge: "충전",
  wait: "대기",
  staging: "임시 대기",
  export: "반출",
});

function finiteNum(value) {
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

function normalizeStops(sitePoints) {
  const raw = Array.isArray(sitePoints?.vehicle_stops) ? sitePoints.vehicle_stops : [];
  return raw.map((stop) => ({
    id: String(stop?.id || ""),
    name: String(stop?.name || stop?.id || ""),
    kind: String(stop?.kind || "stop"),
    portRole: stop?.port_role || null,
    x: finiteNum(stop?.pose?.x),
    y: finiteNum(stop?.pose?.y),
    yaw: finiteNum(stop?.pose?.yaw),
    pinned: Boolean(stop?.pinned),
    stopZone: Array.isArray(stop?.stop_zone) ? stop.stop_zone : null,
    approachM: finiteNum(stop?.approach_m),
    rule: stop?.rule || null,
    edgesIn: Array.isArray(stop?.edges_in) ? stop.edges_in : [],
    edgesOut: Array.isArray(stop?.edges_out) ? stop.edges_out : [],
    status: String(stop?.status || "planned_unverified"),
    dispatchable: Boolean(stop?.dispatchable),
    berth: stop?.berth || null,
  })).filter((s) => s.id);
}

function normalizeStagingBays(stationZones) {
  const raw = Array.isArray(stationZones?.staging_bays) ? stationZones.staging_bays : [];
  return raw.map((bay) => ({
    id: String(bay?.id || ""),
    placeId: bay?.place_id ? String(bay.place_id) : "",
    name: String(bay?.name || bay?.id || ""),
    kind: "staging",
    x: finiteNum(bay?.x),
    y: finiteNum(bay?.y),
    yawDeg: finiteNum(bay?.yaw_deg),
    speedCapMps: finiteNum(bay?.speed_cap_mps),
    maxStepM: finiteNum(bay?.max_step_m),
  })).filter((b) => b.id);
}

function normalizeExportStations(stationZones) {
  const raw = Array.isArray(stationZones?.export_stations) ? stationZones.export_stations : [];
  return raw.map((st) => ({
    id: String(st?.id || ""),
    placeId: st?.place_id ? String(st.place_id) : "",
    name: String(st?.name || st?.id || ""),
    kind: "export",
    cellId: st?.cell_id ? String(st.cell_id) : "",
    armId: st?.arm_id ? String(st.arm_id) : "",
    srcSite: st?.src_site ? String(st.src_site) : "",
    dstSite: st?.dst_site ? String(st.dst_site) : "",
    tier: finiteNum(st?.tier) ?? 1,
    x: finiteNum(st?.x),
    y: finiteNum(st?.y),
    yawDeg: finiteNum(st?.yaw_deg),
  })).filter((s) => s.id);
}

function normalizeArmZones(sitePoints) {
  const zonesRaw = Array.isArray(sitePoints?.arm_zones?.zones) ? sitePoints.arm_zones.zones : [];
  return zonesRaw.map((z) => ({
    id: String(z?.id || ""),
    label: String(z?.label || z?.id || ""),
    role: String(z?.role || ""),
    grid: {
      rows: finiteNum(z?.grid?.rows) ?? 1,
      columns: finiteNum(z?.grid?.columns) ?? 1,
      tiers: finiteNum(z?.grid?.tiers) ?? 1,
    },
    slotCells: finiteNum(z?.slot_cells) ?? 1,
    arms: Array.isArray(z?.arms) ? z.arms.map(String) : [],
    status: String(z?.status || "planned_unverified"),
    holdBoundary: z?.hold_boundary || null,
    slots: (Array.isArray(z?.slots) ? z.slots : []).map((slot) => ({
      id: String(slot?.id || ""),
      label: String(slot?.label || slot?.id || ""),
      row: finiteNum(slot?.row) ?? 1,
      slot: finiteNum(slot?.slot) ?? 1,
      columns: Array.isArray(slot?.columns) ? slot.columns.map((c) => Number(c)) : [1, 1],
      hold: slot?.hold ?? null,
      arms: Array.isArray(slot?.arms) ? slot.arms.map(String) : [],
      physical: Array.isArray(slot?.physical) ? slot.physical.map(String) : [],
      tiers: Array.isArray(slot?.tiers) ? slot.tiers.map((t) => ({
        tier: finiteNum(t?.tier) ?? 1,
        id: String(t?.id || ""),
        item: String(t?.item || ""),
      })) : [],
      status: String(slot?.status || z?.status || "planned_unverified"),
    })),
  })).filter((z) => z.id);
}

function normalizeTasks(cellTasks) {
  const list = Array.isArray(cellTasks)
    ? cellTasks
    : (Array.isArray(cellTasks?.tasks) ? cellTasks.tasks : []);
  return list.map((task) => ({
    id: String(task?.task_id || task?.id || ""),
    state: String(task?.state || task?.status || ""),
    srcSite: String(task?.src_site || task?.source || ""),
    dstSite: String(task?.dst_site || task?.target || ""),
    armId: String(task?.arm_id || ""),
    cellId: String(task?.cell_id || ""),
  })).filter((t) => t.id || t.srcSite || t.dstSite);
}

function computeWorldBounds(stops, stagingBays, exportStations) {
  let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
  const include = (x, y) => {
    if (!Number.isFinite(x) || !Number.isFinite(y)) return;
    if (x < minX) minX = x;
    if (x > maxX) maxX = x;
    if (y < minY) minY = y;
    if (y > maxY) maxY = y;
  };
  for (const s of stops) {
    include(s.x, s.y);
    for (const pt of s.stopZone || []) {
      if (Array.isArray(pt) && pt.length >= 2) include(finiteNum(pt[0]), finiteNum(pt[1]));
    }
  }
  for (const b of stagingBays) include(b.x, b.y);
  for (const e of exportStations) include(e.x, e.y);
  if (!Number.isFinite(minX)) return { minX: -1, maxX: 1, minY: -1, maxY: 1 };
  const padX = Math.max(0.25, (maxX - minX) * 0.14);
  const padY = Math.max(0.25, (maxY - minY) * 0.18);
  return { minX: minX - padX, maxX: maxX + padX, minY: minY - padY, maxY: maxY + padY };
}

export function buildZoneBlueprintModel({ sitePoints = null, stationZones = null, cellTasks = null } = {}) {
  const stops = normalizeStops(sitePoints);
  const stagingBays = normalizeStagingBays(stationZones);
  const exportStations = normalizeExportStations(stationZones);
  const armZones = normalizeArmZones(sitePoints);
  const handoffs = Array.isArray(sitePoints?.handoffs) ? sitePoints.handoffs : [];
  const activeTasks = normalizeTasks(cellTasks);
  const aliases = {
    ...(sitePoints?.arm_zones?.aliases || {}),
    legacy_station_zones: {
      ...(sitePoints?.arm_zones?.aliases?.legacy_station_zones || {}),
      ...(sitePoints?.legacy_aliases || {}),
    },
  };
  const items = [
    ...stops.map((s) => ({
      category: "stop",
      id: s.id,
      label: s.name,
      subtitle: `${ROLE_LABEL[s.portRole] || s.kind}${s.status === "verified" ? " · 검증됨" : " · 계획됨"}`,
      x: s.x,
      y: s.y,
      status: s.status,
      raw: s,
    })),
    ...stagingBays.map((b) => ({
      category: "staging",
      id: b.id,
      label: b.name,
      subtitle: b.placeId ? `대기칸 · ${b.placeId}` : "임시 대기칸",
      x: b.x,
      y: b.y,
      status: "configured",
      raw: b,
    })),
    ...exportStations.map((e) => ({
      category: "export",
      id: e.id,
      label: e.name,
      subtitle: `${e.armId || e.cellId || "반출"} · ${e.tier}단`,
      x: e.x,
      y: e.y,
      status: "configured",
      raw: e,
    })),
    ...armZones.map((z) => ({
      category: "arm_zone",
      id: z.id,
      label: z.label,
      subtitle: `${z.grid.rows}×${z.grid.columns}×${z.grid.tiers} · ${z.arms.join(", ") || "셀"}`,
      x: null,
      y: null,
      status: z.status,
      raw: z,
    })),
  ];
  return {
    stops,
    stagingBays,
    exportStations,
    armZones,
    tierHeightMm: finiteNum(sitePoints?.arm_zones?.tier_height_mm) ?? 32.4,
    handoffs,
    activeTasks,
    aliases,
    items,
    worldBounds: computeWorldBounds(stops, stagingBays, exportStations),
  };
}

export function resolveBlueprintTarget(model, query) {
  const items = model?.items || [];
  if (!items.length) return null;
  const rawQuery = typeof query === "string" ? query.trim() : "";
  if (!rawQuery) return items[0];
  const lower = rawQuery.toLowerCase();

  const byId = items.find((item) => item.id.toLowerCase() === lower);
  if (byId) return byId;

  const byPlace = items.find((item) => item.raw?.placeId && item.raw.placeId.toLowerCase() === lower);
  if (byPlace) return byPlace;

  const aliasMap = model?.aliases || {};
  const mapped = aliasMap.legacy_station_zones?.[rawQuery]
    || aliasMap.legacy_layout?.[rawQuery]
    || aliasMap.legacy_sim?.[rawQuery]
    || "";
  if (mapped) {
    const zoneKey = String(mapped).split(":")[0];
    const hit = items.find((item) => item.id === zoneKey || item.id === mapped);
    if (hit) return hit;
  }

  const colonPrefix = rawQuery.split(":")[0].toLowerCase();
  const byPrefix = items.find((item) => item.id.toLowerCase() === colonPrefix);
  if (byPrefix) return byPrefix;

  return items[0];
}

export function formatZoneDetailRows(item, model) {
  if (!item) return [];
  const raw = item.raw || {};
  const rows = [
    { term: "구분", value: CATEGORY_LABEL[item.category] || item.category },
    { term: "식별자", value: item.id },
    { term: "이름", value: item.label },
    { term: "상태", value: item.status === "verified" ? "검증됨" : item.status === "configured" ? "YAML 구성됨" : "계획 · 실측 대기" },
  ];
  if (Number.isFinite(item.x) && Number.isFinite(item.y)) {
    const angle = Number.isFinite(raw.yaw) ? `${((raw.yaw * 180) / Math.PI).toFixed(1)}°`
      : Number.isFinite(raw.yawDeg) ? `${raw.yawDeg.toFixed(1)}°` : "—";
    rows.push({ term: "좌표 (m)", value: `X ${item.x.toFixed(4)} · Y ${item.y.toFixed(4)}` });
    rows.push({ term: "방향", value: angle });
  }
  if (item.category === "stop") {
    const ruleText = raw.rule ? `${ROLE_LABEL[raw.rule.role] || raw.rule.role} (대기 ${raw.rule.timeout_s ?? "—"}s)` : (ROLE_LABEL[raw.portRole] || "—");
    rows.push({ term: "규칙·역할", value: ruleText });
    rows.push({ term: "주행 연결", value: `진입 ${raw.edgesIn?.length || 0} · 진출 ${raw.edgesOut?.length || 0} · 정지 구역 ${raw.stopZone ? "있음" : "없음"}` });
  } else if (item.category === "staging") {
    rows.push({ term: "연계 지점", value: raw.placeId || "—" });
    rows.push({ term: "속도·스텝 제한", value: `${raw.speedCapMps ?? "—"} m/s · ${raw.maxStepM ?? "—"} m` });
  } else if (item.category === "export") {
    rows.push({ term: "담당 팔·셀", value: `${raw.armId || "—"} (${raw.cellId || "—"})` });
    rows.push({ term: "이동 경로", value: `${raw.srcSite || "—"} -> ${raw.dstSite || "—"} (${raw.tier ?? 1}단)` });
  } else if (item.category === "arm_zone") {
    rows.push({ term: "담당 팔·역할", value: `${(raw.arms || []).join(", ") || "—"} · ${raw.role || "—"}` });
    rows.push({
      term: "슬롯·단 구성",
      value: `${raw.grid?.rows || 1}행 × ${raw.grid?.columns || 1}열 × ${raw.grid?.tiers || 1}단 (층고 ${model?.tierHeightMm ?? 32.4} mm · 슬롯 ${raw.slots?.length || 0}개)`,
    });
  }
  const linkedHandoffs = (model?.handoffs || []).filter((h) =>
    h.vehicle_stop_id === item.id || h.vehicle_exit_stop_id === item.id || h.cell_zone_id === item.id
    || (Array.isArray(h.target_cell_zones) && h.target_cell_zones.includes(item.id)));
  rows.push({
    term: "연결 핸드오프",
    value: linkedHandoffs.length ? linkedHandoffs.map((h) => `${h.id} (${(h.flow || []).join(" -> ")})`).join(" / ") : "없음",
  });
  const tasks = (model?.activeTasks || []).filter((t) =>
    t.srcSite === item.id || t.dstSite === item.id || t.srcSite.startsWith(`${item.id}:`) || t.dstSite.startsWith(`${item.id}:`));
  rows.push({
    term: "활성 작업",
    value: tasks.length ? tasks.map((t) => `${t.id} [${t.state || "대기"}]`).join(", ") : "대기 작업 없음",
  });
  return rows;
}
