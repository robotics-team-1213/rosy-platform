---
surface: core
kind: additive
slug: commission-rear-dock
date: 2026-11-26
title: Stationary rear dock registration
---

Administrators can use `POST /api/v1/docking/commission` to create a dock and its detector type together. Supply `robot_id`, `map_id`, `map_grid_id`, `map_generation`, `dock` and `dock_type`. CORE checks localization, standstill and native ownership under the grid gate. An identical registration returns the existing dock. A different existing dock, a frame change or an active owner returns 409. Registration leaves the base stationary.
