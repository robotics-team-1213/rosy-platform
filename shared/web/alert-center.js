// C25 createAlertCenter: one alert surface per app (D-1117 alerts spec). The app owns one list; this part owns the rules.
//   createAlertCenter({listEl, toastEl, bellEl?, announcer, isOnScreen?, who?}) ->
//     {publish(entry), resolve(key), acknowledge(key, who?), dismissToast(key), syncVisibility(), getItems(), getToasts(), unread()}
//   entry: {kind: "safety"|"crit"|"warn"|"info", key, title, message, target?, action?: {label, run}, code?, status?, oneShot?}
//   publish: the same key is one item (repeat -> x N). A list item toasts only when it is new safety|crit AND the list is off screen
//     (isOnScreen() false). oneShot is a command failure that is not in the list: toast only (kind safety|crit), merged for 1500 ms.
//     A new safety|crit item is announced once (urgent) even when the list is on screen; warn once (polite); info never.
//   resolve: closes item, toast and bell count in one update. A safety item stays until acknowledge(key, who) too.
//   syncVisibility(): call when the list scrolls or its view changes; list toasts close once the list is on screen.
//   The toast region has no aria-live: the announcer is the one voice. Cap 12 items (safety never dropped for room).
// The rules live in createAlertStore (pure, node-tested); createAlertCenter only draws.
export const MERGE_WINDOW_MS = 1500;
export const MAX_ITEMS = 12;
const RANK = {safety: 0, crit: 1, warn: 2, info: 3};
const URGENT = new Set(["safety", "crit"]);

// F1 viewport math (from Fleet alert-popup): a rect is on screen when it overlaps every clipping rect.
export function isOnScreen(rect, clips) {
  if (!rect || !Array.isArray(clips) || clips.length === 0) return false;
  return clips.every((c) => rect.bottom > c.top && rect.top < c.bottom && rect.right > c.left && rect.left < c.right);
}

// The only two toast reasons: (a) new safety|crit while the list is off screen, (b) a oneShot safety|crit failure.
export function shouldToast({kind, oneShot = false, fresh = false, listOnScreen = true}) {
  if (!URGENT.has(kind)) return false;
  return oneShot ? true : fresh && !listOnScreen;
}

function normalise(entry) {
  const kind = entry.kind in RANK ? entry.kind : "crit";
  const status = entry.status ? Number(entry.status) : 0;
  const code = entry.code ? String(entry.code) : "";
  const message = String(entry.message || "오류가 발생했습니다.");
  const key = String(entry.key || `${kind}|${status}|${code}|${message}`);
  return {kind, key, title: String(entry.title || ""), message, status, code, target: entry.target ?? null,
          action: entry.action ?? null, oneShot: Boolean(entry.oneShot)};
}

