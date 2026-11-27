import { setOff } from "/common/cause-line.js";

const CONTROL_WINDOW_S = 30;
export const KIND_META = {
  CHAT: { label: "대화", status: "neutral" }, STATUS: { label: "상태 조회", status: "active" },
  CAUSE: { label: "원인 근거", status: "warn" }, CLARIFY: { label: "추가 확인", status: "warn" },
  CONTROL: { label: "명령 제안", status: "active" }, REFUSE: { label: "요청 거절", status: "crit" },
};
export const elOf = (tag, cls, text = "") => { const e = document.createElement(tag); if (cls) e.className = cls; if (text) e.textContent = text; return e; };
const num = (v) => (v === "" || v == null ? NaN : Number(v));

export function controlRemainingS(row, nowSec = Date.now() / 1000) {
  return !row || typeof row.completed_at !== "number" || !Number.isFinite(row.completed_at) ? null : Math.max(0, Math.ceil(CONTROL_WINDOW_S - (nowSec - row.completed_at)));
}
export function isControlExpired(row, nowSec = Date.now() / 1000) {
  return !row || typeof row.completed_at !== "number" || !Number.isFinite(row.completed_at) ? false : nowSec - row.completed_at > CONTROL_WINDOW_S || nowSec < row.completed_at;
}
export function buildNavigationPayload(robotId, xRaw, yRaw, yawRaw = 0) {
  if (typeof robotId !== "string" || !robotId.trim()) return null;
  const x = num(xRaw), y = num(yRaw), yaw = yawRaw === "" || yawRaw == null ? 0 : Number(yawRaw);
  if (!Number.isFinite(x) || !Number.isFinite(y) || !Number.isFinite(yaw)) return null;
  if (Math.abs(x) > 100000 || Math.abs(y) > 100000 || yaw < -Math.PI || yaw > Math.PI) return null;
  return { robot_id: robotId.trim(), x, y, yaw };
}
export function formatNavigationError(error) {
  const s = error?.status;
  if (s === 409) return "명령 유효 시간(30초)이 지났거나 선택한 로봇·좌표가 변경되었습니다. 다시 요청해 주세요.";
  if (s === 403) return "기명 운영자 권한이 변경되었거나 부족합니다.";
  if (s === 404) return "대상 로봇을 현재 관제 명렬에서 찾을 수 없습니다.";
  if (s === 503) return "명령 실행 연결이 꺼져 있거나 저장소를 사용할 수 없습니다.";
  return "이동 명령을 접수하지 못했습니다. 잠시 후 다시 시도해 주세요.";
}

function coordField(labelText, key, value) {
  const wrap = elOf("label", "assistant-nav-field"), input = elOf("input", "ui-field");
  input.type = "number"; input.step = "0.01"; input.value = value ?? ""; input.dataset.assistantCoord = key;
  wrap.append(elOf("span", "", labelText), input);
  return { wrap, input };
}

