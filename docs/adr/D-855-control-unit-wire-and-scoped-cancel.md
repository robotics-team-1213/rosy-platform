## D-855 관제 위임 요청과 실행 시도에 결속된 취소 계약

**Status:** Accepted for implementation (2026-10-23, 사용자의 실제 파이프라인 구현 지시). D-850/D-851 목표의 첫 소프트웨어 계약이다. 배포·production dispatch·실물 수용을 승인하지 않는다.

### Context

D-851의 상세 설계를 실제 관제 간 요청으로 연결하려면 요청 identity와 owner snapshot을 공유해야 한다. 기존 CORE navigation/cancel은 현재 목표를 취소하므로, 과거 위임의 늦은 취소에 사용하면 새 작업을 취소할 수 있다. body를 기존 취소 경로에 덧붙이면 구버전 서버가 body를 무시하고 무조건 취소할 위험도 있다.

### Decision

API reference v1.297에 관제 후보 생성·직접 부모 inbox·단일 위임 조회·하위 named operator 승인·취소 요청을 추가한다. wire 모델의 정본은 `core_common.protocol.schemas`의 ControlWorkRequest, ControlIngressRequest, ControlApproveRequest, ControlUnitReply와 별도 모델 파일이다. 상위 요청의 actor·임의 endpoint·장치 토큰 필드는 허용하지 않는다.

논리 위임 identity는 발행 관제와 delegation ID다. 관계 revision 변경·응답 유실·재시작으로 이를 바꾸지 않는다. 같은 본문은 같은 작업으로 결속하고 다른 본문은 충돌이다. 서비스 principal은 직접 부모 관계를 검증받으며 후보 접수·조회·취소 요청만 한다. 실제 로컬 실행은 하위 named operator와 기존 admission·원장 claim이 소유한다. nested 상위도 이 구분을 유지한다.

CORE에 새 `POST /api/v1/navigation/cancel-scoped` 경로를 둔다. expected_boot_id·run_id·correlation_id가 모두 현재 실행과 일치할 때만 기존 NavigationManager의 잠금 안에서 조건부 cancel을 수행한다. 불일치는 409이며 다른 목표·lease를 바꾸지 않는다. 구버전 서버의 404는 미지원으로 보존하고 무조건 취소 경로로 fallback하지 않는다. 기존 navigation/cancel의 수동 정지 의미와 호환성은 유지한다.

CORE가 실행과 결과를 소유하며 상위 관제가 최종 명령을 발행하지 않는다. 취소 요청 접수와 물리 정지 완료는 구별한다. 부모는 출처·identity·구성 revision·owner revision이 맞는 응답만 투영하고 stale·불명·부분 응답을 성공으로 덮지 않는다.

### 기존 결정과의 관계

| 결정 | 관계 |
|---|---|
| D-850·D-851 | 독립·상하위·3수준 중첩 목표를 첫 유한 navigation 후보와 owner 응답으로 구체화한다. D-851의 나머지 미결 사항을 일괄 Accepted로 바꾸지 않는다. |
| D-427·D-429 | 기존 파트·관심사·소스 소유를 유지한다. 공유 schema는 leaf foundation, 접수·원장은 Fleet, 최종 실행은 CORE다. |
| D-430·D-419 | 기존 안전·장치 링크 단절 정책이 우선한다. scoped cancel은 장치 owner의 잠금을 사용하고 parent 링크 상태로 장치 정책을 바꾸지 않는다. |
| D-836·D-516 | 기존 후보·승인·실행 및 모델 증거 경계를 유지한다. 모델·상위 서비스가 named operator가 되지 않는다. |

### Consequences and verification

새 경로라 구버전이 요청 body를 무시해 다른 목표를 취소하지 않는다. 그 대가로 scoped cancel 미지원에서는 현재 작업의 취소 결과를 불명/대기로 남기고 기존 현장 정지 수단을 사용해야 한다. 새 claim·자동 재배정·자동 rearm·장치 권한은 추가하지 않는다.

wire strictness·finite 좌표·owner snapshot 상한, 잘못된 boot/run/correlation의 무변경, exact 취소와 과거 취소의 새 목표 보존을 회귀로 검증한다. 관제 HTTP·복구·브라우저·배포와 실제 장치 수용은 후속 구현/증거로 닫는다. 이 계약 등록만으로 파이프라인 완성을 주장하지 않는다.
