# Perception candidate lineage implementation plan

Status: executable subplan within the user's approved D-771 scope, 2026-10-17; contract details are under internal cross-review. Root coordinates the existing tests-first source gates; this is not a new user-approval requirement.

**Goal:** Trace a verified perception candidate to its actual training dataset, fixed evaluation exclusions, parent model, current human review and registered source media without making the catalog an execution or approval authority.

**Architecture:** Native owners verify immutable provenance and return a typed, path-free report. The existing catalog projects references and parent links; the existing Learning UI reads the report. Keep the catalog schema, Coordinator queue semantics and `verify_outputs` three-field result unchanged. Add no graph database, executor or review-label authority.

**Tech stack:** Existing Python native owners, immutable JSON receipts, AssetCatalog SQLite CAS and Learning HTTP/UI.

**Spec:** [D-771](../adr/D-771-integrated-learning-pipeline-ownership.md), [integrated plan P3](2026-10-16-integrated-learning-pipeline.md), [native workflow plan](2026-10-16-perception-native-workflow.md), and [bounded storage plan](2026-10-17-perception-storage-progress.md).

## Existing evidence and missing link

- `learning/registry/catalog/models.py:38` verifies native completion twice but emits `parents=[]`.
- `learning/training/perception/workflow_candidate.py` already verifies the selected cycle, trainer Job input signature and receipts, current review, dataset/eval bytes, parent files and candidate manifest. `workflow_completion.py` binds that verification to the actual terminal ticket and immutable completion receipt.
- `review_dataset.py:481` records video/frame/image/mask identities, source proof hashes, export seal, classes and review authority in the generated dataset. Its `disjoint_from` and evidence files bind evaluation exclusions. These are native provenance, not original media AssetRefs.
- `learning/registry/perception/store.py:157` provides immutable dataset `name@content_sha` identities and fixed evaluation directories. Parent recipes instead carry private model/TorchScript paths; their hashes do not establish an acquisition-owner AssetRef.
- `asset_catalog.py:77` already accepts same-project parent AssetRefs. Its descriptive metadata deliberately has no arbitrary report field. Catalog references are not admission proofs.

This slice addresses P3 traceability. Fixed eval inputs are not an independently evaluated model or a P6 qualification report. Candidate status remains candidate; no intake, READY, activation, publication or quality claim follows from lineage.

## Constraints

1. HTTP supplies an existing opaque run ID only. It cannot supply refs, mappings, receipt JSON, source paths or revision overrides.
2. Native owners remain responsible for current authorization, current review, original input bytes and terminal completion. Catalog data never grants training or completion authority.
3. Mapping uses explicit enrolled owner references and exact owner-verified files. Do not discover parents by filename, directory name, matching hash, model label or catalog search.
4. No mutation of original review labels, dataset bytes, trainer Job, worker outcome or existing completion proof to add lineage retroactively.
5. No imports from training in curation or catalog. Tools composition injects structural callbacks. Default/Windows non-native app behavior stays unchanged.
6. Bounded reads use the existing no-follow descriptor rules. No authority/network callback executes while a catalog/owner SQLite transaction is open.
7. Keep each source module below its applicable cap. Split native lineage verification into one cohesive helper rather than growing `workflow_owner.py`.
8. All pytest/browser verification runs remotely against committed revisions through the existing runner. Root owns commits and test execution; local checks are AST/diff only.

## Proposed contracts to settle before tests

### Immutable input mapping

Add a lineage-capable private binding schema `rosy.learning.perception-workflow-binding/2`. Preserve `/1` parsing and execution as legacy; it cannot claim complete registered lineage. Version 2 adds exactly `lineage_inputs: {path, sha256}` using the existing referenced-file rules. Do not change the ticket schema: its existing binding digest binds this reference.

The referenced canonical document uses schema `rosy.learning.perception-lineage-inputs/1` and exact fields:

| Field | Value |
|---|---|
| `schema` | Fixed schema above |
| `project_id`, `store_id`, `binding_id` | Exact enrolled scope |
| `parent_model` | One mapping described below |
| `source_media` | Nonempty bounded list of explicit mappings described below |

Each source mapping has exact `{ref, receipt_digest, video_file, source_video_sha256, source_proof_sha256}`. `ref` is an existing media AssetRef; receipt/hash values are lowercase SHA256. `video_file` is the explicitly enrolled owner-relative member, not a path discovered by hash. The separately verified curation source-proof document and actual selected review frames must establish the session/capture/frame association. That proof need not have existed inside the original acquisition bundle. A matching video hash alone cannot establish the association or choose a different asset.

