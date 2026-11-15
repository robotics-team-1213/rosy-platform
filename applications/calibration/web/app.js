import "/common/ui.js";
import { renderTopView, renderArmGrid } from "./grid.js";
import { initRequests } from "./requests.js";

const $ = (id) => document.getElementById(id);

const state = {
  bundle: null,
  profileId: null,
  siteName: null,
  zPlane: "z_view",
  frameSource: "live",
  errorScale: 5,
  layout: "both",
  layers: {
    pxGrid: true,
    metricGrid: true,
    sites: true,
    points: true,
    bias: true,
    centerAndTcp: true,
  },
  selectedKey: null,
  selectedData: null,
  frameCache: new Map(),
  lastTopHitTargets: [],
  lastArmHitTargets: [],
};

function currentProfile() {
  const list = state.bundle?.profiles || [];
  return list.find((p) => p.id === state.profileId) || list[0] || null;
}

function defaultSiteForProfile(profile) {
  if (!profile?.sites) return null;
  for (const s of profile.map_sites || []) {
    if (profile.sites[s]?.map) return s;
  }
  for (const [k, v] of Object.entries(profile.sites)) {
    if (!v.extra && v.map) return k;
  }
  return Object.keys(profile.sites)[0] || null;
}

function setSegmentGroup(buttons, activeBtn) {
  for (const b of buttons) {
    const on = b === activeBtn;
    b.classList.toggle("active", on);
    b.setAttribute("aria-pressed", on ? "true" : "false");
  }
}

function addDtDd(dl, term, value) {
  const dt = document.createElement("dt");
  dt.textContent = term;
  const dd = document.createElement("dd");
  dd.textContent = value;
  dl.append(dt, dd);
}

function makeTable(headers) {
  const tbl = document.createElement("table");
  tbl.className = "cal-table";
  const thead = document.createElement("thead");
  const tr = document.createElement("tr");
  for (const h of headers) {
    const th = document.createElement("th");
    th.textContent = h;
    tr.appendChild(th);
  }
  thead.appendChild(tr);
  const tbody = document.createElement("tbody");
  tbl.append(thead, tbody);
  return { tbl, tbody };
}

async function fetchJson(url) {
  const res = await fetch(url, { cache: "no-store" });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw Object.assign(new Error(body.error || `${url}: HTTP ${res.status}`), { status: res.status });
  return body;
}

function loadFrameImage(profileId, source) {
  const key = `${profileId}:${source}`;
  const existing = state.frameCache.get(key);
  if (existing && existing.status === "ready") return existing.img;
  if (!existing) {
    const img = new Image();
    const rec = { img, status: "loading" };
    state.frameCache.set(key, rec);
    img.onload = () => {
      rec.status = "ready";
      renderCanvases();
    };
    img.onerror = () => {
      rec.status = "error";
      renderCanvases();
    };
    img.src = `/api/calibration/v1/profiles/${encodeURIComponent(profileId)}/frame/${encodeURIComponent(source)}?t=${Date.now()}`;
  }
  return null;
}

function refreshActiveFrame() {
  const prof = currentProfile();
  if (!prof) return;
  state.frameCache.delete(`${prof.id}:${state.frameSource}`);
  loadFrameImage(prof.id, state.frameSource);
  renderCanvases();
}

function renderProfileBar() {
  const bar = $("profileBar");
  bar.replaceChildren();
  for (const p of state.bundle?.profiles || []) {
    const btn = document.createElement("ui-button");
    btn.setAttribute("kind", "segment");
    btn.setAttribute("type", "button");
    const active = p.id === state.profileId;
    btn.classList.toggle("active", active);
    btn.setAttribute("aria-pressed", active ? "true" : "false");

    let maxLoo = 0;
    for (const s of Object.values(p.sites || {})) {
      if (!s.extra && s.map?.loo_error_mm?.max > maxLoo) maxLoo = s.map.loo_error_mm.max;
    }
    const errs = (p.hygiene || []).filter((h) => h.level === "error").length;
    const warns = (p.hygiene || []).filter((h) => h.level === "warning").length;
    const badge = errs > 0 ? `E${errs}/W${warns}` : warns > 0 ? `W${warns}` : "OK";
    btn.textContent = `${p.id} · ${maxLoo.toFixed(1)}mm · ${badge}`;
    btn.addEventListener("click", () => {
      state.profileId = p.id;
      state.siteName = defaultSiteForProfile(p);
      state.selectedKey = null;
      state.selectedData = null;
      renderAll();
    });
    bar.appendChild(btn);
  }
}

