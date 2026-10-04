// "기기 연결" 패널의 카메라 연결 승인 구역 (D-341 3–5, 11; D-391 4의 3단계).
// 콘솔은 6자리 코드를 모른다 — 운용자가 폰 화면의 코드를 입력해 Fleet으로만 보낸다.
// 위쪽은 DOM 없는 순수 함수(node 시험 대상), 아래쪽 createCameraPairingPanel 이 화면 배선이다.

import { createPollGate } from "./poll-gate.js";
import { canManage } from "./enrollment.js";

const BASE = "/api/fleet/pairing/v1";

// 대기 목록은 2.5 s마다(폰의 조회 간격 2 s보다 느리게), 자격 목록은 그 세 번에 한 번.
export const PENDING_POLL_MS = 2500;
const CREDENTIAL_EVERY = 3;

export const UNAVAILABLE = "이 Fleet에는 카메라 연결 승인이 설정되지 않았습니다.";
export const CONFIRM_PROMPT = "폰 화면과 이 지문·자격 ID가 같은지 확인하세요";

export function normalizePairingCode(text) {
  return String(text ?? "").replace(/[\s-]/g, "");
}

export function pairingCodeError(text) {
  return /^[0-9]{6}$/.test(normalizePairingCode(text)) ? null : MESSAGES.bad_code;
}

export const MESSAGES = {
  bad_code: "코드는 폰 화면에 뜬 숫자 6자리입니다.",
  no_source: "연결할 카메라 자리를 고르세요.",
  not_revealed_reason: "폰에 아직 코드가 없습니다",
  no_free_source_reason: "빈 카메라 자리가 없습니다 — 먼저 자격을 폐기하세요",
  NOT_REVEALED: "폰이 아직 코드를 띄우지 않았습니다. 폰 화면에 코드가 뜬 뒤 다시 입력하세요.",
  ALREADY_APPROVED: "이미 승인된 요청입니다.",
  SOURCE_NOT_PAIRED: "이 카메라 자리는 설정 파일 토큰을 쓰는 자리라 연결 승인 대상이 아닙니다.",
  SOURCE_HAS_CREDENTIAL: "이 카메라 자리에 이미 자격이 있습니다 — 폰을 바꾸려면 먼저 그 자격을 폐기하세요.",
  UNKNOWN_SOURCE: "모르는 카메라 자리입니다 — 사이트 카메라 설정(site-cameras.yaml)을 확인하세요.",
  PAIRING_REQUEST_CLOSED: "요청이 이미 닫혔습니다(만료·거절·완료). 폰에서 다시 요청하세요.",
  UNKNOWN_PAIRING_REQUEST: "요청이 목록에서 사라졌습니다(만료). 폰에서 다시 요청하세요.",
  UNKNOWN_CREDENTIAL: "모르는 자격입니다. 목록을 다시 확인하세요.",
  ALREADY_REVOKED: "이미 폐기된 자격입니다.",
  PAIRING_RATE_LIMITED: "요청이 너무 많습니다. 잠시 뒤 다시 시도하세요.",
  OPERATOR_IDENTITY_REQUIRED: "이름 있는 운용자 계정으로만 카메라 연결을 승인·거절·폐기할 수 있습니다 — 공용 관제 토큰으로는 할 수 없습니다(site-users.yaml).",
};

// 서버가 말한 분류만 문구로 옮긴다(D-193 S3 규칙). 모르는 분류는 짐작하지 않는다.
export function messageFor(detail) {
  const code = detail?.code;
  if (code === "CODE_MISMATCH") {
    const left = Number(detail.attempts_left ?? 0);
    return [left > 0
      ? `코드가 폰 화면과 다릅니다 — 남은 입력 ${left}회.`
      : "코드가 세 번 틀려 요청이 거절로 닫혔습니다. 폰에서 다시 요청하세요."];
  }
  return [MESSAGES[code] || `처리하지 못했습니다(${code || "알 수 없음"}).`];
}

// 대기 줄이 막히는지 보이게 한다(D-341 7). Fleet 시작 뒤 누계, 둘 다 0이면 말하지 않는다.
export function queueHealthText(listing) {
  const refused = Number(listing?.refused_requests || 0);
  const mismatched = Number(listing?.commit_mismatches || 0);
  if (!refused && !mismatched) return null;
  return `Fleet 시작 뒤: 한도로 거절된 요청 ${refused}건 · 확인값이 맞지 않아 닫힌 요청 ${mismatched}건`;
}

