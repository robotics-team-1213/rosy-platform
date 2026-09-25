// 역할별 화면의 셸(D-204). 매니페스트를 받아 패널을 조립하고,
// 세 화면이 공유하는 것 — 화면 전환기, 역할 표시, 비상 정지 하나 — 만 소유한다.
// 로그인은 아직 /dashboard 가 소유한다(같은 탭의 sessionStorage 토큰을 그대로 쓴다, D-193 6).

import { api, session } from "../client.js";
import { mountPanels } from "./mount.js";
import { createStore } from "./store.js";

const REFRESH_MS = 5_000;
const surface = document.body.dataset.surface;
const status = document.getElementById("surface-status");
const notice = document.getElementById("shell-notice");
const store = createStore(api);
let mounted = null;
let revision = null;
let inflight = null;
let intervalId = null;

function showStatus(text) {
  status.hidden = !text;
  status.textContent = text || "";
}

function renderSwitch(surfaces) {
  const nav = document.getElementById("surface-switch");
  nav.replaceChildren(...surfaces.map(({ id, title }) => {
    const link = document.createElement("a");
    link.href = `/${id}`;
    link.textContent = title;
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
  document.getElementById("shell-role").textContent = manifest.role;
  if (manifest.revision === revision) {
    refreshPanelState(manifest.panels);
    showStatus(manifest.panels.length ? "" : "이 역할로 이 화면에 보일 패널이 없습니다.");
    return;
  }
  revision = manifest.revision;
  renderSwitch(manifest.surfaces);
  if (mounted) mounted.unmountAll();
  mounted = await mountPanels(document, manifest.panels, (panel) => ({
    api,
    store: store.scope(),
    role: manifest.role,
    panel,
  }));
  showStatus(manifest.panels.length ? "" : "이 역할로 이 화면에 보일 패널이 없습니다.");
}

// 매니페스트를 못 받아도 이미 뜬 패널은 그대로 둔다 — 각 패널이 자기 폴링
// 오류를 스스로 보고한다(store.js). revision도 지우지 않는다: 다음 성공
// 응답이 구조 그대로면 불필요한 재mount를 하지 않는다.
function onManifestError(error) {
  if (error.status === 401) {
    if (intervalId) clearInterval(intervalId);
    intervalId = null;
    if (mounted) mounted.unmountAll();
    mounted = null;
    revision = null;
    document.getElementById("shell-role").textContent = "인증 대기";
    showStatus("로그인이 만료되었습니다. 같은 탭에서 /dashboard 로 다시 로그인한 뒤 이 화면을 다시 여세요.");
    return;
  }
  if (error.status === 403) {
    showStatus("이 화면은 현재 계정 역할로 열 수 없습니다. 역할이 허용된 화면으로 이동하세요.");
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
  try {
    await api("/api/v1/safety/stop", { method: "POST" });
    notice.textContent = "비상 정지를 보냈습니다.";
  } catch (error) {
    notice.textContent = `비상 정지 실패: ${error.message}`;
  }
});

if (!session.token) {
  showStatus("로그인이 필요합니다. 같은 탭에서 /dashboard 로 로그인한 뒤 이 화면을 다시 여세요.");
} else {
  refresh();
  intervalId = setInterval(refresh, REFRESH_MS);
}
