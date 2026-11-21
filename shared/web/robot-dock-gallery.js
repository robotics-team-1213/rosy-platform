// Component-gallery binder for C23 robot dock + C24 robot panel.
import {robotProfile} from "./robot-profile.js";
import {createSelection} from "./selection.js";
import {createRobotDock} from "./robot-dock.js";
import {createRobotPanel} from "./robot-panel.js";

const DEMO_SPECS = [
  {
    id: "rosy_42",
    kind: "mobile",
    online: true,
    ageS: 1,
    battery: {percent: 72, charging: false},
    estop: false,
    alarm: {level: "caution", text: "위치 모름"},
    task: "대기",
    detail: {
      locationText: "모름",
      evidence: "Fleet 보고 · 1초 전",
      cameraId: "pinky_42_front",
      cameraStamp: "최신 사진 · 2초 전",
      poseReport: "꺼짐",
      limit: "속도 0.2 m/s",
    },
  },
  {
    id: "rosy_45",
    kind: "mobile",
    online: true,
    ageS: 12,
    battery: {percent: 64, charging: false},
    estop: false,
    task: "대기",
    detail: {
      locationText: "대기 구역",
      evidence: "Fleet 보고 · 12초 전",
      cameraId: "pinky_45_front",
      cameraStamp: "지연 사진 · 12초 전",
      poseReport: "켜짐",
      limit: "속도 0.2 m/s",
    },
  },
  {
    id: "rosy_46",
    kind: "mobile",
    online: true,
    ageS: 1,
    battery: {percent: 88, charging: false},
    estop: false,
    task: "대기",
    detail: {
      locationText: "충전 거치대",
      evidence: "Fleet 보고 · 1초 전",
      cameraId: "pinky_46_front",
      cameraStamp: "최신 사진 · 1초 전",
      poseReport: "켜짐",
      limit: "속도 0.2 m/s",
    },
  },
  {
    id: "arm_s",
    kind: "arm",
    online: true,
    ageS: 1,
    torque: true,
    servo: {currentMa: 120, temperatureC: 38},
    place: "셀 S",
    alarm: {level: "caution", text: "홀드 중"},
    task: "대기",
    detail: {
      holdText: "홀드 중",
      evidence: "Fleet 보고 · 1초 전",
      cameraId: "arm_s_top, arm_s_wrist",
      cameraStamp: "최신 사진 · 1초 전",
      objects: "상자 소형, 상자 중형",
      commandCause: "홀드 중 · 해제는 현장 사람",
    },
  },
  {
    id: "arm_a",
    kind: "arm",
    online: true,
    ageS: 1,
    torque: true,
    servo: {currentMa: 110, temperatureC: 34},
    place: "셀 A",
    task: "대기",
    detail: {
      holdText: "없음",
      evidence: "Fleet 보고 · 1초 전",
      cameraId: "arm_a_top, arm_a_wrist",
      cameraStamp: "최신 사진 · 1초 전",
      objects: "상자 소형",
      commandCause: "현장 작업 화면에서만 보냄",
    },
  },
  {
    id: "arm_b",
    kind: "arm",
    online: false,
    ageS: 95,
    torque: false,
    place: "셀 B",
    task: "대기",
    detail: {
      holdText: "모름",
      evidence: "연결 끊김 · 95초 전",
      cameraId: "arm_b_top, arm_b_wrist",
      cameraStamp: "연결 끊김 · 95초 전",
      objects: "상자 소형",
      commandCause: "연결 끊김 · 현장 전원 확인",
    },
  },
];

function textEl(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text != null) node.textContent = text;
  return node;
}

function uiBtn(kind, label, {disabled = false, describedBy = "", onClick = null} = {}) {
  const btn = document.createElement("ui-button");
  if (kind === "primary") btn.setAttribute("kind", "primary");
  else if (kind === "toggle") btn.setAttribute("kind", "toggle");
  else btn.setAttribute("kind", "quiet");
  btn.setAttribute("type", "button");
  btn.textContent = label;
  if (disabled) btn.setAttribute("disabled", "");
  if (describedBy) btn.setAttribute("aria-describedby", describedBy);
  if (onClick) btn.addEventListener("click", onClick);
  return btn;
}

function kvList(rows) {
  const dl = textEl("dl", "robot-panel-kv");
  for (const [k, v, ev] of rows) {
    dl.append(textEl("dt", "", k), textEl("dd", "", v));
    if (ev) dl.append(textEl("dd", "robot-panel-ev", ev));
  }
  return dl;
}

function pinkySections() {
  return {
    status: (p, d = {}) => kvList([
      ["연결", p.link.text, d.evidence],
      ["배터리", p.power.text],
      ["위치", d.locationText || "모름", d.evidence],
      ["작업", p.task.text],
    ]),
    camera: (_p, d = {}) => {
      const box = textEl("div", "robot-panel-cam", "카메라 화면 (자리표시)");
      box.append(textEl("span", "robot-panel-cam-stamp", d.cameraStamp || "사진 없음"));
      return box;
    },
    commands: (p) => {
      const wrap = textEl("div", "ui-control-stack");
      const actions = document.createElement("ui-actions");
      const causeId = `robot-panel-cause-${p.id}`;
      actions.append(
        uiBtn("primary", "위치 다시 찾기"),
        uiBtn("quiet", "위치 찍기"),
        uiBtn("quiet", "한 바퀴"),
        uiBtn("quiet", "앞 10 cm", {disabled: true, describedBy: causeId}),
        uiBtn("quiet", "뒤 10 cm", {disabled: true, describedBy: causeId}),
      );
      const cause = textEl("p", "robot-panel-cause", "앞·뒤 이동 불가 · 위치 보고가 꺼져 있음");
      cause.id = causeId;
      wrap.append(actions, cause);
      return wrap;
    },
    settings: (_p, d = {}) => kvList([
      ["카메라", d.cameraId || "없음"],
      ["위치 보고", d.poseReport || "모름"],
      ["한계", d.limit || "없음"],
    ]),
  };
}