function renderHygiene(profile) {
  const panel = $("hygienePanel");
  const summary = $("hygieneSummary");
  const list = $("hygieneList");
  const toggleLabel = $("hygieneToggleLabel");
  list.replaceChildren();

  const items = profile?.hygiene || [];
  const errs = items.filter((i) => i.level === "error");
  const warns = items.filter((i) => i.level === "warning");

  if (errs.length > 0) {
    panel.setAttribute("data-level", "error");
    summary.setAttribute("state", "error");
    summary.textContent = `${profile.arm_id}: 오류 ${errs.length}건 · 경고 ${warns.length}건 — ${errs[0].message}`;
  } else if (warns.length > 0) {
    panel.setAttribute("data-level", "warn");
    summary.setAttribute("state", "warning");
    summary.textContent = `${profile.arm_id}: 경고 ${warns.length}건 — ${warns[0].message}`;
  } else {
    panel.setAttribute("data-level", "ok");
    summary.setAttribute("state", "ready");
    summary.textContent = `${profile.arm_id}: 프로파일 및 지도 정합 이상 없음`;
  }
  toggleLabel.textContent = `점검 세부 항목 (${items.length}건)`;

  for (const item of items) {
    const li = document.createElement("li");
    li.className = "cal-hygiene-item";
    li.setAttribute("data-level", item.level);
    li.textContent = `[${item.code}] ${item.message}`;
    list.appendChild(li);
  }

  const holdTag = $("holdBadge");
  const inc = profile?.robot_status?.incident || {};
  if (inc.local_held || inc.fleet_held) {
    holdTag.setAttribute("status", "crit");
    holdTag.textContent = `HELD (${(inc.incident_ids || []).join(",") || "hold"})`;
  } else {
    holdTag.setAttribute("status", "neutral");
    holdTag.textContent = "HOLD CLEAR";
  }

  const srcTag = $("profileSourceTag");
  srcTag.setAttribute("status", state.bundle?.configured ? "active" : "neutral");
  srcTag.textContent = state.bundle?.configured ? "REGISTRY LIVE" : "NO PROFILES";
}

function renderSiteSelect(profile) {
  const sel = $("siteSelect");
  sel.replaceChildren();
  for (const [name, s] of Object.entries(profile?.sites || {})) {
    const opt = document.createElement("option");
    opt.value = name;
    const loo = s.map?.loo_error_mm?.max;
    const looTxt = Number.isFinite(loo) ? `${loo.toFixed(1)}mm` : "지도없음";
    const extraTxt = s.extra ? " [extra]" : s.map_from ? ` ←${s.map_from}` : "";
    opt.textContent = `${name}${extraTxt} (${looTxt})`;
    if (name === state.siteName) opt.selected = true;
    sel.appendChild(opt);
  }
}

