// D-359 §2.5 system.display — 설치·정비 화면의 화면 테마 선택.
// 선호는 이 브라우저에만 저장된다(/common/theme.js, localStorage `rosy.theme`).
// 로봇 설정이 아니라서 API를 부르지 않는다. 기본은 어둡게(관제실·현장 조명 계약).
// 선택지(값·이름)는 theme.js `RosyTheme.choices`가 단일 출처다.

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
  for (const { value, label, icon } of window.RosyTheme?.choices || []) {
    const button = document.createElement("ui-button");
    button.setAttribute("kind", "segment");
    button.setAttribute("type", "button");
    // theme.js가 누름을 받아 RosyTheme.set을 부르고 aria-pressed를 맞춘다.
    button.dataset.themeChoice = value;
    button.setAttribute("aria-pressed", value === current ? "true" : "false");
    // D-405 — 얼굴은 아이콘, 한국어 이름은 sr-only·title로 남는다.
    button.title = label;
    button.innerHTML = icon || "";
    const name = document.createElement("span");
    name.className = "sr-only";
    name.textContent = label;
    button.append(name);
    group.append(button);
  }

  const note = document.createElement("ui-text");
  note.textContent = "이 브라우저에만 저장됩니다. 시스템은 기기의 색상 모드 설정을 따릅니다.";
  const state = document.createElement("ui-status"); state.setAttribute("state", "ready"); state.setAttribute("role", "status");
  function render() {
    const theme = window.RosyTheme;
    const label = value => theme?.choices.find(choice => choice.value === value)?.label || value;
    state.textContent = `선택: ${label(theme?.get() || "dark")} · 현재 화면: ${label(theme?.resolved() || "dark")}`;
  }
  render(); document.addEventListener("rosy:theme", render);
  el.append(head, group, state, note);
  return () => document.removeEventListener("rosy:theme", render);
}
