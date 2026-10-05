// Shared procedure navigation; the caller owns panels and all lifecycle effects.
import "./ui.js";

export const TASK_CONFIRM_TIMEOUT_MS = 10_000;

export function createTaskChooser({ tasks, beforeSelect = () => true, timeoutMs = TASK_CONFIRM_TIMEOUT_MS }) {
  if (!tasks.length || new Set(tasks.map(task => task.id)).size !== tasks.length) {
    throw new Error("Task chooser needs a nonempty, unique inventory");
  }
  const root = document.createElement("div");
  root.className = "ui-task-chooser";
  const rail = document.createElement("div");
  rail.className = "ui-task-rail ui-sidebar";
  rail.setAttribute("role", "tablist");
  rail.setAttribute("aria-label", "작업 선택");
  rail.setAttribute("aria-orientation", "vertical");
  const label = document.createElement("label");
  label.className = "ui-task-compact";
  const caption = document.createElement("span");
  caption.textContent = "작업 선택";
  const select = document.createElement("select");
  select.className = "ui-field";
  select.setAttribute("aria-label", "작업 선택");
  label.append(caption, select);
  const status = document.createElement("ui-status");
  status.hidden = true;
  root.append(rail, label, status);
  const listeners = new AbortController();
  const tabs = new Map();
  let selected = tasks[0].id;
  let busy = false;
  let ready = false;
  let disposed = false;
  let paused = false;
  let generation = 0;
  let activeChoice = null;
  let timer = null;
  let cancelPending = null;

  function render() {
    select.value = selected;
    select.disabled = busy || paused || !ready;
    root.setAttribute("aria-busy", String(busy || paused || !ready));
    for (const task of tasks) {
      const tab = tabs.get(task.id);
      tab.disabled = busy || paused || !ready;
      tab.setAttribute("aria-selected", String(task.id === selected));
      tab.tabIndex = !busy && !paused && ready && task.id === selected ? 0 : -1;
      task.panel.hidden = task.id !== selected;
    }
  }

  async function selectTask(id, focusTab = false) {
    if (disposed || paused || busy || !ready || id === selected || !tabs.has(id)) {
      select.value = selected;
      return false;
    }
    busy = true;
    const attempt = generation;
    const restoreSelect = document.activeElement === select;
    status.hidden = false;
    status.setAttribute("state", "pending");
    status.textContent = "작업 전환 확인 중입니다.";
    render();
    try {
      const result = await Promise.race([
        Promise.resolve().then(() => beforeSelect(selected, id)),
        new Promise((resolve) => {
          cancelPending = () => resolve(false);
          timer = setTimeout(() => resolve({message: "전환 확인 시간이 지났습니다. 현재 작업과 연결을 확인하세요."}), timeoutMs);
        }),
      ]);
      if (disposed || paused || attempt !== generation) return false;
      if (result !== true) {
        status.setAttribute("state", "warning");
        status.textContent = result?.message || "현재 작업을 끝낸 뒤 다시 선택하세요.";
        return false;
      }
      selected = id;
      status.hidden = true;
      status.textContent = "";
      return true;
    } catch (_error) {
      if (!disposed && !paused && attempt === generation) {
        status.setAttribute("state", "error");
        status.textContent = "작업 전환을 확인하지 못했습니다. 현재 작업과 연결을 확인하세요.";
      }
      return false;
    } finally {
      clearTimeout(timer);
      cancelPending = null;
      busy = false;
      if (!disposed) {
        render();
        const focusStayedHere = document.activeElement === document.body
          || document.activeElement === select || [...tabs.values()].includes(document.activeElement);
        if (!paused && focusStayedHere) {
          if (restoreSelect) select.focus();
          else if (focusTab) tabs.get(selected).focus();
        }
      }
    }
  }

  function choose(id, focusTab = false) {
    if (busy || paused || disposed) return Promise.resolve(false);
    activeChoice = selectTask(id, focusTab);
    return activeChoice;
  }

  for (const task of tasks) {
    const tab = document.createElement("ui-button");
    tab.setAttribute("kind", "segment");
    tab.setAttribute("role", "tab");
    tab.id = `${task.panel.id}-tab`;
    tab.setAttribute("aria-controls", task.panel.id);
    tab.textContent = task.title;
    task.panel.setAttribute("role", "tabpanel");
    task.panel.setAttribute("aria-labelledby", tab.id);
    task.panel.tabIndex = 0;
    tabs.set(task.id, tab);
    rail.append(tab);
    const option = document.createElement("option");
    option.value = task.id;
    option.textContent = task.title;
    select.append(option);
    tab.addEventListener("click", () => { choose(task.id, true); }, {signal: listeners.signal});
    tab.addEventListener("keydown", event => {
      if (!["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", "Home", "End"].includes(event.key)) return;
      event.preventDefault();
      const at = tasks.indexOf(task);
      const next = event.key === "Home" ? 0 : event.key === "End" ? tasks.length - 1
        : (at + (["ArrowRight", "ArrowDown"].includes(event.key) ? 1 : -1) + tasks.length) % tasks.length;
      choose(tasks[next].id, true);
    }, {signal: listeners.signal});
  }
  select.addEventListener("change", () => { choose(select.value); }, {signal: listeners.signal});
  render();
  return {
    element: root,
    get selectedId() { return selected; },
    choose,
    setReady() { ready = true; render(); },
    async pause() {
      paused = true;
      generation++;
      render();
      cancelPending?.();
      await activeChoice;
      status.hidden = false;
      status.setAttribute("state", "pending");
      status.textContent = "화면 전환 확인 중입니다.";
    },
    resume(message) {
      paused = false;
      status.hidden = !message;
      status.setAttribute("state", "warning");
      status.textContent = message || "";
      render();
    },
    destroy() {
      disposed = true;
      clearTimeout(timer);
      cancelPending?.();
      listeners.abort();
      root.remove();
    },
  };
}