function renderInspector() {
  const empty = $("inspectorEmpty");
  const dl = $("inspectorDl");
  dl.replaceChildren();
  const d = state.selectedData;
  if (!d) {
    empty.hidden = false;
    dl.hidden = true;
    return;
  }
  empty.hidden = true;
  dl.hidden = false;
  addDtDd(dl, "종류", d.kind || "-");
  if (d.site) addDtDd(dl, "Site", d.site);
  if (d.role) addDtDd(dl, "역할", d.role);
  if (d.arm_m) {
    addDtDd(dl, "Arm XY (m)", `[${d.arm_m[0].toFixed(4)}, ${d.arm_m[1].toFixed(4)}]`);
    addDtDd(dl, "Arm XY (mm)", `[${(d.arm_m[0] * 1000).toFixed(1)}, ${(d.arm_m[1] * 1000).toFixed(1)}] mm`);
  }
  if (d.pixel) addDtDd(dl, "측정 Pixel (z_view)", `[${d.pixel[0].toFixed(1)}, ${d.pixel[1].toFixed(1)}]`);
  if (d.pixel_z_view) addDtDd(dl, "투영 px (z_view)", `[${d.pixel_z_view[0].toFixed(1)}, ${d.pixel_z_view[1].toFixed(1)}]`);
  if (d.pixel_surface_z) addDtDd(dl, "투영 px (surface_z)", `[${d.pixel_surface_z[0].toFixed(1)}, ${d.pixel_surface_z[1].toFixed(1)}]`);
  if (Number.isFinite(d.surface_z)) addDtDd(dl, "surface_z (m)", `${d.surface_z} m`);
  if (Number.isFinite(d.depth_surface_z)) {
    const dTxt = Number.isFinite(d.depth_diff_mm) ? ` (${d.depth_diff_mm >= 0 ? "+" : ""}${d.depth_diff_mm} mm)` : "";
    addDtDd(dl, "D435 depth surface_z", `${d.depth_surface_z} m${dTxt}`);
  }
  if (Number.isFinite(d.place_vs_start_step_mm)) {
    addDtDd(dl, "Place−Start 높이차", `${d.place_vs_start_step_mm >= 0 ? "+" : ""}${d.place_vs_start_step_mm} mm`);
  }
  if (Number.isFinite(d.touch_surface_z)) {
    const tTxt = Number.isFinite(d.touch_diff_mm) ? ` (${d.touch_diff_mm >= 0 ? "+" : ""}${d.touch_diff_mm} mm)` : "";
    addDtDd(dl, "Touch 영수증 surface_z", `${d.touch_surface_z} m${tTxt}`);
  }
  if (Number.isFinite(d.loo_dist_mm)) addDtDd(dl, "LOO 잔차 거리", `${d.loo_dist_mm.toFixed(2)} mm`);
  if (Array.isArray(d.loo_residual_mm)) {
    addDtDd(dl, "LOO 벡터 (map−arm)", `[${d.loo_residual_mm[0].toFixed(2)}, ${d.loo_residual_mm[1].toFixed(2)}] mm`);
  }
  if (Number.isFinite(d.err_dist_mm)) addDtDd(dl, "Dropped 오차", `${d.err_dist_mm} mm (${d.err_px || "?"} px)`);
  if (d.bias_mm) {
    addDtDd(dl, "Bias (map−FK)", `[${d.bias_mm[0]}, ${d.bias_mm[1]}] mm (RMS ${d.rms_mm ?? "?"} mm)`);
    const cnt = d.n ?? d.samples ?? "?";
    addDtDd(dl, "Sample / Map SHA", `${cnt}회 / ${d.map_sha || "-"} (${d.stale_map ? "stale" : "fresh"})`);
  }
  if (d.tcp) {
    addDtDd(dl, "Live TCP", `x=${d.tcp.x} y=${d.tcp.y} z=${d.tcp.z} yaw=${d.tcp.yaw_deg}°`);
    addDtDd(dl, "Freshness", d.stale ? `stale (${d.age_s ?? "?"}s)` : `fresh (${d.age_s}s)`);
  }
}

