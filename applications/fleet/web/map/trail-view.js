// 지도 위 로봇 경로(지나온 길)와 D-512 테더 원(D-526 감시 정지면 위험 색). 표시 전용 — 목표·교통정리에 쓰지 않는다.
// D-594: 경로는 Fleet 이 1 s 마다 기록한 지도 좌표다(GET /api/fleet/robots/{id}/path). 범위를 고르면 그 범위를
// 한 번 받고, 그 뒤로는 PATH_POLL_MS 마다 마지막 점 뒤만 받는다. 새로 고쳐도 남는다. 선 모양이 상태다:
// LOCALIZED 실선, DEGRADED 파선, CAMERA_ONLY(천장 카메라 추적만) 점선. 현재 지도와 map_id가 일치하는 구간만 그린다. 위치 미보고(모터 모드)·odom pose 는
// Fleet 이 기록하지 않으므로 지도에 그려지지 않는다. 테더 밖 판정도 LOCALIZED·map 보고만 쓴다(D-526 감시와 같다).
// map-view 가 자기 toPx(격자 칸 또는 D-513 7 로 돌린 미터 뷰)를 넘기므로 지도와 같이 돈다.
export const PATH_POLL_MS = 2000, TRIPS_POLL_MS = 10000, TETHER_POLL_MS = 5000, WATCH_STALE_S = 2, MAX_POINTS = 20000;

const watching = (view) => view.watchAge != null && view.watchAge <= WATCH_STALE_S; // null: no tick yet

/** The robot's pose only when it reports LOCALIZED in the map frame; `localization: null` may be odom. */
export const mapPose = (robot) => {
  const loc = robot?.state?.localization;
  return loc?.state === "LOCALIZED" && loc?.pose_frame === "map" ? robot.state.pose : null;
};

/** "120" / "600" (seconds) or "trip": the robot's open trip, else its most recent one. */
export function pathQuery(range, tripId, entry, key) {
  const base = range === "trip" ? `trip_id=${encodeURIComponent(tripId)}` : null;
  const last = entry?.key === key ? entry.points[entry.points.length - 1] : null;
  if (last) return [base, `since=${last.t}`].filter(Boolean).join("&");
  return base || `last_s=${Number(range)}`;
}

/** A first page replaces the path, a later page of the same key appends after its last point;
 *  a time range drops points older than the range by the server clock (`body.now`). */
export function mergePath(entry, key, body, rangeS) {
  const points = entry?.key === key ? entry.points : [];
  const lastT = points.length ? points[points.length - 1].t : -Infinity;
  for (const point of body.points || []) if (point.t > lastT) points.push(point);
  const from = rangeS == null ? -Infinity : body.now - rangeS;
  let drop = Math.max(0, points.length - MAX_POINTS);
  while (drop < points.length && points[drop].t < from) drop += 1;
  return { key, now: body.now, points: drop ? points.slice(drop) : points };
}

export function tripFor(trips, robotId) {
  const mine = (list) => (list || []).filter((t) => t.robot_id === robotId)
    .sort((a, b) => String(b.created_at).localeCompare(String(a.created_at)))[0];
  return (mine(trips?.open) || mine(trips?.trips))?.trip_id || null;
}

function ensureTrailAbort(view) {
  if (!view.trailFetchAbort || view.trailFetchAbort.signal.aborted) {
    view.trailFetchAbort = new AbortController();
  }
  return view.trailFetchAbort;
}

function abortTrailFetches(view, includeTether = false) {
  view.trailFetchAbort?.abort();
  view.trailFetchAbort = null;
  view.tripsInFlight = false;
  view.pathInFlight?.clear();
  if (includeTether) {
    view.tetherAbort?.abort();
    view.tetherAbort = null;
    view.tetherInFlight = false;
  }
}

