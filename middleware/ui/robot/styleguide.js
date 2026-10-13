import {createTaskChooser} from "/common/task-chooser.js";
const chooser = createTaskChooser({tasks: [{id: "input", title: "입력", panel: document.getElementById("task-input")}, {id: "readback", title: "결과 확인", panel: document.getElementById("task-readback")}]});
document.getElementById("task-demo").append(chooser.element); chooser.setReady();

// 갤러리의 상태 견본도 실제 탭·토글 동작과 키보드 계약을 사용한다.
const iconTabs = [...document.querySelectorAll(".icon-tab-demo [role='tab']")];
function selectIconTab(selected) {
  for (const tab of iconTabs) {
    tab.setAttribute("aria-selected", String(tab === selected));
    tab.tabIndex = tab === selected ? 0 : -1;
    document.getElementById(tab.getAttribute("aria-controls")).hidden = tab !== selected;
  }
  selected.focus();
}
for (const [index, tab] of iconTabs.entries()) {
  tab.addEventListener("click", () => selectIconTab(tab));
  tab.addEventListener("keydown", event => {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    const next = event.key === "Home" ? 0 : event.key === "End" ? iconTabs.length - 1 : 1 - index;
    selectIconTab(iconTabs[next]);
  });
}
const iconToggle = document.querySelector(".icon-states [aria-pressed]");
iconToggle.addEventListener("click", () => iconToggle.setAttribute("aria-pressed", String(iconToggle.getAttribute("aria-pressed") !== "true")));