function renderRobotAndBias(profile) {
  const dl = $("robotStatusDl");
  dl.replaceChildren();
  const live = profile?.robot_status?.live || {};
  const inc = profile?.robot_status?.incident || {};
  const op = profile?.operating_profile || {};
  const envTag = $("envTag");

  addDtDd(dl, "arm_id / zone", `${profile.arm_id} (${profile.zone_side || "-"} ↔ ${profile.zone_peer || "-"})`);
  addDtDd(dl, "hold 상태", inc.local_held || inc.fleet_held ? `HELD (${(inc.incident_ids || []).join(",")})` : "clear");
  if (live.tcp) {
    addDtDd(dl, "Live TCP", `[${live.tcp.x}, ${live.tcp.y}, ${live.tcp.z}] m · yaw ${live.tcp.yaw_deg}°`);
    addDtDd(dl, "수집 시각 / Chunk", `${live.stale ? "STALE" : "FRESH"} (${live.age_s ?? "?"}s) · ${live.chunk || "-"}`);
  } else {
    addDtDd(dl, "Live TCP", "live.json 없음 / 파싱 불가");
  }
  const h = live.health || {};
  addDtDd(
    dl,
    "Bridge / Torque",
    `ok=${h.bridge_ok ?? "-"} · torque=${h.torque_off_confirmed === false ? "ON" : h.torque_off_confirmed === true ? "OFF" : "-"} · fault=${live.fault ?? "none"}`,
  );
  addDtDd(dl, "operating_profile", `${op.device_id || "-"} · work_dir=${op.work_dir || "-"} (cfg=${profile.paths?.work_dir || "-"})`);

  const codes = new Set((profile.hygiene || []).map((x) => x.code));
  const hasMismatch = codes.has("operating_profile_missing") || codes.has("profile_device_mismatch") || codes.has("profile_workdir_mismatch");
  const hasEnvMissing = codes.has("envelope_missing_on_host");
  if (hasMismatch) {
    envTag.setAttribute("status", "crit");
    envTag.textContent = "PROFILE MISMATCH";
  } else if (hasEnvMissing) {
    envTag.setAttribute("status", "warn");
    envTag.textContent = "ENVELOPE MISSING";
  } else {
    envTag.setAttribute("status", "active");
    envTag.textContent = "PROFILE OK";
  }

  const cv = profile?.cross_verify || {};
  const verdictStatus = (v) => (v === "fail" ? "crit" : v === "warn" ? "warn" : v === "pass" ? "active" : "neutral");
  const verdictLabel = (v) => (v === "pass" ? "OK" : v === "warn" ? "WARN" : v === "fail" ? "FAIL" : "미측정");
  const setCv = (id, name, v, detail = "") => {
    const el = $(id);
    el.setAttribute("status", verdictStatus(v));
    el.textContent = `${name}: ${verdictLabel(v)}${detail}`;
  };
  const dCam = cv.depth || {};
  const dInfo = Number.isFinite(dCam.cam_to_table_mm) ? ` (${dCam.cam_to_table_mm}mm)` : "";
  setCv("cvDepthTag", "Depth", dCam.verdict, dInfo);
  const tInfo = Number.isFinite(cv.touch?.max_diff_mm) ? ` (max ${cv.touch.max_diff_mm}mm)` : "";
  setCv("cvTouchTag", "Touch", cv.touch?.verdict, tInfo);
  const mInfo = Number.isFinite(cv.map?.max_loo_mm) ? ` (${cv.map.max_loo_mm}mm)` : "";
  setCv("cvMapTag", "Map", cv.map?.verdict, mInfo);
  const fInfo = Number.isFinite(cv.fk?.tcp_z_m) ? ` (z=${cv.fk.tcp_z_m}m)` : "";
  setCv("cvFkTag", "FK", cv.fk?.verdict, fInfo);
  const parts = [];
  if (Number.isFinite(dCam.cam_to_table_mm)) parts.push(`cam→table=${dCam.cam_to_table_mm}mm (cfg ${dCam.config_height_m ?? "-"}m)`);
  if (Number.isFinite(dCam.plate_mm)) parts.push(`plate=${dCam.plate_mm}mm`);
  if (cv.measured) parts.push(`verify ${cv.measured}`);
  $("crossVerifyMeta").textContent = parts.length ? parts.join(" · ") : "depth-verify.json 없음 (surface-*.json / Map / FK만 표시)";

  const biasWrap = $("biasTableWrap");
  biasWrap.replaceChildren();
  const regions = profile?.bias?.regions || [];
  if (regions.length === 0) {
    const p = document.createElement("p");
    p.className = "cal-muted";
    p.textContent = "등록된 pivot-near bias region이 없습니다.";
    biasWrap.appendChild(p);
    return;
  }
  const { tbl, tbody } = makeTable(["Site", "Bias (dx, dy mm)", "RMS", "Samples", "Map SHA"]);
  for (const r of regions) {
    const tr = document.createElement("tr");
    const cells = [r.site || "-", `${r.bias_mm[0]}, ${r.bias_mm[1]}`, `${r.rms_mm ?? "-"}`, `${r.n ?? r.samples ?? "-"}`];
    for (const val of cells) {
      const td = document.createElement("td");
      td.textContent = val;
      tr.appendChild(td);
    }
    const tdSha = document.createElement("td");
    tdSha.setAttribute("data-level", r.stale_map ? "warn" : "ok");
    tdSha.textContent = `${r.map_sha || "-"} (${r.stale_map ? "stale" : "fresh"})`;
    tr.appendChild(tdSha);
    tr.addEventListener("click", () => {
      state.selectedKey = `bias:${r.site}`;
      state.selectedData = { kind: "bias", ...r };
      if (profile.sites?.[r.site]) state.siteName = r.site;
      renderAll();
    });
    tbody.appendChild(tr);
  }
  biasWrap.appendChild(tbl);
}

