"""Known-list ratchets (bn H-1, 2026-11-20): a new entry fails, a stale entry only warns.

A stale entry (the list still names something the tree no longer has) is the shrink the ratchet asks for; failing
on it turned main red when another landing removed the thing first. A test file that imports this module is a
ratchet: test_harness_contracts checks it sits in affected_tests.GUARD_SET, so every selection runs it.
"""

import warnings


def check(found, known, what: str) -> None:
    """Fail on entries of found missing from known; warn on entries of known no longer found.

    found may be a dict whose values say where each entry was seen."""
    new = sorted(set(found) - set(known))
    assert not new, f"new {what}: " + "; ".join(f"{key}: {found[key]}" if isinstance(found, dict) else str(key)
                                                 for key in new)
    stale = sorted(set(known) - set(found))
    if stale:
        warnings.warn(f"stale {what} (remove them from the list): {stale}", stacklevel=2)
