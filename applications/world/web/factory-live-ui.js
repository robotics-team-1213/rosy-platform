export function createFactoryLiveUi({ statusEl, canvas, playbackControls }) {
  function setStatus(state, text, login = false) {
    if (statusEl.getAttribute("state") !== state) statusEl.setAttribute("state", state);
    if (statusEl.textContent === text && Boolean(statusEl.querySelector("a")) === login) return;
    statusEl.textContent = text;
    if (login) {
      const link = document.createElement("a");
      link.href = "/console/login?return=/console/world";
      link.textContent = "다시 로그인";
      statusEl.replaceChildren("연결 끊김 · ", link);
    }
  }

  return {
    setStatus,
    lockPlayback(locked) {
      for (const control of playbackControls) control?.toggleAttribute("disabled", locked);
    },
    dim(reason) {
      canvas.dataset.streamState = reason;
      canvas.style.opacity = reason ? "0.35" : "";
    },
    idle(frame) {
      const robotAge = frame?.pinky?.state_age_s;
      const observedAt = frame?.observed_at_ms;
      const age = Number.isFinite(robotAge) && Number.isFinite(observedAt)
        ? robotAge + Math.max(0, (Date.now() - observedAt) / 1000) : robotAge;
      setStatus("empty", Number.isFinite(age)
        ? `데이터 지연 · 마지막 상태 ${Math.floor(age)}초 전`
        : "실물 현장 미연결");
    },
  };
}

export function factoryStreamLabel(frame) {
  if (frame.adapter === "real") return "실시간 현장";
  if (frame.stream_mode === "synthetic_demo") return "합성 데모";
  return frame.stream_mode === "live" ? "실시간 SIM" : "검증 재생";
}

export function factoryMetaText(frame, stageName, simName) {
  const stacked = frame.cell_ab?.stacked?.length ?? 0;
  const totalSlots = Number.isInteger(frame.cell_ab?.total_slots) && frame.cell_ab.total_slots > 0
    ? frame.cell_ab.total_slots
    : (stacked > 18 ? 27 : stacked > 9 ? 18 : 9);
  const fields = [frame.world_id, stageName, simName];
  if (Number.isFinite(frame.sim_time_s)) {
    const duration = Number.isFinite(frame.duration_s) ? ` / ${frame.duration_s.toFixed(1)}` : "";
    fields.push(`${frame.sim_time_s.toFixed(1)}${duration}초`);
  }
  fields.push(`적재 ${stacked}/${totalSlots}`);
  if (frame.training) {
    const { episode, step, reward, loss } = frame.training;
    const score = Number.isFinite(reward) ? ` R ${reward.toFixed(2)}`
      : Number.isFinite(loss) ? ` Loss ${loss.toFixed(3)}` : "";
    fields.push(`Ep ${episode} Step ${step}${score}`);
  }
  const fleet = frame.fleet_summary;
  const online = Number.isFinite(fleet?.online) ? `${fleet.online}/${fleet.total}` : "6";
  fields.push(`ROSY Fleet ${online}대 (rosy_42/45/46 · arm_s/a/b)`, frame.run_id);
  if (frame.safety?.estop === true) fields.push("비상정지(E-STOP)");
  return fields.filter(Boolean).join(" · ");
}

export function realMapMismatch(world) {
  const parity = world?.parity;
  if (world?.adapter === "real" && parity?.map_match === false
      && parity.bundle_map_version != null && parity.live_map_version != null) {
    return `지도 버전 차이 (번들 v${parity.bundle_map_version} / 현장 v${parity.live_map_version})`;
  }
  return "";
}
