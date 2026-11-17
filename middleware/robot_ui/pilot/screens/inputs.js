// 입력 조정 칩(D-323 T8). 주행 HUD 에서 연다. 설정은 input-state.js 의
// localStorage 관리를 쓰고, 미리보기는 연결된 게임패드 축의 실시간 매핑이다.

import {inputConfig, saveInputConfig, stickMap} from "../input-state.js";
import {EVIDENCE_LABEL} from "/common/core_ui_logic.js";
import {createChoiceGroup} from "/common/choice-group.js";

export function mountInputs(root, {onClose} = {}) {
  let config = inputConfig();
  let previewNode;
  let previewTimer;
  let closed = false;
  const returnFocus = document.activeElement;
  const closePanel = () => {
    if (closed) return;
    closed = true;
    clearInterval(previewTimer);
    root.removeEventListener("keydown", onKey);
    onClose?.();
    if (returnFocus?.isConnected && returnFocus.getClientRects().length) returnFocus.focus();
  };
  const onKey = (event) => {
    if (event.key === "Escape") { event.stopPropagation(); closePanel(); }
  };
  root.setAttribute("role", "region");
  root.setAttribute("aria-label", "조종 입력 설정");
  root.addEventListener("keydown", onKey);

  function render() {
    const head = el("ui-head", "입력 조정");
    const grid = el("ui-grid", null, {columns: "1"});

    const deadLabel = el("ui-text", `데드존 ${Number(config.deadzone ?? 0.12).toFixed(2)}`, {scale: "label"});
    const dead = el("input", null, {type: "range", min: "0", max: "0.6", step: "0.02",
                                    "aria-label": "데드존", value: String(config.deadzone ?? 0.12)});
    dead.classList.add("ui-field");
    dead.addEventListener("input", () => {
      config = saveInputConfig({deadzone: Number(dead.value)});
      deadLabel.textContent = `데드존 ${Number(config.deadzone).toFixed(2)}`;
    });
    const deadCell = el("div");
    deadCell.append(deadLabel, dead, el("p", "중앙 부근의 작은 움직임을 무시합니다. 값이 클수록 더 움직여야 반응합니다."));

    // K1: 감도 곡선은 폼 밖 즉시 효과의 짧은 배타 선택. 속도 프리셋은 조작부(drive.js)에 한 곳만 둔다(S2).
    const curves = createChoiceGroup({id: "input-curve", label: "감도 곡선", mode: "single", value: config.curve,
      items: [{value: "linear", label: "직선"}, {value: "expo", label: "중앙 섬세"}],
      onChange: (name) => { config = saveInputConfig({curve: name}); }});
    const curveCell = el("div");
    curveCell.append(curves.element);

    // K21: 독립 켜기·끄기 하나. 보이는 라벨은 바뀌지 않고 aria-pressed 가 상태를 말한다.
    const invertButton = el("ui-button", "조향 반전", {type: "button", "aria-pressed": String(Boolean(config.invertAngular))});
    invertButton.setAttribute("kind", "toggle");
    invertButton.addEventListener("click", () => {
      config = saveInputConfig({invertAngular: !config.invertAngular});
      invertButton.setAttribute("aria-pressed", String(Boolean(config.invertAngular)));
    });
    const invertCell = el("div");
    invertCell.append(invertButton);

    grid.append(deadCell, curveCell, invertCell);

    const previewLabel = el("ui-text", "게임패드 입력 미리보기", {scale: "label"});
    const preview = el("ui-text", EVIDENCE_LABEL.unavailable, {scale: "value", "data-input-preview": ""});

    const close = el("ui-button", "닫기", {type: "button"});
    close.setAttribute("kind", "quiet");
    close.addEventListener("click", closePanel);

    root.replaceChildren(head, el("p", "설정은 바로 저장됩니다. 미리보기만으로 로봇은 움직이지 않습니다."), grid, previewLabel, preview, close);
    previewNode = preview;
    return dead;
  }

  render().focus();
  previewTimer = setInterval(() => {
    const pad = navigator.getGamepads ? [...navigator.getGamepads()].find(Boolean) : null;
    if (!pad) {
      previewNode.textContent = "게임패드 미연결";
      return;
    }
    const raw = {x: pad.axes[0] ?? 0, y: -(pad.axes[1] ?? 0)};
    const mapped = stickMap({kind: "pad", ...raw});
    previewNode.textContent =
      `입력 (${raw.x.toFixed(2)}, ${raw.y.toFixed(2)}) · 전후 ${mapped.linear.toFixed(3)} m/s · 회전 ${mapped.angular.toFixed(3)} rad/s${mapped.pivot ? " (제자리)" : ""}`;
  }, 250);
  // 부모(주행 화면)가 나갈 때 미리보기 타이머까지 거둘 수 있게 닫기 함수를 돌려준다.
  return closePanel;
}

function el(tag, text, attrs = {}) {
  const node = document.createElement(tag);
  if (text !== undefined && text !== null) node.textContent = text;
  for (const [name, value] of Object.entries(attrs)) node.setAttribute(name, value);
  return node;
}
