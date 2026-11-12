// D-991 /console/maintenance — Fleet 데이터베이스 상태·설정·자체 시험 패널.

function node(tag, className, text) {
  const el = document.createElement(tag);
  if (className) el.className = className;
  if (text !== undefined) el.textContent = text;
  return el;
}

function mib(bytes) {
  if (!Number.isFinite(bytes)) return "미확인";
  return `${(bytes / (1024 * 1024)).toFixed(2)} MiB`;
}

const SETTING_FIELDS = [
  ["history_retention_days", "작업 이력 보존 일수 (0=무제한)", 0, 3650, 30],
  ["audit_retention_days", "장치·코어 감사 보존 일수", 0, 3650, 90],
  ["api_audit_retention_days", "API 감사 보존 일수", 0, 3650, 90],
  ["sighting_retention_days", "관측 이력 보존 일수", 0, 3650, 90],
  ["wal_autocheckpoint_pages", "WAL 자동 체크포인트 페이지", 100, 100000, 1000],
  ["incremental_vacuum_pages", "증분 공간 회수 페이지", 0, 10000, 256],
];

const ACTIONS = [
  ["self-test", "DB 자체 시험 실행"],
  ["checkpoint", "WAL 체크포인트"],
  ["incremental-vacuum", "증분 공간 회수"],
  ["flush-audit", "감사 로그 아카이브 플러시"],
  ["prune-expired", "만료 이력 정리"],
];

