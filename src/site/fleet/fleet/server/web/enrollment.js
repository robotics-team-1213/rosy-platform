// "기기 연결" 패널의 로봇 등록 구역 (D-361 1, 8, 10, 11, 12).
// 브라우저는 로봇에 닿지 않고 토큰을 보지 않는다. 코드는 Fleet 서버로만 간다.
// 위쪽은 DOM 없는 순수 함수(node 시험 대상), 아래쪽 createEnrollmentPanel 이 화면 배선이다.

const ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ";

export function normalizeCode(text) {
  return String(text ?? "").replace(/[\s-]/g, "").toUpperCase();
}

export function codeError(text) {
  const code = normalizeCode(text);
  if (code.length !== 8 || [...code].some((ch) => !ALPHABET.includes(ch))) {
    return MESSAGES.bad_format;
  }
  return null;
}

export function formatCode(text) {
  const code = normalizeCode(text);
  return code.length > 4 ? `${code.slice(0, 4)}-${code.slice(4)}` : code;
}

// 사설 IPv4[:포트]만. `.local`·호스트명·공인 주소는 받지 않는다(Fleet 컨테이너가 못 푼다).
export function parseAddress(text) {
  const match = /^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})(?::(\d{1,5}))?$/.exec(String(text ?? "").trim());
  if (!match) return null;
  const octets = match.slice(1, 5).map(Number);
  const port = match[5] === undefined ? 8080 : Number(match[5]);
  if (octets.some((n) => n > 255) || port < 1 || port > 65535) return null;
  const [a, b] = octets;
  const privateNet = a === 10 || (a === 172 && b >= 16 && b <= 31) || (a === 192 && b === 168);
  if (!privateNet) return null;
  return `${octets.join(".")}:${port}`;
}

export const MESSAGES = {
  bad_format: "코드는 ABCD-EFGH 같은 8자입니다(0·1·I·L·O 없음).",
  bad_address: "사설 IPv4 주소만 받습니다(예: 192.168.1.20 또는 192.168.1.20:8080).",
  code_rejected: "코드가 틀렸거나, 이미 쓰였거나, 만료됐습니다. 선택한 행의 이름이 로봇 화면의 이름과 같은지 확인하세요.",
  code_burned: "이 로봇의 화면 코드가 폐기됐습니다 — 로봇 전원을 다시 넣거나 관리자 등록 코드를 받으세요.",
  rate_limited: "시도가 너무 많습니다. 잠시 뒤 다시 입력하세요.",
  lan_forbidden: "로봇이 이 서버를 LAN 밖으로 봅니다(주소 변환 확인).",
  unreachable: "로봇에 닿지 않습니다(주소·포트).",
  code_consumed: "코드가 소모됐습니다 — 로봇을 재시작하거나 관리자 코드를 받으세요.",
  store_unavailable: "자격 키를 읽을 수 없음 — 사이트 관리자가 robot_credential_key를 확인해야 합니다.",
  already_enrolled: "이미 등록된 로봇입니다. 바꾸려면 먼저 등록 해제하세요.",
  conflict: "같은 이름이 여러 주소에 보입니다(신원 충돌) — 코드를 보내지 않습니다.",
  not_discovered: "발견 목록에서 사라졌습니다. 다시 검색되거나 주소로 추가하세요.",
  robot_error: "로봇이 예상하지 못한 답을 했습니다.",
  not_enrollable: "이 행은 등록 대기 상태가 아닙니다(이미 등록됐거나 파일 로봇).",
  not_enrolled: "등록된 로봇이 아닙니다.",
  address_unchanged: "주소가 바뀐 로봇이 아닙니다.",
  no_new_address: "새 주소가 하나로 보이지 않습니다 — 발견 목록을 확인하세요.",
  identity_mismatch: "새 주소의 기기가 등록된 로봇과 다릅니다 — 토큰이 다른 기기에 갔을 수 있습니다. 로봇 대시보드에서 사이트 토큰을 회수하고 새로 등록하세요.",
  ROBOT_BUSY: "진행 중인 목표나 교통 대기가 있습니다 — 먼저 취소하세요.",
  ACTIVE_TASKS: "끝나지 않은 작업이 있습니다 — 먼저 취소하세요.",
  FORMATION_ACTIVE: "대형에 들어 있습니다 — 대형을 먼저 해제하세요.",
  OPERATOR_IDENTITY_REQUIRED: "이름 있는 운영자 계정으로만 등록·해제할 수 있습니다.",
};

