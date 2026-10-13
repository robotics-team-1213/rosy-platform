// D-540 5 · D-539: "배경 다시 학습"은 설치·보정 `카메라 설치·보정` 작업의 일이다(관제 문서에는 없다).
// Vision 은 이 학습만 저장해 재시작 뒤에도 쓴다(D-539 1). D-600: 로봇은 그대로 둔다 — Fleet 이 아는
// 로봇 자리는 배우지 않고, 로봇이 비킨 뒤 채운다. 위치를 모르는 로봇은 응답의 unlocated 로 알린다.
import { isRouteAbsent } from "/console/assets/poll-gate.js";

const WARNING = "배경을 다시 학습합니다(약 10초). 로봇은 매트 위에 그대로 두어도 됩니다 — Fleet이 위치를 아는 "
  + "로봇의 자리는 배우지 않고, 로봇이 비킨 뒤 채웁니다. 로봇이 아닌 물건은 치우세요. 계속할까요?";

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
      const unlocated = new Set();
      for (const source_id of selected) {
        const reply = await call("/api/fleet/tracking/relearn", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ source_id }), signals: [life.signal],
        });
        if (!life.current()) return;
        for (const robot of reply?.unlocated || []) unlocated.add(robot);
      }
      say(unlocated.size
        ? `배경을 다시 학습합니다. 위치를 모르는 로봇 ${[...unlocated].join(", ")}은 배경이 될 수 있습니다 — `
          + "지도에서 위치를 찍은 뒤 다시 학습하세요."
        : "배경을 다시 학습합니다(약 10초). 로봇 자리는 비워 두고, 비킨 뒤 채웁니다.", "warn");
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