export function createDbMaintenance({root, call}) {
  const status = root.querySelector("#db-maintenance-status");
  const report = root.querySelector("#db-maintenance-report");
  const actionsBox = root.querySelector("#db-maintenance-actions");
  const settingsBox = root.querySelector("#db-maintenance-settings");
  const note = root.querySelector("#db-maintenance-note");
  let lastActionResult = null;
  let actionsRendered = false;

  function say(text, state) {
    note.textContent = text;
    note.hidden = !text;
    if (state) note.setAttribute("state", state);
  }

  function paintReport(body) {
    const fleet = body.fleet || {};
    const pg = body.postgres || {};
    const backup = body.backups?.fleet || {};
    const archive = body.audit_archive || {};

    const sqliteCard = node("section", "install-step");
    sqliteCard.append(
      node("h3", "", "Fleet SQLite 원장"),
      node("p", "hint", `저널 모드 · ${fleet.journal_mode || "미설정"} · 크기 ${mib(fleet.size_bytes)} · WAL ${mib(fleet.wal_bytes)}`),
      node("p", "hint", `페이지 ${fleet.page_count ?? 0}개 (${fleet.page_size ?? 0}B) · 빈 페이지 ${fleet.freelist_count ?? 0}개 · 단편화 ${fleet.fragmentation_pct ?? 0}%`),
    );

    const pgCard = node("section", "install-step");
    const pgState = !pg.configured ? "미설정" : pg.reachable ? `연결됨 (${mib(pg.database_size_bytes)})` : "연결 실패";
    pgCard.append(
      node("h3", "", "PostgreSQL 감사 아카이브 · 백업"),
      node("p", "hint", `PostgreSQL 상태 · ${pgState} · 미전송 감사 행 ${archive.pending_rows ?? 0}건`),
      node("p", "hint", `마지막 아카이브 커서 #${archive.last_rowid ?? 0} · 시각 ${archive.flushed_at || "없음"}`),
      node("p", "hint", `원장 백업 · ${backup.count ?? 0}개 · 최신 경과 ${backup.newest_age_hours != null ? `${backup.newest_age_hours}시간` : "없음"}`),
    );

    const children = [sqliteCard, pgCard];
    if (lastActionResult) {
      const resultCard = node("section", "install-step");
      resultCard.append(node("h3", "", `최근 정비 실행 결과 (${lastActionResult.action})`));
      if (lastActionResult.action === "self-test" && lastActionResult.checks) {
        for (const [name, detail] of Object.entries(lastActionResult.checks)) {
          resultCard.append(node("p", "hint", `${name} · ${detail.ok ? "통과" : "실패"}`));
        }
      } else {
        resultCard.append(node("p", "hint", JSON.stringify(lastActionResult)));
      }
      children.push(resultCard);
    }
    report.replaceChildren(...children);

    const warn = (fleet.wal_bytes || 0) > 67108864 || (fleet.fragmentation_pct || 0) > 25 || (pg.configured && !pg.reachable);
    const ok = Boolean(fleet.configured) && fleet.journal_mode === "wal" && !warn;
    status.textContent = ok ? "정상" : warn ? "주의" : "점검 필요";
    status.setAttribute("status", ok ? "ok" : "warn");
  }

  function paintActions() {
    if (actionsRendered) return;
    actionsRendered = true;
    const block = node("section", "install-step");
    block.append(node("h3", "", "온라인 정비 및 자체 시험"));
    const row = node("ui-actions");
    for (const [action, label] of ACTIONS) {
      const btn = node("ui-button", "", label);
      btn.setAttribute("kind", "quiet");
      btn.type = "button";
      btn.dataset.dbAction = action;
      btn.addEventListener("click", () => runAction(action, label));
      row.append(btn);
    }
    block.append(row);
    actionsBox.replaceChildren(block);
  }

  function paintSettings(settings = {}) {
    const form = node("form", "install-step");
    form.append(node("h3", "", "데이터베이스 보존·체크포인트 설정"));
    const inputs = {};
    for (const [key, label, min, max, fallback] of SETTING_FIELDS) {
      const wrap = node("label", "field-row");
      wrap.append(node("span", "", label));
      const input = node("input", "ui-field");
      input.type = "number";
      input.name = key;
      input.min = String(min);
      input.max = String(max);
      input.value = String(settings[key] ?? fallback);
      wrap.append(input);
      form.append(wrap);
      inputs[key] = input;
    }
    const actions = node("ui-actions");
    const save = node("ui-button", "", "DB 설정 저장");
    save.setAttribute("kind", "primary");
    save.type = "submit";
    actions.append(save);
    form.append(actions);
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const body = {};
      for (const [key] of SETTING_FIELDS) body[key] = Number.parseInt(inputs[key].value, 10);
      try {
        await call("/api/fleet/admin/db-settings", {method: "PUT", body});
        say("데이터베이스 설정을 저장했습니다.", "ok");
        await refresh();
      } catch (error) {
        say(`데이터베이스 설정 저장 실패 (${error.detail?.code || error.code || error.status || "오류"})`, "error");
      }
    });
    settingsBox.replaceChildren(form);
  }

  async function runAction(action, label) {
    say("");
    try {
      const answer = await call("/api/fleet/admin/db-maintenance", {method: "POST", body: {action}});
      lastActionResult = answer;
      say(`${label} 완료 (${answer.ok ? "정상" : answer.error || "점검 필요"})`, answer.ok ? "ok" : "error");
      await refresh();
    } catch (error) {
      say(`${label} 거절 (${error.detail?.code || error.code || error.status || "오류"})`, "error");
    }
  }

  async function refresh() {
    try {
      const body = await call("/api/fleet/admin/db-status");
      paintReport(body);
      paintActions();
      paintSettings(body.settings || {});
    } catch (error) {
      if (error.status === 403 || error.detail?.code === "ACCOUNT_ADMIN_REQUIRED" || error.code === "ACCOUNT_ADMIN_REQUIRED") {
        status.textContent = "권한 필요";
        status.setAttribute("status", "neutral");
        report.replaceChildren(node("p", "hint", "데이터베이스 설정과 자체 시험은 계정 관리자(accounts.manage) 로그인 세션이 필요합니다."));
        actionsBox.replaceChildren();
        settingsBox.replaceChildren();
        actionsRendered = false;
        return;
      }
      status.textContent = "점검 실패";
      status.setAttribute("status", "warn");
      report.replaceChildren(node("p", "hint", "데이터베이스 상태를 읽지 못했습니다."));
    }
  }

  return {refresh};
}
