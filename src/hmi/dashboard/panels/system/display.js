// D-359 §2.5 system.display — 설치·정비 화면의 화면 테마 선택.
// 선호는 이 브라우저에만 저장된다(/common/theme.js, localStorage `rosy.theme`).
// 로봇 설정이 아니라서 API를 부르지 않는다. 기본은 어둡게(관제실·현장 조명 계약).

const CHOICES = [["dark", "어둡게"], ["light", "밝게"], ["system", "시스템"]];

export function mount(el) {
  const head = document.createElement("ui-head");
  const title = document.createElement("ui-text");
  title.setAttribute("scale", "label");
  title.id = "display-theme-label";
  title.textContent = "화면 테마";
  head.append(title);

  const group = document.createElement("ui-actions");
  group.setAttribute("role", "group");
  group.setAttribute("aria-labelledby", title.id);
  const current = window.RosyTheme ? window.RosyTheme.get() : "dark";
  for (const [value, label] of CHOICES) {
    const button = document.createElement("ui-button");
    button.setAttribute("kind", "segment");
    button.setAttribute("type", "button");
    // theme.js가 누름을 받아 RosyTheme.set을 부르고 aria-pressed를 맞춘다.
    button.dataset.themeChoice = value;
    button.setAttribute("aria-pressed", value === current ? "true" : "false");
    button.textContent = label;
    group.append(button);
  }

  const note = document.createElement("ui-text");
  note.textContent = "이 브라우저에만 저장됩니다. 시스템은 기기의 밝기 설정을 따릅니다.";
  el.append(head, group, note);
}