export function createAlertStore({now = () => Date.now(), cap = MAX_ITEMS, mergeMs = MERGE_WINDOW_MS} = {}) {
  const items = [];   // list, safety > crit > warn > info, newest first within a kind
  const toasts = [];  // {item, origin: "list"|"oneShot"}
  const recent = new Map();  // oneShot key -> last publish time
  const rank = (item) => RANK[item.kind];
  const dropToast = (key) => { const i = toasts.findIndex((t) => t.item.key === key); if (i !== -1) toasts.splice(i, 1); };
  const lockedToast = (item) => item.kind === "safety" && !item.acknowledged;

  function addToast(item, origin) {
    toasts.push({item, origin});
    while (toasts.length > cap) {
      const i = toasts.findIndex((t) => !lockedToast(t.item));
      if (i === -1) break;
      toasts.splice(i, 1);
    }
  }
  function insert(item) {
    let at = items.findIndex((other) => rank(other) >= rank(item));
    if (at === -1) at = items.length;
    items.splice(at, 0, item);
    while (items.length > cap) {
      let drop = -1;
      for (let i = items.length - 1; i >= 0; i -= 1) if (items[i].kind !== "safety") { drop = i; break; }
      if (drop === -1) break;  // only safety left: never dropped for room
      dropToast(items[drop].key);
      items.splice(drop, 1);
    }
  }

  function publish(entry = {}, {listOnScreen = true} = {}) {
    const next = normalise(entry);
    const t = now();
    if (next.oneShot) {
      const open = toasts.find((x) => x.item.key === next.key);
      const last = recent.get(next.key);
      recent.set(next.key, t);
      if (open || (last !== undefined && t - last < mergeMs)) {
        if (open) { open.item.count += 1; open.item.message = next.message; open.item.updatedAt = t; }
        return {item: open?.item ?? null, fresh: false, merged: true, toast: false};
      }
      const item = {...next, count: 1, acknowledged: false, cleared: false, updatedAt: t};
      const toast = shouldToast({kind: item.kind, oneShot: true});
      if (toast) addToast(item, "oneShot");
      return {item, fresh: true, merged: false, toast};
    }
    let item = items.find((x) => x.key === next.key);
    let fresh = !item;
    if (item?.cleared) {  // a cleared safety item that comes back is a new occurrence
      items.splice(items.indexOf(item), 1);
      item = null;
      fresh = true;
    }
    if (item) {
      const upgraded = rank(next) < rank(item);
      item.count += 1;
      item.updatedAt = t;
      item.message = next.message;
      if (next.title) item.title = next.title;
      if (next.status) item.status = next.status;
      if (next.code) item.code = next.code;
      if (next.target) item.target = next.target;
      if (next.action) item.action = next.action;
      if (upgraded) {
        item.kind = next.kind;
        items.splice(items.indexOf(item), 1);
        insert(item);
        fresh = true;
      }
    } else {
      item = {...next, count: 1, acknowledged: false, cleared: false, updatedAt: t};
      insert(item);
    }
    const toast = shouldToast({kind: item.kind, fresh, listOnScreen}) && !toasts.some((x) => x.item.key === item.key);
    if (toast) addToast(item, "list");
    return {item, fresh, merged: false, toast};
  }

  function resolve(key) {
    const item = items.find((x) => x.key === key);
    let removedItem = false;
    if (item) {
      item.cleared = true;
      if (item.kind !== "safety" || item.acknowledged) { items.splice(items.indexOf(item), 1); removedItem = true; }
    }
    const toast = toasts.find((x) => x.item.key === key);
    const removedToast = Boolean(toast) && !lockedToast(toast.item);
    if (removedToast) dropToast(key);
    return {removedItem, removedToast};
  }

  function acknowledge(key, who = "operator") {
    const item = items.find((x) => x.key === key) ?? toasts.find((x) => x.item.key === key)?.item;
    if (!item) return false;
    item.acknowledged = String(who || "operator");
    if (item.kind === "safety" && item.cleared) { const i = items.indexOf(item); if (i !== -1) items.splice(i, 1); }
    dropToast(key);
    return true;
  }

  function syncVisibility(listOnScreen) {
    if (!listOnScreen) return false;
    const before = toasts.length;
    for (let i = toasts.length - 1; i >= 0; i -= 1) if (toasts[i].origin === "list") toasts.splice(i, 1);
    return toasts.length !== before;
  }

  return {
    publish, resolve, acknowledge, syncVisibility,
    dismissToast: (key) => { const n = toasts.length; dropToast(key); return toasts.length !== n; },
    getItems: () => items.map((x) => ({...x})),
    getToasts: () => toasts.map((x) => ({...x.item})),
    unread: () => items.filter((x) => !x.acknowledged).length,
  };
}

// --- drawing (thin) -----------------------------------------------------------------------------------------------------
function makeButton(doc, label, kind, onClick) {
  const btn = doc.createElement("ui-button");
  btn.setAttribute("kind", kind);
  btn.type = "button";
  btn.textContent = label;
  btn.addEventListener("click", onClick);
  return btn;
}
const setText = (el, text) => { if (el.textContent !== text) el.textContent = text; };

