// Calibration "모눈종이" (Top-Camera Overlay + Arm-Base Metric XY Grid) Canvas Renderer.
// Reads all colours and fonts exclusively from window.RosyPalette (tokens.css) so dark/light themes
// and shared/web token contracts remain intact without inline styles or raw hex values.

const tone = (name) => window.RosyPalette.cssColor(name);
const font = (role = "micro", family = "mono") => window.RosyPalette.canvasFont(role, family);
const siteHit = (site, role, s, pt) => ({ kind: "site", role, site, surface_z: s.surface_z, depth_surface_z: s.depth_surface_z, depth_diff_mm: s.depth_diff_mm, place_vs_start_step_mm: s.place_vs_start_step_mm, touch_surface_z: s.touch_surface_z, touch_diff_mm: s.touch_diff_mm, ...pt });

export function invert3x3(h) {
  const [[a, b, c], [d, e, f], [g, i, j]] = h;
  const c00 = e * j - f * i;
  const c01 = c * i - b * j;
  const c02 = b * f - c * e;
  const det = a * c00 + d * c01 + g * c02;
  if (Math.abs(det) < 1e-18) return null;
  const inv = 1 / det;
  return [
    [c00 * inv, c01 * inv, c02 * inv],
    [(f * g - d * j) * inv, (a * j - c * g) * inv, (c * d - a * f) * inv],
    [(d * i - e * g) * inv, (b * g - a * i) * inv, (a * e - b * d) * inv],
  ];
}

export function applyH(m, x, y) {
  const w = m[2][0] * x + m[2][1] * y + m[2][2];
  if (!Number.isFinite(w) || Math.abs(w) < 1e-12) return null;
  return [(m[0][0] * x + m[0][1] * y + m[0][2]) / w, (m[1][0] * x + m[1][1] * y + m[1][2]) / w];
}

export function parallaxPixel(pixel, fromZ, toZ, camera) {
  if (!pixel || !camera?.center_px || !Number.isFinite(camera?.height_m)) return pixel;
  if (!Number.isFinite(fromZ) || !Number.isFinite(toZ)) return pixel;
  const denom = camera.height_m - toZ;
  if (Math.abs(denom) < 1e-6) return pixel;
  const scale = (camera.height_m - fromZ) / denom;
  const [cx, cy] = camera.center_px;
  return [cx + (pixel[0] - cx) * scale, cy + (pixel[1] - cy) * scale];
}

function drawArrow(ctx, x0, y0, x1, y1, color, headSize = 7, dashed = false) {
  const dx = x1 - x0;
  const dy = y1 - y0;
  const len = Math.hypot(dx, dy);
  ctx.save();
  ctx.strokeStyle = color;
  ctx.fillStyle = color;
  ctx.lineWidth = 2;
  if (dashed) ctx.setLineDash([4, 3]);
  ctx.beginPath();
  ctx.moveTo(x0, y0);
  ctx.lineTo(x1, y1);
  ctx.stroke();
  ctx.setLineDash([]);
  if (len >= 4) {
    const ang = Math.atan2(dy, dx);
    ctx.beginPath();
    ctx.moveTo(x1, y1);
    ctx.lineTo(x1 - headSize * Math.cos(ang - Math.PI / 6), y1 - headSize * Math.sin(ang - Math.PI / 6));
    ctx.lineTo(x1 - headSize * Math.cos(ang + Math.PI / 6), y1 - headSize * Math.sin(ang + Math.PI / 6));
    ctx.closePath();
    ctx.fill();
  }
  ctx.restore();
}

function drawCross(ctx, x, y, r, color, width = 2) {
  ctx.save();
  ctx.strokeStyle = color;
  ctx.lineWidth = width;
  ctx.beginPath();
  ctx.moveTo(x - r, y - r);
  ctx.lineTo(x + r, y + r);
  ctx.moveTo(x - r, y + r);
  ctx.lineTo(x + r, y - r);
  ctx.stroke();
  ctx.restore();
}

