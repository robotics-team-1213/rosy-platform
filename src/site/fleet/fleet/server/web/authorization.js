const previousDisabled = new WeakMap();

export function applyRoleToControls(role, controls) {
  if (role !== "operator") {
    for (const control of controls) {
      if (!previousDisabled.has(control)) {
        previousDisabled.set(control, Boolean(control.disabled));
      }
      control.disabled = true;
    }
    return;
  }

  for (const control of controls) {
    if (previousDisabled.has(control)) {
      control.disabled = previousDisabled.get(control);
      previousDisabled.delete(control);
    }
  }
}
