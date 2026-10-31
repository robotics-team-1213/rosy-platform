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
// D-926 2 — 경로 줄: 주소가 고른 영역을 본문 머리에도 쓴다. 기본 관제 화면이면 문서 제목이 곧 화면이다.
const screenLabel = document.getElementById("console-screen");
const currentArea = [...document.querySelectorAll(".doc-tabs a")].find(link => link.getAttribute("aria-current") === "page");
if (screenLabel) {
  screenLabel.hidden = !areaNav;
  if (areaNav) screenLabel.textContent = (currentArea?.textContent ?? "").trim();
}
