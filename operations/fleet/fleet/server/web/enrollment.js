// "기기 연결" 패널의 로봇 등록 구역 (D-361 1, 8, 10, 11, 12).
// 브라우저는 로봇에 닿지 않고 토큰을 보지 않는다. 코드는 Fleet 서버로만 간다.
// 위쪽은 DOM 없는 순수 함수(node 시험 대상), 아래쪽 createEnrollmentPanel 이 화면 배선이다.

import { createPollGate } from "/console/assets/poll-gate.js";

const ALARM_TEXT = {
  ROBOT_ADDRESS_UNVERIFIED: "주행 중 로봇의 주소가 바뀜 — 상태를 모름",
  TETHER_STOP_FAILED: "케이블 감시 정지 명령 실패 — 로봇 확인",
};
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
  bad_address: "사설 IPv4 주소만 받습니다 — 로봇 화면에 보이는 IPv4 주소를 적으세요(포트를 바꿨으면 :포트를 붙입니다).",
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
  still_at_pinned_address: "로봇이 아직 원래 주소에서 응답합니다 — 옮길 필요가 없습니다.",
  identity_mismatch: "새 주소의 기기가 등록된 로봇과 다릅니다 — 등록된 토큰은 보내지 않았습니다. 발견 목록의 이름과 로봇 화면의 이름이 같은지 확인하세요.",
  ROBOT_BUSY: "진행 중인 목표나 교통 대기가 있습니다 — 먼저 취소하세요.",
  ACTIVE_TASKS: "끝나지 않은 작업이 있습니다 — 먼저 취소하세요.",
  FORMATION_ACTIVE: "대형에 들어 있습니다 — 대형을 먼저 해제하세요.",
  OPERATOR_IDENTITY_REQUIRED: "이름 있는 운영자 계정으로만 등록·해제할 수 있습니다.",
};

// 새 주소로 옮긴 뒤의 문장. Fleet은 옛 토큰을 어디에도 보내지 않으므로(중계 방어) 회수는 사람 몫이다.
export function moveDoneLines(row) {
  const lines = [`${row.robot_id}: ${row.address}(으)로 옮김 — 새 토큰으로 다시 묶었습니다.`];
  if (row.old_token_revoked !== true) {
    lines.push("이전 사이트 토큰은 Fleet이 회수하지 않습니다 — 로봇 대시보드에서 회수하거나 만료되게 두세요.");
  }
  return lines;
}

// 평문 HTTP라 Fleet은 새 주소가 그 로봇인지 증명하지 못한다. 로봇 LCD 정보 화면의 주소 줄
// (`IP:포트`, hmi/face info_screen)과 맞춰 보는 사람이 신원을 묶는다(D-361 2026-10-01 개정).
export const MOVE_CHECK = "코드를 넣기 전에 이 주소가 로봇 화면에 보이는 IP와 같은지 확인하세요"
  + "(LCD 정보 화면의 이름 아래 주소 줄). 다르면 옮기지 마세요 — 같은 이름을 다른 기기가 광고하고 있을 수 있습니다.";

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
  if (row.state === "address_changed") lines.push("고정 주소로 정지 요청만 보냅니다. 새 주소로 옮기려면 로봇 화면의 코드가 필요합니다.");
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
  "운영자 동작: 로봇 전원 켜기 → 등록 → 로봇 화면의 8자 입력. SSH·파일 편집·재시작이 없습니다.",
  "LCD가 있고 카드 login.boot_code가 기본(operator)인 로봇만 이렇게 됩니다. 그 밖에는 관리자 등록 코드나 SSH rosy-login-code가 코드의 출처입니다.",
  "새 화면 코드는 부팅마다 하나입니다: 첫 등록, 토큰 만료(현 이미지 7일), 코드를 소모한 실패 뒤마다 전원 재투입이나 관리자 코드가 필요합니다.",
];

// --- DOM 배선 ------------------------------------------------------------------

