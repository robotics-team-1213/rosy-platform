export function addDtDd(dl, term, value) {
  const dt = document.createElement("dt");
  dt.textContent = term;
  const dd = document.createElement("dd");
  dd.textContent = value;
  dl.append(dt, dd);
}

export function renderInspector(d) {
  const empty = document.getElementById("inspectorEmpty");
  const dl = document.getElementById("inspectorDl");
  dl.replaceChildren();
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
  if (d.map_sigma_mm && Number.isFinite(d.map_sigma_mm.max_mm)) {
    addDtDd(dl, "예측 불확실성 (1σ)", `max ±${d.map_sigma_mm.max_mm} mm (mean ±${d.map_sigma_mm.mean_mm} mm)`);
  }
  if (Array.isArray(d.loo_residual_mm)) {
    addDtDd(dl, "LOO 벡터 (map−arm)", `[${d.loo_residual_mm[0].toFixed(2)}, ${d.loo_residual_mm[1].toFixed(2)}] mm`);
  }
  if (Number.isFinite(d.err_dist_mm)) addDtDd(dl, "Dropped 오차", `${d.err_dist_mm} mm (${d.err_px || "?"} px)`);
  if (d.bias_mm) {
    addDtDd(dl, "Bias (map−FK)", `[${d.bias_mm[0]}, ${d.bias_mm[1]}] mm (RMS ${d.rms_mm ?? "?"} mm)`);
    const sigTxt = Number.isFinite(d.bias_sigma_mm) ? ` · 1σ ±${d.bias_sigma_mm} mm` : "";
    addDtDd(dl, "Fit / Region", `${d.fit_model || "-"} · radius=${d.radius_mm ?? "-"} mm${sigTxt}`);
    const cnt = d.n ?? d.samples ?? "?";
    addDtDd(dl, "Sample / Map SHA", `${cnt}회 / ${d.map_sha || "-"} (${d.stale_map ? "stale" : "fresh"})`);
  }
  if (d.tcp) {
    addDtDd(dl, "Live TCP", `x=${d.tcp.x} y=${d.tcp.y} z=${d.tcp.z} yaw=${d.tcp.yaw_deg}°`);
    addDtDd(dl, "Freshness", d.stale ? `stale (${d.age_s ?? "?"}s)` : `fresh (${d.age_s}s)`);
  }
}
