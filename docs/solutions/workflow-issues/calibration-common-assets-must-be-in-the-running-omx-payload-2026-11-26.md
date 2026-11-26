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
last_updated: 2026-11-26
tags: [omx, calibration, bench-record, release-layout, systemd, static-assets]
applies_when:
  - "An OMX hotfix changes a web application or its release paths."
  - "A healthy unit serves its HTML but shared CSS or JavaScript fails."
  - "A page served from a dedicated omx-*-current link lacks a feature that its deployed release already contains."
---

# Verify Calibration common assets in the running OMX payload

The Calibration HTML and local assets loaded on `:9449`, but the page lost its shared styling and JavaScript. The active user unit `rosy-calibration-web.service` used a service override pointing at `omx-cal-current`. Reading the checked-in unit or the default `omx-tools-current` link would have inspected a different tree.

`omx_hotfix.py` archived the Calibration app and `shared/web/cell-site-map.json`. The app looked for `shared/web/shared-assets.json` and the listed files in the same release tree when serving `/common/`. The application could start and serve its own assets with the shared directory incomplete. Tests against a full checkout still had all of the files.

The packaging fix includes `shared/web` as a directory while the server still serves only the manifest allowlist. The new payload test failed against the old path list. A Git archive built with the corrected list contained the HTML, manifest, all 62 listed assets, and the cell site map.

## Recovery and verification

1. Inspect the active service command and resolve its release link. Compare the running tree's `REVISION` and files with the intended package. Check the journal and request a representative shared stylesheet and module on loopback and through HTTPS. A green unit or an HTTP 200 for `/` only proves that the app started and the HTML was served.
2. When a payload is incomplete, package a new verified revision. A repeated hotfix deploy of the same revision reuses the existing directory when `REVISION` matches, even if files are missing.
3. Deploy to the link used by the active service and restart the Calibration web unit. Confirm HTTP 200 and the expected content types for `/common/tokens.css` and `/common/ui.js`, then check page rendering. The dedicated Calibration link keeps the cell engine release separate.

## Same class: the bench page kept running an older release

On 2026-11-26 the OMX bench recorder on `:8771` did not show the camera preparation panel added in main that day. `omx_hotfix.py status` reported `current: omx-tools-c99d368aca`, a release that contained the panel, so the deploy looked current. That command reads the cell link `omx-tools-current` by default. `rosy-omx-bench-record.service` runs `~/rosy-test/omx-bench-current/deploy/robot/omx/bench_record.py` instead.

- The bench link had switched at 04:57 KST, but `ActiveEnterTimestamp` showed the unit had started at 03:59. `deploy --link omx-bench-current` switched the link and did not restart the unit, and the guide listed the restart as a separate manual step. That step had been skipped.
- To diagnose, read the unit's `ExecStart`, `readlink` the link it uses, and compare the link's mtime with `ActiveEnterTimestamp`. Then fetch the page and look for an element the intended release adds. `omx_hotfix.py status --link omx-bench-current` reads the right link.
- Recovery ran `omx_hotfix.py test` on the main SHA (271 passed) and confirmed the bench was idle through `GET /api/arms`. It then deployed with `--link omx-bench-current`, restarted the unit, and checked that the page served the new element.
- PR #926 (pending at the time of writing) makes a bench-link deploy restart the unit when `/api/arms` is idle with no locked arm. It holds the restart and exits 3 when the bench is busy or unreadable.

Related: [Release paths must be verified in the packaged layout](blanket-path-rewrite-hits-on-device-release-paths-2026-10-01.md).
