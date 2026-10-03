# D-432 Common Discovery and Development Link Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 고정 IP 없이 앱·장치가 발견하고, 명시적인 개발 설정에서 코드 입력 없이 연결하며, 인증된 상대에만 재연결한다.

**Architecture:** 기존 소스 경로에서 공유 계약과 OS 발견 어댑터를 사용한다. CORE의 선택적 TLS와 Fleet의 신뢰된 발견 전송을 연결하고 개발 bootstrap 도구가 장치별 자격과 신뢰 설정을 준비한다. 운영 코드 페어링과 로컬 제어 안전 조건은 유지한다.

**Tech Stack:** Python, httpx/httpcore, uvicorn, zeroconf/Avahi/Bonjour, Kotlin/Android NSD/OkHttp, ESPmDNS, pytest/Gradle.

**2026-10-03 사용자 보정:** 앱의 설정 파일 가져오기를 폐기한다. 실행 즉시 장비 목록을 발견하고 선택해 접속한다.
개발 모드는 장비에서 명시하며 앱이 operator 세션을 자동 요청한다. 일반 모드는 필요한 최초 연결에 기존 8자리 코드를 쓴다. 4자리 통합은 D-432 후속 결정에 따라 추후 적용한다.
bootstrap 파일은 설치 담당자의 내부 경로다. D-432 추가 결정과 API Ref v1.89가 이 흐름을 고정한다.

---

### Task 1: 발견·재시도 어댑터

- Modify: `src/contracts/foundation/core_common/discover.py`
- Create: adjacent discovery cache/retry modules and foundation tests.
- Modify: `src/runtime/services/core_features/fleet_agent/{discovery,agent}.py`
- Test first: SRV의 실제 port/host, update/remove/dedup, 전체 deadline, bounded candidates, 종료 정리, jitter cap.
- Run targeted foundation and FleetAgent discovery tests red; implement adapters; run green; commit exact paths.

### Task 2: 인증된 로봇 주소 자동 추종

- Create: `src/runtime/gateway/core/api_tls.py`, `src/site/fleet/fleet/swarm/discovery_transport.py`
- Modify: `src/runtime/gateway/core/node.py`, `src/site/fleet/fleet/swarm/{robots,transport}.py`
- Modify: common TXT classifier, platform advertisement consumers and shared vectors/profile together.
- Test first: TLS pair/key failure, pinned CA/name over resolved IP for HTTP and WS, no credential on wrong TLS peer, duplicate/stale discovery, DHCP address change and origin checks.
- Run focused tests red; add opt-in TLS config and endpoint trust fields; real loopback TLS tests green; keep legacy plain pin unchanged.

### Task 3: 코드 없는 개발 bootstrap와 연결 정책

- Create: `core_common/protocol/link_policy.py` and shared vectors; development bootstrap CLI under `tools/`.
- Explicit `development` policy plus named site/allowed device identities; default `paired`; no automatic auth downgrade.
- Tool generates per-device TLS/key/credentials and matching CORE/Fleet configs; no fixed-IP config or shared dev tokens. Private files owner-only, no overwrite, no token output. Development configuration is explicit; never enables motor.
- Test first: code-free config consumption and identity binding, mode/site mismatch, ambiguous discovery, expired credential, refusing production profile and unsafe outputs; round-trip loader tests.
- Run red/green and commit.

### Task 4: Cam·사이트·펌웨어 소비자 정렬

- Android initial discovery and reconnect use same bounded resolver lifetime; jitter/retry stability, shared policy vectors and explicit development bootstrap import if required.
- Dock/signal advertisements carry required role/protocol metadata; clients consume actual SRV destinations, not guessed hostname/port.
- Site scanners preserve TLS metadata, single source classification; persistent watcher shares Avahi cache and updates bounded discovery leases, with one-shot compatibility.
- Test native Android JVM/build where toolchain exists; host firmware/advertisement consumers and lifecycle checks.

### Task 5: 통합·리뷰·반영

- Update API reference/config docs with exact new configuration contract; no new REST route without schemas/version update.
- Record SOURCE/LOCAL results in module logs and governance docs; generate harness indexes.
- Run focused suites, meaningful real host TLS/HTTP/WS tests, affected full host suites and repository quick tier; lint and independent spec/quality reviews; address findings.
- Commit owned paths, merge current main in isolated worktree if needed, then fast-forward local main. No remote push or installed device configuration changes.
- Real AP airtime, ARM64 artifact and DEVICE/FIELD remain separate acceptance; record remaining limitations with exact role/path.
