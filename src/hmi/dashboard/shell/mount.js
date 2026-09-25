// 매니페스트의 패널을 슬롯에 끼우고 내린다(D-204 §4).
// 한 패널의 import 실패나 mount 예외는 그 자리에만 머문다 — 나머지 패널과 e-stop은 계속 돈다.
// 자리(ui-section)를 await 전에 먼저 붙이므로 화면 순서는 매니페스트 순서 그대로다.

function linkStyle(href) {
  if (document.head.querySelector(`link[data-panel-css="${href}"]`)) return;
  const link = document.createElement("link");
  link.rel = "stylesheet";
  link.href = href;
  link.dataset.panelCss = href;
  document.head.append(link);
}

function failure(section, panel, error) {
  const note = document.createElement("ui-empty");
  note.textContent = `${panel.title} 패널을 열지 못했습니다: ${error.message || error}`;
  section.replaceChildren(note);
  section.dataset.failed = "true";
}

export async function mountPanels(root, panels, contextFor) {
  const handles = [];
  for (const panel of panels) {
    const slot = root.querySelector(`[data-slot="${panel.slot}"]`);
    if (!slot) continue;
    for (const href of panel.css || []) linkStyle(href);
    const section = document.createElement("ui-section");
    section.dataset.panel = panel.id;
    section.dataset.state = panel.state;
    section.setAttribute("aria-label", panel.title);
    slot.append(section);
    const ctx = contextFor(panel);
    const handle = { section, ctx, unmount: null };
    handles.push(handle);
    try {
      const module = await import(panel.module);
      const unmount = module.mount(section, ctx);
      handle.unmount = typeof unmount === "function" ? unmount : null;
    } catch (error) {
      ctx.store.stopAll();
      failure(section, panel, error);
    }
  }
  return {
    unmountAll() {
      for (const { section, ctx, unmount } of handles) {
        try {
          if (unmount) unmount();
        } catch (_error) {
          // A broken unmount must not keep the next panel mounted.
        }
        ctx.store.stopAll();
        section.remove();
      }
    },
  };
}
