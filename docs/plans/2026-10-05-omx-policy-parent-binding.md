# OMX policy execution and admitted Action parent correlation

## Scope and authority

This implements the next read-only composition from D-449 policy artifacts,
D-386 original asynchronous goal facts, D-336 admitted local Action grants, and
D-282/D-369 execution/stop ownership. It is private in-process evidence, not a
new Action kind, REST/UDS method, issuer, policy executor or learned-task grant.
PICK_PLACE and CELL_TRANSFER retain their existing permitted goals/recipes.
Matching identities never authorize unconstrained policy targets under them.

The root owns ActionRunner/ActionStore readback and local execution composition
in `feat/omx-policy-parent-binding`. Existing policy reviewer independently
reviews these sources. The exclusive GUI owner and current export protocol are
unchanged. Product writes use the registered `policy-parent` worktree; evidence
and pytest scratch use X:/DevTemp/policy-parent only. No push, installation,
GPU/actual learning request, model activation, service change or robot motion.
The user's ONE TOTAL physical distance limit remains <=0.20m across robots,
attempts and stopping travel; none of these HOST checks consumes that budget.

## Why this composition

PolicyExecutionJournal already retains original lease/candidate/command intent,
installed file bytes and accepted ROS goal callbacks. It explicitly does not
assert that the lease's Action exists. Fleet offline joins only validate supplied
receipt schemas and Episode sources. A textual lease/receipt match can otherwise
hide an absent parent or a forged SUCCEEDED outcome.

The chosen composition is a runner-minted, process-local read capability plus
an exact current-receipt verifier. Accepting standalone supplied identity objects
would not establish admission. Adding learned executor semantics or a new public
Action kind would require a separate authority contract and is not implied here.

## Implemented read path

1. `ActionRunner._policy_parent_for_validated_grant` authenticates the actual
   mapped peer, enabled runner, registered executor, full grant digest/expiry/
   workcell/config/current epoch/generation and original stored Action attempt.
   Parent/event/phase rows are read under one SQLite BEGIN snapshot.
2. Mint is possible only for the original nonterminal admitted attempt. The
   capability pins runner/store/file identity, principal, complete grant bytes,
   creation identity and the existing append-only event prefix. It cannot be
   serialized or reconstituted from a matching snapshot. Restart-UNKNOWN does
   not renew it. This is an internal trusted-process capability, not a sandbox
   or cryptographic defense against arbitrary code controlling the same process.
3. `correlate_parent` requires that capability, the native policy journal, command
   identity, and original bytes of the current owner GET receipt. It compares the
   complete D18 projection, including current state, actual goal, event watermark,
   observed time and bounded phase summaries. Old receipts are not accepted as
   current; an historical event reconstruction is a separate future path.
4. Full lease/parent identity, installed policy revision and manifest/controller/
   effective config/model/normalization/evaluation byte closure are checked.
   Original accepted goal/event sequence must match the current Action or phase;
   an internal command UUID is not an accepted ROS UUID. SUCCEEDED additionally
   requires successful native terminal facts. Driver success never proves task
   success or measured stop.
5. Parent, native and installed source reads are compared again. After result
   hashing, the last lightweight capability validation checks peer/grant/config/
   fence, provider/store identity and expiry. Its aware clock sample follows
   every provider callback; the callback cannot hide expiry by taking time after
   an earlier sample. Changes deny the correlation without
   deleting, relabeling or replacing native raw terminal facts. This is a stable
   bounded read across two stores, not a distributed atomic execution fence.
6. A capability minted before terminal completion may read that SAME original
   attempt's later terminal result. A capability cannot be minted retroactively
   from terminal/reopened/restarted records. It never permits dispatch or replay.

## Evidence and qualification boundary

The return preserves the original receipt JSON and SHA, exact private parent and
native snapshot digests, installed source revision, policy revision and actual
goal. `execution_authorized`, `episode_fleet_qualified` and
`inference_consumption_verified` remain false; `task_outcome` remains unknown.
A digest/path is never filled into the existing optional wire `journal_id`.
The current OMX demonstration Episode profile still requires its own original
recording and owner-journal provenance. This private correlation is a prerequisite,
not a substitute for that profile or accepted Fleet join.

HOST fixtures use a synthetic installed model/authority and driver callback;
they prove source correlation and negative controls, not actual ROS transport,
vendor/Gazebo task, inference consumption or hardware. The earlier isolated Jazzy
source2s/lease12s transport receipt remains separately scoped. Original50ms/500ms
timing failures remain HOLD; no policy budget or runtime configuration is widened.
Human mask approval, decoded-video pixel policy and operator grouping gates are
unchanged. Full goal remains ACTIVE.

## Verification

Targeted tests cover missing parent, fabricated capability, incorrect full grant,
peer/config/epoch/expiry changes, forged outcome/event/time/command UUID, source
resealing, post-read revocation, changed parent and changed native intent,
one-connection WAL interleaving, store replacement, and terminal readback without
retroactive mint. The run logs/classifier and independent review belong under
X:/DevTemp/policy-parent and the root learning-cycle evidence directory; local
passing tests do not imply CI, device, model promotion or physical acceptance.
