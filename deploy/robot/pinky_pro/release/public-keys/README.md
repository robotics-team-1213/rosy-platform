# Release trust anchors

`rosy-release-2026-01.pem` is the Ed25519 public trust anchor selected for the
2026 Pinky Pro pilot. Its private key exists only in the operator's protected
offline signing directory; it is not available to CI, this repository, or a
robot. Production ownership and any rotation ceremony still require an explicit
release decision. Never generate a shared key automatically in CI or on a robot.
