## D-533 Fleet의 반복 신원 조회는 승인 증명 한도를 소모하지 않는다

**Status:** Accepted (2026-10-09, 현장 재현; DEVICE/FIELD 검증 별도)

### Context

현장 Fleet은 등록된 두 Pinky에 HTTPS로 연결한다. 로봇 FleetAgent 짝 토큰이 아직 없으므로 1 Hz 화면 갱신은 REST 상태 조회로 폴백한다(D-447). Fleet의 TLS 전송 계층은 Bearer를 보내기 전에 매 요청마다 로봇의 `/api/v1/auth/peer-pairing/identity`를 확인한다. CORE는 이 공개 신원 조회와 승인 challenge/session을 같은 출처별 30회/분 예산으로 세었다. 현장 컨테이너에서 429 `anonymous proof rate limit reached`를 재현했고, 관제 화면의 두 로봇 연결이 2/2와 0/2 사이에서 바뀌었다. `healthz`나 한 번의 연결 성공은 지속 연결의 증거가 아니다.

### Decision

1. HTTPS 공개 identity 조회에만 출처별 300회/60초 예산을 둔다. 기존 출처 맵 128개 상한과 429 거절은 유지한다.
2. 승인 request와 challenge/session 등의 증명은 기존 각 30회/분 한도를 유지한다. identity 조회가 이 한도를 소모하지 않으며, Bearer 전송 전의 TLS·hostname·CA·identity 검사는 매 요청 그대로 수행한다. 신원 응답을 캐시하거나 인증을 건너뛰지 않는다.
3. 이 변경은 통신 안정성의 SOURCE 계약이다. 모델 PC 계약 시험, 서명된 ARM64 설치물, 각 로봇의 429 없는 연속 조회, Fleet Web 2/2 지속 상태를 따로 확인한다. 카메라 몸체 식별·이동 수용은 별도다.

### Consequences

- 공개 identity 응답은 한 출처에서 분당 최대 300회까지 처리된다. 요청 본문·승인 코드·세션 증명의 예산은 늘지 않는다.
- FleetAgent 짝 토큰이 양쪽에 나중에 설정되면 Hub heartbeat가 REST 폴백을 줄인다. 이 결정은 그 설정을 대신하지 않는다.

**References:** [D-361](D-361-site-console-enrolls-robot-by-screen-code.md), [D-447](D-447-web-realtime-reuse-open-sockets.md), [D-483](D-483-robot-screen-approval-code-for-peer-requests.md), [D-529](D-529-role-based-test-execution.md).
