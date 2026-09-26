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

## Revision `7bd81cf3` rerun (LOCAL)

- Source commit: `7bd81cf3919b11c769094a5d7798aaf79eca5b91`; platform:
  `linux/amd64`. Candidate: `X:\DevTemp\rosy-site-candidate-7bd81cf3`.
- Manifest SHA-256: `7649671f758a36fbfa28e9a0b62b78b9b48f9505665f7114a4bf19d1fa6315d7`.
  Image archive SHA-256: `541cf3df0d5633d04c0ef613163fe4a52e75e794ebc510425301fdfba004409f`.
  Fleet image ID: `sha256:0d33e83ad88be9faab88e668f3efd9f6602a06ce85f57756f958207599eec34b`;
  Vision: `sha256:1e59f75b923c90095e75e77e03af1235efebc813495d812e8478cf35274aac49`;
  proxy: `sha256:92285397b659eb03fbe532a76d061738d5f9b0f7f45027a68c662caa44276c3f`.
- Verified all image IDs/platforms, SPDX SBOM hashes, packaged deployment-file
  hashes, archive hash, and candidate Compose config. Loaded that exact archive;
  all three services became healthy.
- Repeated synthetic WSS camera input through Vision/ArUco to Fleet HTTPS/SQLite
  (`ceiling_north`, seq `78`, pose approximately `[2.0, 1.0]`, quality `null`).
  Authenticated `test-operator` submitted a goal and read `REQUESTED -> QUEUED`
  task history. CORE was unreachable and no robot or GPU inference was present.
- Windows Docker Desktop Linux/amd64 with temporary test config and certificates.
  Removed only Compose project `rosy-site-smoke-7bd81cf3`, its volume, and its
  networks; retained the candidate bundle and images under `X:\DevTemp`.

## Revision `01a3946c` rerun: typed intent API and camera pipeline (LOCAL)

- Source commit: `01a3946c3b77bb04ab4338b7b0d976312e8d7429`; platform:
  `linux/amd64`. Candidate: `X:\DevTemp\rosy-site-candidate-01a3946c`.
- Candidate archive SHA-256:
  SHA-256: `687cbac06242dc3cac0beb0022280c24af291e0c1e7d3c07d656029b712b3f34`.
  Fleet image: `sha256:d16108bb1b0779f313aca101e24534ebbe6fd1baa6d93056144db74cb5d18908`;
  Vision: `sha256:a7c83be2e0051fb2328758a2bd1cfa1faed2ea885c841dd838db94417449ad66`;
  proxy: `sha256:92285397b659eb03fbe532a76d061738d5f9b0f7f45027a68c662caa44276c3f`.
  Manifest archive/image/SBOM/deployment hashes and loaded image IDs all matched.
- Started the packaged Compose stack with `--no-build` under isolated project
  `rosy-site-smoke-01a3946c`; Fleet, Vision, and HTTPS proxy all reached
  `healthy`. The proxy bound only to `127.0.0.1:18443`; the smoke certificate
  was self-signed and trusted only by the local test client.
- Verified authenticated session and anonymous `401`; fetched packaged
  `/openapi.json` over certificate-verified HTTPS. All 13 published `do` verbs
  matched the interpreter, and `steps.maxItems` was 8. A mistyped motion value
  returned `400 INVALID_NUMBER`; a nine-step request returned `400 TOO_LONG`.
  The robot URL was synthetic and unreachable (`127.0.0.1:1`); no motion was
  dispatched.
- Sent a synthetic ArUco JPEG over the phone WSS protocol while keeping its
  latest-only connection open. Vision projected and posted the sighting; the
  authenticated Fleet API read it back from SQLite (`ceiling_north`, `rosy_01`,
  sequence `78`, pose approximately `[2.0, 1.0]`, calibration `cal-smoke-v1`).
  The sighting path emitted no robot command.
