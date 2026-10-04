// 매니페스트의 패널을 슬롯에 끼우고 내린다(D-204 §4).
// 한 패널의 import 실패나 mount 예외는 그 자리에만 머문다 — 나머지 패널과 e-stop은 계속 돈다.
// 자리(ui-section)를 await 전에 먼저 붙이므로 화면 순서는 매니페스트 순서 그대로다.

import { createTaskChooser, TASK_CONFIRM_TIMEOUT_MS } from "/common/task-chooser.js";
import { createNode } from "../dom.js";

function linkStyle(href) {
  if (document.head.querySelector(`link[data-panel-css="${href}"]`)) return;
  const link = document.createElement("link");
  link.rel = "stylesheet";
  link.href = href;
  link.dataset.panelCss = href;
  document.head.append(link);
}

function failure(section, panel, error) {
  const note = createNode("ui-empty", "", `${panel.title} 패널을 열지 못했습니다: ${error.message || error}`);
  section.replaceChildren(note);
  section.dataset.failed = "true";
}

function actionGroupPanel(id, title) {
  const panel = createNode("div", "action-group-panel");
  panel.id = `action-group-${id}`;
  panel.setAttribute("role", "tabpanel");
  panel.setAttribute("aria-label", `${title} 조작`);
  return panel;
}

async function canCloseProcedure(handle) {
  if (!handle?.beforeHide) return true;
  let timer;
  try {
    return await Promise.race([
      Promise.resolve().then(() => handle.beforeHide()),
      new Promise(resolve => {
        timer = setTimeout(() => resolve({message: "화면 종료 확인 시간이 지났습니다. 현재 작업과 연결을 확인하세요."}), TASK_CONFIRM_TIMEOUT_MS);
      }),
    ]);
  } finally {
    clearTimeout(timer);
  }
}

export async function mountPanels(root, panels, contextFor, actionGroups = []) {
  const handles = [];
  let teardown = null;
  let closed = false;
  const procedurePanels = panels.filter(panel => panel.slot === "main");
  const procedureSlot = root.querySelector('[data-slot="main"]');
  const procedureContainers = new Map();
  let taskChooser = null;
  if (procedureSlot && procedurePanels.length) {
    linkStyle("/common/task-chooser.css");
    procedureSlot.classList.add("procedure-tasks");
    const content = createNode("div", "procedure-content");
    for (const panel of procedurePanels) {
      const container = createNode("div", "procedure-panel");
      container.id = `procedure-${panel.id}`;
      container.hidden = true;
      content.append(container);
      procedureContainers.set(panel.id, container);
    }
    taskChooser = createTaskChooser({
      tasks: procedurePanels.map(panel => ({id: panel.id, title: panel.title, panel: procedureContainers.get(panel.id)})),
      beforeSelect: async (from) => {
        const handle = handles.find(item => item.panelId === from);
        return handle?.beforeHide ? await handle.beforeHide() : true;
      },
    });
    procedureSlot.append(taskChooser.element, content);
  }
  const actionGroupElements = [];
  const actionPanels = panels.filter((panel) => panel.slot === "act" && panel.action_group);
  const groups = new Map();
  for (const panel of actionPanels) {
    if (!actionGroups.some((group) => group.id === panel.action_group)) continue;
    if (!groups.has(panel.action_group)) groups.set(panel.action_group, []);
    groups.get(panel.action_group).push(panel);
  }
  const orderedGroups = actionGroups
    .filter((group) => groups.has(group.id))
    .sort((left, right) => left.order - right.order);

  async function mountOne(panel, slot) {
    for (const href of panel.css || []) linkStyle(href);
    const section = document.createElement("ui-section");
    section.dataset.panel = panel.id;
    section.dataset.state = panel.state;
    section.setAttribute("aria-label", panel.title);
    const heading = createNode("h2", "sr-only", panel.title);
    section.append(heading);
    // 모듈 import 동안 빈 카드 대신 로딩 상태를 보인다 — 느린 네트워크에서
    // "테두리만 있는 빈 상자"는 정상으로 그리지 않는다는 Law 0의 로딩 번역이다.
    const loading = createNode("ui-empty", "", `${panel.title} 패널을 불러오는 중입니다.`);
    section.append(loading);
    const container = procedureContainers.get(panel.id) || section;
    if (container !== section) {
      container.className = "procedure-panel";
      container.append(section);
    }
    if (!container.isConnected) slot.append(container);
    const ctx = contextFor(panel);
    const handle = {panelId: panel.id, section, container, ctx, unmount: null, actionGroup: panel.action_group || null};
    handles.push(handle);
    try {
      const module = await import(panel.module);
      loading.remove();
      const mounted = await module.mount(section, ctx);
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

  taskChooser?.setReady();

  const actSlot = root.querySelector('[data-slot="act"]');
  const groupHandles = new Map();
  let selectedGroup = null;
  let switching = false;
  if (actSlot && groups.size) {
    const tablist = createNode("div", "action-group-tabs");
    tablist.setAttribute("role", "tablist");
    tablist.setAttribute("aria-label", "조작 그룹");
    actionGroupElements.push(tablist);
    const tabs = new Map();
    const containers = new Map();
    for (const {id, title} of orderedGroups) {
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
        handle.container.remove();
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
      const focusStartedOnTab = document.activeElement === tabs.get(id);
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
        for (const [groupId, tab] of tabs) {
          tab.disabled = false;
          tab.tabIndex = groupId === selectedGroup ? 0 : -1;
        }
        if (focusStartedOnTab && (document.activeElement === document.body
            || document.activeElement === tabs.get(id))) {
          tabs.get(selectedGroup)?.focus();
        }
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

  async function closeAll() {
    if (selectedGroup) {
      if (!await canLeaveGroup(selectedGroup)) throw new Error("현재 조작 작업이 끝나지 않아 화면을 유지합니다.");
    }
    if (taskChooser) {
      await taskChooser.pause();
      try {
        const handle = handles.find(item => item.panelId === taskChooser.selectedId);
        const result = await canCloseProcedure(handle);
        if (result !== true) throw new Error(result?.message || "현재 작업이 끝나지 않아 화면을 유지합니다.");
      } catch (error) {
        taskChooser.resume(error.message || "화면 종료를 확인하지 못했습니다. 현재 작업과 연결을 확인하세요.");
        throw error;
      }
      taskChooser.destroy();
    }
    for (const { container, ctx, unmount } of handles) {
      try {
        if (unmount) unmount();
      } catch (_error) {
        // A broken unmount must not keep the next panel mounted.
      }
      ctx.store.stopAll();
      container.remove();
    }
    procedureSlot?.querySelector(".procedure-content")?.remove();
    procedureSlot?.classList.remove("procedure-tasks");
    for (const element of actionGroupElements) element.remove();
    closed = true;
  }

  return {
    unmountAll() {
      if (closed) return Promise.resolve();
      if (!teardown) teardown = Promise.resolve().then(closeAll).finally(() => { teardown = null; });
      return teardown;
    },
  };
}
