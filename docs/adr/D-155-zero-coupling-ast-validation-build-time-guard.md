## D-155 Zero-Coupling AST Validation (Build-time Guard)

**Date:** 2026-09-21
**Status:** Accepted
**Context:** Static code dependencies between modules are currently maintained manually. Python's dynamic nature makes it easy to accidentally introduce cross-domain imports that pass local monolithic tests but break isolated runtime slices.
**Decision:** Extend `test/test_module_separation.py` with an AST-based guard
that fails when `core/control` production code imports CORE packages. The
existing package-dependency and final-publisher guards remain authoritative.
