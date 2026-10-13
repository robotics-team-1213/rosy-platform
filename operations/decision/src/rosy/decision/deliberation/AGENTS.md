<!-- Parent: ../AGENTS.md -->
# deliberation

**Parent context:** `../AGENTS.md`
**Updated:** 2026-10-12

Bounded advisory opinions only (D-640). `__init__.py` owns canonical Problem,
semantic validation and the finite supervisor; `cli.py` translates fixed provider
argv/output through a mandatory trusted isolated launcher. No shell, database,
Mission dispatch, robot authority or default real launcher belongs here.

Fleet owns `fleet.server.deliberation_journal` and current-case checks. The existing
Fleet distribution explicitly installs this subpackage via fleet_sources.py.
P6 unit and parent measurement: docs/plans/2026-10-12-decision-deliberation-boundary.md.
Remote tests: test_deliberation.py, test_cli_deliberation.py and installed wheel/sdist.
Fake provider results never establish runtime isolation, model quality or FIELD acceptance.
