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

const ACTION_GROUPS = Object.freeze({drive: "운전", docking: "도킹", line_follow: "차선 추종"});

function actionGroupPanel(id, title) {
  const panel = document.createElement("div");
  panel.className = "action-group-panel";
  panel.id = `action-group-${id}`;
  panel.setAttribute("role", "tabpanel");
  panel.setAttribute("aria-label", `${title} 조작`);
  return panel;
}

export async function mountPanels(root, panels, contextFor) {
  const handles = [];
  const actionGroupElements = [];
  const actionPanels = panels.filter((panel) => panel.slot === "act" && panel.action_group);
  const groups = new Map();
  for (const panel of actionPanels) {
    if (!ACTION_GROUPS[panel.action_group]) continue;
    if (!groups.has(panel.action_group)) groups.set(panel.action_group, []);
    groups.get(panel.action_group).push(panel);
  }

  async function mountOne(panel, slot) {
    for (const href of panel.css || []) linkStyle(href);
    const section = document.createElement("ui-section");
    section.dataset.panel = panel.id;
    section.dataset.state = panel.state;
    section.setAttribute("aria-label", panel.title);
    slot.append(section);
    const ctx = contextFor(panel);
    const handle = {section, ctx, unmount: null, actionGroup: panel.action_group || null};
    handles.push(handle);
    try {
      const module = await import(panel.module);
      const mounted = module.mount(section, ctx);
      handle.beforeHide = typeof mounted?.beforeHide === "function" ? mounted.beforeHide : null;
      handle.unmount = typeof mounted === "function" ? mounted
        : typeof mounted?.unmount === "function" ? mounted.unmount : null;
    } catch (error) {
      ctx.store.stopAll();
      failure(section, panel, error);
    }
  }

  const staticPanels = panels.filter((panel) => !(panel.slot === "act" && panel.action_group));
  for (const panel of staticPanels) {
    const slot = root.querySelector(`[data-slot="${panel.slot}"]`);
    if (!slot) continue;
    await mountOne(panel, slot);
  }

  const actSlot = root.querySelector('[data-slot="act"]');
  const groupHandles = new Map();
  let selectedGroup = null;
  let switching = false;
  if (actSlot && groups.size) {
    const tablist = document.createElement("div");
    tablist.className = "action-group-tabs";
    tablist.setAttribute("role", "tablist");
    tablist.setAttribute("aria-label", "조작 그룹");
    actionGroupElements.push(tablist);
    const tabs = new Map();
    const containers = new Map();
    for (const id of groups.keys()) {
      const title = ACTION_GROUPS[id];
      const tab = document.createElement("ui-button");
      tab.type = "button";
      tab.setAttribute("kind", "segment");
      tab.setAttribute("role", "tab");
      tab.id = `action-tab-${id}`;
      tab.setAttribute("aria-controls", `action-group-${id}`);
      tab.setAttribute("aria-selected", "false");
      tab.tabIndex = -1;
      tab.textContent = title;
      const container = actionGroupPanel(id, title);
      actionGroupElements.push(container);
      container.setAttribute("aria-labelledby", tab.id);
      container.hidden = true;
      tablist.append(tab);
      actSlot.append(container);
      tabs.set(id, tab);
      containers.set(id, container);
      groupHandles.set(id, []);
    }
    actSlot.prepend(tablist);

    function setSelected(id) {
      selectedGroup = id;
      for (const [groupId, tab] of tabs) {
        const selected = groupId === id;
        tab.setAttribute("aria-selected", String(selected));
        tab.tabIndex = selected ? 0 : -1;
        containers.get(groupId).hidden = !selected;
      }
    }

    async function unmountGroup(id) {
      for (const handle of groupHandles.get(id) || []) {
        try { if (handle.unmount) handle.unmount(); } catch (_error) { /* Keep other panels tear-down independent. */ }
        handle.ctx.store.stopAll();
        handle.section.remove();
        const index = handles.indexOf(handle);
        if (index >= 0) handles.splice(index, 1);
      }
      groupHandles.set(id, []);
    }

    async function canLeaveGroup(id) {
      const mounted = groupHandles.get(id) || [];
      for (const handle of mounted) {
        if (!handle.beforeHide) continue;
        let result;
        try {
          result = await handle.beforeHide();
        } catch (_error) {
          const notice = document.getElementById("shell-notice");
          if (notice) notice.textContent = "정지 확인을 받지 못해 조작 그룹을 유지합니다. 연결을 확인하세요.";
          return false;
        }
        if (result !== true) {
          const notice = document.getElementById("shell-notice");
          if (notice) notice.textContent = result?.message || "진행 중인 작업을 끝내야 조작 그룹을 바꿀 수 있습니다.";
          return false;
        }
      }
      return true;
    }

    async function mountGroup(id) {
      const mountedGroup = [];
      groupHandles.set(id, mountedGroup);
      for (const panel of groups.get(id)) {
        const before = handles.length;
        await mountOne(panel, containers.get(id));
        if (handles.length > before) mountedGroup.push(handles[handles.length - 1]);
      }
    }

    async function selectGroup(id) {
      if (!groups.has(id) || switching || id === selectedGroup) return;
      switching = true;
      for (const tab of tabs.values()) tab.disabled = true;
      try {
        if (selectedGroup) {
          if (!await canLeaveGroup(selectedGroup)) return;
          const notice = document.getElementById("shell-notice");
          if (notice) notice.textContent = "";
          await unmountGroup(selectedGroup);
        }
        setSelected(id);
        await mountGroup(id);
      } finally {
        switching = false;
        for (const tab of tabs.values()) tab.disabled = false;
      }
    }

    for (const [id, tab] of tabs) {
      tab.addEventListener("click", () => { selectGroup(id); });
      tab.addEventListener("keydown", (event) => {
        if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
        event.preventDefault();
        const ids = [...tabs.keys()];
        const current = ids.indexOf(id);
        const next = event.key === "Home" ? 0 : event.key === "End" ? ids.length - 1
          : (current + (event.key === "ArrowRight" ? 1 : -1) + ids.length) % ids.length;
        tabs.get(ids[next]).focus();
        selectGroup(ids[next]);
      });
    }

    const defaultGroup = groups.has("drive") ? "drive" : groups.keys().next().value;
    setSelected(defaultGroup);
    await mountGroup(defaultGroup);
  }

  return {
    async unmountAll() {
      if (selectedGroup) {
        if (!await canLeaveGroup(selectedGroup)) throw new Error("현재 조작 작업이 끝나지 않아 화면을 유지합니다.");
      }
      for (const { section, ctx, unmount } of handles) {
        try {
          if (unmount) unmount();
        } catch (_error) {
          // A broken unmount must not keep the next panel mounted.
        }
        ctx.store.stopAll();
        section.remove();
      }
      for (const element of actionGroupElements) element.remove();
    },
  };
}
