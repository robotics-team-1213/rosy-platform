# Video reader native integration implementation plan

> **For agentic workers:** Use `superpowers:subagent-driven-development` or
> `superpowers:executing-plans` task by task. Internal coordinator review remains
> within the user's existing D-771 authorization. Each task uses committed remote RED → implementation →
> remote GREEN → independent review. Do not run local pytest.

**Goal:** Connect the bounded R2 MP4 reader to local/HF custody, shared resource
admission, immutable reader receipts, catalog projection and the existing Learning UI.

**Architecture:** The acquisition owner remains the byte and proof writer. A
small enrolled reader execution owner supplies actual service identity, resource
admission and termination evidence; the existing HTTP operation waits for its bounded
result. No new scheduler, background queue or training authority is introduced.

**Tech stack:** Python, existing SQLite compute/volume ledgers, Linux systemd/cgroup
identity, pinned FFmpeg/FFprobe, existing plain JavaScript Learning UI.

**Spec:** [D-771](../adr/D-771-integrated-learning-pipeline-ownership.md) and
[integrated pipeline P1/P2/P7](2026-10-16-integrated-learning-pipeline.md).

Status: internal design review within the authorized D-771 scope, 2026-10-17.
R2 decoder/receipt implementation
and private-tool tests are inputs, not evidence that this integration or a deployed
model PC is qualified. This plan creates no ADR/API reservation and installs nothing.

## 1. Current seams and ownership

| Existing source | Current behavior | Integration change owner |
|---|---|---|
| `learning/curation/perception/learning_pipeline_readers.py` | Advertises and accepts only `image_collection_v1` | HTTP profile selection and dispatch |
| `learning_pipeline.py`, `learning_import_readers.py` | One local/HF reader binding | Profile-specific private configuration selection |
| `local_reader_checks.py` | Native lease, custody recheck, immutable sidecar proof; image limits in cache | Local proof/cache and admission adapter |
| `learning_import_readers.py` | Native lease, completed-attempt proof, SQLite reader receipts | HF proof/cache and admission adapter |
| `asset_readers.py`, `video_reader.py`, `video_reader_mp4.py` | Bounded R2 decoder; temp files currently ambient | Reader algorithm and explicit scratch transport |
| `learning/registry/catalog/acquisitions.py` | Native proof re-read and CAS projection | Profile-specific evidence lookup |
| `learning/registry/catalog/asset_catalog.py` | Public reader runtime allows OpenCV/NumPy only | Exact image/video evidence shape |
| `review_app_web/pipeline.js` | Image-only button and POST profile | Configured reader selection and result copy |

Paths without prefixes above are under `learning/curation/perception/`.
Keep input acquisition manifests, source bytes, native import job states and existing
reader receipt schemas intact. New video evidence lives beside existing historical
proofs. The catalog remains a projection and grants no training eligibility.

## 2. Closed profile configuration

Add a bounded private profile map with exactly the supported keys
`image_collection_v1` and `video_decode_v1`. Each selected profile has a public
`reader_binding` and, for video, a private `execution_binding` reference. Reject
unknown keys, explicit nulls, mismatched runtime keys and duplicate definitions.

- Keep legacy `local_reader` and HF `reader_binding` as image-only aliases.
  Existing R1 configuration and receipts remain readable; do not reinterpret an
  old image binding as video based on file suffix or installed executable presence.
- Public binding stays `code_revision`, `environment_revision`, `runtime`,
  `binding_basis=server_configuration`. Image runtime is exactly OpenCV/NumPy;
  video runtime is exactly FFmpeg/FFprobe. Bind profile and runtime together.
- Private video execution binding pins host, fixed service command/config revision,
  fixed tool pair paths/hashes, shared ledger paths, execution lease, scratch root,
  result root and bounded CPU/memory/storage requirements. No web field selects
  executable, flags, environment, service name, scratch path or tool SHA.