function renderSitesTable(profile) {
  const wrap = $("sitesTableWrap");
  wrap.replaceChildren();
  const entries = Object.entries(profile?.sites || {});
  const extras = entries.filter(([, s]) => s.extra).length;
  $("siteCountNote").textContent = `${entries.length}개 site (extra ${extras}개)`;

  const { tbl, tbody } = makeTable(["Site", "z_view / surf_z", "Depth Δ", "Touch Δ", "Map 출처", "점(OK/Drop/Plan)", "Max LOO", "비고"]);
  for (const [name, s] of entries) {
    const tr = document.createElement("tr");
    if (name === state.siteName) tr.setAttribute("data-selected", "true");
    const m = s.map;
    const zTxt = `${m?.z_view ?? "-"} / ${s.surface_z ?? "없음"}`;
    const fmtDiff = (val, z) => {
      if (!Number.isFinite(val)) return Number.isFinite(z) ? `${z}m` : "-";
      return `${val >= 0 ? "+" : ""}${val.toFixed(1)}mm`;
    };
    const depthTxt = Number.isFinite(s.place_vs_start_step_mm) && Math.abs(s.place_vs_start_step_mm) > 8
      ? `${fmtDiff(s.depth_diff_mm, s.depth_surface_z)} (step ${s.place_vs_start_step_mm >= 0 ? "+" : ""}${s.place_vs_start_step_mm.toFixed(0)}mm)`
      : fmtDiff(s.depth_diff_mm, s.depth_surface_z);
    const touchTxt = fmtDiff(s.touch_diff_mm, s.touch_surface_z);
    const srcTxt = s.extra ? "EXTRA(미사용)" : s.map_from ? `← ${s.map_from}` : s.in_map_sites ? "직접측정" : "미지정";
    const ptsTxt = m ? `${m.inlier_count}/${m.dropped_count}/${m.planned_count}` : "-";
    const lmax = m?.loo_error_mm?.max;
    const looTxt = Number.isFinite(lmax) ? `${lmax.toFixed(1)} mm` : "-";

    const tdName = document.createElement("td");
    tdName.textContent = name;
    if (s.extra) tdName.setAttribute("data-level", "warn");
    const tdZ = document.createElement("td");
    tdZ.textContent = zTxt;
    const tdDepth = document.createElement("td");
    tdDepth.textContent = depthTxt;
    if ((Number.isFinite(s.depth_diff_mm) && Math.abs(s.depth_diff_mm) > 6) || (Number.isFinite(s.place_vs_start_step_mm) && Math.abs(s.place_vs_start_step_mm) > 8)) {
      tdDepth.setAttribute("data-level", "warn");
    } else if (Number.isFinite(s.depth_diff_mm)) {
      tdDepth.setAttribute("data-level", "ok");
    }
    const tdTouch = document.createElement("td");
    tdTouch.textContent = touchTxt;
    if (Number.isFinite(s.touch_diff_mm) && Math.abs(s.touch_diff_mm) > 5) tdTouch.setAttribute("data-level", "error");
    else if (Number.isFinite(s.touch_diff_mm)) tdTouch.setAttribute("data-level", "ok");
    const tdSrc = document.createElement("td");
    tdSrc.textContent = srcTxt;
    const tdPts = document.createElement("td");
    tdPts.textContent = ptsTxt;
    const tdLoo = document.createElement("td");
    tdLoo.textContent = looTxt;
    if (Number.isFinite(lmax) && lmax > 15) tdLoo.setAttribute("data-level", "error");
    else if (Number.isFinite(lmax) && lmax > 5) tdLoo.setAttribute("data-level", "warn");
    const tdNote = document.createElement("td");
    tdNote.textContent = s.note || (m?.measured ? `measured ${m.measured}` : "-");

    tr.append(tdName, tdZ, tdDepth, tdTouch, tdSrc, tdPts, tdLoo, tdNote);
    tr.addEventListener("click", () => {
      state.siteName = name;
      renderAll();
    });
    tbody.appendChild(tr);
  }
  wrap.appendChild(tbl);
}

