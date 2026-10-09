// D-540 5 · D-539: "배경 다시 학습"은 설치·보정 `카메라 설치·보정` 작업의 일이다(관제 문서에는 없다).
// 운영자가 빈 트랙에서 누르는 선언이고, Vision 은 이 학습만 저장해 재시작 뒤에도 쓴다(D-539 1).
import { isRouteAbsent } from "/console/assets/poll-gate.js";

const WARNING = "배경을 다시 학습합니다. 트랙 위의 로봇과 물건을 모두 치운 뒤 진행하세요 — "
  + "남아 있으면 배경으로 굳어 추적되지 않습니다(약 10초). 계속할까요?";

export function createTrackingRelearn({ scope, el, call, auth, confirm }) {
  const button = el("tracking-relearn");
  const line = el("tracking-relearn-state");
  let sources = [], busy = false, absent = false, heldUntil = 0; // 결과 문구를 한동안 덮지 않는다

  function say(text, state = "none") { line.textContent = text; line.dataset.state = state; }

  async function refresh() {
    if (auth.locked || !auth.role || absent || busy) return;
    const life = scope.capture();
    try {
      const body = await call("/api/fleet/tracking");
      if (!life.current()) return;
      sources = (body?.sources || []).map(source => source.source_id);
      button.hidden = !sources.length;
      if (!sources.length) say("추적하는 관제 카메라가 없습니다.");
      else if (Date.now() >= heldUntil) say(`관제 카메라 ${sources.join(", ")}`);
    } catch (error) {
      if (error.name === "AbortError" || !life.current()) return;
      absent = isRouteAbsent(error.status, error.code);
      sources = [];
      button.hidden = true;
      say(absent ? "이 Fleet에는 관제 카메라 추적이 설정되지 않았습니다." : "관제 카메라 추적 상태를 읽지 못했습니다.",
        absent ? "none" : "warn");
    }
  }

  scope.listen(button, "click", async () => {
    if (busy || auth.locked || auth.role !== "operator" || !sources.length) return;
    const life = scope.capture(), selected = [...sources];
    if (!await confirm({ message: WARNING, action: "다시 학습", opener: button, signal: life.signal })
      || !life.current() || auth.locked || auth.role !== "operator") return;
    busy = true;
    try {
      for (const source_id of selected) {
        await call("/api/fleet/tracking/relearn", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ source_id }), signals: [life.signal],
        });
        if (!life.current()) return;
      }
      say("배경을 다시 학습합니다. 트랙을 비워 주세요(약 10초).", "warn");
      heldUntil = Date.now() + 15000;
    } catch (error) {
      if (error.name !== "AbortError" && life.current()) {
        say("배경 다시 학습 실패: " + (error.message || error), "warn");
        heldUntil = Date.now() + 15000;
      }
    } finally { busy = false; }
  });

  function reset() { sources = []; absent = false; busy = false; heldUntil = 0; button.hidden = true; say(""); }
  scope.onDispose(reset); scope.onResume(refresh); scope.interval(refresh, 5000);
  return { refresh, reset };
}
