// 신호등 카드 (D-262 Fleet 분해 2). ROSY-SIGNAL-001 장치의 구동값·고장·명령을
// 그린다. 램프 도트는 장치가 보고한 구동값(lamps)이다. failsafe 는 "고장 표시"이고
// all_red 는 "명령된 정지"다 — 둘을 같은 색으로 뭉뜽그리면 운영자는 장비 고장을
// 정지 성공으로 읽어 버린다.

export function createSignals({ el, view, log, call, refreshState }) {
  const SIGNAL_MODE_TAG = {
    failsafe: { text: "failsafe", cls: "crit" },
    manual: { text: "manual", cls: "" },
    cycle: { text: "cycle", cls: "nav" },
    hold: { text: "hold", cls: "" },
    all_red: { text: "all_red", cls: "warn" },
    flash_red: { text: "flash_red", cls: "warn" },
  };

  function command(signalId, body) {
    return call(`/api/fleet/signals/${encodeURIComponent(signalId)}/command`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then(() => {
      log(`${signalId} 명령 하달 (${body.mode})`, "good");
      refreshState();
    }).catch((err) => {
      log(`${signalId} 명령 거절 — ${err.message}`, "bad");
      refreshState();
    });
  }

  function card(row) {
    const node = document.createElement("article");
    node.className = "signal";
    if (row.mode === "failsafe" || !row.online) node.classList.add("broken");

    const head = document.createElement("div");
    head.className = "robot-head";
    head.innerHTML = `<b>${row.signal_id}</b><span class="spacer"></span>`;
    const info = SIGNAL_MODE_TAG[row.mode] || { text: row.mode || "—", cls: "" };
    const tag = document.createElement("span");
    tag.className = `tag ${!row.online ? "crit" : info.cls}`;
    tag.textContent = !row.online ? "오프라인" : info.text;
    head.appendChild(tag);
    node.appendChild(head);

    const body = document.createElement("div");
    body.className = "signal-body";
    const lamps = document.createElement("div");
    lamps.className = "lamps";
    for (const color of ["red", "yellow", "green"]) {
      const dot = document.createElement("i");
      dot.className = `lamp ${color}${row.lamps && row.lamps[color] ? " on" : ""}`;
      lamps.appendChild(dot);
    }
    body.appendChild(lamps);
    const meta = document.createElement("span");
    meta.className = "signal-meta";
    const faults = row.faults && row.faults.length ? ` · ${row.faults.join(", ")}` : "";
    meta.textContent = row.online
      ? `접촉 ${row.secs_since_contact ?? "—"}s 전${faults}`
      : "닿지 않음";
    body.appendChild(meta);
    node.appendChild(body);

    if (row.mismatch) {
      // 장치의 seq 장부와 우리 것이 어긋났다(다른 클라이언트, 재시작). 자동 재시도로
      // 덮지 않는 이유를 화면이 말한다.
      const why = document.createElement("p");
      why.className = "hint";
      why.textContent = `명령 불일치(${row.mismatch}) — 새 명령을 내려 주세요`;
      node.appendChild(why);
    }

    const actions = document.createElement("div");
    actions.className = "robot-actions";
    const mk = (label, body_, kind) => {
      const button = document.createElement("ui-button");
      button.setAttribute("kind", "quiet");
      button.type = "button";
      button.textContent = label;
      button.disabled = !row.online;
      if (kind) button.classList.add(kind);
      button.addEventListener("click", () => command(row.signal_id, body_));
      return button;
    };
    actions.append(
      mk("녹색", { mode: "manual", lamps: { red: false, yellow: false, green: true } }),
      mk("적색", { mode: "manual", lamps: { red: true, yellow: false, green: false } }),
      mk("점멸", { mode: "flash_red" }),
      mk("전체정지", { mode: "all_red" }, "arming"),
      mk("자동", { mode: "cycle" }),
    );
    node.appendChild(actions);
    return node;
  }

  function render() {
    const box = el("signal-cards");
    if (!box) return;
    const rows = Object.values(view.signals || {});
    box.replaceChildren(...rows.map(card));
    el("signals-state").textContent = rows.length
      ? `${rows.filter((r) => r.online).length}/${rows.length} 연결`
      : "—";
  }

  return { render };
}
