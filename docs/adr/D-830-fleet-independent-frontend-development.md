## D-830 Fleet 프런트 개발은 샘플·실제 API 공급과 앱 소유 자산 목록으로 분리한다

**Status:** Accepted (2026-10-21, 사용자 승인 설계의 구현 결정). 기능 구현·실제 Fleet 연결·배포·장치 수용 완료를 뜻하지 않는다.

### Context

D-822는 Fleet 화면과 gateway 소스를 applications/fleet로 모았다. 현재 자산 목록과 브라우저 fixture는 Fleet 서버에 의존하고, gateway와 Fleet CLI는 서로 호출한다. 사용자는 한 공개 레포와 기존 배포를 유지하면서 백엔드 없이 지원 기능의 프런트를 개발·시험하고 대표 흐름을 샘플로 조작한 뒤 같은 화면을 실제 API에 연결하기로 했다.

### Decision

- 앱이 페이지·정적 자산 목록과 순수 loader를 소유한다. 운영 Fleet과 개발 호스트가 이를 사용하고 기존 URL·CSP·설치 신원을 유지한다.
- 개발 호스트의 sample 공급은 로컬 샘플 상태만 바꾼다. connected 공급은 설정된 개발 Fleet으로 기존 HTTP 계약과 인증·TLS·Origin 의미를 유지해 전달한다. 화면 업무 코드는 공유한다.
- 음성·영상은 기존 의존성 주입 지점에서 native/sample 어댑터를 선택한다. 운영 배포에는 개발 호스트와 샘플을 넣지 않는다.
- Fleet은 공개 실행 진입점을 제공하고 gateway가 소비한다. Fleet이 gateway를 다시 호출하는 의존성과 gateway의 Fleet 비공개 함수 import를 제거한다.
- 인증·원장·admission·dispatch는 Fleet, 최종 Base 명령은 CORE, OMX joint/action은 기존 owner에 남는다. 샘플 승인·완료 표시가 실제 실행 증거가 되지 않는다.
- [설계](../plans/2026-10-21-fleet-frontend-development-design.md), [API 대응](../plans/2026-10-21-fleet-frontend-api-coverage.md), [실행 계획](../plans/2026-10-21-fleet-frontend-separation.md)에 따라 단계별로 구현·검증한다.

| 기존 결정 | 관계 |
|---|---|
| D-427 | 기존 applications/operations 물리 소유와 설치 identity를 유지한다 |
| D-429 | 앱 실행 조립이 공개 플랫폼 인터페이스를 사용하도록 의존 방향을 정리한다 |
| D-430 | 단일 writer·안전 체인·정지 의미를 보존하고 독립 검토한다 |
| D-822 | 소스 holder 결정에 앱 자산 소유·개발 실행·공개 CLI 분리를 추가한다 |

### Consequences

앱 자산 추가와 화면 단위 시험에 Fleet 서버 import가 필요 없어야 한다. 샘플과 실제 API의 method/path·응답·권한·진행·결과를 대응하고 미검증 항목을 숨기지 않는다. 별도 운영 배포·외부 도메인 인증·물리 장치 조작은 별도 범위다.