function renderCanvases() {
  const profile = currentProfile();
  if (!profile) return;
  const siteObj = profile.sites?.[state.siteName] || null;
  const shift = profile.camera_top?.shift;
  const shiftTxt = shift?.ok ? `shift max ${shift.max_px}px` : "shift n/a";
  $("topCardSub").textContent = `${profile.arm_id} · site=${state.siteName || "-"} · z=${state.zPlane} (z_view=${siteObj?.map?.z_view ?? "-"}, surf_z=${siteObj?.surface_z ?? "-"}) · center=${JSON.stringify(profile.camera_top?.center_px || [])} · ${shiftTxt}`;
  const maxReach = profile.limits?.max_reach_m != null ? `${profile.limits.max_reach_m}m` : "n/a";
  const parkReach = profile.limits?.park_reach_m != null ? `${profile.limits.park_reach_m}m` : "n/a";
  $("armCardSub").textContent = `${profile.arm_id} · max_reach=${maxReach} · park=${parkReach} · LOO scale ${state.errorScale}x`;

  const bindErr = profile.hygiene?.find((h) => h.code === "map_binding")?.message;
  const bindTag = $("frameBindTag");
  bindTag.setAttribute("status", bindErr ? "warn" : "active");
  bindTag.textContent = bindErr ? "MAP UNBOUND" : "MAP BOUND";

  const img = loadFrameImage(profile.id, state.frameSource);
  const topRes = renderTopView($("topCanvas"), {
    profile,
    siteName: state.siteName,
    image: img,
    layers: state.layers,
    zPlane: state.zPlane,
    errorScale: state.errorScale,
    selectedKey: state.selectedKey,
  });
  state.lastTopHitTargets = topRes?.hitTargets || [];

  const armRes = renderArmGrid($("armCanvas"), {
    profile,
    siteName: state.siteName,
    layers: state.layers,
    errorScale: state.errorScale,
    selectedKey: state.selectedKey,
  });
  state.lastArmHitTargets = armRes?.hitTargets || [];
}

function pickHit(canvas, clientX, clientY, targets) {
  const rect = canvas.getBoundingClientRect();
  if (!rect.width || !rect.height) return null;
  const x = ((clientX - rect.left) * canvas.width) / rect.width;
  const y = ((clientY - rect.top) * canvas.height) / rect.height;
  let best = null;
  let bestD = 18;
  for (const t of targets) {
    const d = Math.hypot(t.x - x, t.y - y);
    if (d < bestD) {
      bestD = d;
      best = t;
    }
  }
  return best;
}

function renderAll() {
  const profile = currentProfile();
  if (!profile) {
    $("profileBar").replaceChildren();
    $("hygienePanel").setAttribute("data-level", "ok");
    const summary = $("hygieneSummary");
    summary.setAttribute("state", "empty");
    summary.textContent = "등록된 캘리브레이션 프로파일이 없습니다 (--profiles 또는 ROSY_CALIBRATION_PROFILES 미설정).";
    $("profileSourceTag").setAttribute("status", "neutral");
    $("profileSourceTag").textContent = "NO PROFILES";
    return;
  }
  if (!state.siteName || !profile.sites?.[state.siteName]) {
    state.siteName = defaultSiteForProfile(profile);
  }
  $("gridStage").setAttribute("data-layout", state.layout);
  renderProfileBar();
  renderHygiene(profile);
  renderSiteSelect(profile);
  renderRobotAndBias(profile);
  renderSitesTable(profile);
  renderInspector();
  renderCanvases();
}

async function loadSnapshot() {
  try {
    const data = await fetchJson("/api/calibration/v1/profiles");
    state.bundle = data;
    if (!state.profileId || !data.profiles?.some((p) => p.id === state.profileId)) {
      state.profileId = data.profiles?.[0]?.id || null;
    }
    if (!state.siteName) state.siteName = defaultSiteForProfile(currentProfile());
    renderAll();
  } catch (err) {
    const summary = $("hygieneSummary");
    summary.setAttribute("state", err.status === 401 ? "forbidden" : "error");
    summary.textContent = err.status === 401 ? "Rosy Account로 로그인해야 프로파일 모눈종이를 볼 수 있습니다." : `프로파일 로드 실패: ${err.message}`;
  }
}

