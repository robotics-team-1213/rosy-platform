// D-741 6·7 — 주소의 view가 영역을 고른다: 레일의 현재 위치와 그 영역의 하위 탐색, 그 안의 현재 화면(show)이 따라온다.
export const area = new URLSearchParams(location.search);
export const areaNav = [...document.querySelectorAll(".ui-subnav")].find(node => node.dataset.area === area.get("view"));
if (areaNav) {
  areaNav.hidden = false;
  const show = [...areaNav.querySelectorAll("a")].some(link => link.href.endsWith(`show=${area.get("show")}`)) ? area.get("show") : null;
  for (const link of document.querySelectorAll(".doc-tabs a, .ui-subnav a")) {
    const to = new URL(link.href).searchParams;
    if (to.get("view") === area.get("view") && (link.closest(".doc-tabs") || to.get("show") === show)) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  }
}
