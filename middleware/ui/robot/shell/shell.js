// 역할별 화면의 셸(D-204). 매니페스트를 받아 패널을 조립하고,
// 세 화면이 공유하는 것 — 화면 전환기, 역할 표시, 비상 정지 하나 — 만 소유한다.
// 로그인은 아직 /dashboard 가 소유한다(같은 탭의 sessionStorage 토큰을 그대로 쓴다, D-193 6).

import { api, session } from "../client.js";
import { mountPanels } from "./mount.js";
import { createStore } from "./store.js";
import { ROLE_LABEL, enumLabel } from "/common/core_ui_logic.js";
import { dashboardLoginHref } from "../surface-navigation.js";
import { createNode } from "../dom.js";

const REFRESH_MS = 5_000;
const surface = document.body.dataset.surface;
const status = document.getElementById("surface-status");
const notice = document.getElementById("shell-notice");
const safetyStatus = document.getElementById("safety-mode-status");
const store = createStore(api);
let mounted = null;
let revision = null;
let inflight = null;
let intervalId = null;
let stopSafety = null;

function renderSafetyMode(state) {
  if (!safetyStatus || !["setup", "device"].includes(surface)) return;
  if (state?.mode === "SAFE_STOP" || state?.safety?.estop === true) {
    safetyStatus.hidden = false;
    safetyStatus.setAttribute("state", "warning");
    safetyStatus.textContent = "안전 정지 · CORE가 정지 상태를 보고했습니다. 이동은 CORE가 차단합니다. 해제와 물리 상태는 별도로 확인하세요.";
  } else if (typeof state?.mode === "string" && state?.safety?.estop === false) {
    safetyStatus.hidden = true;
    safetyStatus.removeAttribute("state");
    safetyStatus.textContent = "";
  } else {
    safetyStatus.hidden = false;
    safetyStatus.setAttribute("state", "warning");
    safetyStatus.textContent = "안전 상태 확인 불가 · 이동 가능 여부를 판단할 수 없습니다.";
  }
}

function onSafetyModeError() {
  renderSafetyMode(null);
}

function showStatus(text) {
  status.hidden = !text;
  status.textContent = text || "";
}

function showLinkedStatus(text, href, label) {
  status.hidden = false;
  const link = createNode("a", "surface-auth-link", label);
  link.href = href;
  status.replaceChildren(document.createTextNode(`${text} `), link);
}

function showLoginStatus(text) {
  showLinkedStatus(text, dashboardLoginHref(`/${surface}`), "같은 탭에서 로그인");
}

function showRoleDeniedStatus() {
  showLinkedStatus("이 화면은 현재 계정 역할로 열 수 없습니다.", "/console", "운용 화면으로 이동");
}

function renderSwitch(surfaces) {
  const nav = document.getElementById("surface-switch");
  nav.replaceChildren(...surfaces.map(({ id, title }) => {
    const link = createNode("a", "", title);
    link.href = `/${id}`;
    if (id === surface) link.setAttribute("aria-current", "page");
    return link;
  }));
}

// revision이 그대로면 조립은 바뀌지 않았다 — 다시 mount하지 않고 각 패널의
// state/reason만 그 자리에서 갱신한다(D-204 §4, revision은 구조만 해시한다).
function refreshPanelState(panels) {
  for (const panel of panels) {
    const section = document.querySelector(`ui-section[data-panel="${CSS.escape(panel.id)}"]`);
    if (!section) continue;
    section.dataset.state = panel.state;
    if (panel.reason) {
      section.dataset.reason = panel.reason;
    } else {
      delete section.dataset.reason;
    }
  }
}

async function assemble() {
  const manifest = await api(`/api/v1/ui/surfaces/${surface}`, { signal: AbortSignal.timeout(REFRESH_MS * 2) });
  document.getElementById("shell-role").textContent = enumLabel(ROLE_LABEL, manifest.role);
  document.getElementById("shell-role").title = manifest.role;
  if (manifest.revision === revision) {
    refreshPanelState(manifest.panels);
    showStatus(manifest.panels.length ? "" : "이 역할로 이 화면에 보일 패널이 없습니다.");
    return;
  }
  if (mounted) await mounted.unmountAll();
  revision = manifest.revision;
  renderSwitch(manifest.surfaces);
  mounted = await mountPanels(document, manifest.panels, (panel) => ({
    api,
    store: store.scope(),
    role: manifest.role,
    surfaces: manifest.surfaces,
    panel,
  }), manifest.action_groups || []);
  showStatus(manifest.panels.length ? "" : "이 역할로 이 화면에 보일 패널이 없습니다.");
}

