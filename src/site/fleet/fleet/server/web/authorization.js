const previousState = new WeakMap();

// D-359 §5.3 — 권한 잠금은 말없이 막지 않는다. 공용 버튼은 필요한 역할을
// reason으로 보인다. 네이티브 입력은 사유를 그릴 자리가 없어 비활성만 받는다.
export const OPERATOR_REASON = "운용자 권한이 필요합니다";

export function applyRoleToControls(role, controls) {
  if (role !== "operator") {
    for (const control of controls) {
      if (!previousState.has(control)) {
        previousState.set(control, {
          disabled: Boolean(control.disabled),
          reason: control.getAttribute("reason"),
        });
      }
      control.disabled = true;
      if (control.localName === "ui-button") control.setAttribute("reason", OPERATOR_REASON);
    }
    return;
  }

  for (const control of controls) {
    if (previousState.has(control)) {
      const previous = previousState.get(control);
      control.disabled = previous.disabled;
      if (previous.reason) control.setAttribute("reason", previous.reason);
      else control.removeAttribute("reason");
      previousState.delete(control);
    }
  }
}
