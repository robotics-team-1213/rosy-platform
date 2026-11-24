---
surface: cell
kind: additive
slug: cell-readiness-per-cell
date: 2026-11-24
title: OMX /readiness per-cell isolation
history: Additive: GET /readiness cells breakdown and optional ?cell=cell_s|cell_ab filter
---
Added additive `cells` (`cell_s` / `cell_ab`) per-cell readiness breakdown on `GET /readiness` (`rosy.cell-readiness.v1`, `CellReadiness` + `CellScopeReadiness`) and optional `?cell=cell_s|cell_ab` query filter. Unscoped `GET /readiness` retains strict top-level `allowed_tiers_now` behavior.