function drawDiamond(ctx, x, y, r, strokeColor, fillColor) {
  ctx.save();
  ctx.beginPath();
  ctx.moveTo(x, y - r);
  ctx.lineTo(x + r, y);
  ctx.lineTo(x, y + r);
  ctx.lineTo(x - r, y);
  ctx.closePath();
  if (fillColor) {
    ctx.fillStyle = fillColor;
    ctx.fill();
  }
  ctx.strokeStyle = strokeColor;
  ctx.lineWidth = 2;
  ctx.stroke();
  ctx.restore();
}

function drawBadge(ctx, x, y, text, fg, bg) {
  ctx.save();
  ctx.font = font("micro", "mono");
  const w = ctx.measureText(text).width + 8;
  const h = 16;
  ctx.fillStyle = bg;
  ctx.fillRect(x, y - h + 3, w, h);
  ctx.fillStyle = fg;
  ctx.textBaseline = "bottom";
  ctx.fillText(text, x + 4, y + 1);
  ctx.restore();
}

function looColor(distMm) {
  if (!Number.isFinite(distMm)) return tone("--series-primary");
  if (distMm > 15) return tone("--status-crit");
  if (distMm > 5) return tone("--status-warn");
  return tone("--status-good");
}

function collectBounds(profile, siteObj) {
  const pts = [[0, 0]];
  const add = (xy) => {
    if (Array.isArray(xy) && Number.isFinite(xy[0]) && Number.isFinite(xy[1])) pts.push([xy[0], xy[1]]);
  };
  const m = siteObj?.map;
  if (m) {
    for (const p of m.points || []) add(p.arm_m);
    for (const d of m.dropped_marks || []) {
      add(d.arm_m);
      add(d.pred_arm_m);
    }
    for (const p of m.planned_points || []) add(p.arm_m);
  }
  for (const s of Object.values(profile.sites || {})) {
    if (s.extra) continue;
    add(s.start?.arm_m);
    add(s.place?.arm_m);
  }
  for (const r of profile.bias?.regions || []) {
    add(r.point_m);
    add(r.map_point_m);
  }
  const tcp = profile.robot_status?.live?.tcp;
  if (tcp) add([tcp.x, tcp.y]);
  let minX = -0.06;
  let maxX = 0.24;
  let minY = -0.16;
  let maxY = 0.24;
  for (const [x, y] of pts) {
    minX = Math.min(minX, x - 0.04);
    maxX = Math.max(maxX, x + 0.04);
    minY = Math.min(minY, y - 0.04);
    maxY = Math.max(maxY, y + 0.04);
  }
  return { minX, maxX, minY, maxY };
}

