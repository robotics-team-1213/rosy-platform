# Rosy Account native configuration (D-757)

Pilot Android and Cam use external-browser login with S256 PKCE, state, and exact registered HTTPS callbacks. Android Keystore AES-GCM protects access/refresh tokens. Tokens never enter WebView storage, URLs, or logs. The encrypted store and AAD bind issuer, client, and redirect. Signature, issuer, resource, timestamps, grants, and introspection determine access.

## Build and registration

Supply public deployment JSON using `-Prosy.accountConfig=<absolute-json>`. Required fields: `issuer`, `client_id`, `redirect_uri`, `resources`, and `trusted_keys`. Keys map kid to base64url raw 32-byte Ed25519 public keys. Cam requires one site resource; Pilot uses robot resources. Pilot `robots` entries specify `robot_id`, HTTPS `host`, `port`, and `ca_pem`; discovery must match before sending credentials. Robot CAs remain scoped to robot transport; Account uses platform trust.

```json
{"issuer":"https://account.example.test","client_id":"rosy-cam-native","redirect_uri":"https://apps.example.test/cam/account/callback","resources":["site:example-site"],"trusted_keys":{"account-key-1":"<base64url-public-key>"}}
```

Example hosts are not deployment defaults. Register exact client/redirect/resources in Fleet. Publish the deployed APK signer SHA-256 and package name at the callback host's `/.well-known/assetlinks.json`. Verify Android autoVerify with `pm get-app-links` and test actual browser callback delivery. There is no custom-scheme fallback.

Use the existing Gradle wrapper with `testDebugUnitTest assembleDebug --max-workers=1 --no-daemon`. On Windows redirect outputs with `-Prosy.buildRoot=$ROSY_SCRATCH/<session>/scratch/<app>-build`, `--project-cache-dir $ROSY_SCRATCH/<session>/scratch/<app>-cache`, `-Pkotlin.project.persistent.dir=$ROSY_SCRATCH/<session>/scratch/kotlin`, and `-Pkotlin.compiler.execution.strategy=in-process`. Pilot syncs shared Account sources from Cam through sharedContracts.

## Sessions and revocation

Failed logout/revoke requests remain in an encrypted durable outbox and retry after restart. Pilot polls at most two active robots every ten seconds; each HTTP call has a three-second deadline. Motion and stop paths read validated cached tokens without waiting for refresh. Account/family changes close old connections and WebViews.

Cam human management is separate from persistent machine streaming credentials. Revocation cancels pairing and fences delayed replies. Existing machine streaming remains active and transmission stop remains available.

## Evidence limits

JVM tests cover an actual Python-signed fixture, PKCE/replay, refresh identity, restart-safe revoke outbox, delayed pairing, HTTP timeout, and native proxy token isolation. Configured APK builds do not prove device Keystore behavior, verified app links, live SSO, or motion acceptance. Production issuer/callback/signer registration and device readback remain separate. This change does not activate runtime configuration or accounts.