- `/api/learning/pipeline` advertises only configured store/profile/version pairs.
  Existing reader POST keeps `asset_id`, `profile_id`, `expected_generation`.
  Tool paths/hashes and private resource configuration never enter HTTP responses.
- Use one profile lookup for limits/version, cache keys and compatible historical
  lookup. Unknown outcomes are not adopted as successful cached inspections.
  Explicit historical revision lookup remains read-only with current custody checks.

Catalog has one displayed `reader_evidence` per asset today. Preserve that shape:
it describes the explicitly selected profile's last projected evidence. Switching
profile does not merge statuses; old native proofs remain available by revision.

## 3. Actual execution ownership before resource release

`ComputeReservations.claim()` owns a durable intent, not a process. Its
`bind_physical()` requires an actual `.service`, manager InvocationID and cgroup.
`release()` trusts the owner to prove no pending launcher and actual quiescence.
The ordinary synchronous image subprocess establishes none of those facts.

The existing perception owner is bound to perception requests, training receipts
and `perception-workflow/v1`. `ManagerReferences.hold()` hardcodes the perception
unit; `NativeProcesses.unit()` and its constructor enforce that service profile;
`WorkflowResources._snapshot()` validates perception execution. These cannot be
aliased unchanged. Do not fabricate a perception ticket, use the long-lived web
service as the decoder invocation, or invent physical values for the ledger.

Factor only the closed service-identity, launcher-fence and manager-retention
primitives needed by both enrolled profiles. Preserve perception's exact command,
source and receipt validation. Tools composition injects shared ports into curation;
curation must not import training. The reader journal owns custody/proof operation
identity, not a second implementation of the P3 launch/retention lifecycle.

Implement the smallest separate execution port for the existing reader operation:

1. Curation owns an exact `ReaderExecutionRequest` containing project/requester,
   asset/custody digest, profile, binding digest, scratch input/result references,
   and a unique native job/attempt/invocation. No account tokens are persisted.
2. Tools composition creates an enrolled one-shot reader service using a proposed
   fixed `reader-exec <opaque-id>` sibling mode of the D-446 installed controller.
   It selects an exact installed reader profile, command and receipt schema, never
   caller argv. Reuse strict signed source/environment closure and canonical
   inherited `rosy_model_code.work_lock`; do not launch unsigned checkout Python.
   Proposed composition files are
   `tools/perception/video_reader_runtime.py`, `video_reader_service.py`, and
   `learning/curation/perception/reader_execution.py` for the port/owner journal.
3. Under the actual D-446 admission lock, probe fresh CPU/RAM and effective
   ancestor/service limits, claim common compute plus scratch/proof capacity,
   and persist exact request/claim identity. Acquire `RefUnit` **before**
   `StartUnit`; persist the launcher fence before requesting start. Observe exact
   MainPID/InvocationID/cgroup, bind physical admission and recheck limits before
   opening the worker gate. Test each boundary's crash recovery separately.
4. Use the same configured compute/volume databases as other Learning owners.
   Video is CPU-only (`gpu=null`). A busy slot is retryable busy, without a decode
   or pending-work queue. Duplicate handoff adopts only the same request/binding;
   uncertain start or restart must not trigger automatic relaunch.
5. Reuse `deploy/site/model_code_execution.py:supervise()` with its child pidfd,
   gated start and independent deadline loop. Extend only the closed reader policy
   and actual broker enrollment required by that protocol. Live Account checks run
   through the broker during execution and finalization, outside the deadline loop;
   Account stalls cannot extend a permit. Keep the existing at-most-15-second permit
   bound, initial claim before child creation, renewals and independent expiry.
6. The service reads the admitted private snapshot, checks its digest, then uses
   sealed memfd and the fixed decoder protocol. Keep live authority supervision
   through final result/proof fsync, using the existing supervised finalizer port.
   Acquisition owner still validates current custody and fresh authority before
   accepting/publishing its proof. No proof is a stored grant on later requests.
