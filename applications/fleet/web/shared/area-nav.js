// area-first.js has already applied the area to the page; the console reads the same answer here.
export const area = new URLSearchParams(location.search);
export const areaNav = [...document.querySelectorAll(".ui-subnav")].find(node => node.dataset.area === area.get("view"));