export const CONSUMED_REASONS = {
  role_too_low: "원인: 코드 역할이 operator보다 낮습니다.",
  admin_code_refused: "원인: 관리자 역할 코드는 사이트 등록에 쓰지 않습니다.",
  wrong_robot: "원인: 선택한 행과 다른 로봇이 답했습니다.",
  robot_id_conflict: "원인: 같은 robot_id가 이미 로스터에 있습니다.",
  store_failed: "원인: 자격을 저장하지 못했습니다.",
  verify_failed: "원인: 로봇 신원을 읽지 못했습니다.",
};

export const AVAHI_HINT = "같은 이름의 기기가 둘이면 Avahi가 한쪽을 <이름>-2.local로 바꿉니다 — 발견 목록에 -2가 붙은 행이 있으면 그 기기부터 확인하세요.";

// 서버가 말한 분류만 문구로 옮긴다(D-193 S3 규칙). 모르는 분류는 짐작하지 않는다.
export function messageFor(detail) {
  const code = detail?.code;
  const lines = [MESSAGES[code] || `등록하지 못했습니다(${code || "알 수 없음"}).`];
  if (code === "rate_limited" && detail.retry_after) {
    lines[0] = `시도가 너무 많습니다 — ${detail.retry_after}초 뒤에 다시 입력하세요.`;
  }
  if (code === "code_consumed") {
    if (CONSUMED_REASONS[detail.reason]) lines.push(CONSUMED_REASONS[detail.reason]);
    if (detail.reason === "wrong_robot") lines.push(AVAHI_HINT);
  }
  return lines;
}

// 429 동안 버튼을 끈다. now 는 ms.
export function retryUntil(detail, now) {
  return detail?.code === "rate_limited" ? now + 1000 * Number(detail.retry_after || 60) : 0;
}

export const DISCOVERY_LABELS = {
  registration_pending: "등록 대기",
  pairing_pending: "이벤트 연결 대기",
  enrolled: "등록됨",
  verified_online: "확인됨",
  conflict: "신원 충돌",
};

const STATE_LABELS = {
  active: "등록됨",
  needs_new_code: "새 코드 필요",
  address_changed: "주소 바뀜 — 확인 필요",
  pending_logout: "해제 대기",
};

export function rowText(row) {
  const lines = [STATE_LABELS[row.state] || row.state];
  if (row.hold === "conflict") lines.push("신원 충돌 — 고정 주소로 정지 요청만 보냅니다.");
  if (row.state === "address_changed") lines.push("고정 주소로 정지 요청만 보냅니다. 해제 후 새 코드로 다시 등록하거나, 확인 후 새 주소로 옮기세요.");
  if (row.state === "pending_logout") {
    lines.push(`로봇에 토큰이 남아 있음(만료 ${row.expires_at || "알 수 없음"}) — 로봇 대시보드에서 회수 가능`);
  }
  if (row.state === "needs_new_code") lines.push("로봇 화면의 새 코드로 다시 등록하세요.");
  if (row.legacy_lifetime && row.state !== "pending_logout") {
    lines.push("이 이미지는 사이트 수명을 모름 — 7일 뒤 새 코드 필요");
  }
  if (row.lifetime_shortened) {
    lines.push("발급한 관리자 세션의 만료에 묶였습니다 — 카드 관리자 토큰으로 발급한 코드면 90일");
  }
  if (row.expiry_warning && row.state === "active") lines.push(`곧 만료(${row.expires_at}) — 새 코드 준비`);
  return lines;
}