export function renderTopView(canvas, state) {
  const { profile, siteName, image, layers, zPlane, errorScale, selectedKey } = state;
  const hitTargets = [];
  const size = profile?.camera_top?.frame_size || [640, 480];
  const [fw, fh] = size;
  canvas.width = fw;
  canvas.height = fh;
  const ctx = canvas.getContext("2d");
  ctx.fillStyle = tone("--ground-deep");
  ctx.fillRect(0, 0, fw, fh);

  if (image && image.complete && image.naturalWidth > 0) {
    ctx.drawImage(image, 0, 0, fw, fh);
  } else {
    ctx.fillStyle = tone("--ink-quiet");
    ctx.font = font("label", "body");
    ctx.textAlign = "center";
    ctx.fillText("카메라 프레임 없음", fw / 2, fh / 2);
    ctx.textAlign = "start";
  }

  const siteObj = profile?.sites?.[siteName] || null;
  const map = siteObj?.map || null;
  const invH = map?.homography ? invert3x3(map.homography) : null;
  const cam = profile?.camera_top || {};
  const fitZ = map?.z_view;
  const surfaceZ = siteObj?.surface_z;
  const targetZ = zPlane === "surface" && Number.isFinite(surfaceZ) ? surfaceZ : fitZ;

  const projectArm = (armXy) => {
    if (!invH || !armXy) return null;
    const p = applyH(invH, armXy[0], armXy[1]);
    if (!p) return null;
    return targetZ !== fitZ ? parallaxPixel(p, fitZ, targetZ, cam) : p;
  };

  // 1. Pixel grid (80 px major, 40 px minor)
  if (layers.pxGrid) {
    ctx.save();
    ctx.lineWidth = 1;
    for (let x = 0; x <= fw; x += 40) {
      ctx.strokeStyle = x % 80 === 0 ? tone("--line-30") : tone("--line-10");
      ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, fh); ctx.stroke();
    }
    for (let y = 0; y <= fh; y += 40) {
      ctx.strokeStyle = y % 80 === 0 ? tone("--line-30") : tone("--line-10");
      ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(fw, y); ctx.stroke();
    }
    ctx.fillStyle = tone("--ink-quiet");
    ctx.font = font("micro", "mono");
    ctx.textBaseline = "top";
    for (let x = 80; x < fw; x += 160) ctx.fillText(String(x), x + 2, 2);
    for (let y = 80; y < fh; y += 80) ctx.fillText(String(y), 2, y + 2);
    ctx.restore();
  }

  // 2. Projected arm-space metric 모눈종이 (50mm major, 10mm minor over workspace)
  if (layers.metricGrid && invH) {
    ctx.save();
    const xStart = -0.15;
    const xEnd = 0.25;
    const yStart = -0.20;
    const yEnd = 0.25;
    for (let x = xStart; x <= xEnd + 1e-6; x += 0.01) {
      const rx = Math.round(x * 1000);
      const major = rx % 50 === 0;
      const p0 = projectArm([x, yStart]);
      const p1 = projectArm([x, yEnd]);
      if (!p0 || !p1) continue;
      ctx.strokeStyle = major ? tone("--series-primary") : tone("--line-14");
      ctx.globalAlpha = major ? 0.65 : 0.4;
      ctx.lineWidth = major ? 1.25 : 0.75;
      ctx.beginPath(); ctx.moveTo(p0[0], p0[1]); ctx.lineTo(p1[0], p1[1]); ctx.stroke();
    }
    for (let y = yStart; y <= yEnd + 1e-6; y += 0.01) {
      const ry = Math.round(y * 1000);
      const major = ry % 50 === 0;
      const p0 = projectArm([xStart, y]);
      const p1 = projectArm([xEnd, y]);
      if (!p0 || !p1) continue;
      ctx.strokeStyle = major ? tone("--series-primary") : tone("--line-14");
      ctx.globalAlpha = major ? 0.65 : 0.4;
      ctx.lineWidth = major ? 1.25 : 0.75;
      ctx.beginPath(); ctx.moveTo(p0[0], p0[1]); ctx.lineTo(p1[0], p1[1]); ctx.stroke();
    }
    ctx.globalAlpha = 1;
    ctx.font = font("micro", "mono");
    ctx.fillStyle = tone("--series-primary");
    for (let x = -0.10; x <= 0.20 + 1e-6; x += 0.05) {
      const p = projectArm([x, 0]);
      if (p && p[0] > 8 && p[0] < fw - 36 && p[1] > 14 && p[1] < fh - 8) {
        drawBadge(ctx, p[0] + 2, p[1], `X${Math.round(x * 1000)}`, tone("--series-primary"), tone("--scrim"));
      }
    }
    for (let y = -0.15; y <= 0.20 + 1e-6; y += 0.05) {
      if (Math.abs(y) < 1e-6) continue;
      const p = projectArm([0, y]);
      if (p && p[0] > 8 && p[0] < fw - 36 && p[1] > 14 && p[1] < fh - 8) {
        drawBadge(ctx, p[0] + 2, p[1], `Y${Math.round(y * 1000)}`, tone("--series-primary"), tone("--scrim"));
      }
    }
    ctx.restore();
  }

  // 3. Site polygons & ROIs (pixel-space fixtures at surface_z)
  if (layers.sites) {
    for (const [name, s] of Object.entries(profile?.sites || {})) {
      if (s.extra) continue;
      const active = name === siteName;
      if (Array.isArray(s.surface_px) && s.surface_px.length >= 3) {
        ctx.save();
        ctx.beginPath();
        s.surface_px.forEach(([px, py], idx) => (idx === 0 ? ctx.moveTo(px, py) : ctx.lineTo(px, py)));
        ctx.closePath();
        ctx.strokeStyle = active ? tone("--series-goal") : tone("--line-50");
        ctx.lineWidth = active ? 2 : 1;
        ctx.stroke();
        ctx.fillStyle = tone("--series-goal");
        ctx.globalAlpha = active ? 0.14 : 0.05;
        ctx.fill();
        ctx.globalAlpha = 1;
        drawBadge(ctx, s.surface_px[0][0], s.surface_px[0][1] - 2, name,
          active ? tone("--series-goal") : tone("--ink-quiet"), tone("--scrim"));
        ctx.restore();
      }
      if (active && Array.isArray(s.auto_roi) && s.auto_roi.length === 4) {
        const [x0, y0, x1, y1] = s.auto_roi;
        ctx.save();
        ctx.setLineDash([5, 4]);
        ctx.strokeStyle = tone("--series-secondary");
        ctx.lineWidth = 1.5;
        ctx.strokeRect(x0, y0, x1 - x0, y1 - y0);
        ctx.restore();
      }
    }
    if (siteObj?.start?.arm_m) {
      const sp = projectArm(siteObj.start.arm_m);
      if (sp) {
        drawDiamond(ctx, sp[0], sp[1], 7, tone("--series-goal"), tone("--scrim"));
        drawBadge(ctx, sp[0] + 8, sp[1] + 4, `${siteName}.start`, tone("--series-goal"), tone("--scrim"));
        hitTargets.push({ key: `site:${siteName}:start`, x: sp[0], y: sp[1], data: siteHit(siteName, "start", siteObj, siteObj.start) });
      }
    }
    if (siteObj?.place?.arm_m) {
      const pp = projectArm(siteObj.place.arm_m);
      if (pp) {
        ctx.save();
        ctx.strokeStyle = tone("--series-primary");
        ctx.lineWidth = 2;
        ctx.strokeRect(pp[0] - 6, pp[1] - 6, 12, 12);
        ctx.restore();
        drawBadge(ctx, pp[0] + 8, pp[1] + 16, `${siteName}.place`, tone("--series-primary"), tone("--scrim"));
        hitTargets.push({ key: `site:${siteName}:place`, x: pp[0], y: pp[1], data: siteHit(siteName, "place", siteObj, siteObj.place) });
      }
    }
  }

  // 4. Calibration points, LOO residual vectors, dropped marks, missed planned points
  if (layers.points && map) {
    for (const pl of map.planned_points || []) {
      if (pl.status !== "missed") continue;
      const p = projectArm(pl.arm_m);
      if (!p) continue;
      ctx.save();
      ctx.strokeStyle = tone("--ink-quiet");
      ctx.lineWidth = 1.8;
      ctx.setLineDash([3, 2]);
      ctx.beginPath(); ctx.arc(p[0], p[1], 7, 0, Math.PI * 2); ctx.stroke();
      ctx.restore();
      hitTargets.push({ key: `missed:${pl.arm_m.join(",")}`, x: p[0], y: p[1], data: { kind: "missed", ...pl } });
    }
    for (const d of map.dropped_marks || []) {
      const [ox, oy] = d.pixel;
      const pred = projectArm(d.arm_m) || d.pred_pixel;
      if (pred) drawArrow(ctx, pred[0], pred[1], ox, oy, tone("--status-crit"), 7, true);
      drawCross(ctx, ox, oy, 6, tone("--status-crit"), 2.5);
      drawBadge(ctx, ox + 7, oy, `drop ${d.err_dist_mm}mm`, tone("--status-crit"), tone("--scrim"));
      hitTargets.push({ key: `dropped:${d.arm_m.join(",")}`, x: ox, y: oy, data: { kind: "dropped", ...d } });
    }
    for (const pt of map.points || []) {
      const [px, py] = pt.pixel;
      const col = looColor(pt.loo_dist_mm);
      const key = `inlier:${pt.index}`;
      if (pt.loo_residual_mm && invH) {
        const base = applyH(invH, pt.arm_m[0], pt.arm_m[1]);
        const tip = applyH(
          invH,
          pt.arm_m[0] + (pt.loo_residual_mm[0] * errorScale) / 1000,
          pt.arm_m[1] + (pt.loo_residual_mm[1] * errorScale) / 1000,
        );
        if (base && tip) drawArrow(ctx, px, py, px + (tip[0] - base[0]), py + (tip[1] - base[1]), col, 6, false);
      }
      ctx.save();
      ctx.beginPath(); ctx.arc(px, py, selectedKey === key ? 7 : 5, 0, Math.PI * 2);
      ctx.fillStyle = col; ctx.fill();
      ctx.strokeStyle = tone("--ground-deep"); ctx.lineWidth = 1.5; ctx.stroke();
      ctx.restore();
      hitTargets.push({ key, x: px, y: py, data: { kind: "inlier", ...pt } });
    }
  }

  // 5. Bias vectors & optical center & live TCP
  if (layers.bias) {
    for (const r of profile?.bias?.regions || []) {
      const fkPx = zPlane === "surface" && r.fk_pixel_surface_z ? r.fk_pixel_surface_z : r.fk_pixel_z_view;
      const mapPx = zPlane === "surface" && r.map_pixel_surface_z ? r.map_pixel_surface_z : r.map_pixel_z_view;
      const col = r.stale_map ? tone("--status-warn") : tone("--series-secondary");
      if (fkPx && mapPx) {
        drawArrow(ctx, fkPx[0], fkPx[1], mapPx[0], mapPx[1], col, 7, r.stale_map);
        drawBadge(ctx, mapPx[0] + 6, mapPx[1], `bias ${r.bias_mm[0]},${r.bias_mm[1]}mm`, col, tone("--scrim"));
        hitTargets.push({ key: `bias:${r.site}`, x: fkPx[0], y: fkPx[1], data: { kind: "bias", ...r } });
      }
    }
  }

  if (layers.centerAndTcp) {
    if (Array.isArray(cam.center_px) && cam.center_px.length === 2) {
      const [cx, cy] = cam.center_px;
      ctx.save();
      ctx.strokeStyle = tone("--status-warn");
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.moveTo(cx - 10, cy); ctx.lineTo(cx + 10, cy);
      ctx.moveTo(cx, cy - 10); ctx.lineTo(cx, cy + 10);
      ctx.arc(cx, cy, 5, 0, Math.PI * 2);
      ctx.stroke();
      drawBadge(ctx, cx + 8, cy - 4, "center_px", tone("--status-warn"), tone("--scrim"));
      ctx.restore();
    }
    const tcpPx = profile?.robot_status?.live?.tcp_pixel;
    if (Array.isArray(tcpPx)) {
      const stale = profile.robot_status.live.stale;
      const col = stale ? tone("--ink-quiet") : tone("--robot-1");
      drawDiamond(ctx, tcpPx[0], tcpPx[1], 8, col, null);
      drawBadge(ctx, tcpPx[0] + 9, tcpPx[1], stale ? "TCP (stale)" : "TCP", col, tone("--scrim"));
      hitTargets.push({ key: "tcp", x: tcpPx[0], y: tcpPx[1], data: { kind: "tcp", ...profile.robot_status.live } });
    }
  }

  return { hitTargets, invH, projectArm };
}

