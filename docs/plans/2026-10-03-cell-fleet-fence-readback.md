# Cell Fleet fence readback implementation plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the simulation owner's unconditional Fleet-current callback with live authenticated same-host Fleet dispatch-control readback.

**Architecture:** Reuse `GET /api/fleet/dispatch-control` with a separately provisioned named viewer credential. An agent application adapter makes uncached requests to an explicit literal loopback HTTP URL. Motion, stop and rearm requests continue to use the existing UID-checked UDS boundary. No Fleet database, ROS graph, new service or remote motion API is shared.

**Tech stack:** Existing Python stdlib HTTP client, FastAPI, SQLite, UDS and pytest.

**Scope:** D-413 Tasks 4-7 and D-403 G7 consumer composition. Runtime ROS/UDS fault cases (a)-(i), G9, thin-sheet manipulation and full recipe Gazebo acceptance remain separate mandatory requirements.

## 1. Live readback adapter

- Add `apps/agent/src/rosy_agent/fleet_fence.py` and `test/test_platform_fleet_fence_readback.py`.
- Require the exact existing read endpoint, literal `127.0.0.1` or `::1`, no userinfo/query/fragment, explicit viewer secret and a bounded socket timeout. Disable redirects and proxy environment inheritance by using a direct HTTP connection.
- Accept only HTTP 200, bounded finite JSON, strict nonnegative integer epoch/generation and boolean enabled state. Compare both requested generation values; never cache success. Errors, oversized/invalid responses, disabled dispatch and mismatches return False without printing secrets.
- Write failing configuration/readback tests, then implement and verify them. Credentials are runtime inputs; do not register or commit a secret.

## 2. Existing rearm and owner wiring

- Move `stop_transport.rearm` in the existing async Fleet route to `asyncio.to_thread`, preserving operator authorization, attribution and rollback.
- Configure the owner before importing ROS from `ROSY_FLEET_FENCE_URL` and `ROSY_FLEET_FENCE_TOKEN`; absence refuses startup. Supply the adapter to the existing `build_cell_owner` callback.
- Document same-network-namespace loopback configuration and private viewer provisioning in the OMX README. Cross-host access and physical dispatch remain closed.
- Exercise a real loopback Fleet HTTP app: viewer GET succeeds, viewer rearm is denied, operator rearm invokes the actual owner API, reverse readback does not deadlock, site stop/restart revoke the old fence, and transport loss refuses. ROS and UDS credential transport are host substitutes in this test.

## 3. Verify and land

- Run the new tests, existing task rearm/fanout tests, owner/provider/replay suites and platform boundary tests. Mutate the async rearm offload to prove the reverse-readback regression fails, then restore exact bytes.
- Build the changed agent wheel from X: scratch and verify installed imports/configuration. Run production flake8, quick tier, harness lint and independent review.
- Append evidence to deploy/Fleet/docs logs and D-413 tracking without promoting ROS-SIM. Commit only owned paths, merge latest main, rerun affected checks and fast-forward clean local main.

**Status:** SOURCE/LOCAL implemented. Readback18 passed; independent48 passed/1 skipped plus final18. Actual loopback HTTP is covered with owner API and fake UDS/ROS ports; live ROS/UDS and full G7 acceptance remain open. Agent wheel and pip check passed. Detailed evidence is recorded in module logs.

**Linux follow-up (2026-10-03):** The additional real-UDS branch now verifies kernel UID, fixed socket permissions and live identity readiness during actual Fleet HTTP rearm/stop. Caller disconnect is regression-proven and repaired by `6fab54172`. This is threaded same-process transport evidence with injected Cell ROS ports; broad ROS run remains 28 passed / 2 failed. [Evidence and limitations](../validation/cell-fleet-uds-2026-10-03/README.md).
