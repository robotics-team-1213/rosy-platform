// Pure helper model for Zone Blueprint metric slot overlays, live guide robots, and 2-click cell task staging.

export const TASK_STATE_LABEL = {
  RUNNING: "실행 중",
  QUEUED: "대기",
  PROPOSED: "제안",
  PAUSED_HUMAN: "사람 확인 대기",
};

export const SLOT_STATUS_LABEL = {
  verified: "실측 검증",
  planned_unverified: "계획 · 실측 대기",
  cad_registered: "CAD 등록",
};

function polygonBounds(polygon) {
  const xs = polygon.map(([x]) => x);
  const ys = polygon.map(([, y]) => y);
  return {
    minX: Math.min(...xs),
    maxX: Math.max(...xs),
    minY: Math.min(...ys),
    maxY: Math.max(...ys),
  };
}

function centerOf(polygon) {
  const n = polygon?.length || 0;
  if (!n) return null;
  return polygon.reduce(([sx, sy], [x, y]) => [sx + x / n, sy + y / n], [0, 0]);
}

function taskStateFor(tasks, matchIds) {
  const priority = { RUNNING: 3, PAUSED_HUMAN: 2, QUEUED: 1, PROPOSED: 0 };
  let best = null;
  let bestScore = -1;
  for (const task of tasks || []) {
    const hits = matchIds.some((id) =>
      task.dstSite === id || task.srcSite === id
      || task.dstSite.startsWith(`${id}-`) || task.srcSite.startsWith(`${id}-`)
      || task.dstSite.startsWith(`${id}:`) || task.srcSite.startsWith(`${id}:`));
    if (!hits) continue;
    const score = priority[task.state] ?? -1;
    if (score > bestScore) {
      bestScore = score;
      best = task.state;
    }
  }
  return best;
}

/**
 * Project canonical `arm_zones` slots onto `area:<zone_id>` footprints in world metres,
 * plus clickable station endpoints (`BELT` / `S3`), active cell-task flows, and live guide robots.
 */
export function buildBlueprintSlotOverlays(model, guide = null) {
  const footprints = model?.footprints || [];
  const tasks = model?.activeTasks || [];
  const footprintByZoneId = new Map();
  const footprintByPlaceId = new Map();
  const footprintByAreaId = new Map();
  for (const fp of footprints) {
    if (fp.area?.zoneId) footprintByZoneId.set(fp.area.zoneId, fp);
    if (fp.area?.id) footprintByAreaId.set(fp.area.id, fp);
    if (fp.placeId) footprintByPlaceId.set(fp.placeId, fp);
  }

  const slots = [];
  for (const zone of model?.armZones || []) {
    const fp = footprintByZoneId.get(zone.id) || footprintByAreaId.get(zone.id);
    if (!fp?.polygon?.length) continue;
    const box = polygonBounds(fp.polygon);
    const spanX = box.maxX - box.minX;
    const spanY = box.maxY - box.minY;
    const rows = Math.max(1, Number(zone.grid?.rows) || 1);
    const cols = Math.max(1, Number(zone.grid?.columns) || 1);
    const colsAlongY = cols > rows && spanY > spanX;
    const inset = 0.003;

    for (const slot of zone.slots || []) {
      const r0 = Math.max(0, (Number(slot.row) || 1) - 1);
      const colPair = Array.isArray(slot.columns) && slot.columns.length ? slot.columns : [slot.slot || 1, slot.slot || 1];
      const cStart = Math.max(0, Number(colPair[0]) - 1);
      const cEnd = Math.min(cols, Number(colPair[1] ?? colPair[0]));
      let x0, x1, y0, y1;
      if (colsAlongY) {
        x0 = box.minX + (r0 / rows) * spanX + inset;
        x1 = box.minX + ((r0 + 1) / rows) * spanX - inset;
        y0 = box.minY + (cStart / cols) * spanY + inset;
        y1 = box.minY + (cEnd / cols) * spanY - inset;
      } else {
        x0 = box.minX + (cStart / cols) * spanX + inset;
        x1 = box.minX + (cEnd / cols) * spanX - inset;
        y0 = box.minY + (r0 / rows) * spanY + inset;
        y1 = box.minY + ((r0 + 1) / rows) * spanY - inset;
      }
      if (x1 <= x0) { x0 = box.minX + (r0 / rows) * spanX; x1 = x0 + spanX / rows; }
      if (y1 <= y0) { y0 = box.minY + (cStart / cols) * spanY; y1 = y0 + spanY / cols; }
      const polygon = [[x0, y0], [x1, y0], [x1, y1], [x0, y1]];
      const arms = Array.isArray(slot.arms) && slot.arms.length ? slot.arms : (zone.arms || []);
      const maxTier = Math.max(1, (slot.tiers || []).length || Number(zone.grid?.tiers) || 1);
      slots.push({
        id: slot.id,
        slotId: slot.id,
        site: slot.id,
        zoneId: zone.id,
        label: slot.label || slot.id,
        shortLabel: `${zone.id === "yard" ? "Y" : zone.id === "temp_a" ? "TA" : zone.id === "temp_b" ? "TB" : "ST"}${slot.row}-${slot.slot || 1}`,
        arms,
        status: slot.status || zone.status || "planned_unverified",
        maxTier,
        polygon,
        center: [(x0 + x1) / 2, (y0 + y1) / 2],
        taskState: taskStateFor(tasks, [slot.id]),
      });
    }
  }

  const beltArea = (model?.areas || []).find((a) => a.id === "BELT" || a.kind === "belt");
  if (beltArea?.polygon?.length) {
    slots.push({
      id: "station:belt",
      slotId: null,
      site: "belt",
      zoneId: beltArea.id,
      label: beltArea.name || "컨베이어 벨트",
      shortLabel: "BELT",
      arms: ["arm_a", "arm_b"],
      status: beltArea.status || "cad_registered",
      maxTier: 1,
      polygon: beltArea.polygon,
      center: centerOf(beltArea.polygon),
      taskState: taskStateFor(tasks, ["belt"]),
    });
  }

  const s3Footprint = footprintByPlaceId.get("S3");
  if (s3Footprint?.polygon?.length) {
    slots.push({
      id: "station:pinky",
      slotId: null,
      site: "pinky",
      zoneId: "S3",
      label: "정류장 S3 (짐칸)",
      shortLabel: "S3짐칸",
      arms: ["arm_s"],
      status: "verified",
      maxTier: 1,
      polygon: s3Footprint.polygon,
      center: centerOf(s3Footprint.polygon),
      taskState: taskStateFor(tasks, ["pinky", "vehicle_tray"]),
    });
  }

  const centerForSite = (siteRef) => {
    if (!siteRef) return null;
    const hit = slots.find((s) =>
      siteRef === s.id || siteRef === s.site
      || (s.slotId && (siteRef === s.slotId || siteRef.startsWith(`${s.slotId}-`)))
      || (s.site === "pinky" && (siteRef === "pinky" || siteRef === "vehicle_tray"))
      || (s.site === "belt" && (siteRef === "belt" || siteRef === "belt-in")));
    if (hit) return hit.center;
    const zoneId = String(siteRef).split(":")[0];
    const fp = footprintByZoneId.get(zoneId) || footprintByAreaId.get(zoneId);
    return fp ? centerOf(fp.polygon) : null;
  };

  const taskFlows = [];
  for (const task of tasks) {
    const from = centerForSite(task.srcSite);
    const to = centerForSite(task.dstSite);
    if (!from || !to) continue;
    taskFlows.push({ id: task.id, state: task.state, stateLabel: TASK_STATE_LABEL[task.state] || "활성", from, to, armId: task.armId });
  }

  const robots = [];
  for (const row of guide?.robots || []) {
    if (!row?.robot_id || !Number.isFinite(row.x) || !Number.isFinite(row.y)) continue;
    robots.push({
      robotId: row.robot_id,
      x: row.x,
      y: row.y,
      yaw: Number.isFinite(row.yaw) ? row.yaw : 0,
      moving: Boolean(row.moving),
      placeId: row.place_id || null,
    });
  }

  return { slots, taskFlows, robots };
}

