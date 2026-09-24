// 현장 설정 패널: 로봇 신원, API 토큰, 웨이포인트, 안전 정책, 맵핑 세션, 도크.
//
// 이 모듈은 자기 카드 안의 DOM 만 만지고 셸(app.js)을 import 하지 않는다.
// 패널 밖을 갱신해야 할 때는 셸이 넘겨준 hook 을 부른다 — 그래야 import 순환이
// 생기지 않고, 어느 쪽이 어느 쪽을 아는지가 한 방향으로 고정된다.

import {
  bindFormSave,
  elements,
  fillNumberInput,
  fillSelect,
  fillTextInput,
  number,
  setEnabled,
  setFieldMessage,
  setText,
} from "./dom.js";
import { api, expiryLabel, session, sourceLabel } from "./client.js";

const hooks = {
  // 신원을 바꾸면 헤더의 이름도 따라가야 한다. 그것은 셸의 영역이다.
  onIdentityChanged: () => {},
  // 도킹·SLAM·웨이포인트 명령 뒤에는 로봇 상태를 다시 읽는다.
  refreshRobotState: async () => {},
};

export function initSettings(overrides) {
  Object.assign(hooks, overrides);
}

/** 안전 정책 카드의 입력값. 히어로의 E-Stop 표시는 셸이 그린다. */
export function fillSafetyForm(safety) {
  const limits = safety.limits || {};
  setText("limit-max-linear", Number.isFinite(Number(limits.max_linear)) ? `${number(limits.max_linear, 2)} m/s` : "—");
  setText("limit-max-angular", Number.isFinite(Number(limits.max_angular)) ? `${number(limits.max_angular, 2)} rad/s` : "—");
  fillSelect("fleet-loss-policy", safety.fleet_loss_policy);
  fillNumberInput("limit-manual-linear", limits.manual_linear);
  fillNumberInput("limit-manual-angular", limits.manual_angular);
  const battery = safety.battery || {};
  fillNumberInput("battery-warning", battery.warning_percent);
  fillNumberInput("battery-critical", battery.critical_percent);
  fillNumberInput("battery-deep", battery.deep_percent);
  fillSelect("battery-critical-policy", battery.critical_policy);
}

/** 신원 카드의 입력값. */
export function fillIdentityForm(robotId, robotName) {
  fillTextInput("robot-id-input", robotId);
  fillTextInput("robot-name-input", robotName);
}

export function renderTokens(payload) {
  const list = elements["token-list"];
  if (!list) return;
  const tokens = payload.tokens || [];
  list.replaceChildren();
  if (!tokens.length) {
    const empty = document.createElement("li");
    empty.className = "empty-state";
    empty.textContent = "저장된 토큰이 없습니다.";
    list.append(empty);
    return;
  }
  tokens.forEach((item) => {
    const row = document.createElement("li");
    row.dataset.tokenId = item.id || "";
    const title = document.createElement("strong");
    title.textContent = item.role || "viewer";
    const meta = document.createElement("span");
    const created = item.created_at ? String(item.created_at).slice(0, 10) : "";
    // D-193 6g: source, expiry and "this device" are visible per token.
    const parts = [item.label || item.id || "", sourceLabel(item.source), expiryLabel(item.expires_at), created]
      .filter(Boolean);
    if (item.legacy) parts.push("설정 파일 평문");
    if (item.current) parts.push("이 기기");
    meta.textContent = parts.join(" · ");
    const actions = document.createElement("div");
    actions.className = "waypoint-actions";
    const remove = document.createElement("button");
    remove.type = "button";
    remove.dataset.tokenAction = "delete";
    remove.textContent = "삭제";
    // CORE refuses to delete the token in use; log out from the header instead.
    remove.disabled = item.current === true;
    actions.append(remove);
    row.append(title, meta, actions);
    list.append(row);
  });
}

export async function refreshTokens() {
  if (!isAdmin()) return;
  renderTokens(await api("/api/v1/system/tokens"));
}

