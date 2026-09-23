## D-133 CORE SIGSEGV 는 재현 경로로 쫓고, 흔들리는 환경에서의 반복은 폐기한다

**Status:** Accepted (2026-09-20).

**Context:** ROS-SIM LOCAL 실측: 대형 RUNNING 중 리더(rosy_01) CORE 가 탐색+릴레이 가동 중 SIGSEGV(exit -11) 로 사망했다 — 릴레이 리더 스트림 종료, FOR-004 HOLD, 팔로워 `swarm.aborted`(SWM-004 자보 — 정책대로 작동). 같은 박스의 반복 시도에서는 Nav2 container SIGSEGV·-9 리핑이 확인됐다 — 2로봇 풀 스택이 이 공유 WSL 박스의 자원을 넘는다. 환경이 흔들릴 때의 실패는 결함 데이터와 구별이 안 된다.

**Decision:**

1. **재현 경로를 계약으로 남긴다** — 무장 → 리더 goal → 주행 중 관측(`tools/sim/sim_verify.sh`). 누구나 같은 순서로 같은 크래시를 볼 수 있어야 추적이 시작된다.
2. 네이티브 추적은 core 세션이 **안정 세션**(자원 튜닝된 WSL 또는 Pi)에서 수행한다. 공유 박스에서의 반복은 폐기한다 — 무효 숫자다(D-79 정신).
3. (b) 가 닫히기 전까지 대형 주행의 FIELD 주장은 존재하지 않는다(D-91).

**Alternatives:** 지금 상자에서의 반복 — 무효 숫자를 낳는다. 재현 없이 추적 포기 — D-83 을 영원히 막는다.

**Consequences:** (b) 가 닫힐 때까지 D-131 의 대형 주행 증거는 LOCAL 진단 수준이다. 재현 경로가 문서화된 첫 사례로, 이후의 네이티브 크래시도 같은 모양으로 기록된다.

**Validation / Transition:** SIGSEGV 재현(시뮬) → core 세션 추적 → D-83 재실행 통과가 이 ADR 을 닫는다.

**References:** D-79, D-83, D-88, D-91, D-131.

---
