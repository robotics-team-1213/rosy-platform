// DOM-free blueprint model: the active site map (lanes, places), the zone footprints on it and their conflicts.
// One model feeds the 2D and 3D drawings, so the two cannot disagree. Every lane and place comes from the
// active site map; every fixed area and the vehicle footprint come from the station-zones YAML.

import {
  bodyPolygon, centroid, contains, interiorsOverlap, polylinePolygonGap,
} from "./zone-blueprint-geometry.js";

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
  inbound_load: "반입 상차",
});

const STATUS_LABEL = Object.freeze({
  measured: "실측",
  cad_registered: "CAD 등록 후보",
  photo_estimated: "사진 추정",
  planned_unverified: "계획 · 실측 대기",
});

const ANCHOR_LABEL = Object.freeze({
  stop_zone: "정지 구역 (활성 지도)",
  vehicle_body: "장소 자세 + 차체 크기",
  area: "고정 영역 (station-zones YAML)",
});

const AXIS_LABEL = Object.freeze({
  90: "+X ↓ · +Y →",
  180: "+X ← · +Y ↓",
  270: "+X ↑ · +Y ←",
});

/** Gaps smaller than this are reported, not refused: drawing and photo error, not a collision. */
export const NEAR_M = 0.02;

function finiteNum(value) {
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

function polygonOf(raw) {
  if (!Array.isArray(raw)) return null;
  const points = raw
    .filter((pt) => Array.isArray(pt) && Number.isFinite(Number(pt[0])) && Number.isFinite(Number(pt[1])))
    .map((pt) => [Number(pt[0]), Number(pt[1])]);
  return points.length >= 3 ? points : null;
}

// ---- normalization -------------------------------------------------------------------------------

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
    stopZone: polygonOf(stop?.stop_zone),
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
    stored: { x: finiteNum(bay?.x), y: finiteNum(bay?.y) },
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
    stored: { x: finiteNum(st?.x), y: finiteNum(st?.y) },
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
    srcSiteId: String(task?.src_site_id || ""),
    dstSiteId: String(task?.dst_site_id || ""),
    armId: String(task?.arm_id || ""),
    cellId: String(task?.cell_id || ""),
  })).filter((t) => t.id || t.srcSite || t.dstSite);
}

/** The active ``rosy.site_map/1`` view: lanes with their real width, places, and the screen turn every
 * Fleet map follows (D-513 7). null when the site has no active map. */
function normalizeSiteMap(siteMap) {
  const map = siteMap?.map;
  if (!map || !Array.isArray(map.places) || !Array.isArray(map.edges)) return null;
  const turn = Number(map.view_turn_deg);
  return {
    version: finiteNum(siteMap.version),
    mapId: String(map.map_id || ""),
    viewTurnDeg: [90, 180, 270].includes(turn) ? turn : 0,
    places: map.places.map((place) => ({
      id: String(place?.id || ""),
      kind: String(place?.kind || "junction"),
      x: finiteNum(place?.x),
      y: finiteNum(place?.y),
      yaw: finiteNum(place?.yaw),
    })).filter((place) => place.id && Number.isFinite(place.x) && Number.isFinite(place.y)),
    lanes: map.edges.map((edge) => ({
      id: String(edge?.id || ""),
      from: String(edge?.from || ""),
      to: String(edge?.to || ""),
      widthM: finiteNum(edge?.width_m) ?? 0.2,
      direction: edge?.direction === "two_way" ? "two_way" : "one_way",
      driveMode: String(edge?.drive_mode || "lane"),
      points: (Array.isArray(edge?.polyline) ? edge.polyline : [])
        .filter((pt) => Array.isArray(pt) && Number.isFinite(Number(pt[0])) && Number.isFinite(Number(pt[1])))
        .map((pt) => [Number(pt[0]), Number(pt[1])]),
    })).filter((lane) => lane.id && lane.points.length >= 2),
  };
}

function normalizeAreas(stationZones) {
  const raw = Array.isArray(stationZones?.areas) ? stationZones.areas : [];
  return raw.map((area) => ({
    id: String(area?.id || ""),
    name: String(area?.name || area?.id || ""),
    shortName: String(area?.short_name || area?.name || area?.id || ""),
    kind: String(area?.kind || "worktop"),
    polygon: polygonOf(area?.polygon),
    heightM: finiteNum(area?.height_m),
    status: String(area?.status || "planned_unverified"),
    evidence: String(area?.evidence || ""),
    zoneId: area?.zone_id ? String(area.zone_id) : "",
  })).filter((area) => area.id && area.polygon);
}