export function renderDockingStatus(payload) {
  const supported = payload.supported === true;
  session.dockingSupported = supported;
  const chip = elements["dock-capability"];
  if (chip) {
    chip.dataset.mode = supported ? "AVAILABLE" : "HOLD";
    chip.textContent = supported ? "AVAILABLE" : "HOLD";
  }
  const state = payload.state || "UNDOCKED";
  const dockId = payload.dock_id || "없음";
  const phase = payload.phase ? ` · ${payload.phase}` : "";
  const error = payload.error ? ` · ${payload.error}` : "";
  const hold = supported
    ? ""
    : "이 프로필은 도킹 명령을 지원하지 않습니다. 등록과 teach만 저장됩니다. ";
  setText(
    "dock-status-note",
    `${hold}상태 ${state} · 도크 ${dockId}${phase}${error}`,
  );
  setEnabled("dock-undock", supported);
  setEnabled("dock-cancel", supported);
}

export function renderDocks(payload) {
  const list = elements["dock-list"];
  if (!list) return;
  const docks = payload.docks || [];
  session.docks = docks;
  list.replaceChildren();
  if (!docks.length) {
    const empty = document.createElement("li");
    empty.className = "empty-state";
    empty.textContent = "등록된 도크가 없습니다.";
    list.append(empty);
    return;
  }
  docks.forEach((dock) => {
    const row = document.createElement("li");
    row.dataset.id = dock.id || "";
    const title = document.createElement("strong");
    title.textContent = dock.id || "(id 없음)";
    const meta = document.createElement("span");
    meta.textContent = `${dock.type || "?"} · ${number(dock.x, 2)}, ${number(dock.y, 2)}`;
    const actions = document.createElement("div");
    actions.className = "waypoint-actions";
    const teach = document.createElement("button");
    teach.type = "button";
    teach.dataset.dockAction = "teach";
    teach.textContent = "현재 자리 teach";
    const go = document.createElement("button");
    go.type = "button";
    go.dataset.dockAction = "dock";
    go.textContent = "도킹";
    go.disabled = !session.dockingSupported;
    const remove = document.createElement("button");
    remove.type = "button";
    remove.dataset.dockAction = "delete";
    remove.textContent = "삭제";
    remove.disabled = session.role !== "administrator";
    actions.append(teach, go, remove);
    row.append(title, meta, actions);
    list.append(row);
  });
}

export async function refreshDocks() {
  const [status, docks] = await Promise.all([
    api("/api/v1/docking/status"),
    api("/api/v1/docking/docks"),
  ]);
  renderDockingStatus(status);
  renderDocks(docks);
}

export function renderWaypoints(payload) {
  const list = elements["waypoint-list"];
  if (!list) return;
  const waypoints = payload.waypoints || [];
  session.waypoints = waypoints;
  list.replaceChildren();
  if (!waypoints.length) {
    const empty = document.createElement("li");
    empty.className = "empty-state";
    empty.textContent = "저장된 웨이포인트가 없습니다.";
    list.append(empty);
    return;
  }
  waypoints.forEach((waypoint) => {
    const row = document.createElement("li");
    row.dataset.name = waypoint.name || "";
    const title = document.createElement("strong");
    title.textContent = waypoint.name || "(이름 없음)";
    const meta = document.createElement("span");
    meta.textContent = `${number(waypoint.x, 2)}, ${number(waypoint.y, 2)} · yaw ${number(waypoint.yaw, 2)}`;
    const actions = document.createElement("div");
    actions.className = "waypoint-actions";
    const go = document.createElement("button");
    go.type = "button";
    go.dataset.waypointAction = waypoint.name === "__home__" ? "home" : "go";
    go.textContent = waypoint.name === "__home__" ? "복귀" : "이동";
    const remove = document.createElement("button");
    remove.type = "button";
    remove.dataset.waypointAction = "delete";
    remove.textContent = "삭제";
    actions.append(go, remove);
    row.append(title, meta, actions);
    list.append(row);
  });
}

export async function refreshWaypoints() {
  renderWaypoints(await api("/api/v1/waypoints"));
}

