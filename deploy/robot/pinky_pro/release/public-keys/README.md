# Release trust anchors

`rosy-release-2026-01.pem` is the Ed25519 public trust anchor for the Pinky Pro
pilot. On 2026-10-19 the operator authorized replacing the unavailable original
key for three newly enrolled robots. The filename remains stable for the image,
first-boot verifier, SD tools, and updater; the key identity is its fingerprint.

Current public-key fingerprint (SHA-256 of DER SubjectPublicKeyInfo):
`FC:D4:27:F6:FB:81:60:45:6C:FD:07:85:6A:85:EA:10:97:11:90:24:D1:B3:75:83:DC:48:68:72:4B:98:29:6D`.

Rebuild the image with this public key before signing it. An image containing the
previous key cannot verify releases signed with the replacement key. Existing
robots and previously signed releases retain their original trust relationship;
this change does not migrate them.

The private key stays in the operator's protected signing directory, outside
the repository, CI, release artifacts, and robots. The existing Windows signer
defaults to `%LOCALAPPDATA%\Rosy\signing\rosy-release-2026-01.private.pem`.
Use an offline signing station for production releases and retain a protected
offline backup. Never generate a shared key automatically in CI or on a robot.

## OS CMS engineering selection (2026-10-27)

`rosy-os-cms-2026-01.pem` is the public ECDSA P-256, code-signing leaf certificate
selected for engineering full-OS RAUC bundles. It is a separate authority from
the selected Ed25519 release key. The operator's current authorization covers
software/image preparation and nonactivating engineering publication. This
engineering selection records the exact public certificate and SPKI pins below
in `../../image/inputs.lock.yaml` with `cms_verified: true`; the resolver continues
to verify those pins and the certificate before preparing an image.

The operator generated the candidate locally with owner-only NTFS access. Its
private key remains under `%LOCALAPPDATA%/Rosy/signing/rosy-os-cms-2026-01-candidate/`;
only this public certificate is committed. Local OpenSSL verified its current
validity, code-signing extensions and matching public key. Public-only OpenSSL
verification on 2026-10-27 independently confirmed the exact pins, P-256 key,
current validity, Code Signing, Digital Signature and CA:FALSE. Certificate
validity is 2026-10-26 19:57:37 UTC through 2027-10-26 19:57:37 UTC.

- SHA-256 of certificate PEM bytes: `c9b715ef42497e1e1f746529a882604e7159f7957f652d25977d56f49d9104a1`.
- SHA-256 of DER SubjectPublicKeyInfo: `f0a17ffa253b371ea1a5c8ea541730a7b359ced40d70ee83d63d08be24497a88`.

Production ownership and rotation still require the separate release decision
in this directory's AGENTS.md. D-888, production BUILD_GO and physical
boot/update/rollback acceptance remain HOLD. Signed engineering artifacts need
their own source, digest and signing evidence. Keep private keys out of CI,
test PCs, robot images, release assets and repository history.
