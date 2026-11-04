// D-975 설치 노선 — 설치 문서 맨 위의 진행 띠. 각 역의 완료는 서버 근거로만 정한다(아는 만큼 말한다).
// 근거를 읽지 못한 역은 완료로 그리지 않고 "확인 못 함"을 단다. 버튼·조작은 없다: 역은 그 구획으로 가는 링크다.

export const STATIONS = [
  { id: "robots", label: "로봇 등록", anchor: "#robot-enrollment", path: "/api/fleet/enrollment/robots",
    done: (body) => (body.robots || []).length > 0,
    note: (body) => `${(body.robots || []).length}대` },
  { id: "cameras", label: "카메라 승인", anchor: "#camera-link", path: "/api/fleet/pairing/v1/credentials/summary",
    done: (body) => (body.credentials || []).some((row) => row.state !== "revoked"),
    note: (body) => `${(body.credentials || []).filter((row) => row.state !== "revoked").length}대` },
  { id: "calibration", label: "카메라 보정", anchor: "#camera-calibration", path: "/api/fleet/calibrations",
    done: (body) => (body.calibrations || []).length > 0,
    note: (body) => `${(body.calibrations || []).length}개` },
  { id: "start", label: "시작점", anchor: "#start-point-heading", path: "/api/fleet/start-points",
    done: (body) => (body.start_points || []).some((row) => row.valid),
    note: (body) => ((body.start_points || []).some((row) => row.valid) ? "저장됨" : "없음") },
];

/** results[i] = {ok: true, body} | {ok: false}. 반환: 역마다 {state, note} — state는 D-975 어휘(done·now·todo). */
export function stationStates(results) {
  let nowGiven = false;
  return STATIONS.map((station, index) => {
    const result = results[index];
    if (!result || !result.ok) return { state: "todo", note: "확인 못 함" };
    if (station.done(result.body)) return { state: "done", note: station.note(result.body) };
    if (nowGiven) return { state: "todo", note: station.note(result.body) };
    nowGiven = true;
    return { state: "now", note: station.note(result.body) };
  });
}

export function createInstallLine({ root, call, scope }) {
  const items = STATIONS.map((station) => {
    const item = document.createElement("li");
    item.className = "ui-stage";
    item.dataset.station = station.id;
    const link = document.createElement("a");
    link.href = station.anchor;
    link.textContent = station.label;
    const note = document.createElement("small");
    item.append(link, " ", note);
    root.append(item);
    return { item, note };
  });

  async function refresh() {
    const life = scope.capture();
    const results = await Promise.all(STATIONS.map((station) =>
      call(station.path).then((body) => ({ ok: true, body }), () => ({ ok: false }))));
    if (!life.current()) return;
    stationStates(results).forEach(({ state, note }, index) => {
      const { item, note: noteNode } = items[index];
      if (state === "todo") item.removeAttribute("data-state"); else item.dataset.state = state;
      if (state === "now") item.setAttribute("aria-current", "step"); else item.removeAttribute("aria-current");
      noteNode.textContent = note;
    });
  }
  return { refresh };
}
