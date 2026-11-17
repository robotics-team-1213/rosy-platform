// 관제 알림 카드 — D-1117 알림 단일 표면. 규칙(같은 key 병합·×N·승격·상한 12·심도 정렬)은
// shared/web/alert-center.js의 createAlertStore가 가진다. 이 파일은 관제 화면의 카드 동작
// (한 장 카드·다음 알림·모두 닫기·자세히 보기·개입 이동)과 Fleet 호출 정책(GET 관문·폴링 병합·
// 로그 창 병합)만 가진 얇은 어댑터다. 낭독은 announcer가 새 항목마다 한 번 말하고
// 카드 영역 자체는 live가 아니다(#alert-popup-region).
import {createAlertStore, isOnScreen} from "/common/alert-center.js";

export {isOnScreen};  // 공용 것을 가져다 쓴다(console.js 배선 불변)

const POLL_ERROR_KEY = "call|poll|fleet";
const LOG_DEDUPE_WINDOW_MS = 1500;
const ROBOT_RE = /\b(rosy_\d+|arm_[sab])\b/;

function readQueueRowText(li) {
  const summary = li.querySelector?.("summary");
  if (summary) return summary.textContent.trim();
  const b = li.querySelector?.("b")?.textContent.trim() || "";
  const bodyNode = li.querySelector?.(".queue-text");
  if (bodyNode) {
    const body = bodyNode.textContent.trim().replace(/^:\s*/, "");
    if (b && body) return body.startsWith(b) ? body : `${b}: ${body}`;
    return body || b;
  }
  return (li.querySelector?.(".queue-row") || li).textContent.trim();
}

function sanitizeDetail(raw) {
  if (raw == null) return "";
  if (typeof raw === "string") return raw.slice(0, 600);
  try {
    return JSON.stringify(raw, null, 2).slice(0, 600);
  } catch {
    return String(raw).slice(0, 600);
  }
}

function makeButton(kind, label, onClick) {
  const btn = document.createElement("ui-button");
  if (kind === "primary") btn.setAttribute("kind", "primary");
  else btn.setAttribute("kind", "quiet");
  btn.type = "button";
  btn.textContent = label;
  btn.addEventListener("click", onClick);
  return btn;
}

const titleOf = (item) => item.title
  || (item.severity === "warn" ? "주의 알림" : "요청 오류");