export function canManage(identity) {
  return identity?.role === "operator" && Boolean(identity.principal_id)
    && identity.principal_id !== "site-console";
}

// 행마다 보일 버튼. 이름 있는 운영자가 아니면 없다.
export function rowActions(row, manage) {
  if (!manage) return [];
  if (row.state === "pending_logout") return [];
  const actions = [];
  if (row.state === "address_changed") actions.push("move");
  actions.push("unenroll");
  return actions;
}

export function discoveryActions(device, manage, blockedUntil, now) {
  return manage && device.enrollable && now >= blockedUntil ? ["enroll"] : [];
}

export const HELP = [
  "운용자 동작: 로봇 전원 켜기 → 등록 → 로봇 화면의 8자 입력. SSH·파일 편집·재시작이 없습니다.",
  "LCD가 있고 카드 login.boot_code가 기본(operator)인 로봇만 이렇게 됩니다. 그 밖에는 관리자 등록 코드나 SSH rosy-login-code가 코드의 출처입니다.",
  "새 화면 코드는 부팅마다 하나입니다: 첫 등록, 토큰 만료(현 이미지 7일), 코드를 소모한 실패 뒤마다 전원 재투입이나 관리자 코드가 필요합니다.",
];

// --- DOM 배선 ------------------------------------------------------------------

