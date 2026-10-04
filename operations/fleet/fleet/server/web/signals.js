// 신호등 카드 (D-262 Fleet 분해 2). ROSY-SIGNAL-001 장치의 구동값·고장·명령을
// 그린다. 램프 도트는 장치가 보고한 구동값(lamps)이다. failsafe 는 "고장 표시"이고
// all_red 는 "명령된 정지"다 — 둘을 같은 색으로 뭉뜽그리면 운영자는 장비 고장을
// 정지 성공으로 읽어 버린다.

const SIGNAL_INTENT_LABEL = Object.freeze({
  failsafe: "감독 중단", manual: "수동", cycle: "자동 순환",
  hold: "유지", all_red: "전체 적색", flash_red: "적색 점멸",
});

export function signalIntentLabel(mode) {
  if (mode == null || mode === "") return "없음";
  return typeof mode === "string" && Object.hasOwn(SIGNAL_INTENT_LABEL, mode)
    ? SIGNAL_INTENT_LABEL[mode] : "알 수 없는 의도";
}

export async function sendSignalPresence({ operator, visible, configured, call }) {
  if (operator && visible && configured) {
    await call("/api/fleet/signals/presence", { method: "POST" });
  }
}

export function createSignals({ scope, el, view, log, call, refreshState, isOperator = () => false }) {
  let presenceInFlight = false;
  async function presence() {
    if (presenceInFlight) return;
    presenceInFlight = true;
    try {
      await sendSignalPresence({ operator: isOperator(), visible: !document.hidden,
        configured: Object.keys(view.signals || {}).length > 0, call });
    } catch (_) {
      // A failed heartbeat expires server-side; a later tick can renew presence.
    } finally {
      presenceInFlight = false;
    }
  }
  const SIGNAL_MODE_TAG = {
    failsafe: { text: "failsafe", cls: "crit" },
    manual: { text: "manual", cls: "" },
    cycle: { text: "cycle", cls: "active" },
    hold: { text: "hold", cls: "" },
    all_red: { text: "all_red", cls: "warn" },
    flash_red: { text: "flash_red", cls: "warn" },
  };

  function command(signalId, body, label) {
    const life = scope.capture();
    life.check();
    return call(`/api/fleet/signals/${encodeURIComponent(signalId)}/command`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then(() => {
      life.check();
      log(`${signalId} 명령 하달 (${label})`, "good");
      refreshState();
    }).catch((err) => {
      if (!life.current() || err.name === "AbortError") return;
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
    const signalName = document.createElement("b");
    signalName.textContent = row.signal_id;
    const spacer = document.createElement("span");
    spacer.className = "spacer";
    head.append(signalName, spacer);
    const info = SIGNAL_MODE_TAG[row.mode] || { text: row.mode || "—", cls: "" };
    // D-359 §5.2 — 공용 <ui-tag>. cls가 곧 status 어휘다(active·warn·crit).
    const tag = document.createElement("ui-tag");
    tag.setAttribute("status", (!row.online ? "crit" : info.cls) || "neutral");
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
      : `마지막으로 본 값 · ${row.age_s == null ? "시각 모름" : `${Math.floor(row.age_s)}s 전`}`;
    body.appendChild(meta);
    node.appendChild(body);

    if (row.requires_command) {
      const stale = document.createElement("p");
      stale.className = "hint";
      const age = row.intent_age_s == null ? "" : ` · ${Math.floor(row.intent_age_s)}s 전`;
      stale.textContent = `재명령 필요 — 마지막 의도 ${signalIntentLabel(row.intent?.mode)}${age}`;
      node.appendChild(stale);
    }

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
      if (!row.online) button.setAttribute("reason", "오프라인");
      if (kind) button.classList.add(kind);
      button.addEventListener("click", scope.guard(() => command(row.signal_id, body_, label)));
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
    // D-415 — 빈 상태는 ui-empty 규칙으로 말한다.
    const empty = el("signals-hint");
    if (empty) {
      empty.hidden = rows.length > 0;
      if (!rows.length) empty.textContent = "설정된 신호등이 없습니다 — signals.yaml 등록은 설치 화면에서 합니다.";
    }
  }

  return { render, presence };
}
