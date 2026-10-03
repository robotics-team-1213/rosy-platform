// 학습 모델 상태 패널(D-423 §3.6). CORE GET /api/v1/vision/models 를 읽기만 한다.
// 교체(적용·되돌리기)는 운영자 CLI(rosy_ml)에만 있다 — 이 화면은 무엇이 돌고 있는지만 보인다.
// CORE 는 로봇의 포인터 파일을 읽지 못하므로, 노드가 돌지 않는 슬롯은 목록에 없다.

export const MODELS_POLL_MS = 5000;
const TASK_LABEL = {lane_seg: "차선", object_det: "물체"};
const SLOT_LABEL = {shadow: "섀도", active: "적용"};

export function describeModels(body) {
  const tasks = Array.isArray(body?.tasks) ? body.tasks : [];
  return tasks.filter((t) => t && typeof t.task === "string").map((t) => {
    const revision = typeof t.model_revision === "string" && t.model_revision ? t.model_revision : "모델 없음";
    const note = t.stale ? "보고 끊김" : (t.last_error ? String(t.last_error).slice(0, 80) : "정상");
    return {
      name: `${TASK_LABEL[t.task] ?? t.task} · ${SLOT_LABEL[t.slot] ?? t.slot ?? "?"}`,
      revision, note,
      problem: Boolean(t.stale || t.last_error || revision === "모델 없음"),
    };
  });
}

export function createModelStatus({apiGet, onUpdate, schedule, intervalMs = MODELS_POLL_MS}) {
  let running = false;
  let cancel = null;
  async function tick() {
    if (!running) return;
    try {
      const reply = await apiGet("/api/v1/vision/models");
      if (running) onUpdate(reply?.status === 200 ? describeModels(reply.body) : null);
    } catch {
      if (running) onUpdate(null);
    }
    if (running) cancel = schedule(tick, intervalMs);
  }
  return {
    start() { if (running) return; running = true; tick(); },
    stop() { running = false; cancel?.(); cancel = null; },
  };
}

// rows: describeModels() 결과 또는 null(읽기 실패). list 는 <ul>.
export function renderModels(list, rows) {
  list.replaceChildren();
  const items = rows === null ? [{name: "상태를 읽지 못했습니다", revision: "", note: "", problem: true}]
    : rows.length ? rows : [{name: "보고한 모델이 없습니다", revision: "", note: "", problem: false}];
  for (const row of items) {
    const item = document.createElement("li");
    item.textContent = [row.name, row.revision, row.note].filter(Boolean).join(" — ");
    item.dataset.problem = String(row.problem);
    list.append(item);
  }
}