elements["waypoint-save"]?.addEventListener("click", async () => {
  const name = elements["waypoint-name"]?.value.trim();
  const pose = session.robotState?.pose;
  if (!name) {
    setFieldMessage("waypoint-message", "이름을 입력하세요.");
    return;
  }
  if (!pose || !Number.isFinite(Number(pose.x)) || !Number.isFinite(Number(pose.y))) {
    setFieldMessage("waypoint-message", "현재 자세를 아직 받지 못했습니다.");
    return;
  }
  const body = {
    name,
    x: Number(pose.x),
    y: Number(pose.y),
    yaw: Number(pose.yaw) || 0,
    map_id: session.robotState?.map_id || null,
    metadata: {},
  };
  const exists = (session.waypoints || []).some((waypoint) => waypoint.name === name);
  try {
    if (exists) {
      if (!window.confirm(`${name} 웨이포인트를 현재 위치로 덮어쓸까요?`)) return;
      await api(`/api/v1/waypoints/${encodeURIComponent(name)}`, {
        method: "PUT",
        body: JSON.stringify(body),
      });
    } else {
      await api("/api/v1/waypoints", { method: "POST", body: JSON.stringify(body) });
    }
    setFieldMessage("waypoint-message", `${name} 을(를) 저장했습니다.`);
    await refreshWaypoints();
  } catch (error) {
    setFieldMessage("waypoint-message", `저장 실패: ${error.message}`);
  }
});

elements["waypoint-list"]?.addEventListener("click", async (event) => {
  const button = event.target.closest("[data-waypoint-action]");
  const row = event.target.closest("li[data-name]");
  if (!button || !row) return;
  const name = row.dataset.name;
  const action = button.dataset.waypointAction;
  try {
    if (action === "delete") {
      if (!window.confirm(`${name} 웨이포인트를 삭제할까요?`)) return;
      await api(`/api/v1/waypoints/${encodeURIComponent(name)}`, { method: "DELETE" });
      setFieldMessage("waypoint-message", `${name} 을(를) 삭제했습니다.`);
      await refreshWaypoints();
      return;
    }
    if (action === "home") {
      if (!window.confirm("Home으로 복귀할까요? NAVIGATION 모드로 들어갑니다.")) return;
      await api("/api/v1/navigation/home", { method: "POST" });
      setFieldMessage("waypoint-message", "Home 복귀를 요청했습니다.");
      await hooks.refreshRobotState();
      return;
    }
    if (!window.confirm(`${name} 으로 이동할까요? NAVIGATION 모드로 들어갑니다.`)) return;
    await api("/api/v1/navigation/goal", {
      method: "POST",
      body: JSON.stringify({ waypoint: name }),
    });
    setFieldMessage("waypoint-message", `${name} 목표를 전송했습니다.`);
    await hooks.refreshRobotState();
  } catch (error) {
    setFieldMessage("waypoint-message", `웨이포인트 동작 실패: ${error.message}`);
  }
});

elements["limits-save"]?.addEventListener("click", async () => {
  const linear = Number(elements["limit-manual-linear"].value);
  const angular = Number(elements["limit-manual-angular"].value);
  const warning = Number(elements["battery-warning"].value);
  const critical = Number(elements["battery-critical"].value);
  const deep = Number(elements["battery-deep"].value);
  if (!Number.isFinite(linear) || !Number.isFinite(angular) || linear < 0 || angular < 0) {
    setFieldMessage("limits-message", "속도 한계는 0 이상 숫자여야 합니다.");
    return;
  }
  if (![warning, critical, deep].every((value) => Number.isFinite(value) && value > 0 && value <= 100)) {
    setFieldMessage("limits-message", "배터리 임계는 0보다 크고 100 이하여야 합니다.");
    return;
  }
  if (!(deep < critical && critical < warning)) {
    setFieldMessage("limits-message", "배터리 임계는 deep < critical < warning 이어야 합니다.");
    return;
  }
  try {
    const payload = await api("/api/v1/safety/limits", {
      method: "PUT",
      body: JSON.stringify({
        manual_linear: linear,
        manual_angular: angular,
        fleet_loss_policy: elements["fleet-loss-policy"]?.value,
        battery_warning_percent: warning,
        battery_critical_percent: critical,
        battery_deep_percent: deep,
        battery_critical_policy: elements["battery-critical-policy"]?.value,
      }),
    });
    fillSafetyForm(payload);
    setFieldMessage("limits-message", "안전 정책을 적용했고 ~/.rosy/rosy.yaml 에 남겼습니다.");
  } catch (error) {
    setFieldMessage("limits-message", `정책 적용 실패: ${error.message}`);
  }
});

