import { setOff } from "/common/cause-line.js";
import { isOperator } from "/console/assets/authorization.js";
import { randomUUID } from "/console/assets/uuid.js";
// Console owns draft/display only; Fleet owns durable requests and all facts.
import { createVoice } from "./assistant-voice.js";
import { voicePlatform } from "/console/assets/app-runtime.js";
import { KIND_META, elOf as mk, formatNavigationError, renderCommandCard } from "./assistant-command.js";
import { createAssistantObjectsBridge, dispatchAssistantPickPlace, renderObjectPickPlaceCard } from "/console/assets/assistant-pick-place.js";

const PROMPT_TEMPLATES = {
  status: (r) => r ? `${r} 현재 상태 알려줘` : "현재 전체 로봇 상태 알려줘",
  cause: (r) => r ? `${r} 왜 멈췄는지 원인 근거 알려줘` : "최근 정지·오류 사건 원인 알려줘",
  move: (r) => r ? `${r}을 지정한 좌표로 이동해줘` : "로봇 이동 명령을 준비해줘",
};
const STATE_TEXT = { PENDING: "요청 접수", RUNNING: "확인 중", ANSWERED: "답변", HOLD: "보류", UNKNOWN: "처리 결과 미확인" };
const VOICE_TEXT = {
  listening: "듣고 있습니다. 인식을 마치면 내용을 확인하고 전송해 주세요.", ready: "인식문을 확인하고 전송해 주세요.",
  empty: "인식된 음성이 없습니다.", denied: "마이크 사용이 거부되었습니다.",
  unavailable: "이 브라우저에서 한국어 음성 입력을 사용할 수 없습니다. 텍스트로 입력해 주세요.",
  "too-long": "입력 길이를 초과했습니다. 짧게 다시 말해 주세요.", error: "음성을 인식하지 못했습니다. 텍스트로 입력해 주세요.",
  "no-voice": "한국어 읽기 음성이 없습니다. 화면의 답변을 확인해 주세요.",
};

export function createDialogue() {
  let identity = null, generation = 0, conversation = randomUUID(), pending = null;
  const rows = [], navState = new Map();
  function reset() { generation++; conversation = randomUUID(); pending = null; rows.length = 0; navState.clear(); }
  return {
    rows, get busy() { return pending !== null; }, get pending() { return pending; },
    setIdentity(value) { if (value !== identity) { identity = value; reset(); return true; } return false; },
    reset, getNav(id) { return navState.get(id) || null; },
    patchNav(id, patch) { const next = { ...(navState.get(id) || {}), ...patch }; navState.set(id, next); return next; },
    begin(text, selectedRobot = null, locale = "ko-KR") {
      if (!identity) throw new Error("ASSISTANT_IDENTITY_REQUIRED");
      if (pending) throw new Error("ASSISTANT_PENDING");
      if (!text.trim() || text.length > 2000) throw new Error("ASSISTANT_TEXT_INVALID");
      pending = { generation, message: { conversation_id: conversation, request_id: randomUUID(), text, selected_robot_id: selectedRobot || null, locale } };
      return pending;
    },
    retry() { return pending; }, failed(ticket) { return ticket?.generation === generation && ticket === pending; },
    receive(ticket, row) {
      if (ticket?.generation !== generation || row.request_id !== ticket.message.request_id
          || row.conversation_id !== ticket.message.conversation_id || ticket !== pending) return false;
      const merged = { ...row, selected_robot_id: row.selected_robot_id ?? ticket.message.selected_robot_id ?? null };
      const at = rows.findIndex((old) => old.request_id === merged.request_id);
      if (at < 0) rows.push(merged); else rows[at] = merged;
      if (rows.length > 40) rows.shift();
      if (!["PENDING", "RUNNING"].includes(merged.state)) pending = null;
      return true;
    },
  };
}

