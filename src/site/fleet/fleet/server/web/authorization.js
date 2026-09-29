const previousState = new WeakMap();

// D-359 §5.3 — 권한 잠금은 말없이 막지 않는다. 공용 버튼은 필요한 역할을
// reason으로 보인다. 네이티브 입력은 사유를 그릴 자리가 없으므로, 입력을 담은
// [data-role-lock] 묶음의 보이는 공용 안내(.role-lock-note)를 켜고 aria-describedby로 잇는다.
export const OPERATOR_REASON = "운용자 권한이 필요합니다";

function lockNote(control) {
  return control.closest?.("[data-role-lock]")?.querySelector(".role-lock-note") || null;
}

function describe(control, id, on) {
  const ids = (control.getAttribute("aria-describedby") || "").split(/\s+/).filter((item) => item && item !== id);
  if (on) ids.push(id);
  if (ids.length) control.setAttribute("aria-describedby", ids.join(" "));
  else control.removeAttribute("aria-describedby");
}

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
      if (control.localName === "ui-button") {
        control.setAttribute("reason", OPERATOR_REASON);
        continue;
      }
      const note = lockNote(control);
      if (note) {
        note.hidden = false;
        describe(control, note.id, true);
      }
    }
    return;
  }

  for (const control of controls) {
    if (previousState.has(control)) {
      const previous = previousState.get(control);
      control.disabled = previous.disabled;
      if (previous.reason) control.setAttribute("reason", previous.reason);
      else control.removeAttribute("reason");
      const note = lockNote(control);
      if (note) {
        note.hidden = true;
        describe(control, note.id, false);
      }
      previousState.delete(control);
    }
  }
}