- Test-harness corrections: the first fixture reused the site-user token as
  the CORE-registry token and Fleet correctly refused startup; credentials were
  separated. The first camera probe closed WSS before the latest-only worker
  processed the frame; keeping the phone session open produced the readback.
  The oversized-request oracle was aligned to the observed `TOO_LONG` contract,
  which is now listed in D-292/API Reference v1.40.
- This was Windows Docker Desktop `linux/amd64` with synthetic credentials,
  camera, TLS, and calibration. The host enumerated only AMD Radeon 860M; the
  target RTX 5080 was not exposed, and the current Vision image uses CPU ArUco.
  GPU inference, Ubuntu installation/reboot, physical phone, CORE, robot motion,
  and DEVICE/FIELD acceptance remain unverified. Automatic movement and picking
  remain HOLD.
- After readback, removed only this Compose project's containers, networks, and
  test volume. The revision-pinned candidate remains under `X:\DevTemp`. The
  environment policy rejected recursive deletion of the verified scratch
  directory, so its synthetic bearer/CORE token files were blanked; non-secret
  test config and scripts remain under `X:\DevTemp\rosy-site-smoke-01a3946c`.


## Revision `151607c0` rerun: typed API, console, task persistence, and camera path (LOCAL)

- Source commit: `151607c06c32df87028536196a9439b80fcf3e15`; platform: `linux/amd64`; candidate: `X:\DevTemp\rosy-site-candidate-151607c0`.
- `release.json` SHA-256: `567f4538d4f36b175c291a5b306e7d1ddbf9a26a05de96f4a937b7670ff6e687`; `images.tar` SHA-256: `835ee5eed70111f3dffa8425e2c96653bbfd04036b61403d749e70c54cbb3ab4`.
- Fleet image ID: `sha256:923e3259938c872af2d963d4eff202eedb7413682ada63a0c490d2e7cd6701dc`; Vision: `sha256:14fa6ca7c7deb14e43251c3fb15c9c2b5a118d34f237cb3e8917a28a4d881b27`; proxy: `sha256:92285397b659eb03fbe532a76d061738d5f9b0f7f45027a68c662caa44276c3f`. Independently recomputed archive and all three SPDX SBOM hashes matched `release.json`.
- Packaged Compose config passed and all three services became healthy under isolated project `rosy-site-smoke-151607c0`, bound only to `127.0.0.1:18443`. TLS CA verification passed for `/healthz` and `/console`; anonymous session returned 401 and the named operator session succeeded.
- Packaged OpenAPI exposed all 13 runtime intent verbs and the eight-step maximum. Mistyped numeric input returned `400 INVALID_NUMBER`; a nine-step sequence returned `400 TOO_LONG`; the configured CORE URL was synthetic and unreachable, so no robot command was dispatched.
- Synthetic ceiling-camera WSS JPEG passed through Vision ArUco projection and Fleet HTTPS into SQLite (`ceiling_north`, `rosy_01`, sequence `78`, pose approximately `[2.0, 1.0]`). The sighting path generated no robot command.
- A navigation intent to the unreachable synthetic CORE was recorded `REQUESTED -> QUEUED`; after restarting the Fleet container, the same task and history were read back from the persistent Compose volume.
- The first local fixture attempts correctly failed closed for a missing robot credential and for reusing the CORE registry token as a browser user token. The fixture was corrected with a distinct, ephemeral test credential for each boundary. No tracked application change was needed.
- This was Windows Docker Desktop Linux/amd64, using CPU ArUco, synthetic camera data, temporary credentials, and a local test certificate. The site host's RTX 5080 was not available to Docker. Ubuntu installation/reboot, production CA, physical phone/CORE/robot, GPU inference, and SITE/DEVICE/FIELD acceptance remain unverified; automatic movement and picking remain HOLD.
- Docker Scout emitted a temporary archive cleanup warning while writing the Fleet and Vision SBOMs, but both reports were produced and their recorded hashes verified. Candidate images and bundle remain under `X:\DevTemp` for inspection.

## Revision `1e3de3e8` rerun: merged-main candidate (LOCAL, 2026-09-27)

