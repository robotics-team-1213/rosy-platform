import { addDtDd, renderInspector } from "./inspector.js";
export { addDtDd };
import "/common/ui.js";
import { renderTopView, renderArmGrid } from "./grid.js";
import { initRequests } from "./requests.js";
import { loadJobStatus, setJobArm, setJobOperator } from "./job-status.js";
import { mergeIncident, classifyHold, classifyFrameBinding, classifyDrift, defaultSiteForProfile, linkedArm, profileForArm } from "./status-logic.js";

export const $ = (id) => document.getElementById(id);

const state = {
  bundle: null,
  jobStatus: null,
  profileId: null,
  siteName: null,
  zPlane: "z_view",
  frameSource: "live",
  errorScale: 5,
  layout: "both",
  layers: { pxGrid: true, metricGrid: true, sites: true, points: true, bias: true, centerAndTcp: true },
  selectedKey: null,
  selectedData: null,
  frameCache: new Map(),
  lastTopHitTargets: [],
  lastArmHitTargets: [],
};

function currentProfile() {
  const list = state.bundle?.profiles || [];
  return profileForArm(list, linkedArm(location.search), state.profileId);
}

function syncArmLinks(arm) {
  const login = $("account-login");
  if (!login) return;
  const params = new URLSearchParams(arm ? {arm} : {});
  const original = new URLSearchParams(location.search);
  if (arm && original.get("arm") === arm) {
    for (const key of ["src_site", "dst_site", "task_id"]) {
      for (const value of original.getAll(key)) params.append(key, value);
    }
  }
  login.href = "/api/account/login" + (params.size ? "?" + params : "");
}

function setSegmentGroup(buttons, activeBtn) {
  for (const b of buttons) {
    const on = b === activeBtn;
    b.classList.toggle("active", on);
    b.setAttribute("aria-pressed", on ? "true" : "false");
  }
}

export function makeTable(headers) {
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

export async function fetchJson(url) {
  const res = await fetch(url, { cache: "no-store" });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw Object.assign(new Error(body.error || `${url}: HTTP ${res.status}`), { status: res.status });
  return body;
}

function frameFor(profile, source, force = false) {
  const key = `${profile.id}:${source}`;
  let rec = state.frameCache.get(key);
  const generation = profile.camera_top?.generation;
  if (!rec || rec.expected !== generation) {
    clearTimeout(rec?.expiryTimer);
    rec?.image?.close();
    rec = {expected: generation, image: null, loading: false, next: 0};
    state.frameCache.set(key, rec);
  }
  if (rec.loading || (!force && performance.now() < rec.next)) return rec;
  rec.loading = true;
  const started = performance.now();
  const path = `/api/calibration/v1/profiles/${encodeURIComponent(profile.id)}/frame/${source}`;
  (async () => {
    try {
      const res = await fetch(path, {cache: "no-store"});
      if (!res.ok) throw new Error(String(res.status));
      const image = await createImageBitmap(await res.blob());
      if (state.frameCache.get(key) !== rec) { image.close(); return; }
      rec.image?.close();
      rec.image = image;
      rec.binding = res.headers.get("X-Rosy-Frame-Binding");
      rec.generation = res.headers.get("X-Rosy-Frame-Generation");
      rec.reference = res.headers.get("X-Rosy-Frame-Reference-Sha256");
      rec.shift = res.headers.get("X-Rosy-Frame-Shift-Px");
      rec.expires = started + Number(res.headers.get("X-Rosy-Frame-Lifetime-Ms") || 0);
      clearTimeout(rec.expiryTimer);
      if (source === "live" && rec.binding === "aligned" && rec.expires > performance.now()) {
        rec.expiryTimer = setTimeout(renderCanvases, rec.expires - performance.now() + 1);
      }
      if (rec.generation && rec.expected !== rec.generation && rec.requested !== rec.generation) {
        rec.requested = rec.generation;
        void loadSnapshot();
      }
    } catch {
      rec.image?.close();
      rec.image = null;
    } finally {
      rec.loading = false;
      rec.next = source === "live" ? performance.now() + 600 : Infinity;
      if (state.frameCache.get(key) === rec && currentProfile()?.id === profile.id && state.frameSource === source) renderCanvases();
    }
  })();
  return rec;
}

function refreshActiveFrame() {
  const profile = currentProfile();
  if (profile) frameFor(profile, state.frameSource, true);
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
      const url = new URL(location.href);
      const arm = p.arm_id || p.id;
      if (url.searchParams.get("arm") !== arm) {
        for (const key of ["src_site", "dst_site", "task_id"]) url.searchParams.delete(key);
        if (url.hash.startsWith("#route-")) url.hash = "";
      }
      if (["arm_a", "arm_b", "arm_s"].includes(arm)) url.searchParams.set("arm", arm);
      else url.searchParams.delete("arm");
      history.replaceState(null, "", url);
      state.profileId = p.id;
      state.siteName = defaultSiteForProfile(p);
      state.selectedKey = null;
      state.selectedData = null;
      renderAll();
    });
    bar.appendChild(btn);
  }
  const arm = currentProfile()?.arm_id || currentProfile()?.id;
  if (["arm_s", "arm_a", "arm_b"].includes(arm)) {
    const link = document.createElement("a");
    link.href = `/?arm=${arm}`;
    link.textContent = `${arm} 보정 링크`;
    bar.append(link);
  }
}

