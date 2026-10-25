# 937 검수 서버의 Rosy Account 경계

`learning/curation/perception/legacy_review_account.py` wraps the external 937
dataset server. It does not replace its HTML, JSON, CSV, images or review writer.
Its Account client is the existing foundation receiver (D-757); it creates no
second account directory. The previous unauthenticated legacy boundary must not
remain reachable after switching ingress.

Deployment inventory (D-809):

| Component | Source and owner | Intended listener / Account scope | Evidence |
|---|---|---|---|
| Legacy 937 review HTML and review writer | External `/home/rosy/dataset-review-937/server.py`; existing dataset operator | HTTP `127.0.0.1:18770`, reachable only through the Account front | Preserve original HTML, JSON, CSV, images and human decisions; installation is a separate operator check |
| Account front | Platform `learning/curation/perception/legacy_review_account.py`; perception curation | HTTP `127.0.0.1:8770`; `project:learning-dataset-937`; registered HTTPS origin on port 9448 | Source `1bcd83ba3a`: 35 remote synthetic tests passed, NEW 0; production installation and browser acceptance are separate |
| HTTPS ingress | Existing model-host ingress; deployment operator | Exact private registered origin forwards only to the Account front | Confirm TLS, public Host preservation and inaccessible direct backend during activation |

The external HTML is not a Platform frontend and is not registered as a new
`shared/web/surfaces.yaml` surface. This inventory tracks the deployed service
and its Platform Account boundary; it does not assert Platform UI design-system
coverage. [D-809](../adr/D-809-legacy-learning-account-boundary.md) owns the decision
to preserve the external app and its separate protected audit ledger.

Before switching, back up the existing server and hash the human review JSON,
CSV and image files. Move the unchanged legacy service behind a loopback-only
`127.0.0.1:18770` listener. Bind the wrapper to `127.0.0.1:8770` and configure the
existing HTTPS ingress to forward to the wrapper while preserving the exact
registered public Host. Do not forward directly to the legacy backend. Verify
the listeners before enabling ingress. Backend migration and TLS configuration
are operator actions, not performed by the wrapper.

Use a service-owned directory with mode `0700`, configuration files with mode
`0600`, and the model review environment with foundation and its existing crypto
dependencies. Start from the repository root:

```sh
PYTHONPATH=contracts/foundation python -m learning.curation.perception.legacy_review_account --config /private/service/wrapper.json
```

The private wrapper configuration has exactly these fields (the origin below is
a placeholder, never a device address):

```json
{
  "origin": "https://review.example.test:9448",
  "port": 8770,
  "receiver_config": "receiver.json",
  "audit_db": "audit.sqlite"
}
```

`receiver.json` uses the existing Account receiver schema: `issuer`, `client_id`,
`resource`, `callback`, `public_key_files`, `encryption_key_file`, `session_db`.
Register its exact callback as `origin + /api/account/callback` and its resource as the
explicit `project:<id>`. The session database's parent must also be private.
Keep receiver keys and all three databases outside the dataset tree. Back up the
session database and its encryption key together. Do not copy secrets into this
runbook, unit files tracked in git, command lines or browser storage.

Grant `learning.view` for viewing. Editing pending/fix/hold needs the additional
`learning.edit`; ok requires the additional `learning.approve`. Site roles,
`learning.manage` and edit permissions do not imply approval. `/api/account/session`
returns the current account/profile; the injected bar links to the central
profile and submits local logout. A central logout failure leaves a durable
revocation pending and the wrapper retries it while running, including after
restart. Local browser access is removed first.

Only the original read routes and `/api/review` are forwarded. Cookies,
authorization and claimed identity headers are never forwarded. The wrapper
records the server-resolved account, project, exact request body SHA-256 and
time before each allowed write in `review_audit`, followed by success,
upstream_error or unknown. A failed connection or a crashed outstanding intent
is unknown: inspect the real human result before deciding whether to resubmit.
No write is automatically retried. The separate audit database does not add or
alter an actor field in the legacy review JSON. Responses are bounded at 32 MiB,
review bodies at 20,000 bytes and notes at 4,000 characters.

After switching, verify unauthenticated root redirects and API reads/writes
refuse access, complete one browser login and inspect existing results without
creating synthetic reviews. Verify project view/edit/approve grants, logout,
central revocation and a restart. Compare the original file hashes and counts;
any real review write requires an explicit human action. Remote synthetic tests
do not establish production deployment or browser acceptance.