export function canApprove(identity) {
  return canManage(identity);
}

export function freeSources(listing) {
  return (listing?.paired_sources || []).filter((s) => !s.has_credential).map((s) => s.source_id);
}

// expires_in_s 는 조회 순간의 값이다. 다음 조회 전까지 이 브라우저 시계로 줄인다.
export function remainingSeconds(expiresInS, fetchedAt, now) {
  return Math.max(0, Math.ceil(Number(expiresInS) - (now - fetchedAt) / 1000));
}

export function formatClock(seconds) {
  const s = Math.max(0, Math.floor(seconds));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

// 서버 시각(ISO)을 이 브라우저의 현지 분 단위로. 읽지 못하면 받은 그대로 둔다.
export function formatWhen(iso) {
  if (!iso) return "—";
  const when = new Date(iso);
  if (Number.isNaN(when.getTime())) return String(iso);
  const two = (n) => String(n).padStart(2, "0");
  return `${when.getFullYear()}-${two(when.getMonth() + 1)}-${two(when.getDate())} ${two(when.getHours())}:${two(when.getMinutes())}`;
}

export function requestText(row) {
  return [
    row.state === "revealed" ? "폰 화면에 코드가 떠 있습니다" : "폰이 아직 코드를 띄우지 않았습니다",
    `앱 ${row.app_version} · 남은 입력 ${row.attempts_left}회`,
  ];
}

// 행마다 보일 버튼. reason 이 있으면 꺼진 채 그 까닭을 말한다(D-359 §5.3).
export function requestActions(row, manage, sources) {
  if (!manage) return [];
  const approveReason = row.state !== "revealed" ? MESSAGES.not_revealed_reason
    : sources.length === 0 ? MESSAGES.no_free_source_reason : null;
  return [{ action: "approve", reason: approveReason }, { action: "reject", reason: null }];
}

const CREDENTIAL_LABELS = {
  pending_confirm: "폰 확인 대기",
  active: "사용 중",
  revoked: "폐기됨",
};

export function credentialText(row) {
  const state = row.state === "active" && row.expired ? "만료됨 — 다시 연결 승인 필요"
    : CREDENTIAL_LABELS[row.state] || "확인 필요";
  return [
    state,
    `${row.device_label} · 승인 ${row.approved_by} · ${formatWhen(row.approved_at)}`,
    `만료 ${formatWhen(row.expires_at)}`,
  ];
}

export function credentialActions(row, manage) {
  return manage && row.state !== "revoked" ? ["revoke"] : [];
}

// --- DOM 배선 ------------------------------------------------------------------

// dialogs는 /common/ui.js의 { openLiveDialog, confirmIrreversible }다. 셸(console.js)이 넘긴다 —
// 이 파일은 node 시험이 import하므로 DOM 모듈을 정적으로 끌어오지 않는다.
export function createCameraPairingPanel({ scope, headers, identity, locked, log, dialogs }) {
  const el = (id) => document.getElementById(id);
  const state = {
    pending: null, pendingAt: 0, credentials: null, ticks: 0,
    target: null, busy: false, approved: null, approvedAt: 0, inView: true,
  };

  // 분류(detail.code/attempts_left)를 잃지 않으려고 셸의 call() 대신 쓴다.
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
      error.detail = typeof payload?.detail === "object" && payload.detail
        ? payload.detail : { code: `HTTP_${resp.status}` };
      throw error;
    }
    return payload;
  }

  function lines(box, texts, bad) {
    if (!box) return;
    box.replaceChildren(...texts.map((line) => {
      const p = document.createElement("p");
      p.textContent = line;
      return p;
    }));
    box.dataset.kind = bad ? "bad" : "good";
  }

  function showResult(texts, bad, code) {
    const box = el("camera-result");
    lines(box, texts, bad);
    if (code) box.title = code;
    else box.removeAttribute("title");
    if (code === "OPERATOR_IDENTITY_REQUIRED") el("camera-identity-note").hidden = false;
  }

  function button(label, onClick, action, reason) {
    const node = document.createElement("ui-button");
    node.setAttribute("kind", "quiet");
    node.setAttribute("type", "button");
    node.textContent = label;
    node.dataset.action = action;
    if (reason) {
      node.disabled = true;
      node.setAttribute("reason", reason);
    }
    node.addEventListener("click", scope.guard(onClick));
    return node;
  }

  function actionRow(buttons) {
    const row = document.createElement("div");
    row.className = "camera-actions";
    row.append(...buttons);
    return row;
  }

  // 폴링이 목록을 다시 그려도 키보드 포커스는 같은 행의 같은 버튼으로 돌아간다.
  function keepFocus(list, attr, draw) {
    const active = document.activeElement;
    const row = list.contains(active) ? active.closest(`li[${attr}]`) : null;
    const key = row?.getAttribute(attr);
    const action = active?.dataset?.action;
    draw();
    if (!key || !action) return;
    [...list.querySelectorAll(`li[${attr}]`)].find((li) => li.getAttribute(attr) === key)
      ?.querySelector(`ui-button[data-action="${action}"]`)?.focus({ preventScroll: true });
  }

  function remainingNode(row) {
    const small = document.createElement("small");
    small.dataset.remaining = String(row.expires_in_s);
    return small;
  }

  function tickClocks() {
    const now = Date.now();
    for (const node of document.querySelectorAll("#camera-requests [data-remaining]")) {
      node.textContent = `남은 시간 ${formatClock(remainingSeconds(Number(node.dataset.remaining), state.pendingAt, now))}`;
    }
    const approved = state.approved;
    const clock = el("camera-confirm-clock");
    if (approved && clock) {
      const left = remainingSeconds(approved.confirm_within_s, state.approvedAt, now);
      const row = (state.credentials?.credentials || []).find((c) => c.credential_id === approved.credential_id);
      clock.textContent = row?.state === "active" ? "폰에서 일치를 눌러 연결이 완료됐습니다."
        : row?.state === "revoked" || left === 0 ? "확인 시간이 지나 자격이 자동 회수됩니다. 폰에서 다시 요청하세요."
          : `폰에서 일치를 누를 때까지 남은 시간 ${formatClock(left)}`;
    }
  }

  function renderRequests() {
    const list = el("camera-requests");
    const listing = state.pending;
    if (!list || !listing) return;
    const manage = canApprove(identity());
    const sources = freeSources(listing);
    keepFocus(list, "data-request-id", () => {
      const rows = (listing.requests || []).map((row) => {
        const item = document.createElement("li");
        item.dataset.requestId = row.request_id;
        const head = document.createElement("b");
        head.textContent = row.device_label;
        item.append(head);
        for (const line of requestText(row)) {
          const small = document.createElement("small");
          small.textContent = line;
          item.append(small);
        }
        item.querySelector("small").title = row.state;
        item.append(remainingNode(row));
        const actions = requestActions(row, manage, sources).map(({ action, reason }) => (action === "approve"
          ? button("승인…", () => openApprove(row), action, reason)
          : button("거절…", () => reject(row), action, reason)));
        if (actions.length) item.append(actionRow(actions));
        return item;
      });
      if (!rows.length) {
        const empty = document.createElement("li");
        empty.className = "hint";
        empty.textContent = "대기 중인 카메라 연결 요청이 없습니다. 폰의 Rosy Cam에서 연결을 요청하세요.";
        rows.push(empty);
      }
      list.replaceChildren(...rows);
    });
    const fingerprint = el("camera-site-fingerprint");
    if (fingerprint) fingerprint.textContent = listing.site_ca_fingerprint || "—";
    const health = el("camera-queue-health");
    const healthText = queueHealthText(listing);
    health.hidden = healthText === null;
    health.textContent = healthText || "";
    tickClocks();
  }

  function renderCredentials() {
    const list = el("camera-credentials");
    const summary = state.credentials;
    if (!list || !summary) return;
    const manage = canApprove(identity());
    keepFocus(list, "data-credential-id", () => {
      const rows = (summary.credentials || []).filter((row) => row.state !== "revoked").map((row) => {
        const item = document.createElement("li");
        item.dataset.credentialId = row.credential_id;
        const head = document.createElement("b");
        head.textContent = row.source_id;
        const id = document.createElement("code");
        id.className = "camera-id";
        id.textContent = row.credential_id;
        item.append(head, id);
        const [first, ...rest] = credentialText(row);
        const status = document.createElement("small");
        status.textContent = first;
        status.title = row.expired ? `${row.state} expired` : row.state;
        item.append(status);
        for (const line of rest) {
          const small = document.createElement("small");
          small.textContent = line;
          item.append(small);
        }
        const actions = credentialActions(row, manage).map((action) => button("폐기…", () => revoke(row), action));
        if (actions.length) item.append(actionRow(actions));
        return item;
      });
      if (!rows.length) {
        const empty = document.createElement("li");
        empty.className = "hint";
        empty.textContent = "연결된 카메라 자격이 없습니다.";
        rows.push(empty);
      }
      list.replaceChildren(...rows);
    });
    tickClocks();
  }

  function renderIdentity() {
    const who = identity();
    el("camera-identity-note").hidden = !(who?.role === "operator" && !canApprove(who));
  }

  function openApprove(row) {
    state.target = row;
    el("camera-approve-target").textContent = row.device_label;
    const select = el("camera-approve-source");
    select.replaceChildren(...freeSources(state.pending).map((source) => {
      const option = document.createElement("option");
      option.value = source;
      option.textContent = source;
      return option;
    }));
    el("camera-approve-code").value = "";
    lines(el("camera-approve-error"), [], false);
    const dialog = el("camera-approve-dialog");
    // D-280 원칙 2 — 비모달로 연다. 전체 정지는 대화상자 뒤에서도 살아 있다.
    if (dialog && !dialog.open) {
      dialogs.openLiveDialog(dialog, {
        initialFocus: el("camera-approve-code"),
        opener: () => el("camera-requests")?.querySelector(
          `li[data-request-id="${CSS.escape(row.request_id)}"] ui-button[data-action="approve"]`),
      });
    }
  }

  async function submitApprove() {
    const life = scope.capture();
    life.check();
    const row = state.target;
    if (state.busy || !row) return;
    const code = normalizePairingCode(el("camera-approve-code").value);
    const source = el("camera-approve-source").value;
    const error = pairingCodeError(code) || (source ? null : MESSAGES.no_source);
    if (error) return lines(el("camera-approve-error"), [error], true);
    state.busy = true;
    const submit = el("camera-approve-submit");
    submit.disabled = true;
    submit.setAttribute("reason", "승인 요청 중");
    try {
      const result = await call(`${BASE}/requests/${encodeURIComponent(row.request_id)}/approve`, {
        method: "POST", body: { code, source_id: source },
      });
      life.check();
      el("camera-approve-code").value = "";
      el("camera-approve-dialog")?.close?.();
      showApproved(result, row);
      log?.(`카메라 연결 승인 ${result.source_id} (${result.credential_id})`);
    } catch (err) {
      if (err.name === "AbortError") return;
      const detail = err?.detail || {};
      el("camera-approve-code").value = "";
      lines(el("camera-approve-error"), messageFor(detail), true);
      el("camera-approve-error").title = detail.code || "";
      if (detail.code === "OPERATOR_IDENTITY_REQUIRED") el("camera-identity-note").hidden = false;
      // 거절로 닫힌 요청에는 더 입력할 수 없다.
      if (detail.code === "CODE_MISMATCH" && !(detail.attempts_left > 0)) {
        el("camera-approve-dialog")?.close?.();
        showResult(messageFor(detail), true, detail.code);
      }
    } finally {
      if (life.current()) {
        state.busy = false;
        submit.disabled = false;
        submit.removeAttribute("reason");
      }
    }
    await refresh({ credentials: true });
    life.check();
  }

  function showApproved(result, row) {
    state.approved = result;
    state.approvedAt = Date.now();
    el("camera-confirm-device").textContent = `${row.device_label} → ${result.source_id}`;
    el("camera-confirm-fingerprint").textContent = result.site_ca_fingerprint;
    el("camera-confirm-credential").textContent = result.credential_id;
    el("camera-confirm").hidden = false;
    lines(el("camera-result"), [], false);
    tickClocks();
  }

  async function reject(row) {
    const life = scope.capture();
    life.check();
    const confirmed = await dialogs.confirmIrreversible({
      message: `"${row.device_label}" 카메라 연결 요청을 거절할까요? 그 폰은 처음부터 다시 요청해야 합니다.`,
      action: "거절",
      opener: () => el("camera-requests")?.querySelector(
        `li[data-request-id="${CSS.escape(row.request_id)}"] ui-button[data-action="reject"]`),
    });
    life.check();
    if (!confirmed) return;
    try {
      await call(`${BASE}/requests/${encodeURIComponent(row.request_id)}/reject`, { method: "POST" });
      life.check();
      showResult([`${row.device_label} 연결 요청을 거절했습니다.`], false);
      log?.(`카메라 연결 요청 거절 ${row.device_label}`);
    } catch (err) {
      if (err.name === "AbortError") return;
      const detail = err?.detail || {};
      showResult(messageFor(detail), true, detail.code);
    }
    await refresh();
    life.check();
  }

  async function revoke(row) {
    const life = scope.capture();
    life.check();
    const confirmed = await dialogs.confirmIrreversible({
      message: `"${row.credential_id}" 카메라 자격(${row.source_id})을 폐기할까요? 그 폰은 5초 안에 송신이 끊기고, 다시 쓰려면 새로 연결 승인을 받아야 합니다.`,
      action: "폐기",
      opener: () => el("camera-credentials")?.querySelector(
        `li[data-credential-id="${CSS.escape(row.credential_id)}"] ui-button[data-action="revoke"]`),
    });
    life.check();
    if (!confirmed) return;
    try {
      await call(`${BASE}/credentials/${encodeURIComponent(row.credential_id)}/revoke`, { method: "POST" });
      life.check();
      showResult([`${row.source_id} 자격 ${row.credential_id}을(를) 폐기했습니다.`], false);
      log?.(`카메라 자격 폐기 ${row.credential_id}`);
    } catch (err) {
      if (err.name === "AbortError") return;
      const detail = err?.detail || {};
      showResult(messageFor(detail), true, detail.code);
    }
    await refresh({ credentials: true });
    life.check();
  }

  // 페어링이 꺼진 Fleet(라우트 없음 404)은 다음 resetPolling()(로그인) 전까지 묻지 않는다.
  const gate = createPollGate();
  let inFlight = false;

  function showAvailable(available) {
    el("camera-link-unavailable").hidden = available;
    el("camera-link-controls").hidden = !available;
  }

  async function refresh({ credentials = false } = {}) {
    const life = scope.capture();
    life.check();
    if (inFlight || !gate.due()) return;
    inFlight = true;
    try {
      const pending = await call(`${BASE}/pending`);
      life.check();
      state.pending = pending;
      state.pendingAt = Date.now();
      gate.ok();
      if (credentials || state.credentials === null || state.ticks % CREDENTIAL_EVERY === 0) {
        const credentials = await call(`${BASE}/credentials/summary`);
        life.check();
        state.credentials = credentials;
      }
      state.ticks += 1;
    } catch (err) {
      if (err.name === "AbortError") return;
      if (gate.fail(err.status, err.code) === "absent") {
        state.pending = null;
        state.credentials = null;
        showAvailable(false);
      }
      return;
    } finally {
      if (life.current()) inFlight = false;
    }
    showAvailable(true);
    renderIdentity();
    renderRequests();
    renderCredentials();
  }

  // 패널이 화면에 있고 탭이 보일 때만 대기 목록을 묻는다. 잠긴 콘솔은 401을 두드리지 않는다(D-248).
  function poll() {
    if (locked() || document.visibilityState === "hidden" || !state.inView) return;
    refresh();
  }

  const section = el("camera-link");
  if (section && typeof IntersectionObserver === "function") {
    scope.subscribe(() => {
      const observer = new IntersectionObserver(scope.guard((entries) => {
        const wasOut = !state.inView;
        state.inView = entries.some((entry) => entry.isIntersecting);
        if (wasOut && state.inView) poll();
      }));
      observer.observe(section);
      return () => observer.disconnect();
    });
  }
  scope.listen(el("camera-approve-submit"), "click", submitApprove);
  scope.listen(el("camera-approve-cancel"), "click", () => el("camera-approve-dialog")?.close?.());
  scope.listen(el("camera-approve-code"), "keydown", (event) => {
    if (event.key === "Enter") submitApprove();
  });
  scope.listen(el("camera-confirm-close"), "click", () => {
    state.approved = null;
    el("camera-confirm").hidden = true;
  });
  scope.interval(poll, PENDING_POLL_MS);
  scope.interval(tickClocks, 1000);
  scope.onDispose(() => {
    inFlight = false;
    state.busy = false;
    state.target = null;
    el("camera-approve-dialog")?.close?.();
    el("camera-approve-code").value = "";
    el("camera-approve-submit").disabled = false;
    el("camera-approve-submit").removeAttribute("reason");
  });

  return { refresh, resetPolling: () => gate.reset() };
}