function normalizeVehicle(stationZones) {
  const raw = stationZones?.vehicle;
  const frontM = finiteNum(raw?.front_m);
  const rearM = finiteNum(raw?.rear_m);
  const halfWidthM = finiteNum(raw?.half_width_m);
  if (!(frontM > 0) || !(rearM < 0) || !(halfWidthM > 0)) return null;
  return { frontM, rearM, halfWidthM };
}

// ---- footprints and conflicts ----------------------------------------------------------------------

function buildFootprints({ stops, stagingBays, exportStations, armZones, areas, vehicle }) {
  const bound = new Map();
  for (const zone of [...stagingBays, ...exportStations]) {
    if (zone.placeId) bound.set(zone.placeId, [...(bound.get(zone.placeId) || []), zone.id]);
  }
  const footprints = [];
  for (const stop of stops) {
    if (!Number.isFinite(stop.x) || !Number.isFinite(stop.y)) continue;
    const polygon = stop.stopZone || (vehicle && Number.isFinite(stop.yaw) ? bodyPolygon(stop, vehicle) : null);
    if (!polygon) continue;
    footprints.push({
      id: `place:${stop.id}`, placeId: stop.id, kind: stop.kind === "charge" ? "charge" : "stop",
      anchor: stop.stopZone ? "stop_zone" : "vehicle_body", pose: [stop.x, stop.y], yaw: stop.yaw, polygon,
      itemIds: [stop.id, ...(bound.get(stop.id) || [])],
    });
  }
  for (const area of areas.filter((candidate) => candidate.zoneId)) {
    if (!armZones.some((zone) => zone.id === area.zoneId)) continue;
    footprints.push({
      id: `area:${area.id}`, placeId: null, kind: "cell_zone", anchor: "area", pose: centroid(area.polygon), yaw: null,
      area, polygon: area.polygon, itemIds: [area.zoneId],
    });
  }
  return footprints;
}

function computeConflicts({ areas, lanes, footprints, boundZones, placeById }) {
  const conflicts = [];
  const add = (kind, ids, text) => conflicts.push({ kind, ids, text });
  const areaId = (area) => `area:${area.id}`;
  for (const [index, first] of areas.entries()) {
    for (const second of areas.slice(index + 1)) {
      if (interiorsOverlap(first.polygon, second.polygon) && !contains(first.polygon, second.polygon)
        && !contains(second.polygon, first.polygon)) {
        add("overlap", [areaId(first), areaId(second)], `${first.name} ↔ ${second.name}: 영역 겹침`);
      }
    }
  }
  const mm = (metres) => `${Math.round(Math.abs(metres) * 1000)} mm`;
  for (const area of areas) {
    for (const lane of lanes) {
      const cut = lane.widthM / 2 - polylinePolygonGap(lane.points, area.polygon);
      if (cut > NEAR_M) {
        add("overlap", [areaId(area)], `${area.name} ↔ 차로 ${lane.id}: 표준 폭 ${mm(cut)} 안으로 들어옴`);
      } else if (cut > -NEAR_M) {
        add("near", [areaId(area)], `${area.name} ↔ 차로 ${lane.id}: ${
          cut >= 0 ? `표준 폭 ${mm(cut)} 겹침 (오차 범위)` : `여유 ${mm(cut)}`}`);
      }
    }
  }
  const parked = footprints.filter((footprint) => footprint.kind !== "cell_zone");
  for (const area of areas) {
    for (const footprint of parked) {
      if (interiorsOverlap(area.polygon, footprint.polygon)) {
        add("overlap", [areaId(area), footprint.id], `${area.name} ↔ ${footprint.placeId}: 정차 공간 겹침`);
      }
    }
  }
  for (const [index, first] of parked.entries()) {
    for (const second of parked.slice(index + 1)) {
      if (interiorsOverlap(first.polygon, second.polygon)) {
        add("overlap", [first.id, second.id], `${first.placeId} ↔ ${second.placeId}: 정차 공간 겹침`);
      }
    }
  }
  for (const zone of boundZones) {
    const place = placeById.get(zone.placeId);
    if (!place || !Number.isFinite(zone.stored.x) || !Number.isFinite(zone.stored.y)) continue;
    const drift = Math.hypot(zone.stored.x - place.x, zone.stored.y - place.y);
    if (drift > NEAR_M) {
      add("stale_yaml", [`place:${place.id}`],
        `${zone.id}: YAML 좌표가 장소 ${place.id}와 ${Math.round(drift * 100)} cm 어긋남 (장소 좌표로 그림)`);
    }
  }
  return conflicts;
}

