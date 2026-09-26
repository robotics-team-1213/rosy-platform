# Site Fleet container stack: local smoke evidence

Date: 2026-09-26
Source revision: `a99c7671ea7042d61d4b0d1fa25313768d0f4052`
Scope: Windows host with Docker Desktop Linux `linux/amd64`, synthetic fixtures.

## Evidence

- Built the revision-pinned candidate with `deploy/site/build_candidate.py`.
  The manifest image IDs and SPDX SBOM hashes matched the exported candidate;
  `images.tar` matched its recorded SHA-256. Loaded that exact archive and
  validated the packaged Compose configuration.
- Started Fleet, Vision, and the HTTPS proxy from the candidate images. All
  three Compose healthchecks reached `healthy`.
- Sent a synthetic ceiling-phone JPEG over WSS. Vision produced an ArUco
  sighting, and the authenticated Fleet HTTPS API returned it from SQLite:
  `WSS phone -> vision -> HTTPS Fleet -> SQLite`, source `ceiling_north`,
  sequence `78`, pose approximately `[2.0, 1.0]`.
- Authenticated as the temporary `operator` principal, read back `/api/fleet/session`,
  submitted one navigation intent with an idempotency key, and read the same
  task and `REQUESTED -> QUEUED` history through `/api/fleet/tasks/{task_id}`.
- The synthetic CORE endpoint was unreachable and no robot was attached. The
  test established API/task acceptance and readback only; it did not establish
  dispatch, robot motion, or physical arrival.
- The test initially exposed missing and non-distinct credentials in the stale
  scratch fixture. After using the required `site-users.yaml` digest and
  separate temporary console/API credentials, all services became healthy.
  This is evidence that the startup checks enforce the documented secret
  boundaries; no tracked source change was needed.
- Stopped and removed only Compose project `rosy-site-smoke-a99c7671` and its
  test volume after readback. The candidate bundle and images remain in
  `X:\DevTemp` for inspection.

## Limits and open gates

- This was a local Docker Desktop Linux amd64 test, not deployment to the
  always-on Ubuntu RTX 5080 host. It used CPU ArUco processing and did not
  exercise GPU inference, site credentials, real TLS provisioning, reboot
  recovery, or field network conditions.
- No physical ceiling phone, CORE, Pinky, or robot arm was connected. No motion
  or automatic task dispatch was authorized by this test.
- Automatic movement and picking remain HOLD pending D-257/D-268 acceptance,
  measured freshness and false-trigger criteria, and device/field evidence.
