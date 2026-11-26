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

## Same class: the bench page served a release that predated the feature

On 2026-11-26 the OMX bench recorder on `:8771` did not show the camera preparation panel that main gained that day (`8927ea5d6b`). `omx_hotfix.py status` reported `current: omx-tools-c99d368aca`, a release that did contain the panel. That command reads the cell link `omx-tools-current` by default. `rosy-omx-bench-record.service` runs `~/rosy-test/omx-bench-current/deploy/robot/omx/bench_record.py` instead.

Two separate faults lined up:

- **The bench link pointed at an older release.** At 04:57 KST it was switched to `omx-tools-045fc4462b`, which was built from main of 11-25 and does not contain `8927ea5d6b`. No one had deployed the feature to the bench link, so a restart alone would not have shown it.
- **The unit kept serving the release it started with.** `bench_record_http.py` sets `HERE = Path(__file__).resolve().parent` at import time and serves its pages from that resolved directory. Switching the link does nothing until the unit restarts. The unit had started at 03:59, before the 04:57 switch. Later the same day, a deploy without a restart kept serving the old `bench_record.css`, and a restart switched it. This was checked by counting a font-size rule changed in PR #927.

To diagnose:

1. Read the unit's `ExecStart` and `readlink` the link it uses. `omx_hotfix.py status --link omx-bench-current` reads the right link.
2. Check that the linked release contains the commit you expect: `git merge-base --is-ancestor <commit> <release-sha>`.
3. Compare the link's mtime with the unit's `ActiveEnterTimestamp`.
4. Fetch a page asset that the intended release changed.

PR #926 makes a bench-link deploy restart the unit when `/api/arms` reports idle with no locked arm. When the bench is busy or unreadable, it holds the restart and exits 3. The restart only happens when `omx_hotfix.py` comes from a checkout that has #926. A stale local main still runs the old tool, which switches the link and prints no restart line. Run it from an up-to-date worktree or `origin/main`.

Related: [Release paths must be verified in the packaged layout](blanket-path-rewrite-hits-on-device-release-paths-2026-10-01.md).
