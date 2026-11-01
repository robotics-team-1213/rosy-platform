---
title: Fleet holder sibling modules import by their composed flat name, not the source-tree path
date: 2026-10-28
module: operations/fleet fleet/_source_layout.py SERVER_HOLDERS, tools/packaging/fleet_sources.py
problem_type: logic_error
component: packaging
severity: medium
symptoms:
  - "A landing guard round stops with NEW ModuleNotFoundError — 'fleet.server.console.<name>' ... 'fleet.server.console' is not a package — and every traceback lands on one import line."
  - "All NEW ids pass on main; the branch's own suites stayed green because they never import the fleet console app."
root_cause: wrong_abstraction
resolution_type: code_fix
applies_when:
  - "Adding a sibling .py module inside a SERVER_HOLDERS directory (console/, ledger/, trips/, work/, peer/, ...)."
  - "Reviewing an import whose dotted path mirrors the repository file path under operations/fleet/fleet/server/."
tags: [fleet, packaging, imports, server-holders, composed-install, landing]
---

# Import holder siblings as `fleet.server.<name>`, never by the source-tree path

## Problem and verified scope

The 2026-10-28 `fix/site-audit-retention` landing stopped in its prepare round with 13 NEW ids — 10 FAILED plus 3 collection ERRORs — and every traceback was the same line:
`ModuleNotFoundError: No module named 'fleet.server.console.observe'; 'fleet.server.console' is not a package` at `operations/fleet/fleet/server/console/console.py:36`. All 13 ids passed on main (`b58162a6db`), so the branch caused them. One import line change (commit `15538d5db9`) made all 11 affected suites pass again on a remote test host (0 NEW vs `test/known_failures.py`; log `D:/DevTemp/site-audit-retention-20261028/fix-1/`). This is a composed-install import defect, not a runtime defect on any robot.

## Why the source path looked right but composes wrong

`fleet/_source_layout.py` lists holder directories in `SERVER_HOLDERS` (`peer`, `cell`, `auth`, `console`, `ledger`, `missions`, `work`, `trips`, ...). At build time `tools/packaging/fleet_sources.py` (`PureAssessment.find_package_modules`) composes every `*.py` inside a holder as a **flat `fleet.server.<filename>` module**; the holder directory has no `__init__.py` and is never an importable package. In every environment the code actually runs — wheel, colcon full install, remote pytest venvs — `fleet.server.console` binds to the `console.py` module itself. An import written as the repository path (`from fleet.server.console.observe import ...`) therefore cannot resolve anywhere composed, while looking natural in a source editor. The established flat-name precedent is `console_routes`, `monitoring_routes` and `console_view`, all inside `console/` and all imported as `fleet.server.<name>`.

## What caught it and what it cost

The fastest reproduction is any suite that builds the FastAPI app through the composed install — `test/architecture/test_app_roles.py` reached `fleet.server.app` → `console.py` in the guard round. The branch's own suites never imported the fleet console app, so the defect survived until the landing and cost one stopped round in a congested landing queue (13 NEW exceeds the 1-to-5 alone-rerun budget, so the round stopped outright). Before adding a sibling module in a holder directory, run that guard suite on a remote PC, and grep the branch for `from fleet.server.<holder>.` — the dotted path after `fleet.server.` must be a module name, never a holder directory.
