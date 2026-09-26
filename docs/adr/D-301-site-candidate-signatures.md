## D-301 Site Fleet 후보 묶음은 오프라인 Ed25519 서명으로 발행자를 인증한다

**Status:** Accepted for the source contract (2026-09-27). The site signing key has not been provisioned; host activation remains blocked until its trust anchor is enrolled.

**Connects:** D-36, D-267, D-275, D-293.

**Context:** The site candidate verifier checks deployment hashes, SBOMs, archive digest, and loaded image IDs against `release.json`. Because those values are unsigned, replacing the whole candidate and manifest together passes consistency checks. Site host activation needs a publisher-authenticity check before Compose or systemd starts.

**Decision:**

1. The offline release station signs the exact bytes of `release.json` with Ed25519. A detached `release.json.sig` envelope carries the signature version and key ID; the signature input includes a domain separator, the key ID, and the exact manifest bytes.
2. The offline signer runs after candidate building. It verifies candidate contents before signing, accepts a private-key path only as an explicit operator argument, requires the matching public key to verify its result, refuses an existing signature, and never copies or packages private key material.
3. The Ubuntu host receives a site-specific trusted public key and expected key ID through a separate administrator-controlled path outside the candidate. It also installs a reviewed verifier and signing module outside the candidate before the first transfer. Never use an unverified copy from the candidate to authenticate that same candidate. Candidate verification requires the enrolled key ID; missing signature, unknown key ID, altered manifest, or invalid signature fails closed before image loading and before systemd activation.
4. After signature verification, the existing file, SBOM, archive, image-ID, and platform checks still run. These checks prove bundle consistency and loaded-image identity; TLS, host identity, GPU, device connectivity, and field behavior remain separate gates.
5. The site key is separate from the Pinky runtime release key. Its ownership, offline storage, provisioning, and rotation ceremony must be approved and recorded before a production site candidate can be accepted. The repository contains no site private key.

**Consequences:** Candidate builds remain unsigned and can run on ordinary build hosts. Only an offline signing station can issue a deployable site bundle. A signature without a host-enrolled public key is not trusted. The existing candidate is therefore LOCAL-only until reissued with the approved site key.

**Alternatives:** A hash-only manifest cannot authenticate the producer. Reusing the Pinky runtime key would couple trust domains. Embedding a public key in the candidate would let an attacker replace both the artifact and its trust anchor.

**Validation / Transition:** Tests cover missing, malformed, wrong-key, and tampered signatures, key-ID binding, refusal to overwrite, signature-only verification before Docker load, and loaded-image checks after load. The target's expected key ID, public key, and reviewed verifier must be installed independently; only then can signed candidate verification authorize service activation. This ADR does not authorize robot motion or automatic policy execution.