The parent mapping has exact `{ref, receipt_digest, files, manifest_sha256, onnx_sha256, torchscript_sha256}`. `files` has exactly `{manifest, onnx, torchscript}`, each a distinct owner-relative member. `ref` is an existing model AssetRef. Match these explicit members to the actual recipe's model manifest, ONNX file and separate TorchScript file by verified bytes and their enrolled role. Do not discover the members by hash. Its actual acquisition-owner receipt must cover all three files. Candidate `verify_outputs` covers the exported ONNX bundle but does **not** establish custody of a separate TorchScript input: acquire/register an actual three-file bundle first where necessary. Missing coverage blocks the complete-lineage preparation capability; do not invent a parent identity.

Bounds: canonical document at most 1 MiB, at most 1024 source mappings, no duplicate ref/proof pairs, one parent, exact field sets, same project and registered stores. Sort mappings canonically before hashing. These are proposed initial limits, to be checked against existing registered source bundle limits in task L1 before freezing tests.

The trusted preparation path resolves owner receipts and publishes this mapping exclusively **before** publishing a lineage-capable selected request. The binding pins the immutable mapping first. Preparation verifies that every selected source is explicitly covered, and that the parent is the selected recipe's parent. A binding may cover multiple registered sources; the final report contains only sources actually selected into the dataset. No authority is inferred for unused sources.

The tools composition supplies this exact structural port from a trusted registered-store resolver:

```text
verify_registered_input(actor, *, project_id, ref)
  -> {ref, receipt_digest, files: [{path, bytes, sha256}, ...]}
```

Its closed return describes the complete actual owner receipt's payload-file closure, sorted by `path`; it is private, not the HTTP report. Maximum canonical return size is 4 MiB and 10,000 unique files. Relative POSIX paths are nonempty, at most 1024 UTF-8 bytes, contain no control characters, absolute prefix, backslash, empty component, `.` or `..`. `bytes` is an integer, not bool, in `[0, 2**63-1]`; all hashes are SHA256 lowercase hex. Enforce exact fields, duplicate rejection and registered store/project identity before resolving anything. Requests take an existing validated AssetRef only, never a root/member path or owner implementation selected by HTTP.

The local implementation resolves the ref's registered destination root and native request identity, then calls `inspect_local_receipt(project_id=project_id, receipt_root=trusted_root)`. That function is not user authorization: the resolver performs fresh original actor/project view and import authorization before and after native I/O, verifies receipt request/destination/kind/revision against the ref, and maps its verified file rows into the closed return. The HF implementation dispatches only to that store's configured `LearningImports`, calls `verify_completed(actor, project_id, ref.native_id)`, checks the returned exact `asset_ref`, manifest digest, completed producing attempt and declared file closure, and preserves its current selected-connection credential/rights checks. Re-read native evidence and compare before returning; perform final fresh actor authorization after the last file/receipt read. Never use `catalog.get()` as custody verification. Closed named resolver registrations belong in trusted tools configuration; no reflection or generic callback supplied by a client.

The existing HF return already includes verified `files` through `learning_import_receipts.py:192,232`; reuse these rows and its manifest digest, with no new raw-SQL decoder or caller-supplied manifest. L1 tests bind that actual return to the structural resolver before wiring. A missing registered resolver or incomplete bundle is a fixed preparation failure. Legacy lineage unavailability is reserved for genuinely legacy completed bindings, not failed new mapping checks.

### Native report port

Add `WorkflowOwner.verify_lineage(actor, native_ref)` backed by new `workflow_lineage.py`. No caller-supplied proof, version or mapping argument. It reads the actual terminal ticket, existing completion proof, pinned binding/mapping and original verified files. It calls the existing completion verifier and rechecks file identities and current authority after all owner/proof reads before returning.

Successful report has exact fields:

```text
schema: rosy.learning.perception-lineage/1
status: verified
native_ref, receipt_digest, model_ref
training_dataset: {ref, receipt_digest}
eval_exclusions: [{ref, receipt_digest}, ...]
parent_model: {ref, receipt_digest}
source_media: [{ref, receipt_digest}, ...]
review: {workspace_id, generation, decision_sha256, export_contract_sha256,
         classes_sha256, classes_signature}
```

All refs use the existing AssetRef schema. `receipt_digest` at top is the unchanged actual completion digest, and `model_ref` equals its sole output. Nested receipt digests bind each input owner's verified evidence. The canonical UTF-8 report is at most 1 MiB; exactly one training dataset and parent model, 1–1024 distinct selected source entries and 1–64 distinct eval exclusions. Sort ref lists by canonical AssetRef encoding and reject duplicates. `review.generation` is an integer, not bool, in `[0, 9000000000000000]`; `review.workspace_id` must satisfy the existing enrolled workspace identifier validator and equal the binding workspace exactly. `decision_sha256`, `export_contract_sha256`, `classes_sha256` and specifically `classes_signature` are each exactly 64 lowercase hexadecimal characters: the latter is the existing canonical-classes SHA256, not a list or arbitrary label. Require exact schemas/fields throughout, including the smaller unavailable variant.

