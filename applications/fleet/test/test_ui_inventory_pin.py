"""Pins console UI that a later edit once dropped silently: each row is an element a person sees,
the file and the code that makes it work. Static: reads source text, no browser."""

import re
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parents[1] / "web"

# (element, file, code that must be present, code that must be absent, PR that restored it)
INVENTORY = [
    ("right inspector shows the first cell's tabs while nothing is chosen",
     "charge-bays-view.js", ["if (!rows?.cards?.length) {"], ["!activeInspectorId) {"], 311),
    ("robot picker lists OMX cells beside robots",
     "roster.js", ["OMX_CELL_DEFS.filter(def =>", "[...robotOptions, ...omxOptions]"], [], 311),
    ("picker keeps an arm_* focus selected",
     "roster.js", ['String(view.focusAnchorId || "").startsWith("arm_")'], [], 311),
    ("hidden tab polls nothing but presence",
     "console.js", ["const poll = (fn, ms) => pageScope.interval(() => (!document.hidden ? fn() : undefined), ms);",
                    "poll(refreshState, STATE_MS);", "poll(() => trackingView.refresh(), TRACKING_MS);"],
     ["pageScope.interval(refreshState,", "pageScope.interval(() => trackingView.refresh()"], 311),
    ("presence keeps reporting while hidden",
     "console.js", ["pageScope.interval(() => signals.presence(), STATE_MS);"], [], 311),
    ("coming back to the tab reads state and tracking once",
     "console.js", ['pageScope.listen(document, "visibilitychange", () => { if (!document.hidden) { refreshState(); trackingView.refresh(); } });'], [], 311),
]


def squash(text):
    return re.sub(r"\s+", " ", text)


@pytest.mark.parametrize("element,name,present,absent,pr", INVENTORY, ids=[row[0] for row in INVENTORY])
def test_inventory_row_still_in_source(element, name, present, absent, pr):
    text = squash((WEB / name).read_text(encoding="utf-8"))
    why = (f"'{element}' ({name}): this element was restored by #{pr}; if you remove it on purpose, "
           f"change this row in the same PR and name it under \"Replaces:\" in the PR body.")
    for code in present:
        assert squash(code) in text, f"{why} Missing: {code}"
    for code in absent:
        assert squash(code) not in text, f"{why} Back again: {code}"
