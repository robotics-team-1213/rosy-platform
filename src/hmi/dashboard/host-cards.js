// 호스트·릴리스·커미셔닝·하드웨어 카드 렌더 (D-262 세 번째 분해). 셸은
// render*(payload) 호출만 남긴다. 역할 판단(isAdmin)과 커미셔닝 후속
// 조치(onCommissioningRendered)는 셸이 주입한다. map.js·vision.js와 같은
// 팩토리 모양이다.

export function createHostCards({
  elements, setText, setEnabled, isAdmin, onCommissioningRendered,
}) {
  function setCardUnavailable(cardId, noteId, payload) {
    const card = document.getElementById(cardId);
    if (card) card.dataset.available = "false";
    const note = document.getElementById(noteId);
    if (note) {
      const recovery = payload.recovery ? ` ${payload.recovery}` : "";
      note.textContent = `${payload.detail || "정보를 가져올 수 없습니다."}${recovery}`;
    }
  }

  function setChip(id, value) {
    const chip = document.getElementById(id);
    if (!chip) return;
    const mode = value || "UNKNOWN";
    chip.dataset.mode = mode;
    chip.textContent = mode === "UNKNOWN" ? "—" : mode;
  }

  function renderHostNetwork(payload) {
    const status = document.getElementById("host-agent-status");
    if (status) {
      status.dataset.status = payload.available ? "OK" : "UNAVAILABLE";
      status.textContent = payload.available ? "Host Agent 연결됨" : "Host Agent 없음";
    }

    if (!payload.available) {
      setChip("network-mode", "UNKNOWN");
      setCardUnavailable("network-card", "network-note", payload);
      setEnabled("network-apply", false);
      setEnabled("network-ap-off", false);
      setEnabled("network-ap-on", false);
      setEnabled("network-connect", false);
      return;
    }

    const card = document.getElementById("network-card");
    if (card) card.dataset.available = "true";

    const data = payload.data || {};
    setChip("network-mode", data.mode);
    // The SSID is displayable; a PSK never is, and the agent does not send one.
    setText("network-ssid", data.ssid || "—");
    setText("network-ap", data.ap_active === true ? "켜짐" : data.ap_active === false ? "꺼짐" : "—");
    setText("network-ipv4", data.ipv4 || "—");
    setText("network-route", data.default_route || "—");
    setText("network-dns", (data.dns || []).join(", ") || "—");
    setText("network-internet", data.internet ? "도달" : "도달 못함");
    setText("network-peer", data.peer_reachable ? "가능" : "확인 필요");

    const note = document.getElementById("network-note");
    if (note) {
      // Internet and peer reachability fail separately: a router with client
      // isolation gives you the internet and no dashboard.
      note.textContent = data.internet && !data.peer_reachable
        ? "인터넷은 되지만 같은 WLAN 단말에서 접근되지 않습니다. 공유기의 client isolation 설정을 확인하십시오."
        : (payload.detail || "");
    }
    const profile = elements["network-profile-id"];
    if (profile && document.activeElement !== profile) {
      profile.value = data.profile_id || data.mode || profile.value || "rosy-site-sta";
    }
    const ssidInput = elements["network-ssid-input"];
    if (ssidInput && document.activeElement !== ssidInput && data.ssid) {
      ssidInput.value = data.ssid;
    }
    const adminOn = isAdmin() && payload.available === true;
    setEnabled("network-apply", adminOn);
    setEnabled("network-ap-off", adminOn);
    setEnabled("network-ap-on", adminOn);
    setEnabled("network-connect", adminOn);
  }

  function setActionsEnabled(enabled) {
    setEnabled("release-rollback", enabled);
    setEnabled("release-clear-hold", enabled);
  }

  function renderHostRelease(payload) {
    if (!payload.available) {
      setChip("release-state", "UNKNOWN");
      setCardUnavailable("release-card", "release-note", payload);
      setActionsEnabled(false);
      return;
    }

    const card = document.getElementById("release-card");
    if (card) card.dataset.available = "true";

    const data = payload.data || {};
    setChip("release-state", data.state);
    setText("release-current", data.current || "—");
    setText("release-previous", data.previous || "없음");
    setText("release-staged", data.staged || "없음");
    setText("release-revision", (data.git_revision || "").slice(0, 12) || "—");
    setText(
      "release-schema",
      data.config_schema != null ? `${data.config_schema} / ${data.data_schema}` : "—",
    );
    setText("release-failure", data.last_failure || "없음");

    const note = document.getElementById("release-note");
    if (note) note.textContent = data.detail || payload.detail || "";

    // Rollback needs somewhere to go; clearing a hold needs a hold.
    const held = data.state === "RECOVERY_HOLD";
    const admin = isAdmin();
    setEnabled("release-rollback", admin && Boolean(data.previous) && !held);
    setEnabled("release-clear-hold", admin && held);
  }

  function renderCommissioning(payload) {
    setChip("commissioning-mode", payload.runtime_mode);
    const note = document.getElementById("commissioning-note");
    if (note) {
      const holds = [
        payload.motor_hold ? "MOTOR_HOLD" : null,
        payload.lidar_hold ? "LIDAR_HOLD" : null,
        payload.battery_hold ? "BATTERY_HOLD" : null,
        payload.imu_hold ? "IMU_HOLD" : null,
        payload.slam_hold ? "SLAM_HOLD" : null,
        payload.fleet_hold ? "FLEET_HOLD" : null,
      ].filter(Boolean);
      const holdText = holds.length ? `${holds.join(" · ")}. ` : "";
      note.textContent = `${holdText}${payload.detail || ""}`;
    }
    // D-247 7: the operate view says why the robot cannot move in these words.
    onCommissioningRendered(payload.motion_reason || "");
  }

  // D-247 3: six states, fixed. Colour comes from the shared [data-status]
  // vocabulary: OK is the nominal text colour, WARNING the warn text, ERROR the
  // crit fill; the two states a machine cannot judge carry no status at all.
  const DEVICE_STATES = {
    ok: { text: "정상", status: "OK" },
    no_response: { text: "응답 없음", status: "ERROR" },
    bus_missing: { text: "버스 없음", status: "WARNING" },
    driver_missing: { text: "드라이버 없음", status: "WARNING" },
    needs_human: { text: "사람 확인 필요", status: null },
    not_measured: { text: "측정 안 함", status: null },
  };

  function measuredLabel(payload) {
    const stamp = Date.parse(payload.measured_at || "");
    if (!Number.isFinite(stamp)) return "측정 시각 없음";
    const time = new Date(stamp).toLocaleTimeString("ko-KR", { hour12: false });
    const age = Math.max(0, Math.floor(Number(payload.age_s) || 0));
    const ago = age < 60 ? `${age}초` : age < 3600 ? `${Math.floor(age / 60)}분` : `${Math.floor(age / 3600)}시간`;
    return `측정 ${time} · ${ago} 전`;
  }

  // D-247 6: the two devices only a person can judge. The administrator starts
  // one short test, then says what happened; CORE records who and when.
  const HUMAN_TESTS = {
    buzzer: {test: "울려 보기", yes: "들림", no: "안 들림"},
    lamp: {test: "켜 보기", yes: "보임", no: "안 보임"},
  };

  function hardwareButton(text, action, deviceId) {
    const button = document.createElement("ui-button");
    button.setAttribute("kind", "quiet");
    button.type = "button";
    button.dataset.hwAction = action;
    button.dataset.device = deviceId;
    button.textContent = text;
    return button;
  }

  function humanTestActions(device, test) {
    const words = HUMAN_TESTS[device.id];
    if (!words || !isAdmin()) return null;
    const actions = document.createElement("div");
    actions.className = "device-actions";
    const start = hardwareButton(words.test, "test", device.id);
    // The probe already says why it cannot work (no driver, wrong lamp channel).
    start.disabled = device.state === "driver_missing";
    actions.append(start);
    if (test && test.action === device.id) {
      const outcome = document.createElement("span");
      outcome.className = "device-test";
      outcome.textContent = test.detail;
      actions.append(outcome);
      if (test.state === "done") {
        actions.append(hardwareButton(words.yes, "observed", device.id),
          hardwareButton(words.no, "not-observed", device.id));
      }
    }
    return actions;
  }

  function deviceRow(device, test) {
    const known = DEVICE_STATES[device.state] || DEVICE_STATES.not_measured;
    const item = document.createElement("li");
    item.className = "device-row";
    item.dataset.device = device.id;
    item.dataset.state = device.state;
    const name = document.createElement("span");
    name.className = "device-name";
    const label = document.createElement("strong");
    label.textContent = device.label;
    const bus = document.createElement("span");
    bus.className = "device-bus";
    bus.textContent = device.bus;
    name.append(label, bus);
    if (device.product === false) {
      const bench = document.createElement("span");
      bench.className = "machine-tag";
      bench.textContent = "벤치 전용";
      name.append(bench);
    }
    const chip = document.createElement("span");
    chip.className = "mode-chip device-state";
    chip.textContent = known.text;
    if (known.status) chip.dataset.status = known.status;
    const evidence = document.createElement("p");
    evidence.className = "device-evidence";
    evidence.textContent = device.evidence;
    item.append(name, chip, evidence);
    const actions = humanTestActions(device, test);
    if (actions) item.append(actions);
    return item;
  }

  function renderHardware(payload) {
    const card = document.getElementById("hardware-card");
    const list = elements["hardware-list"];
    setEnabled("hardware-refresh", isAdmin());
    if (!payload || payload.available !== true) {
      if (list) list.replaceChildren();
      setText("hardware-measured", "측정 전");
      if (card) card.dataset.stale = "false";
      setCardUnavailable("hardware-card", "hardware-note", payload || {});
      return;
    }
    if (card) {
      card.dataset.available = "true";
      card.dataset.stale = payload.stale ? "true" : "false";
    }
    if (list) list.replaceChildren(...(payload.devices || []).map((device) => deviceRow(device, payload.test)));
    setText("hardware-measured", measuredLabel(payload));
    setText("hardware-note", payload.stale
      ? "측정한 지 오래되었습니다. 관리자가 다시 점검하면 새로 잽니다."
      : "벤치 전용 장치도 모두 보입니다. 제품 기능 여부는 기능 목록이 정합니다.");
  }

  return {
    renderHostNetwork,
    renderHostRelease,
    renderCommissioning,
    renderHardware,
  };
}
