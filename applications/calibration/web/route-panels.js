import { setOff } from "/common/cause-line.js";

const defaults = {arm_s: ["pinky", "belt"], arm_a: ["tmp-a-1-l1", "ship-h1r0-l0"], arm_b: ["tmp-b-2-l1", "ship-h1r2-l0"]};
const panels = new Map();
const actions = {
  resolve_route_arm: "경로에 배정된 팔 확인", resolve_named_site: "칸 이름에 실행 좌표 연결",
  measure_named_xy: "칸 중심 XY 실측", review_invalid_named_xy: "칸 중심 XY 등록값 확인",
  record_depth_floor_reference: "빈 바닥 깊이 검증·등록", check_camera_map_reference: "카메라 기준 확인",
  verify_named_site_on_existing_map: "기존 맵에서 칸 중심 검증", validate_site_map: "칸의 맵 검증",
  verify_named_xy: "등록된 XY 실측 검증", verify_slot_center_at_contact_height: "접촉 높이에서 칸 중심 확인",
  review_surface_evidence_at_named_xy: "칸 중심의 면 높이 확인", verify_surface_contact: "면 접촉 검증",
  register_named_top_roi: "칸 영상 영역 등록", separate_named_top_rois: "두 칸 영상 영역 분리",
  correct_zone_configuration: "구역 설정 확인", review_route_configuration: "이송 경로 설정 확인",
  continue_to_existing_fresh_preflight: "이송 직전 현장 점검",
};

function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text) node.textContent = text;
  if (className) node.className = className;
  return node;
}

function linkedRoute(arm) {
  const q = new URLSearchParams(location.search);
  if (q.get("arm") !== arm || !["src_site", "dst_site", "task_id"].some(k => q.has(k))) return null;
  const route = [q.get("src_site"), q.get("dst_site")];
  const task = q.get("task_id");
  const valid = ["arm", "src_site", "dst_site"].every(k => q.getAll(k).length === 1)
    && route.every(s => s && /^[A-Za-z0-9][A-Za-z0-9_:-]{0,95}$/.test(s)) && route[0] !== route[1]
    && (!q.has("task_id") || (q.getAll("task_id").length === 1 && /^[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}$/.test(task)));
  return {route, task, valid};
}

function linkedTask(panel) {
  const link = panel.link;
  const route = panel.arm === "arm_s" ? defaults.arm_s : panel.selects.map(s => s.value);
  return link?.valid && route.every((s, i) => s === link.route[i]) ? link.task : null;
}

function createPanel(arm, api) {
  const card = element("article", "", "cal-card");
  card.id = "route-" + arm;
  const title = element("h2", arm.slice(-1).toUpperCase() + "팔 경로 점검", "ui-section-heading");
  const form = element("form", "", "answer-form");
  if (arm === "arm_s") form.append(element("p", "공급 경로 · pinky → belt"));
  const selects = (arm === "arm_s" ? [] : ["출발칸", "도착칸"]).map(text => {
    const label = element("label", text);
    const select = element("select", "", "ui-field");
    label.append(select);
    form.append(label);
    return select;
  });
  const button = element("ui-button", "경로 사전 점검");
  button.setAttribute("type", "submit");
  const note = element("p");
  note.id = "route-note-" + arm;
  note.setAttribute("role", "status");
  const result = element("div");
  form.append(button);
  card.append(title, form, note, result);
  const panel = {arm, api, card, selects, button, note, result, rows: [], sites: [], operator: false, timer: null, sending: false};
  form.addEventListener("change", () => render(panel));
  form.addEventListener("submit", async event => {
    event.preventDefault();
    if (button.disabled || panel.sending || !panel.operator) return;
    panel.sending = true;
    const route = selects.map(s => s.value);
    const body = {arm, step: "check"};
    if (arm === "arm_s") body.supply_route = true;
    else body.route = route;
    const task = linkedTask(panel);
    if (task) body.task_id = task;
    render(panel);
    try {
      const job = await api("/api/calibration/jobs", {method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify(body)});
      if (job.arm !== arm || (task && job.task_id !== task) ||
          (arm === "arm_s" ? job.supply_route !== true : job.route?.join("|") !== route.join("|")))
        throw new Error("팔과 경로가 일치하지 않습니다.");
      panel.rows.unshift(job);
    } catch (error) {
      panel.notice = {route, text: error.message};
    } finally {
      panel.sending = false;
      render(panel);
    }
  });
  return panel;
}

