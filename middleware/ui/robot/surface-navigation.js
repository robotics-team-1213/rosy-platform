const ROLE_SURFACES = new Set(["/console", "/setup", "/device"]);

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
export function dashboardSurfaceBridge(nav, surfaces) {
  if (!nav) return;
  const links = (Array.isArray(surfaces) ? surfaces : [])
    .filter((surface) => surface && ROLE_SURFACES.has(`/${surface.id}`))
    .map(({ id, title }) => {
      const link = document.createElement("a");
      link.href = `/${id}`;
      link.textContent = title || id;
      return link;
    });
  nav.replaceChildren(...links);
  nav.hidden = links.length === 0;
}
