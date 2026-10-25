// D-524 / D-530 — 설치·보정 「호스트 서비스」.
// 가드가 이미 읽은 메모리 여유·부하를 보여주고, 닫힌 서비스 제어만 보낸다.
// 프로세스 종료와 로봇 재부팅은 이 화면의 동작이 아니다.

import {HOST_LABEL, stateLabel, resourceText, driftText, gib, hostHealth} from "/console/assets/host-health.js";

function node(tag, className, text) {
  const el = document.createElement(tag);
  if (className) el.className = className;
  if (text !== undefined) el.textContent = text;
  return el;
}

function reportRows(body) {
  return Object.keys(HOST_LABEL).map((name) => {
    let row = body.guard?.[name];
    if (name === "site" && !row && body.drift?.recovery) {
      row = {time: body.drift.time, source: "local", state: body.drift.recovery.state,
        resources: body.drift.recovery.resources, recovery: body.drift.recovery};
    }
    row ||= {};
    const recovery = row.recovery;
    const {current, verified, label, healthy} = hostHealth(row);
    const card = node("section", "install-step");
    card.dataset.host = name;
    card.dataset.state = healthy ? "ok" : "unverified";
    const head = node("div", "robot-head");
    const tag = node("ui-tag", "", label);
    tag.setAttribute("status", healthy ? "ok" : "warn");
    head.append(node("h3", "", HOST_LABEL[name]), tag);
    card.append(head);
    const received = Number.isFinite(row.time) ? new Date(row.time * 1000).toLocaleString() : "없음";
    card.append(node("p", "hint", `마지막 호스트 점검 ${received}`));
    if (current && !["unreachable", "quiet", "error"].includes(row.state)) {
      card.append(node("p", "hint", resourceText(row.resources)));
    }
    if (verified && !["unreachable", "quiet", "error"].includes(row.state)) {
      const watchdog = recovery.watchdog || {};
      const kernel = recovery.kernel || {};
      card.append(node("p", "hint", `워치독 · ${stateLabel(watchdog.state)} · ${watchdog.timeout_s ?? "미확인"}초`));
      card.append(node("p", "hint", `커널 복구 · ${stateLabel(kernel.state)} · 재부팅 ${kernel.panic_s ?? "미확인"}초`));
      card.append(node("p", "hint", `SSH 복구 · ${stateLabel(recovery.ssh?.state)}`));
      const swap = recovery.swap || {};
      card.append(node("p", "hint", `swap · ${stateLabel(swap.state)} · ${gib(swap.used_bytes)} / ${gib(swap.total_bytes)}`));
      card.append(node("p", "hint", `복구 설정 점검 ${new Date(recovery.time * 1000).toLocaleString()}`));
    } else {
      card.append(node("p", "hint", "최신 복구 설정을 확인할 수 없습니다."));
    }
    return card;
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
    const rows = reportRows(body);
    report.replaceChildren(node("p", "hint", driftText(body.drift)), ...rows);
    const hosts = body.hosts || [];
    const key = JSON.stringify(hosts);
    if (key !== commandKey) {
      commandKey = key;
      paintCommands(hosts);
      onPaint?.();
    }
    const allHealthy = rows.every((row) => row.dataset.state === "ok");
    status.textContent = allHealthy ? "PC 3대 정상" : "PC별 점검 결과를 확인하세요";
    status.setAttribute("status", allHealthy ? "ok" : "warn");
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
      if ((host.actions || []).includes("clean-storage")) {
        const clean = node("ui-button", "", "시험 저장소 정리");
        clean.setAttribute("kind", "quiet");
        clean.type = "button";
        clean.addEventListener("click", () => send(host.host, "clean-storage", null, `${HOST_LABEL[host.host] || host.host}의 시험 저장소 정리 서비스를 한 번 실행합니다. 모델·데이터·사용 중 환경은 지우지 않으며, 결과는 다음 점검(최대 10분)의 디스크 여유로 확인합니다.`));
        actions.append(clean);
      }
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
      status.textContent = "호스트 점검 결과를 읽지 못했습니다";
      status.setAttribute("status", "warn");
      report.replaceChildren(node("p", "hint", "연결 실패 · 최신 PC 상태를 확인할 수 없습니다."));
      throw error;
    }
  }

  return {refresh};
}