function armSections() {
  return {
    status: (p, d = {}) => kvList([
      ["토크", p.power.torque === true ? "켜짐" : p.power.torque === false ? "꺼짐" : "모름", d.evidence],
      ["홀드", d.holdText || "모름", d.evidence],
      ["셀", p.place.text],
    ]),
    camera: (_p, d = {}) => {
      const wrap = textEl("div", "ui-control-stack");
      const box = textEl("div", "robot-panel-cam", "팔 카메라 (자리표시)");
      box.append(textEl("span", "robot-panel-cam-stamp", d.cameraStamp || "사진 없음"));
      const actions = document.createElement("ui-actions");
      for (const view of (d.cameraViews || ["상단", "손목"])) {
        const b = uiBtn("toggle", view);
        b.setAttribute("aria-pressed", view === "상단" ? "true" : "false");
        b.addEventListener("click", () => {
          for (const sib of actions.querySelectorAll("ui-button")) {
            sib.setAttribute("aria-pressed", sib === b ? "true" : "false");
          }
        });
        actions.append(b);
      }
      wrap.append(box, actions);
      return wrap;
    },
    commands: (p, d = {}, links = {}) => {
      const wrap = textEl("div", "ui-control-stack");
      const actions = document.createElement("ui-actions");
      const causeId = `robot-panel-cause-${p.id}`;
      const link = textEl("a", "ui-action-link", "작업 화면에서 승인·재개");
      link.dataset.kind = "quiet";
      link.href = links.taskRow ? links.taskRow(`demo-${p.id}`) : "#robot-dock";
      actions.append(
        uiBtn("quiet", "이송 제안 보내기", {disabled: true, describedBy: causeId}),
        uiBtn("quiet", "작업 취소", {disabled: true, describedBy: causeId}),
        link,
      );
      const cause = textEl("p", "robot-panel-cause", d.commandCause || "홀드 중 · 해제는 현장 사람");
      cause.id = causeId;
      wrap.append(actions, cause);
      return wrap;
    },
    settings: (p, d = {}) => kvList([
      ["셀", p.place.text],
      ["카메라", d.cameraId || "없음"],
      ["지원 물체", d.objects || "모름"],
    ]),
  };
}

export function mountRobotDockDemo(container) {
  if (!container) return null;
  const records = DEMO_SPECS.map((spec) => ({
    profile: robotProfile(spec),
    detail: spec.detail,
  }));
  const byId = new Map(records.map((r) => [r.profile.id, r]));
  const resolve = (id) => byId.get(id) ?? null;

  const selection = createSelection(null);
  const pinky = pinkySections();
  const arm = armSections();
  const pickSections = (p) => (p.kind === "arm" ? arm : pinky);

  let dock;
  const panel = createRobotPanel({
    selection,
    resolve,
    stopButton: document.getElementById("robot-panel-stop"),
    links: {taskRow: taskId => `#robot-dock?task=${encodeURIComponent(taskId)}`},
    onClose: () => dock.setOpen(null),
    sections: {
      status: (p, d) => pickSections(p).status(p, d),
      camera: (p, d) => pickSections(p).camera(p, d),
      commands: (p, d, l) => pickSections(p).commands(p, d, l),
      settings: (p, d) => pickSections(p).settings(p, d),
    },
    stop: (p) => (p.kind === "arm"
      ? {note: "팔 단독 정지 없음 · 위 머리의 전체 비상 정지를 쓴다"}
      : {
          label: "주행 취소 · 이 로봇",
          onStop: () => {
            const out = document.getElementById("robot-dock-result");
            if (out) {
              out.setAttribute("state", "ready");
              out.textContent = "취소 요청 견본";
            }
          },
        }),
  });

  dock = createRobotDock({
    selection,
    profiles: records.map((r) => r.profile),
    onToggle: (id) => {
      const found = id ? resolve(id) : null;
      panel.setRobot(found?.profile ?? null, found?.detail);
    },
  });

  const stageMain = textEl("div", "robot-stage-main");
  const mapBox = textEl("section", "robot-demo-map");
  mapBox.setAttribute("aria-label", "지도 자리표시");
  const mapList = textEl("div", "robot-demo-map-list");
  const mapButtons = records.map(({profile}) => {
    const btn = textEl("button", "robot-demo-map-btn", profile.id);
    btn.type = "button";
    btn.dataset.demoMapRobot = profile.id;
    btn.addEventListener("click", () => selection.set(profile.id, {source: "map"}));
    mapList.append(btn);
    return btn;
  });
  const syncMapSelection = (selectedId) => {
    for (const btn of mapButtons) {
      if (btn.dataset.demoMapRobot === selectedId) btn.setAttribute("data-selected", "");
      else btn.removeAttribute("data-selected");
    }
  };
  const offSelection = selection.subscribe(syncMapSelection);
  mapBox.append(
    textEl("h3", "", "지도 (자리표시)"),
    mapList,
    textEl("p", "robot-demo-note", "지도 클릭은 선택만 바꾼다. 도크 버튼을 누르면 패널이 열린다."),
  );
  stageMain.append(mapBox);

  const stage = textEl("div", "robot-stage");
  stage.append(panel.root, stageMain, dock.root);
  container.replaceChildren(stage);

  return {
    selection,
    dock,
    panel,
    dispose() {
      offSelection();
      dock.dispose();
      panel.dispose();
    },
  };
}