async function runSlam(path, body, successText) {
  try {
    const payload = await api(path, {
      method: "POST",
      body: body ? JSON.stringify(body) : undefined,
    });
    setFieldMessage("slam-message", successText);
    if (payload?.map_id) setText("map-id", `map ${payload.map_id}`);
    await hooks.refreshRobotState();
  } catch (error) {
    setFieldMessage("slam-message", error.message);
  }
}

elements["slam-start"]?.addEventListener("click", () => {
  if (!window.confirm("맵핑 세션을 시작할까요? 세션 중에는 목표 주행이 거부됩니다.")) return;
  runSlam("/api/v1/slam/start", null, "맵핑을 시작했습니다.");
});
elements["slam-stop"]?.addEventListener("click", () => {
  runSlam("/api/v1/slam/stop", null, "맵핑을 중지했습니다.");
});
elements["slam-save"]?.addEventListener("click", () => {
  const name = elements["slam-map-name"]?.value.trim() || "rosy_map";
  if (!window.confirm(`${name} 이름으로 맵을 저장할까요?`)) return;
  runSlam("/api/v1/slam/save", { name }, `${name} 맵을 저장했습니다.`);
});

elements["dock-register"]?.addEventListener("click", async () => {
  const id = elements["dock-id"]?.value.trim();
  const type = elements["dock-type"]?.value.trim() || "rosy_v1";
  if (!id) {
    setFieldMessage("dock-message", "도크 ID를 입력하세요.");
    return;
  }
  try {
    await api("/api/v1/docking/types", {
      method: "POST",
      body: JSON.stringify({ name: type, detector: "simulated" }),
    });
    await api("/api/v1/docking/docks", {
      method: "POST",
      body: JSON.stringify({
        id,
        type,
        x: Number(session.robotState?.pose?.x) || 0,
        y: Number(session.robotState?.pose?.y) || 0,
        yaw: Number(session.robotState?.pose?.yaw) || 0,
        map_id: session.robotState?.map_id || null,
      }),
    });
    setFieldMessage("dock-message", `${id} 을(를) 등록했습니다. 맞물린 자리에서 teach 하세요.`);
    await refreshDocks();
  } catch (error) {
    setFieldMessage("dock-message", `등록 실패: ${error.message}`);
  }
});

elements["dock-list"]?.addEventListener("click", async (event) => {
  const button = event.target.closest("[data-dock-action]");
  const row = event.target.closest("li[data-id]");
  if (!button || !row) return;
  const id = row.dataset.id;
  const action = button.dataset.dockAction;
  try {
    if (action === "delete") {
      if (!window.confirm(`${id} 도크를 삭제할까요?`)) return;
      await api(`/api/v1/docking/docks/${encodeURIComponent(id)}`, { method: "DELETE" });
      setFieldMessage("dock-message", `${id} 을(를) 삭제했습니다.`);
      await refreshDocks();
      return;
    }
    if (action === "teach") {
      if (!window.confirm("지금 선 자리를 이 도크 포즈로 기록할까요?")) return;
      await api(`/api/v1/docking/docks/${encodeURIComponent(id)}/teach`, { method: "POST" });
      setFieldMessage("dock-message", `${id} 포즈를 현재 자리로 기록했습니다.`);
      await refreshDocks();
      return;
    }
    if (!window.confirm(`${id} 로 도킹을 시작할까요?`)) return;
    await api("/api/v1/docking/dock", {
      method: "POST",
      body: JSON.stringify({ dock: id }),
    });
    setFieldMessage("dock-message", `${id} 도킹을 요청했습니다.`);
    await refreshDocks();
    await hooks.refreshRobotState();
  } catch (error) {
    setFieldMessage("dock-message", `도크 동작 실패: ${error.message}`);
  }
});

