# Neutral ARM proposal handoff

An external application hands a known `mission_id` to the Fleet work page:
`/console?view=work&arm_transfer=<URL-encoded mission_id>`. The **외부 앱 ARM 제안**
section also supports manual lookup. This is a frontend query on the existing
console, not an execution API or an authorization grant.

The console reads `/api/fleet/arm-transfers/jobs/{mission_id}` under its own Fleet
session and `/api/fleet/dispatch-control` for the current generation. It shows the
neutral object, source, target, device, proposer and proposal digest. Lookup and
page refresh do not submit approval. A different named operator explicitly
confirms **독립 운영자로 실행 승인**, which posts to the job's `/admit` endpoint with
the displayed `expected_proposal_digest` and the generation read with that job.
The server revalidates identity, scope, digest, generation and installed resources.
The existing simulation-only installation gate remains authoritative.

After any approval attempt, the screen requires a new original-job read before
another attempt. A rejection or lost response never triggers automatic resend.
Admission can start device execution when the installed dispatcher is active.
`ACTION_SUCCEEDED` still awaits physical confirmation; `GOAL_CONFIRMED` is physical
closure and does not establish the external application's business completion.
The browser holds no observer token and cannot manufacture observation receipts.

Older Fleet consoles do not implement this handoff section. External applications
must declare deployment of this UI before presenting this specific deep link as
an approval destination. A configured origin or healthy server alone proves no
such compatibility. No job-list endpoint or legacy Mission admission route is used
for neutral ARM jobs.
