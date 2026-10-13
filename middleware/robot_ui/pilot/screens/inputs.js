// 입력 조정 칩(D-323 T8). 주행 HUD 에서 연다. 설정은 input-state.js 의
// localStorage 관리를 쓰고, 미리보기는 연결된 게임패드 축의 실시간 매핑이다.

import {inputConfig, saveInputConfig, stickMap} from "../input-state.js";

export function mountInputs(root, {onClose, onChange} = {}) {
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

    const presetCell = el("div");
    presetCell.append(el("ui-text", "속도 프리셋", {scale: "label"}));
    const presets = el("ui-actions");
    for (const [name, label] of [["low", "저속"], ["mid", "보통"], ["high", "빠름"]]) {
      const button = el("ui-button", label, {type: "button", "aria-pressed": String(config.preset === name)});
      button.setAttribute("kind", "segment");
      button.addEventListener("click", () => {
        config = saveInputConfig({preset: name});
        onChange?.();
        render();
      });
      presets.append(button);
    }
    presetCell.append(presets);

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

    const curveCell = el("div");
    curveCell.append(el("ui-text", "감도 곡선", {scale: "label"}));
    const curves = el("ui-actions");
    for (const [name, label] of [["linear", "직선"], ["expo", "중앙 섬세"]]) {
      const button = el("ui-button", label, {type: "button", "aria-pressed": String(config.curve === name)});
      button.setAttribute("kind", "segment");
      button.addEventListener("click", () => {
        config = saveInputConfig({curve: name});
        render();
      });
      curves.append(button);
    }
    curveCell.append(curves);

    const invertButton = el("ui-button", config.invertAngular ? "반전 켜짐" : "반전 꺼짐",
      {type: "button", "aria-pressed": String(Boolean(config.invertAngular))});
    invertButton.setAttribute("kind", "segment");
    invertButton.addEventListener("click", () => {
      config = saveInputConfig({invertAngular: !config.invertAngular});
      render();
    });
    const invertCell = el("div");
    invertCell.append(el("ui-text", "조향 반전", {scale: "label"}), invertButton);

    grid.append(presetCell, deadCell, curveCell, invertCell);

    const previewLabel = el("ui-text", "게임패드 입력 미리보기", {scale: "label"});
    const preview = el("ui-text", "—", {scale: "value", "data-input-preview": ""});

    const close = el("ui-button", "닫기", {type: "button"});
    close.setAttribute("kind", "quiet");
    close.addEventListener("click", closePanel);

    root.replaceChildren(head, el("p", "설정은 바로 저장됩니다. 미리보기만으로 로봇은 움직이지 않습니다."), grid, previewLabel, preview, close);
    previewNode = preview;
    return preview;
  }

  render();
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