- Source commit: `1e3de3e8f08217b725e0bcf9771fea8f005b0cc0`; platform: `linux/amd64`; candidate: `X:\DevTemp\rosy-site-candidate-1e3de3e8`.
- `release.json` SHA-256: `d7d491817449212e61ce58ddad02bae2bb077fa3fbc1d61838b8269dab459d77`; `images.tar` SHA-256: `a7601e87c1caaf2ec4cadd9142f97b21700bab54a225700d609256df9d80f97e`.
- Fleet image: `sha256:eb952e7d67bb2e7cb2f69de428ce0e26dd52936abf41cd4f69108d4e126653b3`; Vision: `sha256:14fa6ca7c7deb14e43251c3fb15c9c2b5a118d34f237cb3e8917a28a4d881b27`; proxy: `sha256:92285397b659eb03fbe532a76d061738d5f9b0f7f45027a68c662caa44276c3f`. Independently computed archive and Fleet/Vision/proxy SPDX hashes match `release.json`; Compose `config -q` passed.
- Ran the exact tagged images with Compose `--no-build` in isolated project `rosy-site-smoke-1e3de3e8`, using loopback port `18444`, synthetic credentials, a local test CA, and an unreachable CORE URL. TLS `/healthz`, anonymous `401`, authenticated operator session, all 13 interpreter verbs, the 8-step limit, `INVALID_NUMBER`, and `TOO_LONG` checks passed.
- Synthetic ceiling-camera WSS JPEG passed through Vision ArUco and Fleet HTTPS into SQLite (`ceiling_north`, `rosy_01`, sequence `78`, pose approximately `[2.0, 1.0]`). The operator navigation intent persisted as `REQUESTED -> QUEUED`, and the task plus history survived a Fleet container restart.
- `python -m pytest src/site/fleet/test -q -p no:cacheprovider --basetemp X:\\DevTemp\\pytest-site-fleet-1e3de3e8`: 518 passed, 5 skipped. Focused D-293/harness contract tests: 52 passed, 19 existing evidence-freshness warnings. Harness lint: 0 errors, 19 warnings.
- The first broad pytest attempt used the machine's inaccessible default `X:\DevTemp\pytest-of-livs`; rerunning with an explicit isolated `--basetemp` and disabled cache passed. Initial Compose starts also correctly rejected incomplete test-only robot/user credentials; corrected distinct temporary credentials passed without source changes.
- This remains Windows Docker Desktop LOCAL evidence. The candidate archive was hash-verified; the runtime used the matching locally built image IDs with `--no-build`. No Ubuntu installation/reboot, RTX 5080/GPU inference, production CA, physical phone/CORE/robot, dispatch, motion, or SITE/DEVICE/FIELD acceptance was performed. Automatic movement and picking remain HOLD.

## Follow-up after main `2543315d` integration (SOURCE only)

- Integrated the then-current main commit `2543315d9f014060eeeb9d2ee2a1ae2c6fb4e562`, including Pinky runtime capability truth and Fleet/API contract changes. Regenerated `docs/index.md`; D-293 and D-295 remain separately indexed, and the shared-token ADR is D-294.
- Post-integration tests: Fleet `518 passed, 5 skipped`; runtime capability, intent, D-293 docs, and HMI token contracts `73 passed`; final harness/Fleet-doc/HMI/document-placement checks `98 passed`. Harness lint is `0 errors, 19 existing freshness warnings`. The D-295 physical validation gates remain independent.
- A candidate rebuild for the new integration commit was attempted but Docker failed before the first build step: access denied to `C:\Users\livs\.docker\buildx\instances` and the Docker Engine named pipe. The incomplete X: output was removed. Therefore the `1e3de3e8` package above is the last successful image smoke and does not include the later main integration; there is no packaged Docker evidence for `2543315d` yet.
- Ubuntu host/reboot, RTX 5080 GPU, physical phone/CORE/robot, dispatch/motion, and SITE/DEVICE/FIELD acceptance remain unverified. Automatic movement and picking remain HOLD.

## Revision `4c2b46b2` rerun: current integration branch (LOCAL, 2026-09-27)

