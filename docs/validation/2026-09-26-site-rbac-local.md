# Site Fleet RBAC local validation (2026-09-26)

## Scope

This record covers source-level authorization, durable API mutation auditing,
the local Linux/amd64 Docker image build, and a synthetic HTTPS smoke test.
It does not represent Ubuntu host, deployed site, GPU, camera, robot, or field
acceptance.

## Automated checks

Focused suite:

```text
python -m pytest src/site/fleet/test/ test/test_site_candidate.py test/test_site_task_queue_deploy.py test/test_line_follow_contract_docs.py test/test_network_topology_contracts.py -q
527 passed, 5 skipped
```

`docker compose -f deploy/site/compose.yaml config --quiet` passed.

Local Linux/amd64 images built:

| Image | SHA-256 digest |
| --- | --- |
| Fleet | `sha256:8fc670d02fff415cd8ccbd4f9a1d0c53e554f6f89dfe495aabf63a5a2792a294` |
| Vision | `sha256:0d083a319bf2efa035ab5a81f2638075fb8cb6d10797836cd29cca1f39fcbf1f` |
| Proxy | `sha256:2001e8a6a77de6139187f9cb6ba55ac1bfd998a2d7c35b48af02908429f21498` |

## Synthetic HTTPS RBAC smoke

Requests were sent through the local Docker Compose stack using a test CA and
synthetic credentials. The robot URL was `https://robot.invalid:8443`; no
physical robot was reachable or contacted.

| Principal/request | Result |
| --- | --- |
| Missing bearer, read route | `401` |
| Viewer, nonexistent task read | `404` (authenticated read; task absent) |
| Viewer, goal mutation | `403` |
| Viewer, E-Stop mutation | `403` |
| Policy admin, task mutation | `403` |
| Operator, nonexistent task mutation | `404` (authorized; task absent) |

SQLite readback confirmed append-only `INTENT` and `RESULT` audit records with
principal, role, route, and outcome. The bearer and request body were not stored.
The stack, its test network, and its temporary database volume were removed
after the smoke test. Built images remain in the local Docker image store.

## Remaining acceptance gates

- Deploy the pinned candidate on the Ubuntu site host and record its deployed
  image digests, TLS, persistent database, restart/recovery, and health results.
- Perform controlled individual-token handoff, role checks, replacement, and
  revocation on the actual site host.
- Verify CORE event ingestion and command/result readback with the real CORE
  Agent and robot simulator or approved device setup.
- Verify browser-visible role affordances and authenticated operator workflow.
- Measure camera-to-Fleet freshness and false-trigger rates using field data.
- Keep automatic movement, arm pickup, and Pinky camera integration gated on
  their separately accepted contracts and physical evidence.

Local Docker success is not evidence for NVIDIA GPU access, Ubuntu deployment,
or physical movement safety.