// dialogs는 /common/ui.js의 { openLiveDialog, confirmIrreversible }다. 셸(console.js)이 넘긴다 —
// 이 파일은 node 시험이 import하므로 DOM 모듈을 정적으로 끌어오지 않는다.
export function createEnrollmentPanel({ scope, headers, identity, log, dialogs, onMoved, candidateAddress }) {
  const el = (id) => document.getElementById(id);
  const state = { listing: null, blockedUntil: 0, target: null, busy: false, candidatePending: false, candidateEpoch: 0 };
  function cancelCandidate() { state.candidateEpoch++; state.candidatePending = false; }
  scope.onDispose(() => {
    state.busy = false;
    cancelCandidate();
    state.target = null;
    el("enroll-dialog")?.close?.();
    el("enroll-code").value = "";
    el("enroll-submit").disabled = Date.now() < state.blockedUntil;
    if (el("enroll-submit").disabled) el("enroll-submit").setAttribute("reason", "잠시 뒤 다시 시도");
    else el("enroll-submit").removeAttribute("reason");
  });

  // 분류(detail.code/reason)를 잃지 않으려고 셸의 call() 대신 쓴다.
  async function call(path, { method = "GET", body } = {}) {
    const life = scope.capture();
    life.check();
    const init = { method, headers: { ...headers() } };
    if (body !== undefined) {
      init.headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(body);
    }
    const resp = await fetch(path, {...init, signal: life.signal});
    life.check();
    let payload = null;
    try {
      payload = await resp.json();
      life.check();
    } catch (_err) {
      life.check();
      if (_err.name === "AbortError") throw _err;
      payload = null;
    }
    if (!resp.ok) {
      const error = new Error(`HTTP ${resp.status}`);
      error.status = resp.status;
      error.code = typeof payload?.detail === "object" ? payload.detail?.code : undefined;
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
    node.addEventListener("click", scope.guard(onClick));
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
    const life = scope.capture();
    life.check();
    if (state.busy || Date.now() < state.blockedUntil) return;
    const input = el("enroll-code");
    const error = codeError(input.value);
    if (error) return showResult([error], true);
    state.busy = true;
    el("enroll-submit").disabled = true;
    try {
      if (target.move) {
        // D-361 2026-10-01: 새 주소는 평문이라 인증할 수 없다 — 화면 코드로 그 주소에서 다시 페어링한다.
        const path = `/api/fleet/enrollment/robots/${encodeURIComponent(target.move)}/move-address`;
        const row = await call(path, {
          method: "POST", body: { code: input.value },
        });
        life.check();
        input.value = "";
        el("enroll-dialog")?.close?.();
        showResult(moveDoneLines(row), false);
        log?.(`로봇 새 주소로 옮김 ${row.robot_id}`, row.old_token_revoked === false ? "bad" : "good");
        onMoved?.();
        return;
      }
      const row = await call("/api/fleet/enrollment/robots", {
        method: "POST", body: { ...target, code: input.value },
      });
      life.check();
      input.value = "";
      el("enroll-dialog")?.close?.();
      showResult([`등록됨: ${row.robot_id} (${row.hostname}, ${row.address})`, ...rowText(row).slice(1)], false);
      log?.(`로봇 등록 ${row.robot_id}`);
    } catch (err) {
      if (err.name === "AbortError") return;
      const detail = err?.detail || {};
      state.blockedUntil = retryUntil(detail, Date.now());
      showResult(messageFor(detail), true);
    } finally {
      if (life.current()) {
        state.busy = false;
        const blocked = Date.now() < state.blockedUntil;
        el("enroll-submit").disabled = blocked;
        if (blocked) el("enroll-submit").setAttribute("reason", "잠시 뒤 다시 시도");
        else el("enroll-submit").removeAttribute("reason");
        if (state.blockedUntil) {
          scope.timeout(() => { el("enroll-submit").disabled = false; el("enroll-submit").removeAttribute("reason"); render(); },
            Math.max(0, state.blockedUntil - Date.now()));
        }
      }
    }
    await refresh();
    life.check();
  }

  function openDialog(target, label) {
    cancelCandidate();
    state.target = target;
    el("enroll-target").textContent = label;
    el("enroll-submit").textContent = target.move ? "옮기기" : "등록";
    const check = el("enroll-move-check");
    if (check) {
      check.hidden = !target.move;
      el("enroll-move-address").textContent = target.address || "새 주소 미확인";
      el("enroll-move-note").textContent = target.address ? MOVE_CHECK : "새 주소를 확인하지 못했습니다. 로봇 이름과 화면 코드를 확인하세요. 서버가 연결 대상을 확인합니다.";
    }
    el("enroll-code").value = "";
    const dialog = el("enroll-dialog");
    // D-280 원칙 2 — showModal()은 #estop까지 inert로 만든다. 비모달로 열고 정지는 살린다.
    if (dialog && !dialog.open) dialogs.openLiveDialog(dialog, { initialFocus: el("enroll-code") });
  }

  function openMove(robotId, address) {
    openDialog({ move: robotId, address }, address ? `${robotId} → ${address}` : robotId);
  }

  async function act(action, row) {
    const life = scope.capture();
    life.check();
    if (action === "move") {
      if (state.busy || state.candidatePending || !canManage(identity())) return;
      state.candidatePending = true;
      const candidateEpoch = ++state.candidateEpoch;
      let address = null;
      try {
        showResult(["새 주소를 확인하고 있습니다."], false);
        address = await candidateAddress?.(row.robot_id);
      } catch (error) {
        if (error.name === "AbortError" || !life.current()) return;
      } finally { if (life.current() && candidateEpoch === state.candidateEpoch) state.candidatePending = false; }
      if (!life.current() || candidateEpoch !== state.candidateEpoch || !canManage(identity())) return;
      openMove(row.robot_id, address);
      return;
    }
    {
      cancelCandidate();
      // D-371 — 등록 해제는 사이트 토큰 회수라 되돌리려면 다시 등록해야 한다. 대상을 이름으로 묻는다.
      // 폴링이 목록을 다시 그려도 포커스는 지금 화면의 그 행 버튼으로 돌아간다.
      const confirmed = await dialogs.confirmIrreversible({
        message: `"${row.robot_id}" 로봇 등록을 해제할까요? 로봇의 사이트 토큰을 회수하며, 되돌리려면 다시 등록해야 합니다.`,
        action: "등록 해제",
        opener: () => el("enrolled-list")?.querySelector(`li[data-robot-id="${CSS.escape(row.robot_id)}"] ui-button[data-action="unenroll"]`),
      });
      life.check();
      if (!confirmed) return;
    }
    const path = `/api/fleet/enrollment/robots/${encodeURIComponent(row.robot_id)}`;
    try {
      if (action === "unenroll") {
        const result = await call(path, { method: "DELETE" });
        life.check();
        showResult([result.state === "removed" ? `${row.robot_id} 등록 해제됨`
          : `${row.robot_id}: 로봇에 닿지 않아 해제 대기 — 다시 보이면 한 번 회수합니다.`], false);
      }
    } catch (err) {
      if (err.name === "AbortError") return;
      const detail = err?.detail || {};
      showResult(messageFor(detail), true);
    }
    await refresh();
    life.check();
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
      item.dataset.robotId = row.robot_id;
      const head = document.createElement("b");
      head.textContent = `${row.robot_id} · 출처 등록 · ${row.address}`;
      item.append(head);
      for (const line of rowText(row)) {
        const small = document.createElement("small");
        small.textContent = line;
        item.append(small);
      }
      for (const action of rowActions(row, manage)) {
        const node = button(action === "move" ? "새 주소로 옮기기…" : "등록 해제…", () => act(action, row));
        node.dataset.action = action;
        item.append(node);
      }
      rows.push(item);
    }
    list.replaceChildren(...rows);
    const alarms = listing.alarms || [];
    const banner = el("enroll-alarm");
    banner.hidden = alarms.length === 0;
    banner.textContent = alarms.map((a) => `${a.robot_id}: ${ALARM_TEXT[a.code] || ALARM_TEXT.ROBOT_ADDRESS_UNVERIFIED}`).join(" · ");
    const addBlocked = !manage || Date.now() < state.blockedUntil;
    el("enroll-address-add").disabled = addBlocked;
    if (addBlocked) el("enroll-address-add").setAttribute("reason", !manage ? "운영자 권한이 필요합니다" : "잠시 뒤 다시 시도");
    else el("enroll-address-add").removeAttribute("reason");
  }

  function decorateDiscoveryRow(item, device) {
    for (const action of discoveryActions(device, canManage(identity()), state.blockedUntil, Date.now())) {
      if (action === "enroll") {
        item.append(button("등록", () => openDialog({ discovery_name: device.name }, device.name)));
      }
    }
  }

  // 등록 기능이 없는 Fleet(라우트 없음 404)은 다음 resetPolling()(로그인) 전까지 묻지 않는다.
  const gate = createPollGate();

  async function refresh() {
    const life = scope.capture();
    life.check();
    if (!gate.due()) return;
    try {
      const listing = await call("/api/fleet/enrollment/robots");
      life.check();
      state.listing = listing;
      gate.ok();
    } catch (err) {
      if (err.name === "AbortError") return;
      gate.fail(err.status, err.code);
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
  scope.listen(el("enroll-address-add"), "click", () => {
    const address = parseAddress(el("enroll-address").value);
    if (!address) return showResult([MESSAGES.bad_address], true);
    openDialog({ address }, address);
  });
  scope.listen(el("enroll-submit"), "click", () => submit(state.target));
  scope.listen(el("enroll-cancel"), "click", () => { cancelCandidate(); el("enroll-dialog")?.close?.(); });
  scope.listen(el("enroll-code"), "input", (event) => {
    event.target.value = formatCode(event.target.value);
  });

  // 로봇 카드·경보 묶음의 지름길: 등록 패널의 "새 주소로 옮기기…"와 같은 코드 대화상자.
  return { refresh, decorateDiscoveryRow, resetPolling: () => gate.reset(), openMove };
}