elements["dock-undock"]?.addEventListener("click", async () => {
  if (!window.confirm("언도크할까요?")) return;
  try {
    await api("/api/v1/docking/undock", { method: "POST" });
    setFieldMessage("dock-message", "언도크를 요청했습니다.");
    await refreshDocks();
    await hooks.refreshRobotState();
  } catch (error) {
    setFieldMessage("dock-message", `언도크 실패: ${error.message}`);
  }
});

elements["dock-cancel"]?.addEventListener("click", async () => {
  try {
    await api("/api/v1/docking/cancel", { method: "POST" });
    setFieldMessage("dock-message", "도킹을 취소했습니다.");
    await refreshDocks();
    await hooks.refreshRobotState();
  } catch (error) {
    setFieldMessage("dock-message", `취소 실패: ${error.message}`);
  }
});

bindFormSave("waypoint-form", "waypoint-save");
bindFormSave("limits-form", "limits-save");
bindFormSave("slam-save-form", "slam-save");
bindFormSave("dock-form", "dock-register");
bindFormSave("identity-form", "identity-save");
bindFormSave("token-form", "token-add");

elements["identity-save"]?.addEventListener("click", async () => {
  const robotName = elements["robot-name-input"]?.value.trim();
  if (!robotName) {
    setFieldMessage("identity-message", "이름을 입력하세요.");
    return;
  }
  try {
    const info = await api("/api/v1/system/info", {
      method: "PUT",
      body: JSON.stringify({ robot_name: robotName }),
    });
    hooks.onIdentityChanged(info);
    setFieldMessage("identity-message", "표시 이름을 저장했습니다.");
  } catch (error) {
    setFieldMessage("identity-message", `신원 저장 실패: ${error.message}`);
  }
});

elements["token-add"]?.addEventListener("click", async () => {
  const token = elements["token-new"]?.value.trim() || "";
  const label = elements["token-label"]?.value.trim() || "";
  const role = elements["token-role"]?.value || "viewer";
  if (token && token.length < 16) {
    setFieldMessage("token-message", "직접 정하는 토큰은 16자 이상이어야 합니다. 비우면 서버가 생성합니다.");
    return;
  }
  const body = token ? { token, role, label } : { role, label };
  try {
    const created = await api("/api/v1/system/tokens", {
      method: "POST",
      body: JSON.stringify(body),
    });
    if (elements["token-new"]) elements["token-new"].value = "";
    if (elements["token-label"]) elements["token-label"].value = "";
    setFieldMessage(
      "token-message",
      created.token
        ? `${created.role} 토큰을 만들었습니다. 지금 옮겨 적으세요 — 다시 볼 수 없습니다: ${created.token}`
        : `${created.role} 토큰을 추가했습니다.`,
    );
    await refreshTokens();
  } catch (error) {
    setFieldMessage("token-message", `토큰 추가 실패: ${error.message}`);
  }
});

elements["token-list"]?.addEventListener("click", async (event) => {
  const button = event.target.closest("[data-token-action='delete']");
  const row = event.target.closest("li[data-token-id]");
  if (!button || !row) return;
  const tokenId = row.dataset.tokenId;
  if (!window.confirm("이 토큰을 삭제할까요? 되돌릴 수 없습니다.")) return;
  try {
    await api(`/api/v1/system/tokens/${encodeURIComponent(tokenId)}`, { method: "DELETE" });
    setFieldMessage("token-message", "토큰을 삭제했습니다.");
    await refreshTokens();
  } catch (error) {
    setFieldMessage("token-message", `토큰 삭제 실패: ${error.message}`);
  }
});
