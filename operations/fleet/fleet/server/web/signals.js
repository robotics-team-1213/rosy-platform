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

export function createSignals({ scope, el, view, log, call, refreshState, isOperator = () => false,
  namedReason = () => "" }) {
  let presenceInFlight = false;
  async function presence() {
    if (presenceInFlight) return;
    presenceInFlight = true;
    try {
      // D-550 10: operator goals' leases are renewed only while a visible operator console says so.
      // Only while some robot holds a leased goal: with leases off (the default) nothing new is sent.
      const leased = (view.robots || []).some((r) => r?.goal?.goal_lease === "leased");
      if (isOperator() && !document.hidden && leased) {
        await call("/api/fleet/goal-lease/presence", { method: "POST" }).catch(() => {});
      }
      // D-525 4: a virtual manual green lasts while this console is open and visible.
      if (isOperator() && !document.hidden && (view.traffic?.signals || []).length) {
        await call("/api/fleet/traffic/signals/presence", { method: "POST" }).catch(() => {});
      }
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
      // D-540 9: 점멸·전체정지는 멈춤이라 열려 있다. 나머지 명령은 이름 있는 운영자만.
      const why = !row.online ? "오프라인"
        : body_.mode === "flash_red" || body_.mode === "all_red" ? "" : namedReason();
      button.disabled = Boolean(why);
      if (why) button.setAttribute("reason", why);
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

  // D-525 가상 신호 — 장치가 아니라 Fleet 교통 규칙이다. 구동값·연결·관측 대신 단계와 남은 시간만 있다.
  // 버튼은 자동·유지·전체 적색과 입구마다 수동 녹색이다. 수동 녹색은 이 화면이 열려 있는 동안만 유지되고
  // (presence), 닫히면 전체 적색이 된다(D-525 4).
  const VIRTUAL_ASPECT = { green: "녹", yellow: "황", all_red: "전체 적색" };
  function virtualCommand(signalId, verb, label, approach) {
    const life = scope.capture();
    life.check();
    return call(`/api/fleet/traffic/signals/${encodeURIComponent(signalId)}`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(approach ? { verb, approach } : { verb }),
    }).then(() => { life.check(); log(`${signalId} ${label}`, "good"); refreshState(); })
      .catch((err) => {
        if (!life.current() || err.name === "AbortError") return;
        log(`${signalId} 명령 거절 — ${err.message}`, "bad");
      });
  }

  function virtualCard(row) {
    const node = document.createElement("article");
    node.className = "signal";
    if (row.errors?.length) node.classList.add("broken");
    const head = document.createElement("div");
    head.className = "robot-head";
    const name = document.createElement("b");
    name.textContent = row.signal_id;
    const spacer = document.createElement("span");
    spacer.className = "spacer";
    const kind = document.createElement("ui-tag");
    kind.setAttribute("status", "neutral");
    kind.textContent = "가상";
    const tag = document.createElement("ui-tag");
    tag.setAttribute("status", row.errors?.length ? "crit" : row.mode === "cycle" ? "active" : "warn");
    tag.textContent = row.errors?.length ? "설정 오류"
      : row.mode === "manual" ? `수동 · ${row.manual} 녹` : signalIntentLabel(row.mode);
    head.append(name, spacer, kind, tag);
    node.appendChild(head);
    const body = document.createElement("div");
    body.className = "signal-body";
    const lamps = document.createElement("div");
    lamps.className = "lamps";
    for (const approach of row.approaches || []) {
      const dot = document.createElement("i");
      dot.className = `lamp ${approach.lamp} on`;
      dot.title = `${approach.approach} · ${({ green: "녹", yellow: "황", red: "적" })[approach.lamp]}`;
      lamps.appendChild(dot);
    }
    body.appendChild(lamps);
    const meta = document.createElement("span");
    meta.className = "signal-meta";
    const left = typeof row.left_s === "number" ? ` ${Math.ceil(row.left_s)} s` : "";
    meta.textContent = row.errors?.length ? row.errors[0]
      : `${VIRTUAL_ASPECT[row.aspect] || row.aspect}${left} · 구역 ${row.zone}${row.aspect === "all_red" && row.zone_busy && row.mode !== "all_red" ? " · 비기를 기다림" : ""}`;
    body.appendChild(meta);
    node.appendChild(body);
    const actions = document.createElement("div");
    actions.className = "robot-actions";
    const verbs = [["자동", "cycle"], ["유지", "hold"], ["전체 적색", "all_red", "arming"],
      ...(row.approaches || []).map((a) => [`녹 · ${a.approach}`, "set_aspect", "", a.approach])];
    for (const [label, verb, cls, approach] of verbs) {
      const button = document.createElement("ui-button");
      button.setAttribute("kind", "quiet");
      button.type = "button";
      button.textContent = label;
      button.disabled = !isOperator();
      if (!isOperator()) button.setAttribute("reason", "운영자만");
      if (cls) button.classList.add(cls);
      button.addEventListener("click", scope.guard(() => virtualCommand(row.signal_id, verb, label, approach)));
      actions.appendChild(button);
    }
    node.appendChild(actions);
    return node;
  }

  function render() {
    const box = el("signal-cards");
    if (!box) return;
    const rows = Object.values(view.signals || {});
    const virtual = view.traffic?.signals || [];
    box.replaceChildren(...rows.map(card), ...virtual.map(virtualCard));
    el("signals-state").textContent = rows.length
      ? `${rows.filter((r) => r.online).length}/${rows.length} 연결${virtual.length ? ` · 가상 ${virtual.length}` : ""}`
      : virtual.length ? `가상 ${virtual.length}` : "—";
    // D-415 — 빈 상태는 ui-empty 규칙으로 말한다.
    const empty = el("signals-hint");
    if (empty) {
      empty.hidden = rows.length + virtual.length > 0;
      if (!rows.length && !virtual.length) empty.textContent = "설정된 신호등이 없습니다. 장치 연결과 현장 설치 상태를 확인하세요.";
    }
  }

  return { render, presence };
}