7. Cancellation/shutdown closes the gate and stops only the owned invocation.
   HTTP disconnection is not process death or quiescence. Release requires settled
   launcher state, actual whole-subtree quiescence, completed owned scratch cleanup
   and exact claim identity. Keep claims on timeout, uncertain acknowledgement,
   blocked cleanup or manager loss. Recovery uses factored existing launch-fence/
   retention rules, never restored grants, foreign unlink or automatic new attempts.

The HTTP call remains synchronous and bounded. If stop/reconciliation exceeds its
response budget, return unavailable and retain the journal/claims. The next explicit
operation or startup reconciles the old owner first; no independent polling scheduler.

Add a fixed service template only after the port's actual manager tests pass, under
`deploy/model_pc/rosy-learning-video-reader@.service` (proposed path). Include command
closure, execution account, effective CPU/memory limits, stop semantics and private
input roots in validation. Creating the template is not installation authorization.

## 4. Scratch, memory and proof capacity

Claim storage before allocating payload temp files or launching the decoder.
Current local `_save()` and HF `_claim()` occur after decoding and are insufficient
for video. Preserve their proof authority while moving video admission earlier.

- Require registered scratch/result roots with pinned directory custody and actual
  volume identity. Pass an explicit scratch location/descriptor into all temporary
  allocations; never depend on `TMPDIR`, default `/tmp`, cwd or browser paths.
- Current temp-file upper bound is 48 MiB: IPC input 24 MiB, outer worker output
  8 MiB, one active tool stdout/stderr pair 16 MiB. Recompute this budget if the new
  service handoff adds another copy or result file; do not silently retain 48 MiB.
- Round each allocation to filesystem block size and account for directories,
  persisted request/result journals and receipt publication. Reserve proof capacity
  before decoding too: local immutable proof plus directory overhead, or bounded
  HF SQLite transaction/journal growth. Measure/limit SQLite growth with its actual
  configured journal mode; MAX_PROOF_BYTES alone is not a database-space bound.
- Charge different scratch and proof volumes separately. On the same volume share
  its capacity accounting rather than count free bytes twice. All owners use the
  existing `VolumeReservations` configured database and owner-domain bindings.
- The 1 GiB decoder `RLIMIT_AS` is per process, not aggregate job memory. Include
  wrapper, decoder, memfd, bytes/base64 and IPC buffers in a measured bounded service
  `MemoryMax`; validate host/effective limits against that requirement. Runtime
  qualification records the measured fixture peak and configured headroom.
- Cleanup removes only the current operation's owned scratch after actual service
  quiescence. Interrupted retained scratch remains charged until recovered; existing
  acquired originals and prior proofs are never reclaimed by this operation.

## 5. Implementation tasks and test ownership

Each task first commits its regression tests, runs remote RED on that commit,
implements within its owned files, then commits and runs remote GREEN. The root
coordinator manages commits/test logs and independent review; parallel workers must
not edit the same owner files. Proposed test names below are acceptance work, not
claims of existing coverage.

### Task A — Profile selection and historical evidence compatibility

- [ ] Add config/profile lookup tests in `test/learning/perception/` for legacy R1,
  exact video runtime, duplicate/unknown profile rejection and private-field redaction.
- [ ] Implement closed configuration in `learning_pipeline.py`,
  `learning_import_readers.py`, and a small `reader_profiles.py` if needed.
- [ ] Update profile limits/cache selection in `local_reader_checks.py`; exercise
  terminal video cache adoption, unknown retry, R1 cache preservation and read-only
  explicit historical lookup. Do not expose video execution until Task B is ready.
- [ ] Remote suite and independent evidence/ownership review.

### Task B — Bounded reader owner and shared admission

Own the proposed reader files, narrow fixed-mode dispatch changes in
`deploy/site/rosy_model_code.py` and a cohesive sibling to `model_code_workflow.py`,
plus the reviewed shared primitives extracted from manager/process/resource owners.
Coordinate these shared edits with the active perception worker before changes.
Reuse `model_code_execution.supervise()`; any required protocol extension must
preserve existing phase, gate, finalizer and independent-deadline tests.