function pollPaths(view, call, now) {
  if (!call || now - (view.pathAt || 0) < PATH_POLL_MS) return;
  view.pathAt = now;
  view.paths ||= new Map();
  view.pathInFlight ||= new Set();
  const range = view.trailRange || "120";
  const fetchAbort = ensureTrailAbort(view);
  const cachedTrips = view.trailTrips || ((view.trafficTrips || view.endedTrips) ? { open: view.trafficTrips || [], trips: view.endedTrips || [] } : null);
  const tripsFresh = Boolean(cachedTrips) && now - (view.tripsAt || 0) <= TRIPS_POLL_MS;
  if (range === "trip" && !view.tripsInFlight && !tripsFresh) {
    view.tripsAt = now;
    view.tripsInFlight = true;
    call("/api/fleet/trips", { signals: [fetchAbort.signal] }).then((r) => {
      if (fetchAbort.signal.aborted || (view.trailRange || "120") !== range) return;
      view.trailTrips = r;
      view.pathAt = 0;
    }, () => {}).finally(() => {
      if (view.trailFetchAbort === fetchAbort) view.tripsInFlight = false;
    });
  }
  const activeTrips = cachedTrips || view.trailTrips;
  for (const robot of view.robots || []) {
    const id = robot.robot_id, entry = view.paths.get(id);
    const tripId = range === "trip" ? tripFor(activeTrips, id) : null;
    if (view.trailHidden?.has(id) || entry?.busy || view.pathInFlight.has(id) || (range === "trip" && !tripId)) {
      if (range === "trip" && !tripId) view.paths.delete(id);
      continue;
    }
    const key = `${range}:${tripId || ""}`;
    if (entry) entry.busy = true;
    view.pathInFlight.add(id);
    call(`/api/fleet/robots/${encodeURIComponent(id)}/path?${pathQuery(range, tripId, entry, key)}`, { signals: [fetchAbort.signal] }).then(
      (body) => {
        if (fetchAbort.signal.aborted || (view.trailRange || "120") !== range) return; // 범위를 바꾼 뒤 늦게 온 답
        view.paths.set(id, mergePath(view.paths.get(id), key, body, range === "trip" ? null : Number(range)));
      },
      () => {}).finally(() => {
        view.pathInFlight.delete(id);
        const e = view.paths.get(id);
        if (e) e.busy = false;
      }); // 실패하면 직전 경로를 둔다
  }
}

// 범위 선택과 로봇별 켜고 끄기(index.html #trail-control). 표시 선호라 권한과 무관하다.
function bindControls(view, scope = null) {
  const range = document.getElementById("trail-range"), box = document.getElementById("trail-robots");
  if (!range || !box) return { sync() {} };
  view.trailHidden ||= new Set();
  const listen = scope?.listen
    ? (target, type, fn) => scope.listen(target, type, fn)
    : (target, type, fn) => { target.addEventListener(type, fn); return () => target.removeEventListener(type, fn); };
  try {
    const saved = window.sessionStorage?.getItem("rosy-trail-range");
    if (saved && [...range.options].some((o) => o.value === saved)) {
      range.value = saved;
      view.trailRange = saved;
    }
  } catch { /* ignore storage unavailable */ }
  const offRange = listen(range, "change", () => {
    view.trailRange = range.value;
    abortTrailFetches(view);
    view.paths?.clear();
    view.pathAt = 0;
    try { window.sessionStorage?.setItem("rosy-trail-range", range.value); } catch { /* ignore */ }
  });
  let sig = "";
  let offCheckboxes = [];
  const clearCheckboxes = () => {
    for (const off of offCheckboxes) off?.();
    offCheckboxes = [];
  };
  scope?.onDispose?.(() => {
    offRange?.();
    clearCheckboxes();
    abortTrailFetches(view, true);
    view.trailUi = null;
  });
  return {
    sync() {
      const robots = view.robots || [];
      const colors = view.colors || [];
      let nextSig = "";
      for (let i = 0; i < robots.length; i += 1) {
        const col = colors.length ? colors[i % colors.length] : "";
        nextSig += `${i ? "\n" : ""}${robots[i].robot_id}\t${col}`;
      }
      if (nextSig === sig) return;
      sig = nextSig;
      clearCheckboxes();
      box.replaceChildren(...robots.map((robot) => {
        const id = robot.robot_id;
        const label = document.createElement("label"), input = document.createElement("input");
        label.className = "ui-check";
        input.className = "ui-field";
        input.type = "checkbox";
        input.checked = !view.trailHidden.has(id);
        offCheckboxes.push(listen(input, "change", () => {
          if (input.checked) view.trailHidden.delete(id); else view.trailHidden.add(id);
          view.paths?.delete(id); view.pathAt = 0;
        }));
        label.append(input, ` ${id}`);
        return label;
      }));
    },
  };
}

const DASH = { LOCALIZED: [], DEGRADED: [4, 3], CAMERA_ONLY: [1, 2.5] }; // × lineWidth