function buildCard(doc, hooks, withClose) {
  const card = doc.createElement("article");
  card.className = "alert-center-card";
  const head = doc.createElement("div"); head.className = "alert-center-head";
  const tag = doc.createElement("ui-tag"); tag.setAttribute("variant", "inline");
  const meta = doc.createElement("span"); meta.className = "alert-center-meta";
  const count = doc.createElement("span"); count.className = "alert-center-count";
  head.append(tag, meta, count);
  const message = doc.createElement("p"); message.className = "alert-center-message";
  const actions = doc.createElement("div"); actions.className = "alert-center-actions";
  let current = null;
  const act = makeButton(doc, "자세히 보기", "primary", () => current?.action?.run?.(current));
  const ack = makeButton(doc, "확인", "primary", () => hooks.acknowledge(current.key));
  const close = makeButton(doc, "닫기", "quiet", () => hooks.dismissToast(current.key));
  actions.append(act, ack);
  if (withClose) actions.append(close);
  card.append(head, message, actions);
  function update(item) {
    current = item;
    card.dataset.kind = item.kind;
    card.dataset.alertKey = item.key;
    tag.setAttribute("status", item.kind === "warn" ? "warn" : item.kind === "info" ? "neutral" : "crit");
    setText(tag, item.title || (item.kind === "safety" ? "안전" : item.kind === "warn" ? "주의" : "알림"));
    setText(meta, [item.status ? `HTTP ${item.status}` : "", item.code].filter(Boolean).join(" · "));
    meta.hidden = !meta.textContent;
    setText(count, item.count > 1 ? `×${item.count}` : "");
    count.hidden = item.count < 2;
    setText(message, item.cleared ? `${item.message} (해제됨 · 확인 필요)` : item.message);
    act.hidden = !item.action?.run;
    if (item.action?.label) setText(act, item.action.label);
    ack.hidden = !(item.kind === "safety" && !item.acknowledged);
  }
  return {card, update};
}

function sync(container, nodes) {
  const now = Array.from(container.children ?? []);
  if (now.length !== nodes.length || now.some((n, i) => n !== nodes[i])) container.replaceChildren(...nodes);
}

export function createAlertCenter({listEl, toastEl, bellEl = null, announcer, isOnScreen: onScreen = null, who = () => "operator"}) {
  const store = createAlertStore();
  const doc = (listEl ?? toastEl).ownerDocument;
  const cards = {list: new Map(), toast: new Map()};
  const hooks = {
    acknowledge: (key) => { store.acknowledge(key, who()); render(); },
    dismissToast: (key) => { store.dismissToast(key); render(); },
  };
  function listVisible() {
    if (onScreen) return Boolean(onScreen());
    if (!listEl?.getBoundingClientRect || listEl.hidden) return !listEl?.getBoundingClientRect;
    const view = doc.defaultView;
    return isOnScreen(listEl.getBoundingClientRect(), [{top: 0, left: 0, bottom: view.innerHeight, right: view.innerWidth}]);
  }
  function draw(kind, container, source) {
    if (!container) return;
    const map = cards[kind];
    const keep = new Set(source.map((i) => i.key));
    for (const key of [...map.keys()]) if (!keep.has(key)) map.delete(key);
    const nodes = source.map((item) => {
      let entry = map.get(item.key);
      if (!entry) map.set(item.key, entry = buildCard(doc, hooks, kind === "toast"));
      entry.update(item);
      return entry.card;
    });
    sync(container, nodes);
  }
  function render() {
    draw("list", listEl, store.getItems());
    draw("toast", toastEl, store.getToasts());
    if (bellEl) { const n = store.unread(); bellEl.dataset.count = String(n); setText(bellEl, String(n)); }
  }
  function speak(item) {
    if (item.kind === "info") return;
    announcer?.announce(item.title ? `${item.title}: ${item.message}` : item.message, {urgent: URGENT.has(item.kind)});
  }
  return {
    publish(entry) {
      const result = store.publish(entry, {listOnScreen: listVisible()});
      if (result.fresh && result.item && (result.item.oneShot ? result.toast : true)) speak(result.item);
      render();
      return result.item && {...result.item};
    },
    resolve(key) { const r = store.resolve(key); render(); return r; },
    acknowledge(key, name) { const ok = store.acknowledge(key, name ?? who()); render(); return ok; },
    dismissToast: hooks.dismissToast,
    syncVisibility() { if (store.syncVisibility(listVisible())) render(); },
    getItems: store.getItems, getToasts: store.getToasts, unread: store.unread,
  };
}
