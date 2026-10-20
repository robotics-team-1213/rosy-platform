# Fleet frontend development verification · 2026-10-21

Implementation of [D-830](../adr/D-830-fleet-independent-frontend-development.md) and the [accepted plan](../plans/2026-10-21-fleet-frontend-separation.md). The repository and operational Fleet distribution remain shared. This record distinguishes frontend tests, backend HTTP observations and deployment/device acceptance.

## Delivered boundary

- `applications/fleet/web` owns the eight documents, exact public asset registry and native browser provider. Production Fleet and the standalone development host consume the same registry and business UI files.
- `applications/fleet/dev` runs with Python stdlib only. Sample has local state and explicit controls; connected uses a single verified HTTPS site origin and preserves real Fleet authentication and errors. Fleet cookies do not accompany leased Vision frame requests.
- Gateway calls public `fleet.cli.run`; Fleet can run without importing the gateway. Existing command names, URLs, installed resource paths and joint production deployment remain.
- Sample represents account/session, map, enrollment/pairing, navigation/task, Cell, channel review, policy, formation, incident and assistant flows. Unsupported requests fail visibly. Synthetic voice/video require no browser device or external network.

## Evidence

| Scope | Immutable revision | Result |
|---|---|---|
| Existing Fleet + CORE contracts | `3ce1940365` | 6236 passed, 336 skipped; no device acceptance |
| Installed wheel/sdist asset registry | `cab75c20a3` | 4 passed; actual build/install/HTTP resource identity |
| Public CLI and install/import contracts | `a1baa2409f` | 61 passed |
| Broad opt-in backend HTTP capture | `7ab88553a8` | 6046 passed, 323 skipped, 3 failed; receipts retain passing cases only |
| Asset-dependent backend/Node regression correction | `6198da9908` | 50 passed; corrected the three capture-run failures |
| Additional owned HTTP lifecycle reads/writes | `bb9fec5fa4` | 6 passed |
| Assistant submit/poll contract capture | `4cb62aa167` | 6 passed |
| 18 representative browser fetch flows + Cell form + real Fleet HTTPS integration | `7983f783c8` | 20 passed |
| Reviewed sample stop/formation/task-count coherence | `030df77030` | 21 passed, including browser fetch and real cancel-all button |
| Combined app/browser/wheel/sdist/CLI/architecture/real-Fleet-HTTPS regression | `f5aab6d2de` | 264 passed, zero skips |
| Final sample two-person Cell authority and all representative browser flows | `c000a57004` | 36 passed, zero skips; includes actual Cell reviewer and overview form flow |
| Module guard/public fixture corrections and final Cell reviewer navigation | `a7ef52c3aa` | Final secret/provenance checks plus Cell form/overview: 98 passed, zero skips; preceding focused guard/browser run had 294 passed and the two subsequently corrected failures |

The [machine-readable matrix](../../applications/fleet/test/feature_matrix.json) inventories 159 method/path contracts across 18 feature groups. [HTTP receipts](../../applications/fleet/test/backend_http_evidence.json) bind each observed response to an exact passing test ID and full source revision. A conservative literal/prefix inventory can include conditional routes; registration alone is not evidence that every deployment enables them.

Six receipts currently prove refusal paths only: policy window close, trip replan confirmation, Cell reconcile, robot unenrollment, legacy camera rejection and start-point deletion. Their successful configured HTTP paths are not claimed verified by those receipts. The matrix labels this explicitly. Sample representative tests do not upgrade backend or device evidence.

The 54 happy/refused/terminal matrix entries point to 18 browser replay cases; they are classifications within each representative transaction, not 54 independent full UI journeys. Replays use actual browser fetch and then render the application document. Separate form/button tests exercise login/profile, Cell document→preview→admission→recovery→terminal read, camera approval prerequisite, voice/video and cancel-all. Independent review found and prompted fixes for latched cancel-all and missing Cell overview rows; subsequent verification also exposed and fixed the initial Cell session/read race.

## Limits and final checks

Sample state is single-session and process-local. Cell compile supports the supplied recorded example; calibration is display-only; policy execution leases remain refused. No physical robot, operational model, microphone quality, deployment or field acceptance is established here.

Combined app/browser/installed checks passed as recorded above. Standard landing FULL results are recorded in the development module journal when complete. Earlier scoped results do not substitute for that final merged revision.
