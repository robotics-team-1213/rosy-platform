// 관제 콘솔 로봇 실시간 영상(D-801). 사이트 로그인 권한(fleet.read)으로 Fleet이 로봇별 읽기 전용
// 위임을 발급하고, 영상은 MediaMTX가 WHEP로 브라우저에 직접 보낸다(Fleet은 중계하지 않는다).
// 이 변경은 타일마다 SFU 직접 재생이다(최대 6). 사이트 PC 모자이크(MCU)는 후속 변경이다.
// 위임 토큰은 Authorization 헤더로만 보낸다. 패널이 가려지거나 탭이 숨으면 세션을 닫고,
// 다시 보이면 같은 선택으로 연다. 새 화면이 1초 넘게 없으면 경고, 2초 넘으면 영상을 숨긴다.
// 실패한 타일은 "영상 없음"으로 남는다: Fleet 경유 JPEG나 고속 MJPEG는 열지 않는다.

import {createFleetClient} from "/common/fleet-client.js";
import {openRobotCamera} from "/console/assets/app-runtime.js";

export const MAX_TILES = 6;

const LABEL = {
  live: (robot, s) => `${robot} · ${s.fps}fps · ${Math.round(s.ageMs)}ms`,
  stale: (robot, s) => `${robot} · 지연 ${Math.round(s.ageMs)}ms`,
  hidden: (robot) => `${robot} · 영상 숨김(2초 넘게 새 화면 없음)`,
  waiting: (robot) => `${robot} · 첫 화면 대기`,
  connecting: (robot) => `${robot} · 연결 중`,
  lost: (robot) => `${robot} · 영상 없음`,
  closed: (robot) => `${robot} · 중지`,
};

function el(doc, tag, text, attrs = {}) {
  const node = doc.createElement(tag);
  if (text != null) node.textContent = text;
  for (const [name, value] of Object.entries(attrs)) node.setAttribute(name, value);
  return node;
}

export function createRobotVideo({doc = document, call, open = openRobotCamera, fetchImpl}) {
  let sessions = [], running = null;
  const grantPath = (robot, suffix = "") => `/api/fleet/robots/${encodeURIComponent(robot)}/media-grant${suffix}`;

  function show(view, robot, state) {
    view.tile.dataset.state = state.state;
    view.video.hidden = !["live", "stale"].includes(state.state);
    view.label.textContent = (LABEL[state.state] ?? (() => robot))(robot, state);
  }

  async function openTile(stage, robot) {
    const tile = el(doc, "figure", null, {"data-robot-video-tile": robot, "data-state": "connecting"});
    const video = el(doc, "video", null, {"data-robot-video": robot, hidden: ""});
    Object.assign(video, {muted: true, autoplay: true, playsInline: true});
    const label = el(doc, "figcaption", LABEL.connecting(robot));
    tile.append(video, label);
    stage.append(tile);
    const view = {tile, video, label};
    let grant = null;
    try {
      grant = await call(grantPath(robot), {method: "POST"});
      if (running?.stage !== stage) throw new Error("stopped");
      sessions.push(await open({
        grant, video, onState: (state) => show(view, robot, state), ...(fetchImpl ? {fetchImpl} : {}),
        renewGrant: async () => (grant = await call(grantPath(robot, `/${grant.grant_id}/renew`), {method: "POST"})),
        revokeGrant: async () => call(grantPath(robot, `/${grant.grant_id}`), {method: "DELETE"}),
      }));
    } catch (error) {
      show(view, robot, {state: "lost"});
      if (error?.status === 403) label.textContent = `${robot} · 영상 권한 없음`;
      if (grant && error?.message !== "stopped") call(grantPath(robot, `/${grant.grant_id}`), {method: "DELETE"}).catch(() => {});
    }
  }

  return {
    async start(stage, robots) {
      this.stop();
      const picked = [...new Set(robots)].slice(0, MAX_TILES);
      running = {stage, robots: picked};
      stage.dataset.tiles = String(picked.length);
      await Promise.all(picked.map((robot) => openTile(stage, robot)));
    },
    stop() {
      sessions.splice(0).forEach((session) => session.close("stopped"));
      running?.stage.replaceChildren();
      running = null;
    },
    current: () => running,
  };
}

