export async function readFixtureFrame(response) {
  if (!(response.headers.get("Content-Type") || "").startsWith("application/json")) {
    return {image: await createImageBitmap(await response.blob()), observation: null};
  }
  const value = await response.json();
  const bytes = Uint8Array.from(atob(value.image), c => c.charCodeAt(0));
  return {image: await createImageBitmap(new Blob([bytes], {type: value.media})), observation: value.fixture_observation};
}

export function fixtureSummary(fixtures) {
  const status = {observed: "전체 외곽 관측", partial: "일부 선분 관측", unverified: "외곽 미확인"};
  const side = {left: "왼쪽", right: "오른쪽", top: "위", bottom: "아래"};
  return Object.entries(fixtures).map(([name, value]) => {
    const lines = [`${name === "pallet" ? "선박" : "임시대"} · ${status[value.status] || "미확인"}`];
    if (value.clipping_edges?.length) lines.push("화면 밖 경계  " + value.clipping_edges.map(s => side[s] || s).join(", "));
    if (value.plane_z_m != null) lines.push(`기준면 Z  ${value.plane_z_m} m · 지도 피팅면 Z  ${value.fit_plane_z_m ?? "미확인"} m`);
    if (value.uncertainty?.projection_limit) lines.push("테두리 높이 미측정 · 기준면 XY는 점검용 추정값");
    const pads = value.placement_slots;
    if (pads) {
      lines.push(`임시대 버전  ${pads.revision || "미확인"} · 빈 트레이 기록 정합  ${pads.status === "candidate" ? "후보 위치 확인" : "미확인"}`);
      if (pads.status === "unverified" && pads.reason) lines.push(String(pads.reason));
      for (const [label, slot] of Object.entries(pads.slots || {})) {
        lines.push(`${label} · ${slot.slot_id || ""}  중심 후보 [${slot.center_px.join(", ")}] px · ±${slot.uncertainty_px ?? "?"} px`);
        const pattern = slot.empty_pattern;
        if (pattern) {
          const state = {visible: "보임", not_visible: "보이지 않음", unknown: "판별 어려움"};
          lines.push(`  빈 패드의 글자·점 무늬  ${state[pattern.status] || "미확인"} · 유사도 ${pattern.score ?? "미측정"} · 점유 미확인`);
        }
        const p = slot.plane_estimate;
        if (p) lines.push(`  ${value.arm_id} 평면 XY  [${p.xy_m.join(", ")}] m · 지도 σ ${p.map_sigma_mm ?? "?"} mm / 허용 ${slot.map_sigma_limit_mm} mm`);
      }
    }
    for (const target of value.targets || []) {
      const point = target.plane_estimate;
      lines.push(`${target.slot} 영상 영역 중심  [${target.center_px.join(", ")}] px`);
      if (point) lines.push(`  ${value.arm_id} 기준면 추정 XY  [${point.xy_m.join(", ")}] m · 지도 σ ${point.map_sigma_mm ?? "미확인"} mm`);
    }
    if (value.outline_arm_xy_m?.length) lines.push("외곽 기준면 추정 XY (m)  " + JSON.stringify(value.outline_arm_xy_m));
    const kinds = {rim_table_boundary: "테두리·작업대 경계", visible_plastic_boundary: "노출된 플라스틱 경계", image_edge: "외곽 선분"};
    for (const segment of value.segments || []) {
      if (segment.points_px?.length) lines.push(`${kinds[segment.kind] || "관측 선분"} (px)  ${JSON.stringify(segment.points_px)}${segment.uncertainty_px != null ? " · ±" + segment.uncertainty_px + " px" : ""}`);
    }
    if (value.uncertainty?.edge_search_radius_px != null) lines.push(`가장자리 탐색 반경  ${value.uncertainty.edge_search_radius_px} px`);
    return lines.join("\n");
  }).join("\n\n");
}

export function drawFixtureOutlines(ctx, fixtures, palette) {
  for (const [name, fixture] of Object.entries(fixtures || {})) {
    if (!["observed", "partial"].includes(fixture.status) && fixture.placement_slots?.status !== "candidate") continue;
    // Segments leave occluded and clipped edges open. Only a fully observed perimeter can close.
    const segments = fixture.status === "observed" && fixture.outline_px?.length ? [fixture.outline_px] :
      (fixture.segments || []).map(line => line.points_px);
    ctx.save();
    ctx.strokeStyle = palette("--series-secondary");
    ctx.fillStyle = ctx.strokeStyle;
    ctx.setLineDash([5, 3]);
    ctx.lineWidth = 2;
    for (const points of segments) {
      if (!Array.isArray(points) || points.length < 2) continue;
      ctx.beginPath();
      points.forEach(([x, y], i) => i ? ctx.lineTo(x, y) : ctx.moveTo(x, y));
      if (fixture.status === "observed" && points === fixture.outline_px) ctx.closePath();
      ctx.stroke();
    }
    const first = segments.find(points => points?.length)?.[0];
    if (first) ctx.fillText(name === "pallet" ? "선박 외곽" : "임시대 외곽", first[0], first[1] - 4);
    if (fixture.placement_slots?.status === "candidate") {
      for (const [label, slot] of Object.entries(fixture.placement_slots.slots || {})) {
        const [x, y] = slot.center_px;
        ctx.beginPath();
        ctx.arc(x, y, 4, 0, Math.PI * 2);
        ctx.stroke();
        ctx.fillText(`${label} 후보`, x + 6, y - 2);
      }
    }
    ctx.restore();
  }
}
