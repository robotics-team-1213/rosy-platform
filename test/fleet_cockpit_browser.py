"""Shared Playwright entry points for Fleet cockpit robot selection and controls."""

from __future__ import annotations


def robot_picker(page):
    """Return the active cockpit robot picker locator."""
    return page.locator("#robot-dock")


def selected_robot_id(page) -> str:
    """Return the currently selected robot id from the active cockpit dock."""
    btn = page.locator("#robot-dock .robot-dock-btn[data-selected]")
    if btn.count() == 0:
        return ""
    return btn.first.get_attribute("data-robot-id") or ""


def clear_robot_selection(page) -> None:
    """Close the cockpit panel and clear active robot selection."""
    panel = page.locator("#robot-panel")
    if panel.count() > 0 and panel.is_visible():
        panel.locator(".robot-panel-close").click()
        panel.wait_for(state="hidden")
    else:
        active = page.locator('#robot-dock .robot-dock-btn[aria-pressed="true"]')
        if active.count() > 0:
            active.first.click()


def select_robot(page, robot_id: str | None = None, *, wait_workspace: bool = True) -> str:
    """Wait for dock readiness, open/select one robot via the C23 dock, and return its id."""
    page.wait_for_function("() => document.querySelectorAll('#robot-dock .robot-dock-btn').length > 0")
    if robot_id is None:
        robot_id = page.locator("#robot-dock .robot-dock-btn").evaluate_all(
            "btns => btns.some(b => b.dataset.robotId === 'rosy_01') ? 'rosy_01' : btns[0].dataset.robotId"
        )
    btn = page.locator(f'#robot-dock .robot-dock-btn[data-robot-id="{robot_id}"]')
    if btn.get_attribute("aria-pressed") != "true":
        if not wait_workspace and page.locator("dialog.ui-confirm").count() > 0:
            btn.dispatch_event("click")
        else:
            btn.click()
    if wait_workspace and not str(robot_id).startswith(("arm_", "cell_")):
        page.locator(f'#robot-workspace article[data-robot-id="{robot_id}"]').wait_for(state="visible")
        page.evaluate("() => document.activeElement?.blur()")
    return robot_id


def open_robot_workspace(page, robot_id: str | None = None):
    """Select `robot_id` via the C23 dock and return its workspace locator inside C24 panel."""
    chosen = select_robot(page, robot_id, wait_workspace=True)
    return page.locator(f'#robot-workspace article[data-robot-id="{chosen}"]')


def open_manual_controls(page, robot_id: str = "rosy_45"):
    """Open `robot_id` in C24 panel, expand collapsed manual controls if needed, and return directions."""
    select_robot(page, robot_id, wait_workspace=True)
    details = page.locator('#robot-panel details[data-section="manual"]')
    details.wait_for(state="visible")
    if not details.evaluate("node => node.open"):
        details.locator("summary").click()
    controls = page.locator("[data-manual-direction]")
    controls.first.wait_for(state="visible")
    return controls