// 화면이 숨거나 패널이 보이지 않으면 세션을 닫고, 다시 보이면 같은 선택으로 연다.
export function bindVisibility({doc = document, target, video, Observer = globalThis.IntersectionObserver}) {
  let wanted = null, onScreen = true;
  const pause = () => { const now = video.current(); if (now) { wanted = now; video.stop(); } };
  const resume = () => {
    if (wanted && onScreen && doc.visibilityState === "visible") { const w = wanted; wanted = null; video.start(w.stage, w.robots); }
  };
  const onVisibility = () => (doc.visibilityState === "hidden" ? pause() : resume());
  doc.addEventListener("visibilitychange", onVisibility);
  const observer = Observer ? new Observer((entries) => entries.forEach((entry) => {
    onScreen = entry.isIntersecting;
    (onScreen ? resume() : pause());
  })) : null;
  observer?.observe(target);
  return () => { doc.removeEventListener("visibilitychange", onVisibility); observer?.disconnect(); };
}

// 콘솔 패널: 사이트 카메라 패널 다음에 붙는다. index.html은 이 모듈을 불러오기만 한다.
export function mountRobotVideoPanel({doc = document} = {}) {
  const anchor = doc.querySelector(".vision-preview");
  if (!anchor || doc.getElementById("robot-video")) return null;
  const link = el(doc, "link", null, {rel: "stylesheet", href: "/console/assets/robot-video.css"});
  doc.head.append(link);
  // 접힌 채 시작한다: 펼치기 전에는 Fleet에 아무것도 묻지 않고(상태 폴링에 요청을 더하지 않는다) 영상도 열지 않는다.
  const panel = el(doc, "details", null, {class: "panel robot-video", id: "robot-video"});
  const heading = el(doc, "summary", "로봇 실시간 영상", {id: "robot-video-heading"});
  const picker = el(doc, "fieldset", null, {"data-robot-video-picker": ""});
  picker.append(el(doc, "legend", `로봇 선택(최대 ${MAX_TILES}대)`));
  const show = el(doc, "button", "영상 보기", {type: "button", "data-robot-video-start": ""});
  const stopButton = el(doc, "button", "중지", {type: "button", "data-robot-video-stop": ""});
  const status = el(doc, "p", "로봇을 고르고 영상 보기를 누르세요.", {class: "hint", role: "status"});
  const stage = el(doc, "div", null, {class: "robot-video-stage", "data-robot-video-stage": ""});
  panel.append(heading, picker, show, stopButton, status, stage);
  anchor.after(panel);

  // console.js와 같은 자격: 로그인 쿠키, 또는 이 탭의 고급 접속 토큰.
  const call = createFleetClient({credential: () => sessionStorage.getItem("rosy-console-token") || ""});
  const video = createRobotVideo({doc, call});
  // 관찰자는 패널이 펼쳐진 동안만 둔다: 접힘·pagehide에서 세션과 관찰자를 모두 정리한다.
  let unbind = null;
  const release = () => { video.stop(); unbind?.(); unbind = null; };

  async function loadRobots() {
    try {
      const snapshot = await call("/api/fleet/state");
      const ids = (snapshot.robots ?? []).map((robot) => robot.robot_id).filter(Boolean);
      picker.replaceChildren(picker.firstChild, ...ids.map((id) => {
        const label = el(doc, "label", null);
        label.append(el(doc, "input", null, {type: "checkbox", value: id, "data-robot-video-choice": id}), ` ${id}`);
        return label;
      }));
    } catch { status.textContent = "로봇 목록을 불러오지 못했습니다."; }
  }
  picker.addEventListener("change", () => {
    const boxes = [...picker.querySelectorAll("input:checked")];
    for (const box of picker.querySelectorAll("input")) {
      box.disabled = !box.checked && boxes.length >= MAX_TILES;
      if (box.disabled) box.setAttribute("reason", `한 번에 ${MAX_TILES}대까지 볼 수 있습니다`);
      else box.removeAttribute("reason");
    }
  });
  show.addEventListener("click", async () => {
    const robots = [...picker.querySelectorAll("input:checked")].map((box) => box.value);
    if (!robots.length) { status.textContent = "로봇을 한 대 이상 고르세요."; return; }
    status.textContent = `${robots.length}대 영상을 엽니다.`;
    await video.start(stage, robots);
  });
  stopButton.addEventListener("click", () => { video.stop(); status.textContent = "영상을 닫았습니다."; });
  panel.addEventListener("toggle", () => {
    if (!panel.open) { release(); return; }
    unbind ??= bindVisibility({doc, target: panel, video});
    loadRobots();
  });
  doc.defaultView?.addEventListener("pagehide", release);
  return {panel, video};
}

if (typeof document !== "undefined" && document.querySelector?.(".vision-preview")) mountRobotVideoPanel();
