const ROLE_SURFACES = new Set(["/console", "/setup", "/device"]);

// D-945 — 역할 화면 레일의 어휘는 한 곳이 정본이다: 셸 레일과 인증 브리지의
// 목적지 목록이 같은 아이콘·짧은 이름·접근 이름을 쓴다(2026-11-01 사용자 지시).
export const SURFACE_RAIL = {console: ["robot", "운용"], setup: ["settings", "준비"], device: ["install", "설치"]};

export function dashboardReturnTarget(search) {
  const params = new URLSearchParams(search || "");
  const values = params.getAll("return_to");
  if (values.length !== 1 || !ROLE_SURFACES.has(values[0])) return null;
  return values[0];
}

export function dashboardLoginHref(pathname) {
  const target = ROLE_SURFACES.has(pathname) ? pathname : "/console";
  return `/dashboard?return_to=${encodeURIComponent(target)}`;
}

export function completeDashboardAuthentication(location = window.location) {
  if (location.pathname !== "/dashboard") return false;
  const target = dashboardReturnTarget(location.search);
  if (!target) return false;
  location.replace(target);
  return true;
}

// 비평 P1(2026-09-26): /dashboard는 인증 브리지다. 인증된 호출자가 열 수 있는
// 역할 화면은 매니페스트의 surfaces 메타데이터가 말한다 — 역할 화면의 스위치와
// 같은 단일 출처다. 클라이언트는 등록된 역할 표면만 남기고 그릴 뿐이다.
// D-945(2026-11-01): 목적지 목록도 셸 레일과 같은 부품(ui-rail-item·아이콘·짧은 이름)이다.
// 아이콘 그리기(actionIcon)는 /common/ui.js가 부팅 때만 훑으므로 호출 쪽에서 다시 칠한다.
export function dashboardSurfaceBridge(nav, surfaces) {
  if (!nav) return;
  const links = (Array.isArray(surfaces) ? surfaces : [])
    .filter((surface) => surface && ROLE_SURFACES.has(`/${surface.id}`))
    .map(({ id, title }) => {
      const [icon, short] = SURFACE_RAIL[id] || [null, title || id];
      const link = document.createElement("a");
      link.className = "ui-rail-item";
      link.href = `/${id}`;
      link.textContent = short;
      link.setAttribute("aria-label", title || id);
      if (icon) link.dataset.actionIcon = icon;
      return link;
    });
  nav.replaceChildren(...links);
  nav.hidden = links.length === 0;
}