function displayResult(panel, job) {
  if (panel.arm === "arm_s") {
    const list = element("ul");
    for (const name of defaults.arm_s) {
      const site = panel.siteStatus?.[name];
      const height = Number.isFinite(site?.surface_z) ? site.surface_z + " m" : "미등록";
      list.append(element("li", name + " · 맵 " + (site?.map ? "등록" : "미등록")
        + " · XY 편차 기록 " + (site?.bias?.length || 0) + "건 · 면 높이 " + height));
    }
    panel.result.append(list);
    if (job?.status !== "done" || !job.result?.check) return;
    const check = job.result.check;
    const camera = check.camera_issue || check.map_binding_error || (check.camera_shift?.ok ? "기준 영상 확인" : "확인 필요");
    panel.result.append(element("p", "카메라 · " + camera), element("p", "다음 단계 · " + (job.result.todo?.join(", ") || "이송 직전 현장 점검")));
    showEvidence(panel, job);
    return;
  }
  const report = job?.result?.check?.route?.calibration_evidence;
  if (!report || job.status !== "done") return;
  const list = element("ul");
  for (const [role, site] of Object.entries(report.sites || {})) {
    const slot = role === "source" ? job.route[0] : job.route[1];
    const floor = site.floor_reference?.optical_depth_mm;
    const xy = Array.isArray(site.xy_m) ? site.xy_m.join(", ") + " m" : "미등록";
    list.append(element("li", slot + " · 영상 영역 " + (site.top_roi ? "등록" : "미등록")
      + " · 팔 XY " + xy + " · 바닥 깊이 " + (floor == null ? "미등록" : String(floor) + " mm")));
  }
  const camera = report.reference_current ? "카메라 기준 유효" : "카메라 기준 확인 필요";
  const remap = job.result.todo?.includes("remap") ? " · 카메라 XY 맵 재측정 필요" : "";
  const next = report.next_machine_action;
  const nextText = next ? actions[next] || next : "결과 확인 필요";
  panel.result.append(element("p", camera + remap), list, element("p", "다음 단계 · " + nextText));
  showEvidence(panel, job);
}

function showEvidence(panel, job) {
  const details = element("details");
  details.append(element("summary", "점검 근거 · " + (job.route_config || job.arm) + (job.task_id ? " · Fleet " + job.task_id : "")),
    element("pre", JSON.stringify(job.result, null, 2)));
  panel.result.append(details);
}

function render(panel) {
  clearTimeout(panel.timer);
  const route = panel.selects.map(s => s.value);
  const active = panel.rows.find(j => j.status === "running");
  const task = linkedTask(panel);
  const job = panel.rows.find(j => j.step === "check"
    && (!task || j.task_id === task)
    && (panel.arm === "arm_s" ? j.supply_route === true : j.route?.join("|") === route.join("|")));
  const reason = panel.invalidLink ? "이 팔에서 점검할 수 없는 Fleet 경로 링크입니다." :
    !panel.operator ? "작업 권한으로 로그인하세요." : active ? "팔에서 작업 실행 중 · " + active.id
    : panel.sending ? "점검 요청 중" : panel.arm !== "arm_s" && (!route[0] || !route[1]) ? "이송 실행기 설정과 칸 목록을 확인하세요."
    : route.length && route[0] === route[1] ? "서로 다른 칸을 선택하세요." : "";
  setOff(panel.button, !!reason, reason, panel.note.id);
  const notice = panel.notice;
  panel.notice = null;
  panel.note.textContent = notice?.route.join("|") === route.join("|") ? notice.text : reason ||
    (job ? job.id + " · " + ({done: "점검 종료", failed: "점검 실패", interrupted: "중단"}[job.status] || job.status) : "");
  panel.result.replaceChildren();
  if (task) panel.result.append(element("p", "연결된 Fleet 작업 · " + task));
  if (!panel.invalidLink) displayResult(panel, job);
  if (active) panel.timer = setTimeout(async () => {
    try {
      const fresh = await panel.api("/api/calibration/jobs/" + encodeURIComponent(active.id));
      if (panels.get(panel.arm) !== panel) return;
      if (fresh.id !== active.id || fresh.arm !== panel.arm) throw new Error("작업 기록 불일치");
      panel.rows = panel.rows.map(j => j.id === fresh.id ? fresh : j);
    } catch (error) { panel.notice = {route, text: error.message}; }
    if (panels.get(panel.arm) === panel) render(panel);
  }, 2500);
}

export function setRoutePanels(arms, jobs, operator, api) {
  const root = document.getElementById("routePanels");
  if (!root) return;
  for (const arm of Object.keys(defaults)) {
    let panel = panels.get(arm);
    if (!arms[arm]) {
      if (panel) { clearTimeout(panel.timer); panel.card.remove(); panels.delete(arm); }
      continue;
    }
    if (!panel) {
      panel = createPanel(arm, api);
      panels.set(arm, panel);
      root.append(panel.card);
    }
    panel.rows = jobs.filter(j => j.arm === arm);
    panel.siteStatus = arms[arm].sites;
    const sites = arms[arm].route_sites || [];
    const link = linkedRoute(arm);
    const linkChanged = JSON.stringify(panel.link) !== JSON.stringify(link);
    panel.link = link;
    panel.invalidLink = link && (!link.valid || (arm === "arm_s" ? link.route.join("|") !== defaults.arm_s.join("|")
      : !link.route.every(s => sites.includes(s))));
    if (linkChanged || panel.sites.join("|") !== sites.join("|")) {
      panel.selects.forEach((s, index) => {
        const previous = link ? link.route[index] : s.value || panel.rows.find(j => j.route)?.route[index] || defaults[arm][index];
        s.replaceChildren(new Option("칸 선택", ""), ...sites.map(id => new Option(id, id)));
        s.value = sites.includes(previous) ? previous : "";
      });
      panel.sites = sites;
    }
    panel.operator = operator;
    render(panel);
  }
  root.hidden = !panels.size;
  const linked = panels.get(new URLSearchParams(location.search).get("arm"));
  if (linked && !linked.anchorShown && location.hash === "#" + linked.card.id) {
    linked.anchorShown = true;
    linked.card.scrollIntoView({block: "start"});
  }
}
