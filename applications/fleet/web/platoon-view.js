// D-941 2: gaps between robots on the active map's loop, read-only. Following runs on CORE;
// Fleet only shows who is ahead and how far (`dispatch: false`).
import { isRouteAbsent } from "/console/assets/poll-gate.js";

const GAP_STATE = Object.freeze({
  ok: ["간격 정상", "active"], close: ["간격 좁음", "warn"], too_close: ["너무 가까움", "crit"],
  alone: ["앞차 없음", "neutral"], off_loop: ["고리 밖", "neutral"],
});

const metres = (m) => `${Number(m).toFixed(2)} m`;

/** Pure: the platoon body as display rows. */
export function platoonRows(body) {
  const robots = (body?.robots || []).map((r) => {
    const [label, status] = GAP_STATE[r.state] || ["알 수 없음", "neutral"];
    const parts = [label];
    if (r.leader) parts.push(`앞차 ${r.leader} · ${metres(r.gap_m)}`);
    if (r.state === "off_loop") parts.push(`차선에서 ${metres(r.off_m)}`);
    return { robot: r.robot_id, text: parts.join(" · "), status };
  });
  const loop = body?.loop;
  const summary = loop
    ? `고리 ${loop.edges.length}구간 · ${metres(loop.perimeter_m)} · 목표 간격 ${metres(body.target_gap_m)} · 보기 전용`
    : "";
  return { robots, summary };
}

export function createPlatoonView({ scope, el, call, auth }) {
  const state = el("platoon-state");
  const list = el("platoon-rows");
  const hint = el("platoon-hint");
  let inFlight = false;
  let unavailable = false;

  function show(rows, note) {
    list.replaceChildren();
    for (const r of rows?.robots || []) {
      const li = document.createElement("li");
      const t = document.createElement("ui-tag");
      t.setAttribute("status", r.status);
      t.textContent = r.text;
      li.append(`${r.robot} `, t);
      list.append(li);
    }
    hint.textContent = note;
    hint.hidden = !note;
  }

  async function refresh() {
    const life = scope.capture();
    life.check();
    if (inFlight || unavailable || auth.locked) return;
    inFlight = true;
    try {
      const body = await call("/api/fleet/platoon", { signals: [life.signal] });
      life.check();
      const rows = platoonRows(body);
      state.textContent = `${rows.robots.filter((r) => r.status !== "neutral").length}대 따라감`;
      show(rows, rows.robots.length ? rows.summary : `${rows.summary} · 위치가 잡힌 로봇이 없습니다`);
    } catch (error) {
      if (error.name === "AbortError") return;
      if (isRouteAbsent(error.status, error.code)) unavailable = true;
      state.textContent = "—";
      show(null, error.code === "NO_ACTIVE_MAP" ? "활성 지도가 없습니다"
        : error.code === "NO_LOOP" ? "활성 지도에 한 방향 고리가 없습니다" : "대열 간격을 읽지 못했습니다");
    } finally {
      inFlight = false;
    }
  }

  return { refresh };
}
