# drive

**Parent context:** `../AGENTS.md`

Base-control backends: `planning/` currently contains Nav2. CORE navigation, line tracking, docking, recovery and output guards retain their existing owners while their responsibility seams are extracted independently. Folder placement alone does not unify those algorithms or their Safety coverage.

Every backend submits a candidate to CORE. No operational final publisher, new mode or automatic recovery activation belongs in this holder. Curvature, clearance, pivot/reverse and bounded recovery must retain their own behavioral evidence.