function makeProject(turnDeg) {
  const theta = (turnDeg * Math.PI) / 180;
  const c = Math.cos(theta);
  const s = Math.sin(theta);
  // A clockwise screen turn of the map is a -theta turn of world points (y up in both).
  return [(x, y) => [x * c + y * s, -x * s + y * c], (vx, vy) => [vx * c - vy * s, vx * s + vy * c]];
}

function viewBounds(lanes, areas, footprints, project) {
  let minX = Infinity; let maxX = -Infinity; let minY = Infinity; let maxY = -Infinity;
  const include = (x, y, margin) => {
    const [vx, vy] = project(x, y);
    minX = Math.min(minX, vx - margin); maxX = Math.max(maxX, vx + margin);
    minY = Math.min(minY, vy - margin); maxY = Math.max(maxY, vy + margin);
  };
  const laneMargin = Math.max(0, ...lanes.map((lane) => lane.widthM)) / 2 + 0.02;
  for (const lane of lanes) for (const [x, y] of lane.points) include(x, y, laneMargin);
  for (const polygon of [...areas.map((area) => area.polygon), ...footprints.map((footprint) => footprint.polygon)]) {
    for (const [x, y] of polygon) include(x, y, 0.06);
  }
  return Number.isFinite(minX)
    ? { minX, maxX, minY, maxY }
    : { minX: -1, maxX: 1, minY: -1, maxY: 1 };
}

// ---- model ----------------------------------------------------------------------------------------

export function buildZoneBlueprintModel({ sitePoints = null, stationZones = null, cellTasks = null, siteMap = null } = {}) {
  const stops = normalizeStops(sitePoints);
  const stagingBays = normalizeStagingBays(stationZones);
  const exportStations = normalizeExportStations(stationZones);
  const armZones = normalizeArmZones(sitePoints);
  const handoffs = Array.isArray(sitePoints?.handoffs) ? sitePoints.handoffs : [];
  const activeTasks = normalizeTasks(cellTasks);
  const map = normalizeSiteMap(siteMap);
  const lanes = map?.lanes || [];
  // Every place of the active map: the site-map view wins, and site-points (the same places server-side)
  // stands in when the view itself could not be read.
  const placeById = new Map([
    ...stops.filter((stop) => Number.isFinite(stop.x) && Number.isFinite(stop.y))
      .map((stop) => [stop.id, { id: stop.id, kind: stop.kind, x: stop.x, y: stop.y, yaw: stop.yaw }]),
    ...(map?.places || []).map((place) => [place.id, place]),
  ]);
  const areas = normalizeAreas(stationZones);
  const vehicle = normalizeVehicle(stationZones);
  const footprints = buildFootprints({ stops, stagingBays, exportStations, armZones, areas, vehicle });
  const boundZones = [...stagingBays, ...exportStations];
  const conflicts = computeConflicts({ areas, lanes, footprints, boundZones, placeById });
  const aliases = {
    ...(sitePoints?.arm_zones?.aliases || {}),
    legacy_station_zones: {
      ...(sitePoints?.arm_zones?.aliases?.legacy_station_zones || {}),
      ...(sitePoints?.legacy_aliases || {}),
    },
  };
  const footprintById = new Map(footprints.map((footprint) => [footprint.id, footprint]));
  const itemFootprint = (footprintId) => (footprintById.has(footprintId) ? footprintId : null);
  const conflictsOf = (footprintId) => conflicts.filter((conflict) => conflict.ids.includes(footprintId));

  const items = [
    ...stops.map((s) => ({
      category: "stop",
      id: s.id,
      label: s.name,
      subtitle: `${ROLE_LABEL[s.portRole] || s.kind}${s.status === "verified" ? " · 검증됨" : " · 계획됨"}`,
      x: s.x,
      y: s.y,
      placeInMap: Number.isFinite(s.x),
      footprintId: itemFootprint(`place:${s.id}`),
      status: s.status,
      raw: s,
    })),
    ...stagingBays.map((b) => ({
      category: "staging",
      id: b.id,
      label: b.name,
      subtitle: b.placeId ? `대기칸 · ${b.placeId}` : "임시 대기칸",
      ...placedAt(placeById, b),
      footprintId: itemFootprint(`place:${b.placeId}`),
      status: "configured",
      raw: b,
    })),
    ...exportStations.map((e) => ({
      category: "export",
      id: e.id,
      label: e.name,
      subtitle: `${e.armId || e.cellId || "반출"} · ${e.tier}단`,
      ...placedAt(placeById, e),
      footprintId: itemFootprint(`place:${e.placeId}`),
      status: "configured",
      raw: e,
    })),
    ...armZones.map((z) => {
      const area = areas.find((candidate) => candidate.zoneId === z.id);
      const centre = area ? centroid(area.polygon) : [null, null];
      return {
        category: "arm_zone",
        id: z.id,
        label: z.label,
        subtitle: `${z.grid.rows}×${z.grid.columns}×${z.grid.tiers} · ${
          area ? STATUS_LABEL[area.status] || area.status : "위치 미등록"}`,
        x: centre[0],
        y: centre[1],
        placeInMap: Boolean(area),
        footprintId: itemFootprint(area ? `area:${area.id}` : ""),
        status: z.status,
        raw: z,
      };
    }),
  ];

  const [project, unproject] = makeProject(map?.viewTurnDeg || 0);
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
    siteMap: map,
    lanes,
    areas,
    vehicle,
    footprints,
    conflicts,
    conflictsOf,
    links: handoffs.map((h) => ({
      id: String(h?.id || ""),
      kind: String(h?.kind || ""),
      fromPlaceId: h?.vehicle_stop_id ? String(h.vehicle_stop_id) : "",
      toZoneId: h?.cell_zone_id ? String(h.cell_zone_id)
        : (Array.isArray(h?.target_cell_zones) && h.target_cell_zones[0] ? String(h.target_cell_zones[0]) : ""),
      toPlaceId: h?.vehicle_exit_stop_id ? String(h.vehicle_exit_stop_id) : "",
    })),
    project,
    unproject,
    bounds: viewBounds(lanes, areas, footprints, project),
    axisLabel: AXIS_LABEL[map?.viewTurnDeg] || "+X → · +Y ↑",
  };
}

