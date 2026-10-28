# Fleet applications source move

## Scope

Branch `refactor/fleet-applications`, base `7b2ffac91f`. D-822 groups the existing Console source in `applications/fleet/web` and gateway wheel in `applications/fleet/gateway`. Fleet service, authentication, ledger, admission and dispatch remain in `operations/fleet`. Existing URLs, wheel names, import paths and installed web resources remain unchanged.

This is an application source boundary, not independent deployment or an external integration. The gateway still calls Fleet CLI and the Fleet distribution still installs the web holder. Shared web assets remain a repository dependency. See [application guide](../../../applications/fleet/README.md).

## Verification

| Revision | Check | Result |
|---|---|---|
| `237f2d386e` | Remote AI test PC: architecture, ownership, colcon roots, size limits, dependency boundaries, folder layout, installed wheel/sdist, gateway composition, site candidate closure/workflow, browser scope, affected selector and harness | 329 passed, 0 skipped; known-failure comparison NEW 0 |
| `b674b70aae` | Remote model test PC: site candidate and size-limit suites | 38 passed, 0 skipped; NEW 0. Includes the COPY-source guard's missing-holder injection and restoration. |
| `2aeec99374` | Remote model test PC with `ROSY_RUN_BROWSER_TESTS=1`: Console browser, account, work and Cell flows, Node wrapper, site deployment contracts | 289 passed, 0 skipped; NEW 0. The Node wrapper runs every Console `.test.mjs`. |

The browser revision and `b674b70aae` differ only in `test/test_site_candidate.py`; runtime, packaging and browser/Node test sources are identical. Later evidence-only commits do not change those sources.

The first remote run at `1f8fe3dedc` found three failures caused by old Docker COPY paths. They were fixed in `2aeec99374`; the 329-test run above verifies the corrected revision. Independent read-only review found those Docker paths and old Node imports, verified both fixes, and reported no remaining supported source finding at `237f2d386e`. A delta review through `b674b70aae` also accepted the narrow missing-holder fault injection; it does not establish a real Docker build.

Local non-pytest checks: `git diff --check`, harness lint, size-range and safety-review range checks passed. Harness warnings concern existing verification age and historical moved logs; they do not establish runtime acceptance. The affected selector remains FULL because manifests, CI and source holders changed. The selected remote suites do not discharge full CI.

## Evidence binding

Logs are outside the checkout under the invoking machine's temporary directory. SHA-256 binds the retained files:

| Log | SHA-256 |
|---|---|
| `rosy-fleet-applications-source-final/run-1.txt` | `8c6a426de8002207a15d7abea639af64b0f49f83cb80d4e87ab9ed3d8aa48a14` |
| `rosy-fleet-applications-mutation/run-1.txt` | `6ed8477a3c1091827fa32a76e0cf2af525dbc9c2a8ecd57686413eb94c47dd7e` |
| `rosy-fleet-applications-browser/run-1.txt` | `d309d514f400c3df5e50bcaf9e3e6fcca378a0551fc38ba201e1e467a096240f` |

## Remaining gates

Real Docker/site candidate image build, full GitHub CI, deployment, devices and field acceptance have not run. No main landing, push, PR publication or remote repository changes are included in this work.