// 매니페스트를 못 받아도 이미 뜬 패널은 그대로 둔다 — 각 패널이 자기 폴링
// 오류를 스스로 보고한다(store.js). revision도 지우지 않는다: 다음 성공
// 응답이 구조 그대로면 불필요한 재mount를 하지 않는다.
async function onManifestError(error) {
  if (error.status === 401) {
    if (stopSafety) { stopSafety(); stopSafety = null; }
    if (intervalId) clearInterval(intervalId);
    intervalId = null;
    try {
      if (mounted) await mounted.unmountAll();
    } catch (stopError) {
      showStatus(`로그인이 만료되었습니다. ${stopError.message}`);
      return;
    }
    mounted = null;
    revision = null;
    document.getElementById("shell-role").textContent = "인증 대기";
    showLoginStatus("로그인이 만료되었습니다.");
    return;
  }
  if (error.status === 403) {
    if (stopSafety) { stopSafety(); stopSafety = null; }
    if (safetyStatus) safetyStatus.hidden = true;
    if (intervalId) clearInterval(intervalId);
    intervalId = null;
    if (mounted) await mounted.unmountAll();
    mounted = null;
    revision = null;
    renderSwitch([]);
    document.getElementById("shell-role").textContent = "권한 제한";
    showRoleDeniedStatus();
    return;
  }
  if (error.status === 404) {
    showStatus("요청한 화면이 없습니다. 주소를 확인하세요.");
    return;
  }
  showStatus(`화면 구성을 받지 못했습니다: ${error.message}. 잠시 뒤 다시 시도합니다.`);
}

function refresh() {
  if (inflight) return;
  inflight = assemble().catch(onManifestError).finally(() => { inflight = null; });
}

document.getElementById("shell-estop").addEventListener("click", async () => {
  window.dispatchEvent(new Event("rosy:stop-motion"));
  try {
    await api("/api/v1/safety/stop", { method: "POST" });
    let readback = null;
    try {
      readback = await api("/api/v1/robot/state");
      renderSafetyMode(readback);
    } catch (_error) {
      onSafetyModeError();
    }
    notice.textContent = readback?.safety?.estop === true || readback?.mode === "SAFE_STOP"
      ? "\uBE44\uC0C1 \uC815\uC9C0 \uC694\uCCAD \uC811\uC218 \u00B7 CORE \uC815\uC9C0 \uC0C1\uD0DC \uD655\uC778. \uBB3C\uB9AC \uC815\uC9C0\uB294 \uBCC4\uB3C4\uB85C \uD655\uC778\uD558\uC138\uC694."
      : "\uBE44\uC0C1 \uC815\uC9C0 \uC694\uCCAD \uC811\uC218 \u00B7 \uC0C1\uD0DC \uD655\uC778 \uBD88\uAC00. \uC2E4\uC81C \uC815\uC9C0\uB97C \uD655\uC778\uD558\uC138\uC694.";
  } catch (error) {
    notice.textContent = `비상 정지 실패: ${error.message}`;
  }
});

if (!session.token) {
  showLoginStatus("로그인이 필요합니다.");
} else {
  if (["setup", "device"].includes(surface) && safetyStatus) {
    safetyStatus.hidden = false;
    safetyStatus.setAttribute("state", "pending");
    safetyStatus.textContent = "안전 상태 확인 중 · CORE의 첫 상태 응답을 기다리고 있습니다.";
  }
  refresh();
  intervalId = setInterval(refresh, REFRESH_MS);
  if (["setup", "device"].includes(surface)) {
    stopSafety = store.scope().poll("/api/v1/robot/state", 1_000, renderSafetyMode, onSafetyModeError);
  }
}