/** A staging bay or export station stands at its site-map place; the place owns the coordinates. */
function placedAt(placeById, zone) {
  const place = zone.placeId ? placeById.get(zone.placeId) : null;
  return { x: place ? place.x : null, y: place ? place.y : null, placeInMap: Boolean(place) };
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

const cm = (metres) => `${Math.round(metres * 1000) / 10}`;

function locationRows(item, model) {
  const footprint = model?.footprints?.find((candidate) => candidate.id === item.footprintId);
  if (!footprint) {
    return [{ term: "위치", value: item.placeInMap ? "그림 없음" : "활성 지도에 없음 (위치 미등록)" }];
  }
  const rows = [{ term: "위치 근거", value: ANCHOR_LABEL[footprint.anchor] || footprint.anchor }];
  if (footprint.area) {
    const xs = footprint.polygon.map(([x]) => x);
    const ys = footprint.polygon.map(([, y]) => y);
    rows.push({
      term: "영역 크기 (cm)",
      value: `${cm(Math.max(...xs) - Math.min(...xs))} × ${cm(Math.max(...ys) - Math.min(...ys))}`,
    });
    if (footprint.area.evidence) rows.push({ term: "영역 근거", value: footprint.area.evidence });
  }
  return rows;
}

export function formatZoneDetailRows(item, model) {
  if (!item) return [];
  const raw = item.raw || {};
  const rows = [
    { term: "구분", value: CATEGORY_LABEL[item.category] || item.category },
    { term: "식별자", value: item.id },
    { term: "이름", value: item.label },
    { term: "상태", value: item.status === "verified" ? "검증됨" : item.status === "configured" ? "YAML 구성됨" : "계획 · 실측 대기" },
    ...locationRows(item, model),
  ];
  if (Number.isFinite(item.x) && Number.isFinite(item.y)) {
    const angle = Number.isFinite(raw.yaw) ? `${((raw.yaw * 180) / Math.PI).toFixed(1)}°` : "—";
    const where = item.category === "stop" ? "좌표 (m)" : `장소 ${raw.placeId || ""} 좌표 (m)`;
    rows.push({ term: where, value: `X ${item.x.toFixed(4)} · Y ${item.y.toFixed(4)}` });
    if (item.category === "stop") rows.push({ term: "방향", value: angle });
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
  const conflicts = item.footprintId ? model.conflictsOf(item.footprintId) : [];
  rows.push({
    term: "겹침·여유",
    value: conflicts.length ? conflicts.map((conflict) => conflict.text).join(" / ") : "없음",
  });
  return rows;
}
