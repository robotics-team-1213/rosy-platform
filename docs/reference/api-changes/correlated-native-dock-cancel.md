---
surface: core
kind: additive
slug: correlated-native-dock-cancel
date: 2026-11-26
title: Correlated native docking cancellation
---

The docking status advertises `operation_cancel_supported`. Operators can cancel the current dock or undock with `POST /api/v1/docking/cancel-operation` using `run_id`, `expected_boot_id` and `expected_owner_generation`. The native owner compares all three before stopping and returns its readback. Fleet named charging-bay trips keep the requested dock and expose the staging place and operation phase in `parking_handoff`.
