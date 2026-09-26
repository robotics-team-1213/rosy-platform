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

## Revision `46b7465b` rerun (LOCAL)

- Source commit: `46b7465b3685c6fffadb9491a500846616df9778`; platform:
  `linux/amd64`. Candidate: `X:\DevTemp\rosy-site-candidate-46b7465b`.
- Manifest SHA-256: `98d98bad573e238f3db2ed02e37f1180aee5ba0ca5a2a19ff886674f2d0b98c9`.
  Image archive SHA-256: `d1c468159e1d68cfd496abb0fc312cc26b656507e7418d2a64109f86570b8152`.
  Fleet image ID: `sha256:d1bc03e459a11872b97989f34dfc554ab24ae23ad46f23b3a34bc70392157c5f`;
  Vision: `sha256:053224b0cc32e72b9b8dbba83fad29f2aeab96f2e0521122cbce97c536eb982e`;
  proxy: `sha256:92285397b659eb03fbe532a76d061738d5f9b0f7f45027a68c662caa44276c3f`.
- Compared each image ID/platform, all SPDX SBOM hashes, the archive hash, and
  packaged deployment-file hashes to `release.json`; loaded the exact archive
  and validated its Compose configuration. Fleet, Vision, and HTTPS proxy all
  became healthy.
- Repeated synthetic WSS camera input through Vision/ArUco to Fleet HTTPS and
  SQLite (`ceiling_north`, seq `78`, pose approximately `[2.0, 1.0]`, quality
  `null`). Authenticated `test-operator` read its session, submitted a goal,
  and read `REQUESTED -> QUEUED` from durable task history.
- This was Windows Docker Desktop Linux/amd64 with temporary test config,
  credentials, and certificates. CORE was unreachable; there was no robot or
  GPU inference. It proves local service/API wiring only. Removed only Compose
  project `rosy-site-smoke-46b7465b`, its volume, and its networks; retained
  candidate images and bundle under `X:\DevTemp`.
