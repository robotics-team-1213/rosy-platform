# Release trust anchors

`rosy-release-2026-01.pem` is the Ed25519 public trust anchor for the Pinky Pro
pilot. On 2026-10-19 the operator authorized replacing the unavailable original
key for three newly enrolled robots. The filename remains stable for the image,
first-boot verifier, SD tools, and updater; the key identity is its fingerprint.

Current public-key fingerprint (SHA-256 of DER SubjectPublicKeyInfo):
`fcd427f6fb8160456cfd07856a85ea1097119024d1b37583dc4868724b98296d`.

Rebuild the image with this public key before signing it. An image containing the
previous key cannot verify releases signed with the replacement key. Existing
robots and previously signed releases retain their original trust relationship;
this change does not migrate them.

The private key stays in the operator's protected signing directory, outside
the repository, CI, release artifacts, and robots. The existing Windows signer
defaults to `%LOCALAPPDATA%\Rosy\signing\rosy-release-2026-01.private.pem`.
Use an offline signing station for production releases and retain a protected
offline backup. Never generate a shared key automatically in CI or on a robot.