export function createEnrollmentPanel({ headers, identity, log }) {
  const el = (id) => document.getElementById(id);
  const state = { listing: null, blockedUntil: 0, target: null, busy: false };

  // 분류(detail.code/reason)를 잃지 않으려고 셸의 call() 대신 쓴다.
  async function call(path, { method = "GET", body } = {}) {
    const init = { method, headers: { ...headers() } };
    if (body !== undefined) {
      init.headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(body);
    }
    const resp = await fetch(path, init);
    let payload = null;
    try {
      payload = await resp.json();
    } catch (_err) {
      payload = null;
    }
    if (!resp.ok) {
      const error = new Error(`HTTP ${resp.status}`);
      error.detail = payload && payload.detail ? payload.detail : { code: `HTTP_${resp.status}` };
      throw error;
    }
    return payload;
  }

  function button(label, onClick) {
    const node = document.createElement("ui-button");
    node.setAttribute("kind", "quiet");
    node.setAttribute("type", "button");
    node.textContent = label;
    node.addEventListener("click", onClick);
    return node;
  }

  function showResult(lines, bad) {
    const box = el("enroll-result");
    if (!box) return;
    box.replaceChildren(...lines.map((line) => {
      const p = document.createElement("p");
      p.textContent = line;
      return p;
    }));
    box.dataset.kind = bad ? "bad" : "good";
  }

  async function submit(target) {
    if (state.busy || Date.now() < state.blockedUntil) return;
    const input = el("enroll-code");
    const error = codeError(input.value);
    if (error) return showResult([error], true);
    state.busy = true;
    el("enroll-submit").disabled = true;
    try {
      const row = await call("/api/fleet/enrollment/robots", {
        method: "POST", body: { ...target, code: input.value },
      });
      input.value = "";
      el("enroll-dialog")?.close?.();
      showResult([`등록됨: ${row.robot_id} (${row.hostname}, ${row.address})`, ...rowText(row).slice(1)], false);
      log?.(`로봇 등록 ${row.robot_id}`);
    } catch (err) {
      const detail = err?.detail || {};
      state.blockedUntil = retryUntil(detail, Date.now());
      showResult(messageFor(detail), true);
    } finally {
      state.busy = false;
      el("enroll-submit").disabled = Date.now() < state.blockedUntil;
      if (state.blockedUntil) {
        setTimeout(() => { el("enroll-submit").disabled = false; render(); },
          Math.max(0, state.blockedUntil - Date.now()));
      }
    }
    await refresh();
  }

  function openDialog(target, label) {
    state.target = target;
    el("enroll-target").textContent = label;
    el("enroll-code").value = "";
    const dialog = el("enroll-dialog");
    if (dialog?.showModal) dialog.showModal();
  }

  async function act(action, row) {
    const question = action === "move"
      ? `${row.robot_id}을(를) 새 주소로 옮길까요? 옮긴 뒤 Fleet이 새 주소에서 신원을 다시 확인합니다.`
      : `${row.robot_id} 등록을 해제할까요? 로봇의 사이트 토큰을 회수합니다.`;
    if (!window.confirm(question)) return;
    const path = `/api/fleet/enrollment/robots/${encodeURIComponent(row.robot_id)}`;
    try {
      if (action === "unenroll") {
        const result = await call(path, { method: "DELETE" });
        showResult([result.state === "removed" ? `${row.robot_id} 등록 해제됨`
          : `${row.robot_id}: 로봇에 닿지 않아 해제 대기 — 다시 보이면 한 번 회수합니다.`], false);
      } else if (action === "move") {
        await call(`${path}/move-address`, { method: "POST" });
        showResult([`${row.robot_id} 새 주소로 옮김`], false);
      }
    } catch (err) {
      const detail = err?.detail || {};
      showResult(messageFor(detail), true);
    }
    await refresh();
  }

  function render() {
    const listing = state.listing;
    const manage = canManage(identity());
    const list = el("enrolled-list");
    if (!list || !listing) return;
    el("enroll-unavailable").hidden = listing.available !== false;
    const rows = [];
    for (const rid of listing.static_robot_ids || []) {
      const item = document.createElement("li");
      item.textContent = `${rid} · 출처 파일`;
      rows.push(item);
    }
    for (const row of listing.robots || []) {
      const item = document.createElement("li");
      const head = document.createElement("b");
      head.textContent = `${row.robot_id} · 출처 등록 · ${row.address}`;
      item.append(head);
      for (const line of rowText(row)) {
        const small = document.createElement("small");
        small.textContent = line;
        item.append(small);
      }
      for (const action of rowActions(row, manage)) {
        item.append(button(action === "move" ? "새 주소로 옮기기" : "등록 해제", () => act(action, row)));
      }
      rows.push(item);
    }
    list.replaceChildren(...rows);
    const alarms = listing.alarms || [];
    const banner = el("enroll-alarm");
    banner.hidden = alarms.length === 0;
    banner.textContent = alarms.map((a) => `${a.robot_id}: 주행 중 로봇의 주소가 바뀜 — 상태를 모름`).join(" · ");
    el("enroll-address-add").disabled = !manage || Date.now() < state.blockedUntil;
  }

  function decorateDiscoveryRow(item, device) {
    for (const action of discoveryActions(device, canManage(identity()), state.blockedUntil, Date.now())) {
      if (action === "enroll") {
        item.append(button("등록", () => openDialog({ discovery_name: device.name }, device.name)));
      }
    }
  }

  async function refresh() {
    try {
      state.listing = await call("/api/fleet/enrollment/robots");
    } catch (_err) {
      state.listing = null;
      const controls = el("enroll-controls");
      if (controls) controls.hidden = true;
      return;
    }
    el("enroll-controls").hidden = false;
    render();
  }

  el("enroll-help")?.replaceChildren(...HELP.map((line) => {
    const li = document.createElement("li");
    li.textContent = line;
    return li;
  }));
  el("enroll-address-add")?.addEventListener("click", () => {
    const address = parseAddress(el("enroll-address").value);
    if (!address) return showResult([MESSAGES.bad_address], true);
    openDialog({ address }, address);
  });
  el("enroll-submit")?.addEventListener("click", () => submit(state.target));
  el("enroll-cancel")?.addEventListener("click", () => el("enroll-dialog")?.close?.());
  el("enroll-code")?.addEventListener("input", (event) => {
    event.target.value = formatCode(event.target.value);
  });

  return { refresh, decorateDiscoveryRow };
}
