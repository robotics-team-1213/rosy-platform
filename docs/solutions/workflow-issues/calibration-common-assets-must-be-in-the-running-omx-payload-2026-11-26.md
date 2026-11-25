---
title: Verify Calibration common assets in the running OMX payload
date: 2026-11-26
category: workflow-issues
module: OMX Calibration deployment
problem_type: build_error
component: deployment
symptoms:
  - "The Calibration HTML and local stylesheet returned HTTP 200 while /common/tokens.css and /common/ui.js returned HTTP 502 through the HTTPS proxy."
  - "The application journal reported FileNotFoundError for shared/web/shared-assets.json."
root_cause: missing_validation
resolution_type: code_fix
severity: medium
tags: [omx, calibration, release-layout, systemd, static-assets]
applies_when:
  - "An OMX hotfix changes a web application or its release paths."
  - "A healthy unit serves its HTML but shared CSS or JavaScript fails."
---

# Verify Calibration common assets in the running OMX payload

The Calibration HTML and local assets loaded on `:9449`, but the page lost its shared styling and JavaScript. The active user unit `rosy-calibration-web.service` used a service override pointing at `omx-cal-current`. Reading the checked-in unit or the default `omx-tools-current` link would have inspected a different tree.

`omx_hotfix.py` archived the Calibration app and `shared/web/cell-site-map.json`. The app looked for `shared/web/shared-assets.json` and the listed files in the same release tree when serving `/common/`. The application could start and serve its own assets with the shared directory incomplete. Tests against a full checkout still had all of the files.

The packaging fix includes `shared/web` as a directory while the server still serves only the manifest allowlist. The new payload test failed against the old path list. A Git archive built with the corrected list contained the HTML, manifest, all 62 listed assets, and the cell site map.

## Recovery and verification

1. Inspect the active service command and resolve its release link. Compare the running tree's `REVISION` and files with the intended package. Check the journal and request a representative shared stylesheet and module on loopback and through HTTPS. A green unit or an HTTP 200 for `/` only proves that the app started and the HTML was served.
2. When a payload is incomplete, package a new verified revision. A repeated hotfix deploy of the same revision reuses the existing directory when `REVISION` matches, even if files are missing.
3. Deploy to the link used by the active service and restart the Calibration web unit. Confirm HTTP 200 and the expected content types for `/common/tokens.css` and `/common/ui.js`, then check page rendering. The dedicated Calibration link keeps the cell engine release separate.

Related: [Release paths must be verified in the packaged layout](blanket-path-rewrite-hits-on-device-release-paths-2026-10-01.md).
