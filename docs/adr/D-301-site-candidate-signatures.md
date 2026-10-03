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

### 2026-10-03 — CI 빌드·로컬 서명 (D-437)

- 사이트 후보는 이제 GitHub hosted runner(`build-site-candidate.yml`)에서 빌드되고, 서명되지 않은 GitHub prerelease `site-<짧은 커밋>`으로 올라간다. 키는 GitHub에 가지 않는다(결정 2·5 유지).
- 결정 2를 보강한다. 서명 스테이션은 `sign_candidate.py --manifest-only --manifest <release.json> --expected-commit <sha> --expected-manifest-sha256 <hash>`로 `release.json` 바이트만 서명할 수 있다. 이때 manifest가 적은 파일을 로컬에서 검사하지 않는다. 그래서 수 GB `images.tar`를 서명 스테이션에 받을 필요가 없다. 덮어쓰기 거부와 공개 키 자가 검증은 그대로다.
- Release 자산은 저장소 쓰기 권한으로 바꿀 수 있으므로, 서명 전에 `release.json`을 CI 실행에 묶는다. 둘 다 필수다.
  - 서명기는 정확한 바이트의 SHA-256이 `--expected-manifest-sha256`과 다르면 거부한다. 이 값은 운영자가 CI 실행 페이지(job summary, 빌드 로그 notice)에서 옮긴다. 실행 기록은 자산 쓰기 권한으로 고칠 수 없다. `source_commit`도 40자리 16진수이고 기대 커밋과 같아야 한다.
  - 운영자는 서명 전에 `gh attestation verify release.json --repo <owner>/<repo> --signer-workflow <owner>/<repo>/.github/workflows/build-site-candidate.yml --source-ref refs/heads/main`을 통과시킨다(빌드 job의 `actions/attest-build-provenance`). 서명기 플래그가 아니라 문서화된 운영자 절차다.
- 이 서명이 증명하는 것은 "그 커밋에서 이 CI 실행이 만든 이 manifest를 운영자가 승인했다"이다. 묶음 내용의 일치는 결정 3·4대로 사이트 호스트가 확인한다. 따로 설치한 검증기가 `docker load` 전에 배포 파일·SBOM·`images.tar` 해시를 서명된 manifest와 대조한다. 후보 전체를 받는 기존 서명 경로(`--candidate-dir`)도 남는다.
- SBOM은 runner에서 syft가 SPDX JSON으로 만든다(같은 `sbom/<service>.spdx` 경로). manifest 형식과 검증기는 바뀌지 않는다.