export function createAlertPopup({ mount, onNavigate = null, onChange = null, announcer = null }) {
  if (!mount) {
    return {
      push: () => null,
      dismiss: () => {},
      clearByKey: () => {},
      clear: () => {},
      pushLogError: () => {},
      pushCallError: () => {},
      clearCallError: () => {},
      syncCritRows: () => {},
      attachWindowErrors: () => {},
      getItems: () => [],
    };
  }
  const store = createAlertStore();   // 규칙의 정본: 병합·승격·상한·정렬
  const extras = new Map();           // Fleet 카드 칸(detail·path·시각·펼침 상태) — key별
  const ids = new Map();              // key → 카드 id(카드 갱신 안정성)
  const cardRefs = new WeakMap();
  let seq = 0;
  let rotation = 0;                   // 다음 알림 회전
  let seededCrit = false;
  const seenCritKeys = new Set();

  function compose(item) {
    const extra = extras.get(item.key) || {};
    return {...item, severity: item.kind, id: ids.get(item.key),
      actionLabel: item.action?.label || "", detail: extra.detail ?? "", path: extra.path || "",
      timeLabel: extra.timeLabel || "", openDetail: Boolean(extra.openDetail), sticky: Boolean(extra.sticky)};
  }
  const items = () => store.getItems().map(compose);
  const findItem = (key) => store.getItems().find((item) => item.key === key) || null;
  function ordered() {  // 다음 알림이 돌려 놓은 순서 — 활성 카드는 첫 항목
    const list = items();
    const shift = list.length ? rotation % list.length : 0;
    return shift ? [...list.slice(shift), ...list.slice(0, shift)] : list;
  }
  function purge() {  // 해소된 key의 카드 칸을 지운다 — 같은 사건 재발은 새 카드다
    const live = new Set(store.getItems().map((item) => item.key));
    for (const key of [...extras.keys()]) if (!live.has(key)) { extras.delete(key); ids.delete(key); }
  }
  // 새 항목 한 번: crit는 urgent, warn은 polite, info는 침묵(createAlertCenter와 같은 규칙).
  function speak(item, severity) {
    if (!announcer || severity === "info") return;
    const title = item.title || (severity === "warn" ? "주의 알림" : "요청 오류");
    announcer.announce(`${title}: ${item.message}`,
      {urgent: severity === "safety" || severity === "crit"});
  }

  function syncCard(refs, item) {
    refs.item = item;
    const { card, tag, badges, codeEl, countEl, queueEl, timeEl, msgEl, pathSlot, pathEl,
      detailSlot, details, pre, nextSlot, nextEl, queueActions, nextBtn, clearBtn, navSlot, navBtn } = refs;
    card.dataset.severity = item.severity;
    card.dataset.alertKey = item.key;
    card.dataset.alertId = String(item.id);
    tag.setAttribute("status", item.severity === "warn" ? "warn" : "crit");
    tag.textContent = titleOf(item);

    const badgeNodes = [tag];
    const metaCode = [
      item.status ? `HTTP ${item.status}` : "",
      item.code || "",
    ].filter(Boolean).join(" · ");
    if (metaCode) {
      codeEl.textContent = metaCode;
      badgeNodes.push(codeEl);
    }
    if (item.count > 1) {
      countEl.textContent = `×${item.count}`;
      badgeNodes.push(countEl);
    }
    const total = store.getItems().length;
    if (total > 1) {
      queueEl.textContent = `외 ${total - 1}건`;
      badgeNodes.push(queueEl);
    }
    badges.replaceChildren(...badgeNodes);
    timeEl.textContent = item.timeLabel;
    msgEl.textContent = item.message;

    if (item.path) {
      pathEl.textContent = item.path;
      if (pathSlot.children.length === 0) pathSlot.replaceChildren(pathEl);
      pathSlot.hidden = false;
    } else {
      if (pathSlot.children.length > 0) pathSlot.replaceChildren();
      pathSlot.hidden = true;
    }

    const rawText = sanitizeDetail(item.detail);
    if (rawText) {
      if (pre.textContent !== rawText) pre.textContent = rawText;
      if (item.openDetail) details.open = true;
      if (detailSlot.children.length === 0) detailSlot.replaceChildren(details);
      detailSlot.hidden = false;
    } else {
      if (detailSlot.children.length > 0) detailSlot.replaceChildren();
      detailSlot.hidden = true;
    }

    const next = ordered()[1] || null;
    if (total > 1 && next) {
      nextEl.textContent = `다음: ${titleOf(next)} — ${next.message}`;
      if (nextSlot.children.length === 0) nextSlot.replaceChildren(nextEl);
      nextSlot.hidden = false;
      if (queueActions.children.length === 0) queueActions.replaceChildren(nextBtn, clearBtn);
      queueActions.hidden = false;
    } else {
      if (nextSlot.children.length > 0) nextSlot.replaceChildren();
      nextSlot.hidden = true;
      if (queueActions.children.length > 0) queueActions.replaceChildren();
      queueActions.hidden = true;
    }

    if (onNavigate && item.target) {
      const label = item.actionLabel || "자세히 보기";
      if (navBtn.textContent !== label) navBtn.textContent = label;
      if (navSlot.children.length === 0) navSlot.replaceChildren(navBtn);
      navSlot.hidden = false;
    } else {
      if (navSlot.children.length > 0) navSlot.replaceChildren();
      navSlot.hidden = true;
    }
  }

  function buildCard(item) {
    const card = document.createElement("article");
    card.className = "alert-popup-card";

    const head = document.createElement("div");
    head.className = "alert-popup-head";
    const badges = document.createElement("div");
    badges.className = "alert-popup-badges";
    const tag = document.createElement("ui-tag");
    tag.setAttribute("variant", "inline");
    const codeEl = document.createElement("span");
    codeEl.className = "alert-popup-code";
    const countEl = document.createElement("span");
    countEl.className = "alert-popup-count";
    const queueEl = document.createElement("span");
    queueEl.className = "alert-popup-queue";
    const timeEl = document.createElement("span");
    timeEl.className = "alert-popup-time";
    head.append(badges, timeEl);

    const msgEl = document.createElement("p");
    msgEl.className = "alert-popup-message";

    const pathSlot = document.createElement("div");
    const pathEl = document.createElement("p");
    pathEl.className = "alert-popup-path";

    const detailSlot = document.createElement("div");
    const details = document.createElement("details");
    details.className = "alert-popup-detail";
    const summary = document.createElement("summary");
    summary.textContent = "오류 상세 보기";
    const pre = document.createElement("pre");
    pre.className = "alert-popup-raw";
    details.append(summary, pre);

    const nextSlot = document.createElement("div");
    const nextEl = document.createElement("p");
    nextEl.className = "alert-popup-next";

    const actions = document.createElement("div");
    actions.className = "alert-popup-actions";
    const queueActions = document.createElement("span");
    const nextBtn = makeButton("quiet", "다음 알림", () => {
      const total = store.getItems().length;
      if (total < 2) return;
      rotation = (rotation + 1) % total;
      render();
    });
    const clearBtn = makeButton("quiet", "모두 닫기", () => clear());
    const navSlot = document.createElement("span");
    const navBtn = makeButton("primary", "자세히 보기", () => {
      const target = refs.item.target;
      dismiss(refs.item.id);
      onNavigate(target);
    });
    const closeBtn = makeButton("quiet", "닫기", () => dismiss(refs.item.id));
    actions.append(queueActions, navSlot, closeBtn);

    card.append(head, msgEl, pathSlot, detailSlot, nextSlot, actions);
    const refs = {
      item, card, tag, badges, codeEl, countEl, queueEl, timeEl, msgEl,
      pathSlot, pathEl, detailSlot, details, pre, nextSlot, nextEl,
      queueActions, nextBtn, clearBtn, navSlot, navBtn, closeBtn,
    };
    details.addEventListener("toggle", () => { refs.item.openDetail = details.open; });
    syncCard(refs, item);
    return refs;
  }

  function render() {
    const list = ordered();
    if (!list.length) {
      mount.replaceChildren();
      onChange?.(items());
      return;
    }
    const activeCard = mount.firstElementChild ?? mount.children?.[0] ?? null;
    const existing = activeCard ? cardRefs.get(activeCard) : null;
    if (existing && activeCard.dataset?.alertId === String(list[0].id)) {
      syncCard(existing, list[0]);
    } else {
      const refs = buildCard(list[0]);
      cardRefs.set(refs.card, refs);
      mount.replaceChildren(refs.card);
    }
    onChange?.(items());
  }

  function push(entry = {}) {
    const severity = entry.severity === "warn" ? "warn" : "crit";
    const status = entry.status ? Number(entry.status) : 0;
    const code = entry.code ? String(entry.code) : "";
    const path = entry.path ? String(entry.path).split("?")[0] : "";
    const message = String(entry.message || "오류가 발생했습니다.");
    const key = String(entry.key || `${severity}|${status}|${code}|${path}|${message}`);
    const timeLabel = new Date().toTimeString().slice(0, 8);
    const result = store.publish({kind: severity, key, title: String(entry.title || ""),
      message, status, code, target: entry.target || null,
      action: entry.actionLabel ? {label: String(entry.actionLabel)} : null});
    if (!ids.has(key)) ids.set(key, ++seq);
    const prev = extras.get(key);
    if (prev) {
      prev.timeLabel = timeLabel;
      if (entry.detail !== undefined) prev.detail = entry.detail;
      if (path) prev.path = path;
      if (entry.sticky) prev.sticky = true;
    } else {
      extras.set(key, {detail: entry.detail ?? (status || code ? {status: status || undefined, code: code || undefined, path: path || undefined} : ""),
        path, timeLabel, openDetail: false, sticky: Boolean(entry.sticky)});
    }
    if (entry.followUp && !result.fresh) result.item.count -= 1;  // 같은 사건의 이어지는 로그는 ×N을 올리지 않는다
    if (result.fresh) speak(result.item, severity);
    render();
    return ids.get(key);
  }

  function dismiss(id) {
    const item = items().find((x) => x.id === id);
    if (!item) return;
    store.resolve(item.key);
    purge();
    render();
  }

  function clearByKey(key) {
    if (!findItem(key)) return;
    store.resolve(key);
    purge();
    render();
  }

  function clear() {
    if (!store.getItems().length) return;
    for (const item of store.getItems()) store.resolve(item.key);
    purge();
    rotation = 0;
    render();
  }

  let lastCallError = { at: 0, method: "", message: "", code: "", status: 0, robotId: null, key: "" };
  const pollPaths = new Set();

  function pushLogError(message, meta = {}) {
    if (meta?.silent === true) return;
    const msg = String(message || "오류가 발생했습니다.");
    const match = ROBOT_RE.exec(msg);
    if ((Date.now() - lastCallError.at) < LOG_DEDUPE_WINDOW_MS) {
      const sameMessage = Boolean(lastCallError.message) && msg.includes(lastCallError.message);
      const sameCode = meta?.code !== undefined && meta?.code !== "" && meta.code === lastCallError.code;
      const sameStatus = Boolean(meta?.status) && Number(meta.status) === lastCallError.status;
      const hasExplicitConflict = (
        (meta?.code !== undefined && meta?.code !== "" && Boolean(lastCallError.code) && meta.code !== lastCallError.code)
        || (Boolean(meta?.status) && Boolean(lastCallError.status) && Number(meta.status) !== lastCallError.status)
      );
      const isUnannotatedFollowup = meta?.code === undefined && !meta?.status
        && Boolean(lastCallError.method) && lastCallError.method !== "GET" && Boolean(lastCallError.key);
      if (!hasExplicitConflict && (sameMessage || sameCode || sameStatus || isUnannotatedFollowup)) {
        const existing = lastCallError.key ? findItem(lastCallError.key) : null;
        if (existing) {
          // 같은 사건의 이어지는 로그: 두 번째 카드 없이 같은 key에-message만 갱신(×N은 올라간다).
          const nextRobotId = match?.[1] || meta?.robotId || existing.target?.robotId || null;
          push({key: existing.key, severity: "crit", message: msg, followUp: true,
            target: { kind: "log", robotId: nextRobotId }});
        }
        return;
      }
    }
    push({
      severity: "crit",
      title: meta?.title || "오류 알림",
      message: msg,
      status: meta?.status,
      code: meta?.code,
      path: meta?.path,
      detail: meta?.detail,
      target: { kind: "log", robotId: match?.[1] || meta?.robotId || null },
    });
  }

  function pushCallError(path, options = {}, error = {}, authLocked = false, meta = {}) {
    if (!error || error.name === "AbortError") return;
    if (authLocked || error?.status === 401 || error?.code === "PASSWORD_CHANGE_REQUIRED") return;
    const cleanPath = String(path || "").split("?")[0];
    const method = String(options?.method || "GET").toUpperCase();
    const optionalVision = (cleanPath === "/api/fleet/vision/sources" || cleanPath === "/api/fleet/vision/lease") && error.status === 404;
    if (optionalVision) return;
    if (method === "GET" && error?.status && error.status < 500) return;

    const isPollFailure = method === "GET" && (!error?.status || error.status >= 500);
    if (isPollFailure && meta?.isStaleHoldover) return;
    // Fleet에 닿지 않음(응답 없음·상태 조회 실패)은 머리말 연결 표시(#link-state)가 한 곳에서 말한다. 카드를 만들지 않는다.
    if (isPollFailure && (!error?.status || cleanPath === "/api/fleet/state")) return;

    const match = ROBOT_RE.exec(cleanPath) || ROBOT_RE.exec(String(error.message || ""));
    const robotId = match?.[1] || meta?.robotId || null;
    const key = isPollFailure ? POLL_ERROR_KEY : `call|${cleanPath}`;

    let detail = error.detail;
    if (isPollFailure) {
      if (!findItem(POLL_ERROR_KEY)) pollPaths.clear();
      if (cleanPath) pollPaths.add(cleanPath);
      detail = {
        status: error.status || undefined,
        code: error.code || undefined,
        latestPath: cleanPath || undefined,
        paths: [...pollPaths],
        ...(error.detail !== undefined ? { detail: error.detail } : {}),
      };
    }

    lastCallError = {
      at: Date.now(),
      method,
      message: String(error.message || ""),
      code: error.code ? String(error.code) : "",
      status: error.status ? Number(error.status) : 0,
      robotId,
      key,
    };

    push({
      key,
      severity: "crit",
      title: method !== "GET" ? "명령·요청 오류" : "서버 응답 오류",
      message: error.message || "요청을 처리하지 못했습니다.",
      status: error.status,
      code: error.code,
      path: cleanPath,
      detail,
      target: { kind: "log", robotId },
    });
  }

  function clearCallError(path) {
    const cleanPath = String(path || "").split("?")[0];
    clearByKey(`call|${cleanPath}`);
    if (cleanPath === "/api/fleet/state") clearByKey(POLL_ERROR_KEY);
  }

  // Queue rows reach the operator as a toast only while .queues-panel is away from view (another
  // view, or scrolled out of the viewport). While the panel is on screen it is the one alert
  // surface: new rows seed silently and a toast left over from the off-screen spell closes.
  // 새 긴급 행은 패널이 화면에 있어도 announcer로 한 번 urgent 낭독한다(패널은 live가 아니다).
  function syncCritRows(listEl, ready = false, { panelVisible = false } = {}) {
    if (!listEl || !ready) return;
    const currentKeys = new Set();
    for (const li of listEl.querySelectorAll(":scope > li[data-key]")) {
      const key = li.dataset.key;
      if (!key) continue;
      currentKeys.add(key);
      if (seededCrit && !seenCritKeys.has(key)) {
        const text = readQueueRowText(li);
        const match = ROBOT_RE.exec(key) || ROBOT_RE.exec(text);
        if (panelVisible) speak({title: "긴급 개입 알림", message: text || key}, "crit");
        if (!panelVisible) {
          push({
            key: `crit|${key}`,
            severity: "crit",
            title: "긴급 개입 알림",
            message: text || key,
            target: { kind: "queue", key, robotId: match?.[1] || null },
            actionLabel: "개입 확인",
          });
        }
      } else if (panelVisible) {
        clearByKey(`crit|${key}`);  // 패널이 다시 그 행의 유일한 알림 표면이다
      }
      seenCritKeys.add(key);
    }
    for (const k of [...seenCritKeys]) {
      if (!currentKeys.has(k)) {
        seenCritKeys.delete(k);
        clearByKey(`crit|${k}`);
      }
    }
    seededCrit = true;
  }

  function attachWindowErrors(scope) {
    scope.listen(window, "error", (event) => {
      if (event.error?.name === "AbortError") return;
      push({
        severity: "crit",
        title: "화면 런타임 오류",
        message: event.message || event.error?.message || "예상하지 못한 스크립트 오류가 발생했습니다.",
        detail: event.error?.stack || `${event.filename || ""}:${event.lineno || ""}`,
        target: { kind: "log" },
      });
    });
    scope.listen(window, "unhandledrejection", (event) => {
      const reason = event.reason;
      if (!reason || reason.name === "AbortError") return;
      push({
        severity: "crit",
        title: "비동기 처리 오류",
        message: reason.message || String(reason),
        status: reason.status,
        code: reason.code,
        path: reason.path,
        detail: reason.detail || reason.stack,
        target: { kind: "log" },
      });
    });
  }

  return { push, dismiss, clearByKey, clear, pushLogError, pushCallError, clearCallError, syncCritRows, attachWindowErrors, getItems: () => items() };
}
