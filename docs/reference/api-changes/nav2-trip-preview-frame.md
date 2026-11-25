---
surface: fleet
kind: additive
slug: nav2-trip-preview-frame
date: 2026-11-26
title: Nav2 trip preview shows frame readiness
---
For `drive_mode: nav2`, the trip planning response includes `nav2_preflight` with `code`, `binding_required`, and `binding_status`. `code` is null when the sampled CORE pose, capabilities, and configured binding policy permit the preview. `binding_status` records `MATCHED` or the reason a binding did not match, including when the site treats bindings as optional. Planning returns route geometry with this readback and issues no motion command.