function wireControls(reqs) {
  const tabGrid = $("tabGrid");
  const tabReq = $("tabRequests");
  const switchTab = (isGrid) => {
    tabGrid.classList.toggle("active", isGrid);
    tabReq.classList.toggle("active", !isGrid);
    tabGrid.setAttribute("aria-selected", isGrid ? "true" : "false");
    tabReq.setAttribute("aria-selected", !isGrid ? "true" : "false");
    $("panelGrid").hidden = !isGrid;
    $("panelRequests").hidden = isGrid;
    if (!isGrid) reqs.refresh();
  };
  tabGrid.addEventListener("click", () => switchTab(true));
  tabReq.addEventListener("click", () => switchTab(false));

  $("btnTheme").addEventListener("click", () => {
    const next = (window.RosyTheme?.resolved?.() || "dark") === "dark" ? "light" : "dark";
    window.RosyTheme?.set?.(next);
    renderCanvases();
  });
  $("btnReloadSnapshot").addEventListener("click", () => loadSnapshot());
  $("btnRefreshFrame").addEventListener("click", () => refreshActiveFrame());
  $("btnClearSelect").addEventListener("click", () => {
    state.selectedKey = null;
    state.selectedData = null;
    renderCanvases();
    renderInspector();
  });

  $("siteSelect").addEventListener("change", (ev) => {
    state.siteName = ev.target.value;
    state.selectedKey = null;
    state.selectedData = null;
    renderAll();
  });

  const zBtns = [$("zPlaneView"), $("zPlaneSurface")];
  $("zPlaneView").addEventListener("click", () => { state.zPlane = "z_view"; setSegmentGroup(zBtns, $("zPlaneView")); renderCanvases(); });
  $("zPlaneSurface").addEventListener("click", () => { state.zPlane = "surface"; setSegmentGroup(zBtns, $("zPlaneSurface")); renderCanvases(); });

  const fBtns = [$("frameRef"), $("frameLive")];
  $("frameRef").addEventListener("click", () => { state.frameSource = "reference"; setSegmentGroup(fBtns, $("frameRef")); renderCanvases(); });
  $("frameLive").addEventListener("click", () => { state.frameSource = "live"; setSegmentGroup(fBtns, $("frameLive")); renderCanvases(); });

  const scaleBtns = [$("scale1"), $("scale5"), $("scale10")];
  for (const b of scaleBtns) {
    b.addEventListener("click", () => { state.errorScale = Number(b.getAttribute("data-scale")) || 5; setSegmentGroup(scaleBtns, b); renderCanvases(); });
  }
  const layoutBtns = [$("layoutBoth"), $("layoutTop"), $("layoutArm")];
  for (const b of layoutBtns) {
    b.addEventListener("click", () => { state.layout = b.getAttribute("data-layout") || "both"; setSegmentGroup(layoutBtns, b); $("gridStage").setAttribute("data-layout", state.layout); });
  }
  for (const [id, key] of [["layerPxGrid", "pxGrid"], ["layerMetricGrid", "metricGrid"], ["layerSites", "sites"], ["layerPoints", "points"], ["layerBias", "bias"], ["layerTcp", "centerAndTcp"]]) {
    $(id).addEventListener("change", (ev) => { state.layers[key] = Boolean(ev.target.checked); renderCanvases(); });
  }

  for (const [canvasId, getTargets] of [["topCanvas", () => state.lastTopHitTargets], ["armCanvas", () => state.lastArmHitTargets]]) {
    const c = $(canvasId);
    c.addEventListener("click", (ev) => {
      const hit = pickHit(c, ev.clientX, ev.clientY, getTargets());
      if (hit) {
        state.selectedKey = hit.key;
        state.selectedData = hit.data;
        renderCanvases();
        renderInspector();
      }
    });
  }
}

const reqs = initRequests({
  onSessionChanged: () => {
    loadSnapshot();
  },
});
wireControls(reqs);
reqs.session.restore().then(() => {
  reqs.refresh();
  loadSnapshot();
});