export function renderArmGrid(canvas, state) {
  const { profile, siteName, layers, errorScale, selectedKey } = state;
  const hitTargets = [];
  const W = 640;
  const H = 560;
  canvas.width = W;
  canvas.height = H;
  const ctx = canvas.getContext("2d");
  ctx.fillStyle = tone("--ground-deep");
  ctx.fillRect(0, 0, W, H);

  const siteObj = profile?.sites?.[siteName] || null;
  const map = siteObj?.map || null;
  const bounds = collectBounds(profile, siteObj);
  const pad = 42;
  const spanX = Math.max(0.05, bounds.maxX - bounds.minX);
  const spanY = Math.max(0.05, bounds.maxY - bounds.minY);
  const pxPerM = Math.min((W - 2 * pad) / spanX, (H - 2 * pad) / spanY);
  const midX = (bounds.minX + bounds.maxX) / 2;
  const midY = (bounds.minY + bounds.maxY) / 2;
  // Right-handed arm frame: +X right, +Y up!
  const toCanvas = (x, y) => [W / 2 + (x - midX) * pxPerM, H / 2 - (y - midY) * pxPerM];
  const toWorld = (cx, cy) => [midX + (cx - W / 2) / pxPerM, midY - (cy - H / 2) / pxPerM];

  // 1. 모눈종이 10mm minor / 50mm major grid
  const xMinMm = Math.floor(((W / 2 - pad) / pxPerM * -1 + midX) * 100) * 10;
  const xMaxMm = Math.ceil(((W / 2 - pad) / pxPerM + midX) * 100) * 10;
  const yMinMm = Math.floor(((H / 2 - pad) / pxPerM * -1 + midY) * 100) * 10;
  const yMaxMm = Math.ceil(((H / 2 - pad) / pxPerM + midY) * 100) * 10;

  ctx.save();
  ctx.font = font("micro", "mono");
  for (let xm = xMinMm; xm <= xMaxMm; xm += 10) {
    const [cx] = toCanvas(xm / 1000, 0);
    if (cx < pad - 2 || cx > W - pad + 2) continue;
    const major = xm % 50 === 0;
    const axis = xm === 0;
    ctx.strokeStyle = axis ? tone("--ink-quiet") : major ? tone("--line-30") : tone("--line-10");
    ctx.lineWidth = axis ? 1.5 : 1;
    ctx.beginPath(); ctx.moveTo(cx, pad); ctx.lineTo(cx, H - pad); ctx.stroke();
    if (major) {
      ctx.fillStyle = tone("--ink-quiet");
      ctx.textAlign = "center";
      ctx.textBaseline = "top";
      ctx.fillText(String(xm), cx, H - pad + 6);
    }
  }
  for (let ym = yMinMm; ym <= yMaxMm; ym += 10) {
    const [, cy] = toCanvas(0, ym / 1000);
    if (cy < pad - 2 || cy > H - pad + 2) continue;
    const major = ym % 50 === 0;
    const axis = ym === 0;
    ctx.strokeStyle = axis ? tone("--ink-quiet") : major ? tone("--line-30") : tone("--line-10");
    ctx.lineWidth = axis ? 1.5 : 1;
    ctx.beginPath(); ctx.moveTo(pad, cy); ctx.lineTo(W - pad, cy); ctx.stroke();
    if (major) {
      ctx.fillStyle = tone("--ink-quiet");
      ctx.textAlign = "right";
      ctx.textBaseline = "middle";
      ctx.fillText(String(ym), pad - 6, cy);
    }
  }
  ctx.strokeStyle = tone("--border-strong");
  ctx.strokeRect(pad, pad, W - 2 * pad, H - 2 * pad);
  ctx.restore();

  // Origin + axis arrows (+X right, +Y up)
  const [ox, oy] = toCanvas(0, 0);
  drawArrow(ctx, ox, oy, ox + 28, oy, tone("--status-crit"), 6, false);
  drawArrow(ctx, ox, oy, ox, oy - 28, tone("--status-good"), 6, false);
  ctx.save();
  ctx.font = font("micro", "mono");
  ctx.fillStyle = tone("--ink");
  ctx.fillText("+X mm", ox + 30, oy - 3);
  ctx.fillText("+Y mm", ox + 4, oy - 30);
  ctx.restore();

  // 2. Reach & limit circles + low_zones
  const lim = profile?.limits || {};
  const drawCircle = (rM, color, label, dashed = true) => {
    if (!Number.isFinite(rM) || rM <= 0) return;
    ctx.save();
    if (dashed) ctx.setLineDash([5, 4]);
    ctx.strokeStyle = color;
    ctx.lineWidth = 1.25;
    ctx.beginPath(); ctx.arc(ox, oy, rM * pxPerM, 0, Math.PI * 2); ctx.stroke();
    ctx.fillStyle = color;
    ctx.font = font("micro", "mono");
    ctx.fillText(label, ox + rM * pxPerM * 0.7 + 4, oy - rM * pxPerM * 0.7);
    ctx.restore();
  };
  drawCircle(lim.singularity_radius_m, tone("--status-warn"), `r=${Math.round((lim.singularity_radius_m || 0) * 1000)}mm`);
  drawCircle(lim.park_reach_m, tone("--series-secondary"), `park=${Math.round((lim.park_reach_m || 0) * 1000)}mm`);
  drawCircle(lim.max_reach_m, tone("--status-crit"), `max=${Math.round((lim.max_reach_m || 0) * 1000)}mm`);

  for (const lz of lim.low_zones || []) {
    if (!lz?.x || !lz?.y) continue;
    const [x0, y0] = toCanvas(lz.x[0], lz.y[1]);
    const [x1, y1] = toCanvas(lz.x[1], lz.y[0]);
    ctx.save();
    ctx.strokeStyle = tone("--status-warn");
    ctx.setLineDash([4, 3]);
    ctx.strokeRect(x0, y0, x1 - x0, y1 - y0);
    drawBadge(ctx, x0, y0 - 2, `low_zone z>=${lz.z_min_m}`, tone("--status-warn"), tone("--scrim"));
    ctx.restore();
  }

  // 3. Site start / place markers
  if (layers.sites) {
    for (const [name, s] of Object.entries(profile?.sites || {})) {
      if (s.extra) continue;
      const active = name === siteName;
      if (s.start?.arm_m) {
        const [sx, sy] = toCanvas(s.start.arm_m[0], s.start.arm_m[1]);
        drawDiamond(ctx, sx, sy, active ? 7 : 5, active ? tone("--series-goal") : tone("--line-50"), tone("--scrim"));
        if (active) drawBadge(ctx, sx + 8, sy, `${name}.start`, tone("--series-goal"), tone("--scrim"));
        hitTargets.push({ key: `site:${name}:start`, x: sx, y: sy, data: siteHit(name, "start", s, s.start) });
      }
      if (s.place?.arm_m) {
        const [px, py] = toCanvas(s.place.arm_m[0], s.place.arm_m[1]);
        ctx.save();
        ctx.strokeStyle = active ? tone("--series-primary") : tone("--line-50");
        ctx.lineWidth = active ? 2 : 1;
        ctx.strokeRect(px - 5, py - 5, 10, 10);
        ctx.restore();
        if (active) drawBadge(ctx, px + 8, py + 14, `${name}.place`, tone("--series-primary"), tone("--scrim"));
        hitTargets.push({ key: `site:${name}:place`, x: px, y: py, data: siteHit(name, "place", s, s.place) });
      }
    }
  }

  // 4. Calibration points + LOO residuals + dropped + missed
  if (layers.points && map) {
    for (const pl of map.planned_points || []) {
      if (pl.status !== "missed") continue;
      const [px, py] = toCanvas(pl.arm_m[0], pl.arm_m[1]);
      ctx.save();
      ctx.strokeStyle = tone("--ink-quiet");
      ctx.setLineDash([3, 2]);
      ctx.lineWidth = 1.8;
      ctx.beginPath(); ctx.arc(px, py, 7, 0, Math.PI * 2); ctx.stroke();
      ctx.restore();
      hitTargets.push({ key: `missed:${pl.arm_m.join(",")}`, x: px, y: py, data: { kind: "missed", ...pl } });
    }
    for (const d of map.dropped_marks || []) {
      const [tx, ty] = toCanvas(d.arm_m[0], d.arm_m[1]);
      const [px, py] = d.pred_arm_m ? toCanvas(d.pred_arm_m[0], d.pred_arm_m[1]) : [tx, ty];
      if (d.pred_arm_m) drawArrow(ctx, tx, ty, px, py, tone("--status-crit"), 7, true);
      drawCross(ctx, tx, ty, 6, tone("--status-crit"), 2.5);
      drawBadge(ctx, tx + 7, ty, `drop ${d.err_dist_mm}mm`, tone("--status-crit"), tone("--scrim"));
      hitTargets.push({ key: `dropped:${d.arm_m.join(",")}`, x: tx, y: ty, data: { kind: "dropped", ...d } });
    }
    for (const pt of map.points || []) {
      const [ax, ay] = toCanvas(pt.arm_m[0], pt.arm_m[1]);
      const col = looColor(pt.loo_dist_mm);
      const key = `inlier:${pt.index}`;
      if (pt.loo_residual_mm) {
        const [ex, ey] = toCanvas(pt.arm_m[0] + (pt.loo_residual_mm[0] * errorScale) / 1000, pt.arm_m[1] + (pt.loo_residual_mm[1] * errorScale) / 1000);
        drawArrow(ctx, ax, ay, ex, ey, col, 6, false);
      }
      ctx.save();
      ctx.beginPath(); ctx.arc(ax, ay, selectedKey === key ? 7 : 5, 0, Math.PI * 2);
      ctx.fillStyle = col; ctx.fill();
      ctx.strokeStyle = tone("--ground-deep"); ctx.lineWidth = 1.5; ctx.stroke();
      ctx.restore();
      hitTargets.push({ key, x: ax, y: ay, data: { kind: "inlier", ...pt } });
    }
  }

  // 5. Bias vectors (point_m -> point_m + bias_mm/1000, labeled "map - FK") + reach circle
  if (layers.bias) {
    for (const r of profile?.bias?.regions || []) {
      if (!r.point_m) continue;
      const [fx, fy] = toCanvas(r.point_m[0], r.point_m[1]);
      const [mx, my] = r.map_point_m ? toCanvas(r.map_point_m[0], r.map_point_m[1]) : [fx, fy];
      const col = r.stale_map ? tone("--status-warn") : tone("--series-secondary");
      ctx.save();
      ctx.strokeStyle = col;
      if (r.stale_map) ctx.setLineDash([4, 3]);
      ctx.globalAlpha = 0.45;
      ctx.beginPath(); ctx.arc(fx, fy, (r.reach_mm / 1000) * pxPerM, 0, Math.PI * 2); ctx.stroke();
      ctx.restore();
      drawArrow(ctx, fx, fy, mx, my, col, 7, r.stale_map);
      drawBadge(ctx, mx + 6, my + 16, `bias(${r.site}) ${r.bias_mm[0]},${r.bias_mm[1]}mm`, col, tone("--scrim"));
      hitTargets.push({ key: `bias:${r.site}`, x: fx, y: fy, data: { kind: "bias", ...r } });
    }
  }

  // 6. Live TCP + yaw heading
  if (layers.centerAndTcp && profile?.robot_status?.live?.tcp) {
    const tcp = profile.robot_status.live.tcp;
    const stale = profile.robot_status.live.stale;
    const col = stale ? tone("--ink-quiet") : tone("--robot-1");
    const [tx, ty] = toCanvas(tcp.x, tcp.y);
    const rad = (tcp.yaw_deg * Math.PI) / 180;
    drawArrow(ctx, tx, ty, tx + 22 * Math.cos(rad), ty - 22 * Math.sin(rad), col, 6, stale);
    drawDiamond(ctx, tx, ty, 7, col, tone("--scrim"));
    drawBadge(ctx, tx + 8, ty, `TCP (${Math.round(tcp.x * 1000)}, ${Math.round(tcp.y * 1000)})`, col, tone("--scrim"));
    hitTargets.push({ key: "tcp", x: tx, y: ty, data: { kind: "tcp", ...profile.robot_status.live } });
  }

  return { hitTargets, toWorld, toCanvas };
}
