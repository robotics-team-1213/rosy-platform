## D-822 Fleet 화면과 실행 조합은 applications/fleet에 모으고 플랫폼 서비스 소유권은 유지한다

**Status:** Accepted (2026-10-20, 사용자 요청에 따른 폴더 경계 결정). 소스 배치 결정이며 독립 배포·외부 연동·실물 수용 완료를 뜻하지 않는다.

### Context

공개 저장소 하나에서 플랫폼과 제품 앱을 나누어 공동 개발한다. 기존 Fleet 화면은 `operations/site_ui/console`, 실행 조합은 `operations/apps/fleet`에 흩어져 있다. 독립 제품 앱의 작업 위치를 `applications/<제품명>`으로 모으되 플랫폼 원장과 실행 권한을 옮기지 않는다.

### Decision

- `applications/fleet/web`은 기존 Fleet 화면의 유일한 소스다. `applications/fleet/gateway`는 기존 `rosy-app-gateway` wheel의 소스다.
- `operations/fleet`는 HTTP API·인증·Mission 원장·admission·dispatch를 계속 소유한다. CORE와 OMX의 로컬 실행 권한도 유지한다. 새 서버나 원장을 만들지 않는다.
- Fleet은 계속 화면을 `fleet.server.web`으로 설치하고 기존 `/console` 및 `/api/fleet/*` 경로를 제공한다. wheel 이름·import·명령·설치 프로필을 바꾸지 않는다.
- `applications`는 제품별 소스 holder다. 현 Fleet 앱의 manifest `part: operations`, 불변 `d427_target`, import 방향은 유지하고 물리 경로는 `layout_target`으로 기록한다. `colcon_roots`에 `applications`를 등록하되 gateway는 기존 `COLCON_IGNORE`를 유지한다.
- 앱별 실행 안내와 플랫폼 의존성을 해당 앱 README에 기록한다. 화면은 Fleet HTTP API를 사용하고 원장에 직접 접근하지 않는다. 기존 gateway는 Fleet CLI·공개 공정/실행 타입을 조립한다. 이는 독립적인 외부 클라이언트가 아니며 향후 레포 분리 시 이 조립 의존성을 먼저 해소해야 한다.
- 제품과 무관한 Robot·Pilot·Face·Cam, World·Decision·공정 구현은 이번에 옮기지 않는다.

| 기존 결정 | 관계 |
|---|---|
| D-427 | Fleet 앱의 물리 배치만 부분 대체한다. middleware·operations·learning 책임과 불변 소유 ID는 유지한다. |
| D-429 | concern과 API/import 방향을 유지한다. 폴더 이동으로 권한을 추가하지 않는다. |
| D-430 | 안전 체인·단일 writer·정지 의미와 독립 검토 의무를 유지한다. |
| D-425·D-637 | Fleet 화면 holder만 변경한다. 화면/API/원장/실행 소유와 설치 신원은 유지한다. |

### Consequences

앱 담당자는 `applications/fleet`에서 작업하고 플랫폼 변경은 소유 모듈에서 수행한다. 별도 레포로 추출할 위치가 분명해지지만 현재 Fleet 배포와 공통 web 자산 의존성은 남는다. 배포 분리는 후속 결정이다.

이동 시 source holder, wheel 빌드 경로, CI·배포 입력, browser scope, 테스트 fixture와 크기 검사 경로를 함께 바꾼다. 기존 작은 크기 단위 `site_ui/console/work`의 예외는 같은 소스의 새 이름 `fleet/web/work`으로만 이전하며 크기 한도를 늘리지 않는다. 소스·설치 wheel·브라우저 검증은 각 실행 결과로 판정한다.
