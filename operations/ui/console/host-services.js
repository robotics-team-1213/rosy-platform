// D-524 / D-530 — 설치·보정 「호스트 서비스」.
// 가드가 이미 읽은 메모리 여유·부하를 보여주고, 닫힌 서비스 제어만 보낸다.
// 프로세스 종료와 로봇 재부팅은 이 화면의 동작이 아니다.

const STATE_LABEL = {
  ok: "정상",
  bad: "나쁨",
  "load-high": "부하 높음",
  unreachable: "응답 없음",
  quiet: "새벽 창",
  error: "확인 실패",
};

const HOST_LABEL = {site: "관제 PC", ai: "AI PC", model: "모델 PC"};

function node(tag, className, text) {
  const el = document.createElement(tag);
  if (className) el.className = className;
  if (text !== undefined) el.textContent = text;
  return el;
}

function stateLabel(state) {
  return STATE_LABEL[state] || state || "확인 불가";
}

function resourceText(resources) {
  if (!resources || typeof resources !== "object") return "여유 수치 없음";
  const parts = [];
  if (Number.isFinite(resources.avail_pct)) parts.push(`메모리 여유 ${resources.avail_pct}%`);
  if (Number.isFinite(resources.swap_pct)) parts.push(`스왑 ${resources.swap_pct}%`);
  if (Number.isFinite(resources.load) && Number.isFinite(resources.cores)) {
    parts.push(`부하 ${resources.load}/${resources.cores}코어`);
  }
  if (Number.isFinite(resources.uptime_s)) parts.push(`가동 ${resources.uptime_s}초`);
  if (Array.isArray(resources.down) && resources.down.length) {
    parts.push(`멈춘 유닛 ${resources.down.join(", ")}`);
  }
  return parts.length ? parts.join(" · ") : "여유 수치 없음";
}

function driftText(drift) {
  if (!drift) return "바라는 상태 확인 불가";
  const driftN = (drift.drift || []).length;
  const errorN = (drift.errors || []).length;
  const waitN = (drift.awaiting_approval || []).length;
  if (!driftN && !errorN) {
    return waitN ? `바라는 상태 차이 없음 · 승인 대기 ${waitN}` : "바라는 상태 차이 없음";
  }
  return `바라는 상태 차이 ${driftN} · 오류 ${errorN} · 승인 대기 ${waitN}`;
}

function guardRows(guard) {
  if (!guard) return [node("p", "hint", "가드 보고 없음. 관제 PC의 rosy-host-guard가 아직 남긴 파일이 없습니다.")];
  return Object.keys(guard).sort().map((name) => {
    const row = guard[name] || {};
    const line = node("p", "hint");
    line.append(node("strong", "", `${name} · ${stateLabel(row.state)} `));
    line.append(document.createTextNode(resourceText(row.resources)));
    return line;
  });
}

export function createHostServices({root, call, confirmIrreversible, onPaint}) {
  const status = root.querySelector("#host-services-status");
  const report = root.querySelector("#host-services-report");
  const commands = root.querySelector("#host-services-commands");
  const note = root.querySelector("#host-services-note");
  let commandKey = "";

  function say(text, state) {
    note.textContent = text;
    note.hidden = !text;
    if (state) note.setAttribute("state", state);
  }

  function paint(body) {
    report.replaceChildren(node("p", "hint", driftText(body.drift)), ...guardRows(body.guard));
    const hosts = body.hosts || [];
    const key = JSON.stringify(hosts);
    if (key !== commandKey) {
      commandKey = key;
      paintCommands(hosts);
      onPaint?.();
    }
    const sawGuard = Boolean(body.guard) && typeof body.guard === "object";
    status.textContent = sawGuard ? "호스트 여유를 읽었습니다" : "가드 보고 없음";
    status.setAttribute("status", sawGuard ? "ok" : "neutral");
  }

  function paintCommands(hosts) {
    commands.replaceChildren();
    for (const host of hosts) {
      const block = node("section", "install-step");
      block.append(node("h3", "", HOST_LABEL[host.host] || host.host));
      const actions = node("ui-actions");
      const reboot = node("ui-button", "", "10분 뒤 재부팅");
      reboot.setAttribute("kind", "quiet");
      reboot.type = "button";
      reboot.addEventListener("click", () => send(host.host, "reboot", null, `${HOST_LABEL[host.host] || host.host}를 10분 뒤에 재부팅합니다. 그 전에 취소할 수 있습니다.`));
      const cancel = node("ui-button", "", "재부팅 취소");
      cancel.setAttribute("kind", "quiet");
      cancel.type = "button";
      cancel.addEventListener("click", () => send(host.host, "cancel-reboot", null, `${HOST_LABEL[host.host] || host.host}에 예약된 이 재부팅만 취소합니다.`));
      actions.append(reboot, cancel);
      block.append(actions);
      for (const unit of host.units || []) {
        const row = node("ui-actions");
        const restart = node("ui-button", "", `${unit} 다시 시작`);
        restart.setAttribute("kind", "quiet");
        restart.type = "button";
        restart.addEventListener("click", () => send(host.host, "restart-unit", unit, `${unit}을 다시 시작합니다.`));
        row.append(restart);
        if ((host.stoppable_units || []).includes(unit)) {
          const stop = node("ui-button", "", `${unit} 정지`);
          stop.setAttribute("kind", "quiet");
          stop.type = "button";
          stop.addEventListener("click", () => send(host.host, "stop-unit", unit, `${unit}을 멈춥니다. 관제 PC의 Docker·스택·방화벽은 여기서 멈추지 않습니다.`));
          row.append(stop);
        }
        block.append(row);
      }
      commands.append(block);
    }
  }

  async function send(host, action, unit, message) {
    const confirmed = await confirmIrreversible({message, action: "실행"});
    if (!confirmed) return;
    say("");
    try {
      const answer = await call("/api/fleet/hosts/" + encodeURIComponent(host) + "/control", {
        method: "POST",
        body: {action, unit, operator_confirmed: true},
      });
      say(`${HOST_LABEL[host] || host} ${action} 접수 (${answer.code || "ACCEPTED"})`, "ok");
    } catch (error) {
      const code = error.detail?.code || error.code || "";
      say(code === "OPERATOR_IDENTITY_REQUIRED"
        ? "이름 있는 운영자만 호스트를 제어할 수 있습니다."
        : `제어가 거절되었습니다. ${code}`.trim(), "error");
    }
  }

  async function refresh() {
    try {
      paint(await call("/api/fleet/hosts"));
    } catch (error) {
      if (status.getAttribute("status") !== "ok") {
        status.textContent = "호스트 여유를 읽지 못했습니다";
        status.setAttribute("status", "error");
      }
      throw error;
    }
  }

  return {refresh};
}
