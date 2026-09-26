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
