# Pinky camera learning pipeline composition

User scope: complete source and isolated integration, without push, real approval invention, live service/GPU/model activation or safety HOLD overrides. Actual driving is a separate single cumulative physical-distance budget of at most 0.20m; no automatic retry or reset.

## Composition

Reuse camera and perception producers, existing draft catalog, exclusive Pinky review app, current/export transport and immutable store. Classical threshold observations and learned model predictions keep separate source identities. Draft labels never become human GT automatically.

The trusted producer constructs `ReviewPipeline` with explicit source proof paths, scratch placement, dataset name and optional sealed evaluation companions. The existing cycle scans decisions, then this context independently validates delivered current authority and its persisted transport highwater, builds the dataset, opens fresh `IndexedReview` before exclusively publishing an immutable research request, and supplies that exact owner context to `train_job.run`. The default cycle CLI has no indexed grant; an indexed request without a context is rejected before trainer invocation.

`review_pipeline.py` is the explicit owner entrypoint. Its private config contains `cycle` (existing learning cycle configuration) and `review` (source proof paths, staging parent, dataset name, optional companion paths and bounded authority age). Do not place site paths or secrets in the public repository. This is producer configuration, not a new external API or a receipt-based admission mechanism. Running it against an eligible real dataset may train; source/isolated verification uses synthetic fixtures only.

Requests use one stable raw capture for hashing and parsing, reject duplicate keys, and publish atomically with exclusive hard-link creation. Cycle Job locking, persisted highwater and terminal states survive restarts. Logical GT identity excludes only authority generation and decision digest, retaining frame/version/mask/class/source identities, source proof bytes, evaluation versions, companion seal and owner gate/camera bindings. Generation-only refresh neither retrains completed GT nor resets attempts. Different immutable byte provenance uses its own training Job directory while retaining the logical attempt budget.

The same sealed companion inputs reach build and private reconstruction. Companions provide exact original evaluation lineage and conservative exclusion, with all active versions reconciled. They do not override missing collection assertions, synthesize current manifest fields, relax candidate PNG decoded-pixel proof, or make eval JPEGs qualified. Captured dataset/eval bytes and companion resources are immutable; Windows private snapshots use extended paths to retain nested hash evidence and clean up without dropping files.

Existing trainer evaluation/champion comparison, intake, final authority check before READY, delivery shadow and rollback remain their existing owners' behavior. CORE remains the only final command publisher, with fresh lane evidence, mode, obstacle and safety gates. Source/isolated completion is not device activation or actual driving acceptance.

## Tests and acceptance

- Synthetic lossless source videos, explicit indexed masks and disjoint evaluation inventory: build -> immutable request -> actual private admission -> isolated trainer boundary, plus synthetic stage pass/rejection -> actual READY publisher.
- No approved masks, expired/wrong workspace/missing transport highwater, revocation during build/request staging/restart, source/eval/companion mutation, gate/config changes, duplicate requests and generation-only retry-budget refresh deny or retain terminal work.
- One-capture request regression reproduces and rejects hash/body replacement races.
- Evaluation companion inventory, canonical full-row labels digest, exact accepted-row/frame relation, stable resources and pre/post publication checks are independently reviewed.
- Existing model intake/READY/compare/delivery, shadow/rollback/paint and CORE line/camera suites run separately; optional skips remain explicitly unverified.

Actual pending masks, unverified original JPEG decoded-pixel conversion, collection-group assertions and physical stopping bounds remain real blockers. Synthetic approvals and synthetic evaluation receipts are never promoted into actual training or operational evidence.
