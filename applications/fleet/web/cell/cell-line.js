// D-975 Cell 준비 노선. 화면이 서버 응답으로 이미 채운 요소만 읽고 새 판정을 만들지 않는다.
// 문서 저장·미리보기·제안·작업 조회 응답이 각 요소를 바꾸면 노선이 따라 바뀐다.

export const STATIONS = [
  { id: "recipe", label: "레시피", anchor: "#recipe-heading" },
  { id: "cell", label: "셀 설정", anchor: "#cell-heading" },
  { id: "plan", label: "적재 계획", anchor: "#preview-heading" },
  { id: "proposal", label: "작업 제안", anchor: "#proposal-heading" },
  { id: "run", label: "승인·진행", anchor: "#mission-heading" },
];

// facts: {recipe, cell, plan: bool, proposal: bool, job: {status, reason} | null, jobNote: string}
export function cellLineStates(facts) {
  const done = [facts.recipe, facts.cell, facts.plan, facts.proposal || !!facts.job, facts.job?.status === "GOAL_CONFIRMED"];
  const notes = [
    facts.recipe ? "저장됨" : "저장 전",
    facts.cell ? "저장됨" : "저장 전",
    facts.plan ? "계산됨" : "미리보기 전",
    done[3] ? "제안됨" : "제안 전",
    facts.job ? facts.jobNote || "상태 확인됨" : "작업 조회 전",
  ];
  const now = done.indexOf(false);
  return done.map((isDone, index) => {
    let state = isDone ? "done" : index === now ? "now" : "todo";
    if (index === 4 && facts.job?.status === "HOLD" && facts.job.reason) state = "blocked";
    return { state, note: notes[index] };
  });
}

export function createCellLine({ root, $ }) {
  const items = STATIONS.map((station) => {
    const item = document.createElement("li");
    item.className = "ui-stage";
    const link = document.createElement("a");
    link.href = station.anchor;
    link.textContent = station.label;
    const note = document.createElement("small");
    item.append(link, " ", note);
    root.append(item);
    return { item, note };
  });

  function render() {
    let job = null;
    try { job = $("job-state").textContent ? JSON.parse($("job-state").textContent) : null; } catch { job = null; }
    const ready = (id) => $(id).getAttribute("state") === "ready";
    cellLineStates({
      recipe: ready("recipe-revision"), cell: ready("cell-revision"), plan: ready("summary"),
      proposal: !!$("proposal").textContent, job, jobNote: $("job-summary").textContent.split(" · ")[0],
    }).forEach(({ state, note }, index) => {
      const { item, note: noteNode } = items[index];
      if (state === "todo") item.removeAttribute("data-state"); else item.dataset.state = state;
      if (state === "now") item.setAttribute("aria-current", "step"); else item.removeAttribute("aria-current");
      noteNode.textContent = note;
    });
  }

  const watched = ["recipe-revision", "cell-revision", "summary", "proposal", "job-state", "job-summary"];
  const observer = new MutationObserver(render);
  for (const id of watched) observer.observe($(id), { attributes: true, attributeFilter: ["state"], childList: true, characterData: true, subtree: true });
  render();
  return { render };
}