Generated dataset/eval receipts use the exact canonical body `{schema, ref, manifest_sha256, files}` with `schema=rosy.learning.perception-input-closure/1`; `ref` is the native dataset/eval AssetRef. `files` is the complete sorted relative-path closure, each entry exactly `{path, sha256}`, including `manifest.json`, with the same path bounds above, at most 10,000 entries and 4 MiB canonical body. `manifest_sha256` hashes the actual raw manifest bytes. Reuse `read_fixed_manifest()` and `content_sha()` from the native Store, with descriptor-safe capture/recheck around their reads: the complete captured file list must reproduce the ref revision using Store's sorted `relative + NUL + SHA + LF` algorithm. Reject changed/missing/extra files, links and inconsistent repeated reads; do not redefine content identity.

Define canonical JSON as UTF-8, `sort_keys=True`, `ensure_ascii=False`, separators `(',', ':')`, `allow_nan=False`, plus one LF. Nested `receipt_digest = SHA256(domain + canonical_body)`, where domain is exactly `b'rosy.learning.perception.dataset-closure/1\0'` for dataset and `b'rosy.learning.perception.evalset-closure/1\0'` for evalset. The body excludes consuming run/native execution ref, current review generation, wall-clock time and absolute paths. Immutable review evidence already inside the dataset is naturally covered as bytes. Thus a fresh review check or another consuming run does not churn the same input asset's digest.

Dataset/eval native IDs reuse existing store names and content revisions: `kind=dataset|evalset`, `native_id=<existing native name>`, `revision=<content_sha>`. The native binding supplies project/store identity. Do not expose a filesystem path as `native_id`.

For a valid completed legacy `/1` binding, return exactly `{schema,status,native_ref,receipt_digest,model_ref,reason}`, with `status=unavailable` and `reason=legacy_unbound_lineage`. Validate the actual completion first. Corrupt/missing new mapping, changed owner bytes, revoked access or stale review are failures, never silently downgraded to legacy. Return fixed public errors; retain diagnostic detail only privately.

Keep `verify_outputs()` exactly `{native_ref,receipt_digest,output_refs}`. Existing completion proof bytes need no rewrite: the new binding digest already binds mapping bytes. The report is a fresh derivation from that closure, not a portable proof or new terminal result.

### Catalog and HTTP projection

Keep AssetCatalog's schema unchanged. Add a structural lineage callback to the model projection path; compare its native reference, completion digest and model ref with the fresh `verify_outputs` result. Recheck both before the final authorized CAS.

- Generated training dataset observation: source-media refs as `parents`.
- Fixed evalset observation: no invented source parents; verified native byte closure only.
- Candidate model observation: training dataset and parent model refs as `parents`.
- Eval exclusions, review revision and typed relationship roles remain in the native report, not generic catalog metadata or model training parents.

Project input observations idempotently before the model observation. A partial projection can leave independently verified inputs visible; it must never leave a model with invented or unverified parents. Generation conflicts require a fresh native verification and normal CAS retry, not an unconditional overwrite. Existing model rows with empty parents require explicit expected generation when upgraded. Legacy unavailable reports keep their existing observation unchanged.

Add `GET /api/learning/runs/<run_id>/lineage` through the existing facade and tools-injected runtime port; reject query parameters and request bodies. Require a current authenticated session in the run's project, exact run requester identity, and fresh view/manage/import authority, matching native completion access. Resolve the existing run's perception native ref server-side; only an actually succeeded native ticket may return a verified or legacy-unavailable report. Check the same actor/session after all native/registered-source reads immediately before HTTP return; logout, project switch, selected HF connection revocation or capability removal denies rather than returning a cached graph. Other-project/other-requester access is denied without revealing native data. Use fixed public errors: 400 malformed request, 403 authority/requester denial, 404 absent accessible run, 409 not completed or changed proof, 503 unavailable configured native/source owner. No path/query/body overrides, private paths or raw exceptions. Keep current API version 1.246; update its current contract documentation without reserving another version or ADR.

## Execution and ownership

Unqualified native Python filenames below are under `learning/training/perception/`; unqualified test filenames are under `test/learning/perception/`. Tools composition is `tools/perception/learning_pipeline_runtime.py`; facade/routes are under `learning/curation/perception/`. Ownership must be assigned before parallel edits; no task may revert another task's changes.

For every task: freeze failing tests, root commits and runs remote RED, inspect the actual failure cause, then authorize source changes. Freeze source after AST/diff review; root commits and runs the focused GREEN plus affected existing tests. A skipped test or fixture error is not RED/GREEN evidence. Do not commit from implementation agents.

### L1 — Enrolled mappings and trusted preparation