export function createAssistantPanel({
  scope, call, el, readSelection, readRobots = () => [], readPlaces = () => [],
  objectHighlight = null, onSelectRobot = null, onOpenRobot = null, confirm = null, log = null,
}) {
  const dialogue = createDialogue();
  const panel = el("assistant-panel"), input = el("assistant-input"), list = el("assistant-messages");
  const status = el("assistant-state"), voiceState = el("assistant-voice-state");
  const robotPicker = el("assistant-robot"), modeTag = el("assistant-mode-tag"), newChatBtn = el("assistant-new-chat");
  const triggers = [el("assistant-toggle"), el("assistant-quick-toggle")].filter(Boolean);
  const promptButtons = panel ? [...panel.querySelectorAll("[data-assistant-prompt]")] : [];
  let identity = null, available = false, executionEnabled = false, timer = null, listening = false;
  let lastOpener = triggers[0] || null, selectedRobotId = null, lastSyncedFocus = null, listDirty = true;
  const objBridge = createAssistantObjectsBridge({ scope, call, objectHighlight, getIdentity: () => identity, onChange: () => { listDirty = true; if (!panel?.hidden) paint(); } });

  const voice = createVoice({
    platform: voicePlatform,
    onText(text) { if (identity && !dialogue.busy) { input.value = text; input.focus(); } },
    onState(state) { listening = state === "listening"; voiceState.textContent = VOICE_TEXT[state] || ""; paintControls(); },
  });
  const clearTimer = () => { clearTimeout(timer); timer = null; };
  const activeRobotId = () => robotPicker ? (robotPicker.value || null) : (readSelection?.() || null);
  const syncModeTag = () => {
    if (!modeTag) return;
    modeTag.setAttribute("status", !identity ? "neutral" : !available ? "warn" : "active");
    modeTag.textContent = !identity ? "인증 필요" : !available ? "연결 준비 중" : executionEnabled ? "대화·명령 가능" : "조회 전용";
  };

  function syncContext() {
    const focus = readSelection?.() || null;
    if (focus !== lastSyncedFocus) { lastSyncedFocus = focus; selectedRobotId = focus; }
    if (!robotPicker) return;
    const robots = Array.isArray(readRobots()) ? readRobots() : [], want = selectedRobotId || "";
    const opts = [{ value: "", label: "전체 로봇" }, ...robots.map((r) => ({ value: r.robot_id, label: `${r.robot_id}${r.online === false ? " (오프라인)" : ""}` }))];
    if (want && !opts.some((o) => o.value === want)) opts.push({ value: want, label: want });
    const sig = opts.map((o) => `${o.value}\t${o.label}`).join("\n");
    if (robotPicker.dataset.sig !== sig) {
      robotPicker.dataset.sig = sig;
      robotPicker.replaceChildren(...opts.map((o) => { const opt = mk("option", "", o.label); opt.value = o.value; return opt; }));
    }
    if (robotPicker.value !== want) robotPicker.value = want;
  }

  function paintControls() {
    const reason = !identity ? "기명 운영자로 로그인해 주세요." : listening ? "음성 인식을 마쳐 주세요." : "요청 처리 중입니다.";
    const noModel = identity && !available ? "관제 AI 연결 준비 중입니다." : reason;
    setOff(el("assistant-send"), !identity || !available || dialogue.busy || listening, noModel);
    setOff(input, !identity || dialogue.busy || listening, reason);
    input.setAttribute("aria-describedby", "assistant-state assistant-voice-state");
    setOff(el("assistant-dictate"), !identity || dialogue.busy || listening, reason);
    setOff(el("assistant-read"), !identity || listening || !dialogue.rows.some((r) => r.state === "ANSWERED" && r.response),
      !identity || listening ? reason : "읽을 답변이 없습니다.");
    setOff(el("assistant-voice-prepare"), !identity, reason);
    if (newChatBtn) setOff(newChatBtn, !identity || dialogue.busy || !dialogue.rows.length, !identity || dialogue.busy ? reason : "대화 기록이 없습니다.");
    if (robotPicker) setOff(robotPicker, !identity || dialogue.busy, reason);
    for (const btn of promptButtons) setOff(btn, !identity || !available || dialogue.busy || listening, noModel);
    syncModeTag();
  }

  async function submitNavigation(row, payload, opener) {
    if (typeof confirm !== "function" || !available || !executionEnabled || !identity || dialogue.getNav(row.request_id)?.submitting) return;
    await confirm({
      message: `${payload.robot_id} 로봇에 (${payload.x.toFixed(2)}, ${payload.y.toFixed(2)}) 좌표로 이동 명령을 접수할까요?`,
      kind: "assistant-navigation", opener,
      eligible: () => Boolean(identity && available && executionEnabled && !dialogue.getNav(row.request_id)?.receipt),
      request: async (owner) => {
        dialogue.patchNav(row.request_id, { submitting: true, error: "" }); renderMessages();
        try {
          const receipt = await call("/api/fleet/assistant/messages/" + encodeURIComponent(row.request_id) + "/navigation", {
            method: "POST", body: JSON.stringify(payload), signals: owner?.signal ? [owner.signal] : [],
          });
          if (owner && !owner.current()) return;
          dialogue.patchNav(row.request_id, { submitting: false, receipt, error: "" });
          log?.(`관제 AI 이동 접수: ${payload.robot_id} -> (${payload.x.toFixed(2)}, ${payload.y.toFixed(2)})`, "good");
        } catch (error) {
          if (error?.name === "AbortError") throw error;
          dialogue.patchNav(row.request_id, { submitting: false, error: formatNavigationError(error) });
          throw error;
        } finally { renderMessages(); }
      },
      onError: (error) => { dialogue.patchNav(row.request_id, { submitting: false, error: formatNavigationError(error) }); renderMessages(); },
    });
  }

  async function submitObjectPickPlace(row, payload, opener) {
    if (typeof confirm !== "function" || !available || !executionEnabled || !identity || dialogue.getNav(row.request_id)?.objSubmitting) return;
    await confirm({
      message: `선택 객체(${payload.object.catalog_id})를 ${payload.destSite}로 1회 집기·놓기 실행할까요?`,
      kind: "assistant-pick-place", opener,
      eligible: () => Boolean(identity && available && executionEnabled && !dialogue.getNav(row.request_id)?.objReceipt),
      request: (owner) => dispatchAssistantPickPlace({ call, dialogue, row, payload, owner, log, randomUUID, onRender: renderMessages }),
      onError: (e) => { dialogue.patchNav(row.request_id, { objSubmitting: false, objError: e?.message || "1회 집기·놓기 요청이 거부되었습니다." }); renderMessages(); },
    });
  }

  function renderMessages() {
    listDirty = false; list.replaceChildren();
    const places = Array.isArray(readPlaces()) ? readPlaces() : [];
    const highlightedRef = objectHighlight?.get?.() ?? null;
    for (const row of identity ? dialogue.rows : []) {
      const item = mk("li"), userBubble = mk("div", "assistant-msg assistant-msg-user"), botBubble = mk("div", "assistant-msg assistant-msg-bot");
      userBubble.append(mk("p", "", "나: " + row.text));
      const head = mk("div", "assistant-msg-meta"), kindInfo = row.kind && KIND_META[row.kind];
      if (kindInfo) {
        const badge = mk("ui-tag", "", kindInfo.label);
        badge.setAttribute("variant", "inline"); badge.setAttribute("status", kindInfo.status); head.append(badge);
      }
      head.append(mk("small", "", STATE_TEXT[row.state] || "상태 확인 필요"));
      botBubble.append(head, mk("p", "", row.response || STATE_TEXT[row.state] || "상태 확인 필요"));
      if (row.reason) botBubble.append(mk("small", "hint", row.reason));
      if (row.facts?.length) {
        const facts = mk("ul", "assistant-facts");
        for (const f of row.facts) facts.append(mk("li", "", `${f.text} · 조회 ${new Date(f.observed_at * 1000).toLocaleTimeString("ko-KR")}`));
        botBubble.append(facts);
      }
      const nav = dialogue.getNav(row.request_id) || {};
      const card = renderCommandCard({ row, executionEnabled, available, identity, places, receipt: nav.receipt || null, errorText: nav.error || "", submitting: Boolean(nav.submitting), draft: nav.draft || null, onDraftChange: (draft) => dialogue.patchNav(row.request_id, { draft }), onSubmit: (payload, opener) => { void submitNavigation(row, payload, opener); }, onOpenRobot });
      if (card) botBubble.append(card);
      const objCard = renderObjectPickPlaceCard({ row, cellObjects: objBridge.get(), highlightedRef, executionEnabled, available, identity, receipt: nav.objReceipt || null, errorText: nav.objError || "", submitting: Boolean(nav.objSubmitting), draft: nav.objDraft || null, onHighlightObject: (ref) => objectHighlight?.set?.(ref, { source: "assistant" }), onDraftChange: (objDraft) => dialogue.patchNav(row.request_id, { objDraft }), onSubmit: (payload, opener) => { void submitObjectPickPlace(row, payload, opener); } });
      if (objCard) botBubble.append(objCard);
      item.append(userBubble, botBubble); list.append(item);
    }
    list.scrollTop = list.scrollHeight;
  }

  function paint() { syncContext(); paintControls(); if (listDirty) renderMessages(); }

  async function refreshStatus() {
    if (!identity) { status.textContent = "기명 운영자로 로그인해 주세요."; syncModeTag(); return; }
    const owner = identity;
    try {
      const result = await call("/api/fleet/assistant/status");
      if (owner !== identity) return;
      available = Boolean(result.available); executionEnabled = Boolean(result.execution_enabled);
      status.textContent = !available ? "관제 AI 연결 준비 중입니다. 기존 관제 기능을 이용해 주세요." : executionEnabled ? "상태 조회와 이동 명령 제안을 요청할 수 있습니다." : "상태 조회와 상황 설명을 요청할 수 있습니다.";
    } catch (error) {
      if (owner !== identity || error.name === "AbortError") return;
      available = false; executionEnabled = false;
      status.textContent = error.status === 403 ? "기명 운영자 접속이 필요합니다." : "관제 AI 연결 상태를 확인하지 못했습니다.";
    }
    listDirty = true; paint(); void objBridge.refresh();
  }

  async function poll(ticket) {
    try {
      const row = await call("/api/fleet/assistant/messages/" + encodeURIComponent(ticket.message.request_id));
      if (!dialogue.receive(ticket, row)) return;
      listDirty = true; paint();
      if (dialogue.busy) timer = setTimeout(() => poll(ticket), 1000); else { status.textContent = STATE_TEXT[row.state] || "상태 확인 필요"; if (row.state === "ANSWERED") void objBridge.refresh(); }
    } catch (error) {
      if (!dialogue.failed(ticket) || error.name === "AbortError") return;
      status.textContent = "요청 상태를 확인하지 못했습니다. 같은 요청 확인을 눌러주세요."; el("assistant-retry").hidden = false;
    }
  }

  async function post(ticket) {
    if (!ticket) return;
    el("assistant-retry").hidden = true; status.textContent = "요청을 확인하고 있습니다."; paintControls();
    try {
      const row = await call("/api/fleet/assistant/messages", { method: "POST", body: JSON.stringify(ticket.message) });
      if (!dialogue.receive(ticket, row)) return;
      input.value = ""; listDirty = true; paint();
      if (dialogue.busy) timer = setTimeout(() => poll(ticket), 1000); else { status.textContent = STATE_TEXT[row.state] || "상태 확인 필요"; if (row.state === "ANSWERED") void objBridge.refresh(); }
    } catch (error) {
      if (!dialogue.failed(ticket) || error.name === "AbortError") return;
      status.textContent = "접수 여부를 확인하지 못했습니다. 같은 요청 확인을 눌러주세요."; el("assistant-retry").hidden = false;
    }
  }

  const send = () => { if (available && identity && !dialogue.busy && input.value.trim()) post(dialogue.begin(input.value, activeRobotId(), el("assistant-locale").value)); };
  const setExpanded = (open) => { for (const btn of triggers) btn.setAttribute("aria-expanded", String(open)); };
  function close() {
    voice.cancel(); listening = false; voiceState.textContent = ""; panel.hidden = true;
    setExpanded(false); paintControls(); (lastOpener || triggers[0])?.focus();
  }

  for (const btn of triggers) {
    scope.listen(btn, "click", () => {
      if (panel.hidden) lastOpener = btn;
      panel.hidden = !panel.hidden; setExpanded(!panel.hidden);
      if (!panel.hidden) { syncContext(); refreshStatus(); input.focus(); }
    });
  }
  if (robotPicker) scope.listen(robotPicker, "change", () => { selectedRobotId = robotPicker.value || null; onSelectRobot?.(selectedRobotId); });
  if (newChatBtn) scope.listen(newChatBtn, "click", () => {
    if (!identity || dialogue.busy) return;
    clearTimer(); dialogue.reset(); el("assistant-retry").hidden = true; listDirty = true; status.textContent = "새 대화를 시작했습니다."; paint(); input.focus();
  });
  for (const btn of promptButtons) scope.listen(btn, "click", () => {
    const fn = PROMPT_TEMPLATES[btn.dataset.assistantPrompt];
    if (fn && identity && available && !dialogue.busy) { input.value = fn(activeRobotId()); input.focus(); }
  });
  scope.listen(el("assistant-close"), "click", close);
  scope.listen(el("assistant-locale"), "change", () => { voice.setLocale(el("assistant-locale").value); listening = false; paintControls(); });
  scope.listen(panel, "keydown", (event) => { if (event.key === "Escape") close(); });
  scope.listen(el("assistant-send"), "click", send);
  scope.listen(input, "keydown", (event) => { if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) { event.preventDefault(); send(); } });
  scope.listen(el("assistant-retry"), "click", () => { clearTimer(); post(dialogue.retry()); });
  scope.listen(el("assistant-dictate"), "click", () => { if (identity && !dialogue.busy) voice.start(); });
  scope.listen(el("assistant-dictate-stop"), "click", () => voice.stop());
  scope.listen(el("assistant-voice-prepare"), "click", async () => {
    if (!identity) return;
    const owner = identity; voiceState.textContent = "한국어 음성 입력을 준비하고 있습니다.";
    try { const ready = await voice.prepare(); if (owner === identity) voiceState.textContent = ready ? "음성 입력을 사용할 수 있습니다." : "이 브라우저에서 한국어 음성 입력을 사용할 수 없습니다."; }
    catch { if (owner === identity) voiceState.textContent = "음성 입력을 준비하지 못했습니다. 텍스트로 입력해 주세요."; }
  });
  scope.listen(el("assistant-read"), "click", () => { if (identity) { const last = dialogue.rows.findLast((r) => r.state === "ANSWERED" && r.response); if (last) voice.speak(last.response); } });
  scope.listen(el("assistant-read-stop"), "click", () => voice.stopSpeaking());
  scope.onDispose(() => {
    clearTimer(); voice.cancel(); listening = false; identity = null; available = false; executionEnabled = false;
    input.value = ""; voiceState.textContent = ""; el("assistant-retry").hidden = true; status.textContent = "접속을 확인하고 있습니다."; listDirty = true; paint();
  });

  return {
    syncContext,
    setIdentity(auth) {
      const next = !auth.locked && isOperator(auth.role) && auth.principal !== "site-console" && !auth.principal?.startsWith("development-") ? auth.principal || null : null;
      const changed = dialogue.setIdentity(next);
      if (!changed && identity === next) return;
      identity = next; available = false; executionEnabled = false; clearTimer(); voice.cancel(); listening = false;
      input.value = ""; voiceState.textContent = ""; el("assistant-retry").hidden = true; listDirty = true; paint();
      status.textContent = identity ? "대화를 열면 연결 상태를 확인합니다." : "기명 운영자로 로그인해 주세요.";
      if (!panel.hidden) refreshStatus();
      if (identity && dialogue.pending) poll(dialogue.pending);
    },
  };
}
