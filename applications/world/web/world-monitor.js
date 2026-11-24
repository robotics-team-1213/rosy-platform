// Multi-world environment monitor and single-contract parity controller for Rosy World.

const STATUS_LABEL = {
  live: "실시간",
  replay: "검증 재생",
  waiting: "미연결",
  stalled: "중단됨",
};

const ADAPTER_TITLE = {
  real: "Real",
  isaac: "Isaac Sim",
  gazebo: "Gazebo",
  mujoco: "MuJoCo",
};

function makeNode(tag, className, text) {
  const el = document.createElement(tag);
  if (className) el.className = className;
  if (text !== undefined) el.textContent = text;
  return el;
}

export function createWorldMonitor({
  adaptersBarEl,
  worldsStripEl,
  parityEl,
  onSelectWorld,
}) {
  const adapterBtns = adaptersBarEl
    ? [...adaptersBarEl.querySelectorAll("[data-adapter]")]
    : [];
  let selectedAdapter = "all";
  let activeWorldId = null;
  let lastRegistry = null;
  let pollTimer;
  let inflight;
  let active = false;

  function syncAdapterButtons() {
    for (const btn of adapterBtns) {
      btn.setAttribute("aria-pressed", String(btn.dataset.adapter === selectedAdapter));
    }
  }

  function updateParityStatus(world) {
    if (!parityEl) return;
    if (!world) {
      parityEl.setAttribute("state", "ready");
      parityEl.textContent = "검증 번들 기준 · 맵/URDF 일치";
      return;
    }
    if (world.safety?.estop === true) {
      const robots = Array.isArray(world.safety.estop_robots) && world.safety.estop_robots.length
        ? world.safety.estop_robots.join(", ")
        : (ADAPTER_TITLE[world.adapter] ?? world.adapter);
      parityEl.setAttribute("state", "warning");
      parityEl.textContent = `비상정지(E-STOP) 활성 · ${robots}`;
      return;
    }
    if (world.adapter === "real" && world.status === "waiting") {
      parityEl.setAttribute("state", "empty");
      parityEl.textContent = "실물 현장 미연결 · 맵/URDF/짐칸(J-v3) 기준 대기";
      return;
    }
    const p = world.parity;
    if (p?.ok) {
      const label = ADAPTER_TITLE[world.adapter] ?? world.adapter;
      parityEl.setAttribute("state", "ready");
      parityEl.textContent = `현장 동일 · 맵/URDF/J-v3 일치 (${label} 환경)`;
      return;
    }
    const reasons = Array.isArray(p?.reasons) && p.reasons.length
      ? p.reasons.join(", ")
      : "검증 메타 누락";
    parityEl.setAttribute("state", "warning");
    parityEl.textContent = `동등성 불일치 · ${reasons}`;
  }

  function renderStrip() {
    if (!worldsStripEl) return;
    const allWorlds = lastRegistry?.worlds ?? [];
    const visibleWorlds = selectedAdapter === "all"
      ? allWorlds
      : allWorlds.filter((w) => w.adapter === selectedAdapter);
    if (!visibleWorlds.length) {
      worldsStripEl.hidden = allWorlds.length <= 1;
      worldsStripEl.replaceChildren();
      return;
    }
    worldsStripEl.hidden = allWorlds.length <= 1 && selectedAdapter === "all";
    const cards = visibleWorlds.map((w) => {
      const btn = makeNode("button", "world-card");
      btn.type = "button";
      btn.dataset.worldId = w.world_id;
      btn.dataset.adapter = w.adapter;
      btn.dataset.status = w.status;
      btn.dataset.parity = w.parity?.ok ? "ok" : "mismatch";
      btn.dataset.estop = String(Boolean(w.safety?.estop));
      const isSelected = activeWorldId
        ? w.world_id === activeWorldId
        : (selectedAdapter === "all" && w.world_id === "verified-replay");
      btn.setAttribute("aria-pressed", String(isSelected));

      const head = makeNode("span", "world-card-head");
      const title = makeNode("strong", "", w.world_id);
      const st = makeNode(
        "span",
        "world-card-state",
        `${ADAPTER_TITLE[w.adapter] ?? w.adapter} · ${STATUS_LABEL[w.status] ?? w.status}`,
      );
      head.append(title, st);

      let line = "";
      if (w.safety?.estop === true) {
        line = "비상정지(E-STOP) 활성";
      } else if (w.training) {
        const ep = w.training.episode ?? "-";
        const step = w.training.step ?? "-";
        let score = "-";
        if (Number.isFinite(w.training.reward)) {
          score = `R ${w.training.reward.toFixed(2)}`;
        } else if (Number.isFinite(w.training.loss)) {
          score = `Loss ${w.training.loss.toFixed(3)}`;
        }
        const fps = Number.isFinite(w.training.sim_fps) ? `${Math.round(w.training.sim_fps)}Hz` : "";
        line = `Ep ${ep} · Step ${step} · ${score} ${fps}`.trim();
      } else if (w.stage_idx && w.total_stages) {
        line = `단계 ${w.stage_idx}/${w.total_stages}`;
      } else if (w.status === "waiting") {
        line = "CORE/Fleet 실시간 수신 대기";
      } else {
        line = w.parity?.ok ? "맵·로봇·짐칸 일치" : "동등성 경고";
      }
      if (!w.safety?.estop && w.fleet_summary && Number.isFinite(w.fleet_summary.online)) {
        line = `${line} · 온라인 ${w.fleet_summary.online}/${w.fleet_summary.total}대`;
      }
      const meta = makeNode("span", "world-card-meta", `${line} · ${w.parity?.ok ? "동일" : "불일치"}`);
      btn.append(head, meta);
      btn.addEventListener("click", () => {
        activeWorldId = w.world_id;
        renderStrip();
        updateParityStatus(w);
        onSelectWorld?.({ worldId: w.world_id, adapter: w.adapter, world: w });
      });
      return btn;
    });
    worldsStripEl.replaceChildren(...cards);
    const activeObj = visibleWorlds.find((w) => w.world_id === activeWorldId)
      ?? allWorlds.find((w) => w.world_id === activeWorldId)
      ?? visibleWorlds[0];
    updateParityStatus(activeObj);
  }

  async function refresh() {
    if (!active || document.hidden) return;
    inflight?.abort();
    const ctrl = new AbortController();
    inflight = ctrl;
    try {
      const res = await fetch("./api/worlds", { cache: "no-store", signal: ctrl.signal });
      if (!res.ok) {
        updateParityStatus(null);
        return;
      }
      const reg = await res.json();
      if (ctrl.signal.aborted || reg?.schema !== "rosy.world.registry.v1") return;
      lastRegistry = reg;
      renderStrip();
    } catch {
      // Offline bundle fallback: keep baseline parity badge quietly.
      if (!lastRegistry) updateParityStatus(null);
    }
  }

  for (const btn of adapterBtns) {
    btn.addEventListener("click", () => {
      const next = btn.dataset.adapter || "all";
      if (selectedAdapter === next) return;
      selectedAdapter = next;
      syncAdapterButtons();
      const worlds = lastRegistry?.worlds ?? [];
      if (next === "real") {
        const realWorld = worlds.find((w) => w.adapter === "real");
        activeWorldId = realWorld?.world_id ?? "real-site";
        renderStrip();
        onSelectWorld?.({ worldId: activeWorldId, adapter: "real", world: realWorld });
        return;
      }
      if (next === "all") {
        activeWorldId = null;
        renderStrip();
        onSelectWorld?.({ worldId: null, adapter: "all", world: null });
        return;
      }
      const match = worlds.find((w) => w.adapter === next && w.status === "live")
        ?? worlds.find((w) => w.adapter === next);
      if (match) {
        activeWorldId = match.world_id;
        renderStrip();
        onSelectWorld?.({ worldId: match.world_id, adapter: match.adapter, world: match });
      } else {
        renderStrip();
      }
    });
  }

  syncAdapterButtons();

  return {
    start() {
      active = true;
      void refresh();
      clearInterval(pollTimer);
      pollTimer = setInterval(() => { void refresh(); }, 1000);
    },
    stop() {
      active = false;
      clearInterval(pollTimer);
      pollTimer = undefined;
      inflight?.abort();
      inflight = undefined;
    },
    getSelection() {
      return { worldId: activeWorldId, adapter: selectedAdapter };
    },
    updateFromFrame(frame) {
      if (!frame) return;
      const worldObj = (lastRegistry?.worlds ?? []).find((w) => w.world_id === frame.world_id)
        ?? {
          world_id: frame.world_id ?? "verified-replay",
          adapter: frame.adapter ?? frame.simulator ?? "mujoco",
          status: frame.stream_mode === "live" ? "live" : "replay",
          parity: frame.parity,
        };
      if (frame.parity) worldObj.parity = frame.parity;
      if (frame.safety) worldObj.safety = frame.safety;
      if (frame.fleet_summary) worldObj.fleet_summary = frame.fleet_summary;
      updateParityStatus(worldObj);
    },
  };
}