**Own:** `workflow_binding.py`, new `workflow_lineage_inputs.py`, the narrow trusted preparation hook in `review_pipeline.py`; tools runtime injection only after native ports freeze. Coordinate storage ownership before touching preparation. Tests: new `test_workflow_lineage_inputs.py` and narrow existing binding tests.

1. Inventory existing local/HF/model owner verifier call signatures; freeze exact structural resolver contract and byte-coverage limits with root. An unresolved parent model verifier is a blocking contract gap, not a fake test grant.
2. RED: immutable mapping before request publication; wrong project/store/owner/ref/revision/receipt, incomplete TorchScript coverage, unknown source proof, duplicates, forged same-hash alternate asset, symlink/oversize/future schema and mapping drift all reject. Legacy binding still loads but lacks lineage capability.
3. Implement bounded mapping loader and exclusive publication using existing native custody rules. Validate selected source membership without admitting disconnected/unselected review frames.
4. GREEN: new mapping/binding tests plus existing selected-cycle and review preparation/admission tests. Verify unchanged logical cycle key, request idempotency and attempt budget.

### L2 — Fresh native lineage verification

**Own:** new `workflow_lineage.py`, narrow `workflow_owner.py` forwarding port and any cohesive read-only candidate helper extraction. Do not duplicate completion SQLite decoding. Tests: new `test_workflow_lineage.py` reusing actual terminal/candidate fixtures.

1. RED: original dataset name/content revision, all fixed eval refs, selected source memberships, parent bundle and human review identity are derived from real files/owner receipts.
2. Cover changed input after first verification, role revocation after last mapping/manager I/O, stale/retracted review, wrong physical/attempt/spec, forged completion, proof unavailable, legacy unavailable and changed source-owner receipt. Require unchanged native ticket/Job/outcome/proof bytes after both success and failure.
3. Implement report from actual terminal completion; preserve manager-retention/whole-unit-quiescence rules and final fresh authorization. Reuse existing candidate closure checks rather than accepting its JSON as a grant.
4. GREEN: lineage tests plus completion, retention, candidate and late-authorization regressions. Verify nested input proof digests stay stable across different consuming model runs.

### L3 — Catalog projection and path-free report route

**Own:** `learning/registry/catalog/models.py`, tools runtime structural composition, narrow pipeline facade/routes and `docs/reference/learning-pipeline-api.md`. Tests: catalog structural tests and new native HTTP lineage cases.

1. RED: model parents are exactly training dataset plus enrolled parent; dataset parents are exactly selected source media; eval exclusions never become training parents or model-evaluation reports.
2. Test repeated projection, two runs sharing inputs, explicit generation conflicts, existing empty-parent row upgrade, failure after input projection, late revocation and native report/output digest mismatch. No model write follows denied verification.
3. Implement projections and run-ID-only route without training imports in catalog/curation. Public report has no paths, credentials, private registry/config identifiers or caller-grant flags.
4. GREEN: catalog/HTTP/default-app import boundary tests, mixed HF/native runs and existing options/create/advance/cancel behavior.

### L4 — Existing UI and actual composition acceptance

**Own:** existing `review_app_web/runs.js` and minimal existing Learning markup; focused browser test and extension of `test_learning_pipeline_native_execution.py`. Coordinate ownership before edits.

1. RED: existing model/run row displays separate training dataset, eval exclusions, parent model, selected sources and current review revision. Legacy displays lineage unavailable, not an empty verified graph.
2. Preserve session epoch/preflight behavior: account switch/logout clears old report, denied reads show fixed errors, busy/retry controls do not launch training. Test narrow/mobile layout and path redaction.
3. Extend actual HTTP→supervisor→worker→native completion→catalog acceptance. Worker must produce its own Job/outcome/receipt; test may not backfill lineage into them after exit. Include role revocation and mapped-source change before final acceptance.
4. GREEN: opted-in Chromium with zero skips, actual native composition cases and affected old browser regressions. Record exact committed revision and fixture seams.

## Review focus and completion evidence

- Same bytes in two unrelated assets must not transfer source ownership: L1 explicit-owner tests.
- One dataset consumed by two model runs must not acquire run-specific receipt churn: L2/L3 replay tests.
- Review or permission changes during final I/O must deny even if the first proof was valid: L2/L3 late-I/O tests.
- Partial catalog projection must not advertise complete model lineage: L3 failure/CAS tests.
- Fixed eval exclusions must never appear as independent model evaluation or training data: L3/L4 typed-role tests.

Completion of this subplan requires all four tasks, remote executed regressions and actual worker-produced lineage readback. Structural model/parity fixture bytes prove plumbing and custody only. Actual CPU serializers, signed-source checks, installed-service acceptance, numerical parity and independent model-quality evaluation remain separately identified evidence. This document does not declare full P3 or the integrated pipeline complete.