export function drawTrails(ctx, view, toPx, lineWidth, call, scope = view?.scope || null) {
  const now = Date.now();
  if (typeof document !== "undefined" && typeof document.getElementById === "function") {
    (view.trailUi ||= bindControls(view, scope)).sync();
  }
  pollPaths(view, call, now);
  if (call && !view.tetherInFlight && now - (view.tetherAt || 0) > TETHER_POLL_MS) {
    view.tetherAt = now;
    view.tetherInFlight = true;
    view.tetherAbort?.abort();
    const tetherAbort = new AbortController();
    view.tetherAbort = tetherAbort;
    call("/api/fleet/tethers", { signals: [tetherAbort.signal] }).then((r) => {
      if (tetherAbort.signal.aborted) return;
      view.tethers = r.tethers || [];
      view.watchAge = r.watch_age_s;
    }, () => {}).finally(() => {
      if (view.tetherAbort === tetherAbort) view.tetherInFlight = false;
    }); // 실패하면 직전 목록을 둔다
  }
  const rangeS = (view.trailRange || "120") === "trip" ? null : Number(view.trailRange || "120");
  const mapId = view.map ? view.map.map_id : view.activeSiteMap?.map?.map_id;
  let drawn = 0;
  ctx.save();
  ctx.lineWidth = lineWidth;
  ctx.lineCap = "round";
  view.robots.forEach((robot, index) => {
    const entry = view.layers?.poses === false || view.trailHidden?.has(robot.robot_id) ? null : view.paths?.get(robot.robot_id);
    const points = entry?.points || [];
    ctx.strokeStyle = view.colors[index % view.colors.length];
    for (let i = 1; i < points.length; i += 1) {
      const p = points[i - 1], q = points[i];
      if (p.seg !== q.seg) continue; // 기록이 끊긴 곳은 잇지 않는다
      if (!mapId || p.map_id !== mapId || q.map_id !== mapId) continue;
      const a = toPx(p.x, p.y), b = toPx(q.x, q.y);
      ctx.setLineDash((DASH[q.state] || DASH.CAMERA_ONLY).map((d) => d * lineWidth));
      ctx.globalAlpha = rangeS == null ? 0.8 : 0.8 * Math.max(0.15, 1 - (entry.now - q.t) / rangeS); // 오래될수록 흐리게
      ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke();
      drawn += 1;
    }
  });
  ctx.globalAlpha = 1;
  ctx.setLineDash([lineWidth * 3, lineWidth * 2]);
  for (const tether of view.tethers || []) {
    const [ax, ay] = tether.anchor_xy, r = tether.radius_m;
    const pose = mapPose(view.robots.find((robot) => robot.robot_id === tether.robot_id));
    // 로봇이 원 밖이면 주의 색, D-526 감시가 정지를 내렸으면 위험 색 — 테더 자체는 경계선일 뿐 경고가 아니다.
    const outside = pose && Math.hypot(pose.x - ax, pose.y - ay) > r;
    // 감시 루프가 멈췄거나(마지막 틱이 2 s 넘게 전, 또는 틱 없음) 죽었으면 정지 못 하니 트립과 같은 위험 색.
    const tripped = tether.watch?.state === "tripped" || !watching(view);
    ctx.strokeStyle = ctx.fillStyle = window.RosyPalette.cssColor(
      tripped ? "--status-crit" : outside ? "--status-warn" : "--ink-quiet");
    ctx.beginPath(); // 원도 toPx 로 점을 찍는다 — 격자 y 뒤집기와 화면 회전을 그대로 따른다.
    for (let k = 0; k <= 48; k += 1) {
      const p = toPx(ax + r * Math.cos(k * Math.PI / 24), ay + r * Math.sin(k * Math.PI / 24));
      if (k === 0) ctx.moveTo(p.x, p.y); else ctx.lineTo(p.x, p.y);
    }
    ctx.stroke();
    const c = toPx(ax, ay);
    ctx.beginPath(); ctx.arc(c.x, c.y, lineWidth * 2.5, 0, Math.PI * 2); ctx.fill();
  }
  ctx.restore();
  window.__trailOverlay = { segments: drawn, tethers: (view.tethers || []).length,
    tripped: (view.tethers || []).filter((t) => t.watch?.state === "tripped").map((t) => t.robot_id),
    watchRunning: watching(view) };
}