export function renderCommandCard({
  row, executionEnabled, available, identity, places = [], receipt = null,
  errorText = "", submitting = false, draft = null, onDraftChange = null, onSubmit = null, onOpenRobot = null,
}) {
  if (!row || row.state !== "ANSWERED" || row.kind !== "CONTROL") return null;
  const card = elOf("div", "assistant-command-card");
  if (receipt) {
    const box = elOf("div", "assistant-receipt"), link = elOf("a", "ui-action-link", "작업 화면에서 추적·취소");
    box.setAttribute("role", "status"); link.href = "/console?view=work";
    box.append(elOf("strong", "", "이동 명령이 작업 큐에 접수되었습니다."),
      elOf("small", "", `작업 ${receipt?.task?.task_id || "—"} · 대상 ${receipt?.task?.robot_id || "—"} · 큐 상태 ${receipt?.task?.status || "QUEUED"}`), link);
    card.append(box);
    return card;
  }
  const robotId = row.selected_robot_id || "";
  if (!executionEnabled || !robotId) {
    const note = elOf("p", "hint", !executionEnabled
      ? "현재 관제 AI는 조회 전용 모드입니다. 아래 작업 화면에서 이동 명령을 보내 주세요."
      : "상단 대상 로봇을 먼저 고른 뒤 다시 요청하면 대화에서 바로 이동을 접수할 수 있습니다.");
    const actions = elOf("div", "assistant-command-actions"), workLink = elOf("a", "ui-action-link", "작업 화면에서 실행");
    workLink.href = "/console?view=work&show=new"; actions.append(workLink);
    if (robotId && typeof onOpenRobot === "function") {
      const openBtn = document.createElement("ui-button");
      openBtn.textContent = "로봇 제어 열기";
      openBtn.setAttribute("kind", "quiet"); openBtn.setAttribute("type", "button"); openBtn.dataset.assistantOpenRobot = "true";
      openBtn.addEventListener("click", () => onOpenRobot(robotId));
      actions.append(openBtn);
    }
    card.append(note, actions);
    return card;
  }

  const head = elOf("div", "assistant-command-head"), ttl = controlRemainingS(row);
  head.append(elOf("strong", "", `명령 대상: ${robotId}`), elOf("small", "", ttl === null ? "30초 안에 확인" : ttl > 0 ? `유효 ${ttl}초` : "유효 시간 만료"));
  const placeList = (Array.isArray(places) ? places : []).filter((p) => p && typeof p.id === "string" && p.id && Number.isFinite(Number(p.x)) && Number.isFinite(Number(p.y)));
  const placeWrap = elOf("label", "assistant-nav-field"), placeSelect = elOf("select", "ui-field");
  placeSelect.dataset.assistantPlace = "true";
  placeSelect.append(elOf("option", "", placeList.length ? "장소 선택 또는 아래 좌표 입력" : "등록된 장소 없음 · 좌표 직접 입력"));
  placeSelect.firstChild.value = "";
  for (const p of placeList) {
    const opt = elOf("option", "", `${p.name || p.id} (${Number(p.x).toFixed(2)}, ${Number(p.y).toFixed(2)})`);
    opt.value = p.id; placeSelect.append(opt);
  }
  placeSelect.value = draft?.placeId || "";
  placeWrap.append(elOf("span", "", "지도 장소 선택"), placeSelect);

  const grid = elOf("div", "assistant-nav-grid"), fx = coordField("X (m)", "x", draft?.x ?? ""), fy = coordField("Y (m)", "y", draft?.y ?? ""), fyaw = coordField("Yaw (rad)", "yaw", draft?.yaw ?? "0");
  grid.append(fx.wrap, fy.wrap, fyaw.wrap);
  const actions = elOf("div", "assistant-command-actions"), submitBtn = document.createElement("ui-button");
  submitBtn.textContent = submitting ? "접수 중…" : "이동 명령 접수";
  submitBtn.setAttribute("kind", "primary"); submitBtn.setAttribute("type", "button"); submitBtn.dataset.assistantNavSubmit = "true";
  actions.append(submitBtn); card.append(head, placeWrap, grid, actions);

  const syncSubmitState = () => {
    const payload = buildNavigationPayload(robotId, fx.input.value, fy.input.value, fyaw.input.value);
    const reason = !identity ? "기명 운영자로 로그인해 주세요." : !available ? "관제 AI 연결이 필요합니다." : submitting ? "이동 명령을 접수하는 중입니다."
      : isControlExpired(row) ? "30초 유효 시간이 지났습니다. 명령을 다시 요청해 주세요." : !payload ? "유효한 목표 X·Y 좌표를 입력하세요." : "";
    setOff(submitBtn, Boolean(reason), reason);
    return payload;
  };
  const emitDraft = () => onDraftChange?.({ placeId: placeSelect.value, x: fx.input.value, y: fy.input.value, yaw: fyaw.input.value });
  placeSelect.addEventListener("change", () => {
    const chosen = placeList.find((p) => p.id === placeSelect.value);
    if (chosen) {
      fx.input.value = String(Number(chosen.x).toFixed(2)); fy.input.value = String(Number(chosen.y).toFixed(2));
      fyaw.input.value = Number.isFinite(Number(chosen.yaw)) ? String(Number(chosen.yaw).toFixed(2)) : "0";
    }
    emitDraft(); syncSubmitState();
  });
  for (const field of (fx.input, fy.input, fyaw.input)) field.addEventListener("input", () => { emitDraft(); syncSubmitState(); });
  submitBtn.addEventListener("click", () => { const payload = syncSubmitState(); if (payload && typeof onSubmit === "function") onSubmit(payload, submitBtn); });
  syncSubmitState();
  if (errorText) { const err = elOf("p", "hint assistant-nav-error", errorText); err.setAttribute("role", "alert"); card.append(err); }
  return card;
}