- Source commit: `4c2b46b21b8ad77d010aa37e03c084bbe6716cc0`; platform: `linux/amd64`; candidate: `X:\DevTemp\rosy-site-candidate-4c2b46b2-20260927`.
- `release.json` SHA-256: `449d7d571fbc28f4cbebf84f3a66bcc3915263245751e14d4fef7091094bfe95`; `images.tar` SHA-256: `78fb40eb247120fce42487e503381956902b16897619581625789957adafc866`.
- Fleet image: `sha256:a271d2a6c1fd3bdca4e23cfabfe36000bb4de0db05106bce333049fbee56c80f`; Vision: `sha256:8798ebfd32ce37f17d364889e86196c2e9f088b04ec6e6d5e9fd40c360a65531`; proxy: `sha256:92285397b659eb03fbe532a76d061738d5f9b0f7f45027a68c662caa44276c3f`.
- Independently recomputed every deployment-file SHA-256, all three SBOM hashes (Fleet `d714fbff6d0605b7384334f3088b73e2a25fe7eca745e8ac845fc5a7dafb9ad4`, Vision `3d66ccc52f8a08eeca774163365f2660596766e0fbbf652256b38554e96af023`, proxy `e61079b570a93c01780b767bc87d7683ba77f7a8d6f6e964191e5ac02907c57b`), and the archive hash. Candidate Compose config passed; the exact archive was loaded and all image IDs/platforms matched the manifest.
- Ran the candidate images with packaged Compose (`--no-build`) under isolated project `rosy-site-smoke-4c2b46b2`, loopback port `18445`, synthetic credentials/certificate and unreachable CORE endpoint. Fleet, Vision and HTTPS proxy reached `healthy`.
- TLS CA verification and `/healthz` passed; anonymous session returned `401`; the named operator session succeeded. Packaged OpenAPI matched the runtime's 13 verbs and eight-step limit; `INVALID_NUMBER` and `TOO_LONG` were rejected before dispatch.
- A synthetic overhead-phone WSS JPEG passed through Vision ArUco to authenticated Fleet HTTPS and SQLite (`ceiling_north`, sequence `78`, pose approximately `[2.0, 1.0]`). The authenticated operator task was stored as `REQUESTED -> QUEUED`; its task and history remained readable after restarting Fleet.
- Fleet suite: `518 passed, 5 skipped`. CORE/Fleet hub, API, console integration, event API/store and CORE Agent tests: `47 passed`. Docker Desktop Engine and packaged services ran locally on Windows; the host did not expose a usable `nvidia-smi` command.
- Test setup initially encountered exhausted Docker default IPAM pools and an empty `robots.yaml` copied from an old scratch fixture. The isolated smoke used the existing explicit test CIDRs and a non-empty fake robot at `https://127.0.0.1:1`; no tracked runtime source changed for these fixture corrections.
- This remains LOCAL Windows Docker Desktop evidence. No Ubuntu installation/reboot, RTX 5080/GPU inference, production CA, physical phone, real CORE readback, robot dispatch/motion, or SITE/DEVICE/FIELD acceptance was performed. Automatic movement and picking remain HOLD. The candidate and generated synthetic credentials are in X: scratch storage; credentials are not recorded here.


## Revision `4c2b46b2`: packaged CORE Agent event path (LOCAL, 2026-09-27)

- Started the same revision-pinned Fleet/Vision/proxy images on an isolated Compose project with a synthetic robot identity, distinct REST and Fleet pairing credentials, loopback TLS, and unreachable REST endpoint `https://127.0.0.1:1`.
- A synthetic CORE Agent sent HELLO, heartbeat (`seq=4`), and `nav.completed` event (`seq=1`) over `wss://localhost:18446/ws/robots`. Fleet accepted the event; anonymous event-history access returned `401`; the named operator read the event and its payload through authenticated HTTPS.
- Restarted Fleet and read the same event from SQLite, confirming event persistence over service restart. No physical CORE or robot was connected and no command/motion was issued. Generated credentials were blanked after the exact smoke project and volume were removed.