/**
 * Validate two selected blueprint slots/endpoints and build the exact `POST /api/fleet/pipeline/cell-tasks` body.
 * Canonical `cell_ab` sites always pass tier-encoded `<slot_id>-t<tier>` IDs so backend `resolve_cell_ab_site` accepts both src and dst.
 */
export function buildCellStagePayload({ src, dst, tier = 1, armId = "" } = {}) {
  if (!src) return { payload: null, error: "도면에서 출발 구역(슬롯·벨트·S3)을 먼저 선택하세요." };
  if (!dst) return { payload: null, error: "도면에서 도착 구역(슬롯·벨트)을 선택하세요." };
  if (src.id === dst.id) return { payload: null, error: "출발과 도착 위치가 같습니다." };

  if (src.site === "pinky" || dst.site === "pinky") {
    if (src.site === "pinky" && dst.site === "belt") {
      return {
        payload: { cell_id: "cell_s", arm_id: "arm_s", src_site: "pinky", dst_site: "belt", tier: 1, propose: false },
        error: "",
      };
    }
    return { payload: null, error: "정류장 S3 짐칸에서는 벨트(BELT)로만 하역 작업을 지정할 수 있습니다." };
  }

  const commonArms = (src.arms || []).filter((a) => (dst.arms || []).includes(a) && a !== "arm_s");
  if (!commonArms.length) {
    return { payload: null, error: "출발과 도착 구역을 함께 닿는 로봇 팔(arm_a/arm_b)이 없습니다." };
  }
  const chosenArm = armId && commonArms.includes(armId) ? armId : (commonArms.length === 1 ? commonArms[0] : "");
  const reqTier = Math.max(1, Math.min(3, Math.trunc(Number(tier) || 1)));
  const srcTier = Math.min(reqTier, Number(src.maxTier) || 1);
  const dstTier = Math.min(reqTier, Number(dst.maxTier) || 1);
  const srcSite = src.site === "belt" ? "belt" : `${src.slotId || src.id}-t${srcTier}`;
  const dstSite = dst.site === "belt" ? "belt" : `${dst.slotId || dst.id}-t${dstTier}`;
  const payload = {
    cell_id: "cell_ab",
    src_site: srcSite,
    dst_site: dstSite,
    tier: dstTier,
    propose: false,
  };
  if (chosenArm) payload.arm_id = chosenArm;
  return { payload, error: "" };
}
