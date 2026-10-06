---
name: rosy-pinky-review
description: Use when an agent must run, look at, verify, or improve the Pinky label review web app (Pinky 검수, 객체 검수, 픽셀 검수, /pixels, /catalog, /learning, review_app.py, D-459/D-461/D-469) — launching it locally on real or copied review state, screenshotting each screen at desktop and phone width, walking a reviewer flow with Playwright, or when a review screen is slow, blank, scrolls sideways, or a browser test skips.
---

# Running and checking the Pinky review app

## Overview

`learning/training/perception/dataset/review_app.py` is a PC-only stdlib server (SQLite +
static files). It needs no robot, ROS or model API, so it always runs locally. Operator
manual: `learning/training/perception/docs/review-app.md`. This card covers how an agent
gets it running and judges a change with its own eyes.

## 1. Get a state you may write to

The `--state` folder is the reviewer's record of truth (SQLite, frozen originals, exports).
**Never point a write-capable session at an operational state.** Copy it under `X:\DevTemp`:

```bash
ls -d /x/DevTemp/*/reviews.sqlite3 /x/DevTemp/*/*/reviews.sqlite3   # existing states
mkdir -p X:/DevTemp/<name> && cp -r <state> X:/DevTemp/<name>/state
```

`X:/DevTemp/pinky-review-flow-20261005/visual-state-ready` holds 357 real Pinky frames: copy from it, never serve it directly.
With no state, the first run needs `--source <jsonl> --human <jsonl> --images <root>`.

## 2. Look before changing anything

```bash
python tools/review_app_smoke.py --state X:/DevTemp/<name>/state --out X:/DevTemp/<name>/smoke
```

It copies the state under `--out` (app startup may migrate the schema), serves the copy on a
free loopback port and opens `/`, `/?filter=pending`, `/pixels`, `/catalog` and `/learning`
at 1440×900 and 390×844. It writes a screenshot of each screen and prints the object and
pixel decision counts. The browser sends GET requests only. Exit 1 means
a page error, an HTTP ≥ 400, a failed request, sideways page scroll, or no photos. Then
**Read the PNGs**. A passing exit code does not show whether the editor is usable.

For a running app, use `--base-url http://127.0.0.1:<port>` instead (no copy is made). To keep one up while
iterating, start it in the background. Static files are re-read on every request, so a
browser reload picks up JS/CSS edits without restarting the server:

```bash
python learning/training/perception/dataset/review_app.py --state X:/DevTemp/<name>/state --port 8791
```

## 3. Walk a reviewer flow (copied state only)

The per-photo loop: check `#complete`, click `#approve` (or `#exclude`), and the next
pending photo opens. The `pending` filter stays on, and `#drag-status` names the photo that
was just decided. Inside the `approved`/`excluded` filters (an audit) a decision stays on
the photo and widens the filter to `all`. Pixel review has the same loop with
`#pixel-complete` + `#pixel-background` → `#pixel-approve`, skips object-excluded photos and
keeps the chosen paint class.

| Element | Selector |
|---|---|
| Photo title / progress | `#frame-title`, `#frame-progress` (pixels: `#pixel-title`, `#pixel-status`) |
| Image ready | `#image-message` hidden |
| Status filter | `#filter` (pixels: `#pixel-filter`): `all` `pending` `approved` `excluded` |
| Why a button is disabled | its `reason` attribute |
| Photo strip | `#frames` (`[aria-pressed="true"]` = open photo) |
| Saved version | `#save-status` → `서버 저장됨 · vN` |

Wait for `#image-message` to be hidden before acting. Buttons stay disabled until the
original image has loaded and been hash-checked.

## 4. Prove the change

```bash
ROSY_RUN_BROWSER_TESTS=1 PYTHONIOENCODING=utf-8 python -m pytest \
  learning/training/perception/test/test_review_flow_browser.py \
  learning/training/perception/test/test_pixel_review_browser.py \
  learning/training/perception/test/test_review_app_smoke.py \
  -q -rfE -p no:cacheprovider --basetemp X:/DevTemp/<name>/bt > X:/DevTemp/<name>/browser.txt
python test/known_failures.py X:/DevTemp/<name>/browser.txt
```

Without `ROSY_RUN_BROWSER_TESTS=1` these tests **skip** and "pass". Their fixture has two
frames (approved, excluded). Use `store.update(i, {'version': ..., 'action': 'reopen'})` for
pending ones, and `page.reload()` after a store write so the page sees it. Server and
contract suites: the test block in `review-app.md`. Run `node --test` for
`review_box_geometry.test.mjs`.

## Common mistakes

- Approving in a test or walkthrough on the operational state turns synthetic approvals into training truth. Copy first.
- Setting `img.src` before `img.loading='lazy'`: Chromium fetches eagerly, and a reload pulls every thumbnail (352 requests instead of 70).
- Treating `wait_until='networkidle'` time as server time. `/api/workspace` is ≈0.6 s for 357 frames, and an image ≈16 ms. Seconds-long loads mean too many requests or a busy host.
- Grid or flex children with long content need `min-width: 0`, or the photo strip widens the page.
- Printing Korean to the Windows console garbles it. Set `PYTHONIOENCODING=utf-8` or read the screenshots.
- `--host` other than loopback opens an unauthenticated editor (D-478). Keep it on 127.0.0.1 for agent runs.