- [ ] Write owner tests for compute contention, insufficient effective CPU/RAM,
  absent/wrong physical identity, scratch/proof volume contention and identity drift.
- [ ] Implement the port/journal and fixed signed reader mode from section 3;
  minimally factor shared launch/retention identity primitives and preserve existing
  perception behavior. Adapt `video_reader.py` to explicit admitted scratch.
- [ ] Test actual service launch/adopt, lost acknowledgement, caller termination,
  decoder/descendant kill, delayed stop, restart reconciliation and retained claims.
  A fake manager unit test does not satisfy actual service/cgroup acceptance.
- [ ] Verify no arbitrary command/flags, no fabricated identity, no foreign cleanup,
  no launch on admission failure, no release while a launcher/descendant may survive.
- [ ] Exercise signed-source/environment drift, inherited-lock loss, broker Account
  revocation/stall during decode and final fsync, independent deadline expiry,
  RefUnit-before-StartUnit ordering, HTTP disconnect and finalizer failure. Run the
  existing D-446/perception supervisor/retention regressions after factoring.
- [ ] Remote RED/GREEN, actual isolated service evidence and independent review.

### Task C — Local and HF native proof producers

- [ ] Extend `local_reader_checks.py` and `learning_import_readers.py` to invoke the
  admitted reader port under their existing native leases. Keep source/receipt and
  HF job/attempt/producing-attempt ownership unchanged.
- [ ] Actual MP4 local acquisition → decoder → native proof; actual MP4 bytes from
  a deterministic fake HF provider → real importer → decoder → native proof.
  These tests run the real video decoder; provider fixtures need no live HF account.
- [ ] Check unchanged original hashes, authorization loss during decode, input
  replacement, damaged last frame, external-reference rejection, runtime/config
  drift, failed proof persistence and claim release only after quiescence.
- [ ] Remote RED/GREEN with both native proof suites plus R1 regression and review.

### Task D — Catalog and existing HTTP/UI closure

- [ ] Update `acquisitions.py` profile binding selection and
  `asset_catalog.py` exact profile/runtime validation. Retain owner re-read and CAS.
- [ ] Update `learning_pipeline_readers.py` and `review_app_web/pipeline.js` to use
  configured profiles; no new endpoint or decoder settings in HTTP.
- [ ] Test local and HF real-video HTTP success → exact native proof → catalog
  evidence, stale generation conflict, proof mismatch, other project denial and
  fresh-account changes. Verify current bytes before projecting historical proof.
- [ ] Browser exercises actual image/video profile selection, status/reason/profile
  display, permission removal, disabled unconfigured video and redacted responses.
  Browser fixtures must not replace the video verifier with a fabricated success.
- [ ] Remote RED/GREEN, actual browser execution (report skips), independent review.

## 6. Completion and evidence limits

The offline R2 decoder/receipt milestone can close first. It does not close this
plan: the fixed signed reader mode and local/HF HTTP/browser acceptance remain
required implementation work within the authorized scope.

- [ ] Source, native owner tests, actual decoder, actual service/cgroup tests and
  browser tests are recorded separately with committed revisions and known failures.
- [ ] Run required harness/architecture checks for new modules/templates; root owns
  log/index generation and any required registry changes outside this plan file.
- [ ] All receipts and originals survive application restart; a held stale claim
  blocks new decoding until owned execution is conclusively reconciled.
- [ ] No evidence in this slice establishes installed-host qualification, live HF
  account rights, training eligibility, model quality, publication or robot activation.

Remote invocation: `python tools/remote/remote_pytest.py --log-dir <external-log-dir>
-- <committed-owned-test-paths> -q`, followed by `test/known_failures.py` on that log.
Use the session-approved external log directory; never substitute local pytest.
Document actual manager/decode/browser evidence and skips before marking this plan
complete. Missing target-host enrollment is a deployment prerequisite with an exact
qualification checklist, not a reason to omit the testable owner implementation.
