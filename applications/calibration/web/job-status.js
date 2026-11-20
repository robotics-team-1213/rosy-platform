import { $, fetchJson, makeTable, addDtDd } from "./app.js";

const JOB_STEP_LABEL = { check: "사전 점검(check)", "depth-verify": "깊이 검증(depth-verify)", "pivot-near": "피벗 근접 보정(pivot-near)", remap: "재매핑(remap)" };
const JOB_RESULT = { running: ["실행 중", "warn"], done: ["성공", "ok"], failed: ["실패", "error"] };

function leaseText(lease) {
  if (!lease) return "비어 있음";
  const until = Number.isFinite(lease.expires) ? new Date(lease.expires * 1000).toLocaleString("ko-KR") : "-";
  return `${lease.live ? "점유 중" : "만료됨"} · ${lease.owner} · ${lease.purpose || "-"} · 만료 ${until}`;
}

function renderRecentJobs(rows) {
  const wrap = $("recentJobsWrap");
  wrap.replaceChildren();
  if (!rows.length) {
    const p = document.createElement("p");
    p.className = "cal-muted";
    p.textContent = "최근 작업이 없습니다.";
    wrap.appendChild(p);
    return;
  }
  const { tbl, tbody } = makeTable(["팔", "종류", "결과", "시각"]);
  tbl.setAttribute("data-readonly", "true");
  for (const j of rows.slice(0, 3)) {
    const tr = document.createElement("tr");
    const tdArm = document.createElement("td");
    tdArm.textContent = j.arm || "-";
    const tdStep = document.createElement("td");
    tdStep.textContent = JOB_STEP_LABEL[j.step] || j.step || "-";
    const tdResult = document.createElement("td");
    const [label, level] = JOB_RESULT[j.status] || [j.status || "-", ""];
    tdResult.textContent = label;
    if (level) tdResult.setAttribute("data-level", level);
    const tdWhen = document.createElement("td");
    tdWhen.textContent = j.ended || j.started ? new Date(j.ended || j.started).toLocaleString("ko-KR") : "-";
    tr.append(tdArm, tdStep, tdResult, tdWhen);
    tbody.appendChild(tr);
  }
  wrap.appendChild(tbl);
}

export async function loadJobStatus() {
  const note = $("jobStatusNote");
  const tag = $("jobStatusTag");
  let status;
  try {
    status = await fetchJson("/api/calibration/status");
  } catch (err) {
    const noCells = err.status === 404;
    const login = err.status === 401;
    tag.setAttribute("status", noCells || login ? "neutral" : "crit");
    tag.textContent = noCells ? "셀 미설정" : login ? "로그인 필요" : "오류";
    note.textContent = noCells
      ? "셀이 설정되지 않았습니다(--cells 없이 실행). 리스 점유와 최근 작업을 볼 수 없습니다."
      : login
        ? "Rosy Account로 로그인해야 작업 상태를 볼 수 있습니다."
        : `작업 상태를 불러오지 못했습니다: ${err.message}`;
    $("jobStatusBody").hidden = true;
    return;
  }
  const leaseDl = $("jobLeaseDl");
  leaseDl.replaceChildren();
  note.textContent = "읽기 전용입니다. 화면에서 작업을 시작하지 않습니다.";
  tag.setAttribute("status", "active");
  tag.textContent = "표시 중";
  if (status.leases_error) addDtDd(leaseDl, "리스 조회", `실패: ${status.leases_error}`);
  for (const [arm, info] of Object.entries(status.arms || {})) addDtDd(leaseDl, arm, leaseText(info?.lease));
  if (!leaseDl.children.length) addDtDd(leaseDl, "팔", "cells.json에 등록된 팔이 없습니다.");
  try {
    renderRecentJobs((await fetchJson("/api/calibration/jobs")).jobs || []);
  } catch (err) {
    renderRecentJobs([]);
    note.textContent = `상태는 표시했지만 최근 작업을 불러오지 못했습니다: ${err.message}`;
  }
  $("jobStatusBody").hidden = false;
}