function effectiveIncident(profile) {
  return mergeIncident(profile?.robot_status?.incident, state.jobStatus?.arms?.[profile?.arm_id || profile?.id]?.incident);
}

function renderHygiene(profile) {
  const panel = $("hygienePanel");
  const summary = $("hygieneSummary");
  const list = $("hygieneList");
  const toggleLabel = $("hygieneToggleLabel");
  list.replaceChildren();

  const hold = classifyHold(effectiveIncident(profile));
  const items = profile?.hygiene || [];
  const errs = items.filter((i) => i.level === "error");
  const warns = items.filter((i) => i.level === "warning");

  if (hold.state === "held") {
    panel.setAttribute("data-level", "error");
    summary.setAttribute("state", "error");
    summary.textContent = `${profile.arm_id}: ${hold.badge} — 실행 보류 중`;
  } else if (errs.length > 0) {
    panel.setAttribute("data-level", "error");
    summary.setAttribute("state", "error");
    summary.textContent = `${profile.arm_id}: 오류 ${errs.length}건 · 경고 ${warns.length}건 — ${errs[0].message}`;
  } else if (warns.length > 0) {
    panel.setAttribute("data-level", "warn");
    summary.setAttribute("state", "warning");
    summary.textContent = `${profile.arm_id}: 경고 ${warns.length}건 — ${warns[0].message}`;
  } else if (hold.state === "error" || hold.state === "partial") {
    panel.setAttribute("data-level", "warn");
    summary.setAttribute("state", "warning");
    summary.textContent = `${profile.arm_id}: ${hold.badge} (${hold.detail})`;
  } else {
    panel.setAttribute("data-level", "ok");
    summary.setAttribute("state", "ready");
    const extras = [!profile.camera_top?.shift?.ok ? "카메라 이동 미확인" : "", hold.state === "unknown" ? "보류 미확인" : ""].filter(Boolean);
    summary.textContent = extras.length ? `${profile.arm_id}: 프로파일·지도 결속 (${extras.join(" · ")})` : `${profile.arm_id}: 프로파일 및 지도 정합 이상 없음`;
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
  holdTag.setAttribute("status", hold.status);
  holdTag.textContent = hold.badge;
  holdTag.title = hold.detail;

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

function renderRobotAndBias(profile) {
  const dl = $("robotStatusDl");
  dl.replaceChildren();
  const live = profile?.robot_status?.live || {};
  const hold = classifyHold(effectiveIncident(profile));
  const op = profile?.operating_profile || {};
  const envTag = $("envTag");

  addDtDd(dl, "arm_id / zone", `${profile.arm_id} (${profile.zone_side || "-"} ↔ ${profile.zone_peer || "-"})`);
  addDtDd(dl, "hold 상태", hold.detail);
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
  const driftInfo = classifyDrift(profile);
  const drift = driftInfo.drift;
  const verdictStatus = (v) => (v === "fail" || v === "hold" ? "crit" : v === "warn" || v === "advisory" ? "warn" : v === "pass" ? "active" : "neutral");
  const verdictLabel = (v) => (v === "pass" ? "OK" : v === "warn" ? "WARN" : v === "fail" ? "FAIL" : v === "hold" ? "HOLD" : v === "advisory" ? "ADVISORY" : "미측정");
  const setCv = (id, name, v, detail = "") => {
    const el = $(id);
    if (!el) return;
    el.setAttribute("status", verdictStatus(v));
    el.textContent = `${name}: ${verdictLabel(v)}${detail}`;
  };
  const evDate = typeof cv.measured === "string" && cv.measured.length >= 10 ? ` (${cv.measured.slice(0, 10)})` : "";
  setCv("cvEvalTag", "Eval", cv.eval_verdict || "unknown", evDate);
  const dCam = cv.depth || {};
  const dInfo = Number.isFinite(dCam.cam_to_table_mm) ? ` (${dCam.cam_to_table_mm}mm)` : "";
  setCv("cvDepthTag", "Depth", dCam.verdict, dInfo);
  const tInfo = Number.isFinite(cv.touch?.max_diff_mm) ? ` (max ${cv.touch.max_diff_mm}mm)` : "";
  setCv("cvTouchTag", "Touch", cv.touch?.verdict, tInfo);
  const mInfo = Number.isFinite(cv.map?.max_loo_mm) ? ` (${cv.map.max_loo_mm}mm)` : "";
  setCv("cvMapTag", "Map", cv.map?.verdict, mInfo);
  const lat = cv.lateral_xy || {};
  const xyVerdict = lat.verdict || (cv.lateral_xy_verified === true ? "pass" : "unknown");
  const maxLatMm = Object.values(lat.sites || {}).reduce(
    (acc, s) => (Number.isFinite(s?.residual_mag_mm) ? Math.max(acc, s.residual_mag_mm) : acc), -1,
  );
  setCv("cvXyTag", "XY", xyVerdict, maxLatMm >= 0 ? ` (max ${maxLatMm}mm)` : "");
  const fInfo = Number.isFinite(cv.fk?.tcp_z_m) ? ` (z=${cv.fk.tcp_z_m}m)` : "";
  setCv("cvFkTag", "FK", cv.fk?.verdict, fInfo);
  setCv("cvDriftTag", "Drift", driftInfo.verdict, driftInfo.detail);
  const parts = [];
  if (Number.isFinite(dCam.cam_to_table_mm)) parts.push(`cam→table=${dCam.cam_to_table_mm}mm (cfg ${dCam.config_height_m ?? "-"}m)`);
  if (Number.isFinite(dCam.cam_to_plate_mm)) parts.push(`cam→plate=${dCam.cam_to_plate_mm}mm`);
  else if (Number.isFinite(dCam.plate_mm)) parts.push(`plate=${dCam.plate_mm}mm`);
  if (!cv.lateral_xy_verified) parts.push(xyVerdict === "unmeasured" || xyVerdict === "unknown" ? "XY미검증" : `XY=${xyVerdict}`);
  if ((drift.suggested_advisory || []).length) parts.push(`권고: ${drift.suggested_advisory.join(", ")}`);
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
    const siteTxt = r.kind && r.kind !== "pivot" ? `${r.site || "-"} (${r.kind})` : (r.site || "-");
    const cells = [siteTxt, `${r.bias_mm[0]}, ${r.bias_mm[1]}`, `${r.rms_mm ?? "-"}`, `${r.n ?? r.samples ?? "-"}`];
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
    const sigmaMax = s.map_sigma_mm?.max_mm;
    const looTxt = (Number.isFinite(lmax) ? `${lmax.toFixed(1)}mm` : "-") + (Number.isFinite(sigmaMax) ? ` · ±${sigmaMax.toFixed(1)}` : "");
    const alarmed = classifyDrift(profile).alarmed.includes(name);

    const tdName = document.createElement("td"); tdName.textContent = name;
    if (s.extra) tdName.setAttribute("data-level", "warn");
    const tdZ = document.createElement("td"); tdZ.textContent = zTxt;
    const tdDepth = document.createElement("td"); tdDepth.textContent = depthTxt;
    if ((Number.isFinite(s.depth_diff_mm) && Math.abs(s.depth_diff_mm) > 6) || (Number.isFinite(s.place_vs_start_step_mm) && Math.abs(s.place_vs_start_step_mm) > 8)) tdDepth.setAttribute("data-level", "warn");
    else if (Number.isFinite(s.depth_diff_mm)) tdDepth.setAttribute("data-level", "ok");
    const tdTouch = document.createElement("td"); tdTouch.textContent = touchTxt;
    if (Number.isFinite(s.touch_diff_mm) && Math.abs(s.touch_diff_mm) > 5) tdTouch.setAttribute("data-level", "error");
    else if (Number.isFinite(s.touch_diff_mm)) tdTouch.setAttribute("data-level", "ok");
    const tdSrc = document.createElement("td"); tdSrc.textContent = srcTxt;
    const tdPts = document.createElement("td"); tdPts.textContent = ptsTxt;
    const tdLoo = document.createElement("td"); tdLoo.textContent = looTxt;
    if (Number.isFinite(lmax) && lmax > 15) tdLoo.setAttribute("data-level", "error");
    else if (Number.isFinite(lmax) && lmax > 5) tdLoo.setAttribute("data-level", "warn");
    const tdNote = document.createElement("td");
    const noteText = s.note || (m?.measured ? `measured ${m.measured}` : "-");
    tdNote.textContent = alarmed ? `[DRIFT] ${noteText}` : noteText;
    if (alarmed) tdNote.setAttribute("data-level", "warn");

    tr.append(tdName, tdZ, tdDepth, tdTouch, tdSrc, tdPts, tdLoo, tdNote);
    tr.addEventListener("click", () => { state.siteName = name; renderAll(); });
    tbody.appendChild(tr);
  }
  wrap.appendChild(tbl);
}

function renderCanvases() {
  const profile = currentProfile();
  if (!profile) return;
  const siteObj = profile.sites?.[state.siteName] || null;
  const source = state.frameSource;
  const frame = frameFor(profile, source);
  const verified = Boolean(frame.image && frame.generation && frame.generation === frame.expected &&
    frame.reference && frame.reference === profile.camera_top?.reference_sha256 &&
    (source === "reference" ? frame.binding === "reference" :
      frame.binding === "aligned" && performance.now() < frame.expires));
  const tagged = source === "reference" ? "기준 영상 일치" : "실시간 영상 정합 확인";
  const shiftText = frame.shift == null ? "" : `이동 ${frame.shift}px`;
  const fb = classifyFrameBinding(profile);
  $("topCardSub").textContent = `${profile.arm_id} · site=${state.siteName || "-"} · z=${state.zPlane} (z_view=${siteObj?.map?.z_view ?? "-"}, surf_z=${siteObj?.surface_z ?? "-"}) · center=${JSON.stringify(profile.camera_top?.center_px || [])} · ${shiftText || fb.shiftText}`;
  const maxReach = profile.limits?.max_reach_m != null ? `${profile.limits.max_reach_m}m` : "n/a";
  const parkReach = profile.limits?.park_reach_m != null ? `${profile.limits.park_reach_m}m` : "n/a";
  $("armCardSub").textContent = `${profile.arm_id} · max_reach=${maxReach} · park=${parkReach} · LOO scale ${state.errorScale}x`;

  const bindTag = $("frameBindTag");
  bindTag.setAttribute("status", verified ? "ok" : "warn");
  bindTag.textContent = verified ? tagged : "정합 미확인 · 오버레이 숨김";
  bindTag.title = verified ? [tagged, shiftText].filter(Boolean).join(" · ") : (shiftText || fb.title);

  const topRes = renderTopView($("topCanvas"), {
    profile, siteName: state.siteName, image: frame.image, frameSource: source, frameVerified: verified, layers: state.layers,
    zPlane: state.zPlane, errorScale: state.errorScale, selectedKey: state.selectedKey,
  });
  state.lastTopHitTargets = topRes?.hitTargets || [];

  const armRes = renderArmGrid($("armCanvas"), {
    profile, siteName: state.siteName, layers: state.layers,
    errorScale: state.errorScale, selectedKey: state.selectedKey,
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
  const arm = linkedArm(location.search) || profile?.arm_id || profile?.id || null;
  setJobArm(arm);
  syncArmLinks(linkedArm(location.search));
  if (!profile) {
    renderProfileBar();
    $("hygienePanel").setAttribute("data-level", "ok");
    const summary = $("hygieneSummary");
    summary.setAttribute("state", "empty");
    summary.textContent = arm ? `${arm} 보정 프로파일이 등록되어 있지 않습니다.` : "등록된 캘리브레이션 프로파일이 없습니다.";
    $("profileSourceTag").setAttribute("status", "neutral");
    $("profileSourceTag").textContent = "NO PROFILES";
    const holdTag = $("holdBadge");
    holdTag.setAttribute("status", "neutral");
    holdTag.textContent = "HOLD 미확인";
    holdTag.title = "미확인 (보류 정보 없음)";
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
  renderInspector(state.selectedData);
  renderCanvases();
}

async function loadSnapshot() {
  loadJobStatus({  // independent of the profile registry: --cells alone turns the section on
    onStatus: (st) => {
      state.jobStatus = st;
      const p = currentProfile();
      if (p) { renderHygiene(p); renderRobotAndBias(p); }
    },
  });
  try {
    const data = await fetchJson("/api/calibration/v1/profiles");
    state.bundle = data;
    state.profileId = currentProfile()?.id || null;
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
    state.selectedKey = null; state.selectedData = null; renderCanvases(); renderInspector(state.selectedData);
  });
  $("siteSelect").addEventListener("change", (ev) => {
    state.siteName = ev.target.value; state.selectedKey = null; state.selectedData = null; renderAll();
  });
  const zBtns = [$("zPlaneView"), $("zPlaneSurface")];
  const fBtns = [$("frameRef"), $("frameLive")];
  for (const [el, val, grp, key] of [
    [$("zPlaneView"), "z_view", zBtns, "zPlane"], [$("zPlaneSurface"), "surface", zBtns, "zPlane"],
    [$("frameRef"), "reference", fBtns, "frameSource"], [$("frameLive"), "live", fBtns, "frameSource"],
  ]) el.addEventListener("click", () => { state[key] = val; setSegmentGroup(grp, el); renderCanvases(); });

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
      if (hit) { state.selectedKey = hit.key; state.selectedData = hit.data; renderCanvases(); renderInspector(state.selectedData); }
    });
  }
}

const initialArm = linkedArm(location.search);
syncArmLinks(initialArm);
setJobArm(initialArm);
const reqs = initRequests({ onSessionChanged: account => {
  setJobOperator(account.can_operate === true);
  loadSnapshot();
} });
wireControls(reqs);
reqs.session.restore().then(() => { reqs.refresh(); loadSnapshot(); });

setInterval(() => {
  if (!document.hidden && !$("panelGrid").hidden && state.frameSource === "live") renderCanvases();
}, 400);
