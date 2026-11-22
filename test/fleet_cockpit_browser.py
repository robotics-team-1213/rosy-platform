"""Shared Playwright entry points for Fleet cockpit robot selection and controls."""

from __future__ import annotations


def robot_picker(page):
    """Return the active cockpit robot picker locator."""
    return page.locator("#robot-choice")


def selected_robot_id(page) -> str:
    """Return the currently selected robot id from the active cockpit picker."""
    return robot_picker(page).input_value()


def clear_robot_selection(page) -> None:
    """Clear the selected cockpit robot."""
    robot_picker(page).select_option("")


def select_robot(page, robot_id: str | None = None, *, wait_workspace: bool = True) -> str:
    """Wait for roster readiness, pick one robot in the cockpit picker, and return its id."""
    page.wait_for_function("() => document.querySelectorAll('#roster article').length > 0")
    if robot_id is None:
        robot_id = page.locator('#robot-choice option[value]:not([value=""])').evaluate_all(
            "options => options.some(option => option.value === 'rosy_01') ? 'rosy_01' : options[0].value"
        )
    robot_picker(page).select_option(robot_id)
    if wait_workspace:
        page.locator("#robot-workspace article").wait_for(state="visible")
        page.evaluate("() => document.activeElement?.blur()")
    return robot_id


def open_robot_workspace(page, robot_id: str | None = None):
    """Select `robot_id` (switching to the status context tab if present) and return its workspace locator."""
    tab = page.locator('[data-context-tab="status"]')
    if tab.count() > 0 and tab.get_attribute("aria-selected") != "true":
        tab.click()
    chosen = select_robot(page, robot_id, wait_workspace=True)
    return page.locator(f'#robot-workspace article[data-robot-id="{chosen}"]')


def open_manual_controls(page, robot_id: str = "rosy_45"):
    """Select `robot_id`, ensure manual drive controls are accessible, and return direction buttons locator."""
    select_robot(page, robot_id, wait_workspace=True)
    return page.locator("[data-manual-direction]")
