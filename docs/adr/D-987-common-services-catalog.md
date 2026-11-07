## D-987 공통 서비스의 정의와 카탈로그

**Status:** Accepted (2026-11-07, 사용자 지시: 공통 서비스를 구조화하되 폴더 이동 전 단계까지 구현). 정의와 시험의 수용이며 서비스의 배포·현장 수용을 뜻하지 않는다.

**관련:** D-427 · D-429 · D-430 · D-757 · D-807 · D-841 · D-876 · D-936 · D-789 · D-801 · D-939 · D-955 · D-962

### Context

Account, Monitoring, Media는 각자 ADR과 소유 패키지가 있지만 이들을 묶는 정의가 없다. 그래서 다음 일이 생겼다.

- D-962 뒤에도 [앱별 작업과 책임](../reference/app-responsibilities.md)은 Account 소유자를 Fleet auth로 적었다. Fleet의 해당 파일은 이미 `rosy_account`를 가리키는 호환 import다.
- [앱 이름과 역할](../reference/app-names-and-roles.md)은 Media를 별도 서비스로 분류하면서 Account는 앱 안의 기능으로 분류했다.
- `platform_parts.yaml`의 `capability`는 Jira 역할 Epic의 검토 담당을 나타낸다. Account는 `platform`, Monitoring은 `fleet`이므로 공통 서비스 여부를 판단하는 표식으로 쓸 수 없다.
- 새 공통 기능이 어디로 가야 하는지 정할 기준이 없다.

폴더 이동으로 해결할 문제는 아니다. 소유 패키지는 이미 독립되어 있고, 아키텍처 설계 v0.2는 새로운 `common` 통합 저장소를 만들지 않는다고 정했으며, D-841은 새 전역 utils 패키지를 금지한다.

### Decision

1. **공통 서비스는 세 조건을 모두 만족한다.** 여러 제품 앱이나 현장 전체에 같은 기능을 제공해 앱마다 따로 만들지 않는다. 특정 앱의 업무 원장을 소유하지 않는다. 장치 명령 권한이 없다.
2. **두 종류로 나눈다.** 실행 서비스는 자기 프로세스로 돌고 현장 Compose 서비스로 배치된다. 공용 코드는 자기 프로세스가 없고 소비자와 함께 설치·컴파일되며, 수용 판정은 그것을 싣는 런타임 모듈이 맡는다.
3. **정본은 [공통 서비스 카탈로그](../reference/common-services.md) 한 곳이다.** 소스 경로, Compose 서비스, 책임 경계를 적는다. 수용 상태는 복사하지 않고 각 모듈의 `progress.md`로 연결한다.
4. **현장 서비스는 분류 없이 추가하지 않는다.** `deploy/site/compose*.yaml`의 모든 서비스는 카탈로그의 실행 서비스이거나 "공통 서비스가 아닌 현장 서비스" 목록에 있어야 한다. `test/architecture/test_common_services.py`가 불일치를 거절한다.
5. **이 결정은 폴더를 옮기지 않는다.** 소스 경로·패키지·이미지·서비스 이름과 D-936의 Monitoring 동반 배치를 유지한다. 폴더를 옮기려면 서명 이미지와 배포 영향을 적은 별도 ADR을 쓴다.
6. **사람 자격과 기계 자격을 합치지 않는다.** Account는 사람 신원·권한·세션을 소유한다. 기계·장치·서비스 자격과 미디어 위임은 D-807대로 기존 owner에 남는다. 공통 토큰과 범용 자격 저장소를 만들지 않으며, 각 앱은 자기 자원의 허용 여부를 자기 서버에서 판단한다.
7. **이름이 같아도 의미가 다르면 합치지 않는다.** `same_origin`은 `Origin`을 `Host`와 비교하는 검사와 등록된 origin(callback 또는 설정 목록)과 비교하는 검사가 있다. 전자는 Fleet과 Account가 함께 쓰므로 foundation으로 옮기고 동작을 유지한다. 후자는 각 수신부에 둔다. 하나로 통일하려면 별도 결정이 필요하다.
8. **Android 계정 세션은 D-939 위치로 옮긴다.** Cam에서 `shared/android/account`로 옮기고, 기존 Keystore 별칭과 저장소 이름을 유지해 로그인 상태를 보존한다.
9. **브라우저 세션은 세 갈래를 유지한다.** Robot·Pilot·Games는 `shared/web/account-session.js`를 쓴다. Learning과 Fleet은 같은 파일로 합치지 않는다. 합치면 옵션만 늘고 다음 동작을 바꿀 위험이 있다.
   - Learning은 세션 응답의 `account_session`으로 신원을 비교하고, 5xx가 아닌 실패 응답을 세션 없음으로 보며, 요청의 응답을 받을 때마다 신원을 다시 확인해 바뀌었으면 응답과 작성 중 화면을 막는다. 공용 도구는 `account_id`·`session_family`·`revision`으로 비교하고, 실패 응답을 확인 불가로 처리하며, 요청마다가 아니라 시작 때와 10초 주기, 다른 탭 알림으로 확인한다.
   - Fleet은 콘솔의 로그인·계정 컨트롤(`password-login.js`)이 신원 표식을 쓰고 계정 관리 화면(`account-page.js`)만 그 표식을 읽어 요청마다 확인한다. Fleet 전용 인증 경로를 쓴다.

### 기존 결정과의 관계

| 결정 | 관계 |
|---|---|
| D-427 | 새 part와 최상위 폴더가 없다. 기존 경계를 유지한다. |
| D-429 | 관심사 분류와 source manifest를 바꾸지 않는다. 카탈로그 경로는 manifest root 아래에 있어야 한다. |
| D-430 | 공통 서비스 분류는 실행 권한을 주지 않는다. Fleet admission과 CORE·OMX의 최종 제어·안전 경계는 그대로다. |
| D-757 · D-962 | Account 소유 범위와 프로토콜을 바꾸지 않는다. 호환 import가 있어도 Account는 Fleet을 import하지 않는다(D-962, `operations/account/test/test_boundaries.py`). |
| D-807 | Decision 6은 D-807의 자격 구분을 공통 서비스 경계로 옮겨 적은 것이다. |
| D-841 | 새 전역 utils 패키지를 만들지 않는다. CORE·Fleet proof helper 복제와 동일성 검사를 유지한다. |
| D-876 · D-936 | Monitoring의 독립 소유와 Fleet 이미지 동반 배치를 유지한다. |
| D-789 · D-801 | Media의 위임 경계를 유지한다. 카탈로그 등재는 배포 활성화가 아니다. |
| D-939 | Android 공용 위치 규칙을 계정 세션에 적용한다. 빌드 때 Cam 원본을 복사하는 다른 파일의 처리는 이 결정에 넣지 않는다. D-939 Decision 5의 웹 규칙은 같은 로직에 적용되며, Learning·Fleet의 세션은 Decision 9의 이유로 같은 로직이 아니다. |
| D-955 | 단계 계획을 바꾸지 않는다. 결정 1의 "Fleet의 Account 원장"은 뒤에 수용된 D-962의 독립 Account 원장으로 읽는다. |

### Consequences

- 새 현장 서비스를 넣는 변경은 분류를 함께 적어야 구조 시험을 통과한다.
- 카탈로그의 등재는 구현·배포·현장 수용의 증거가 아니다.
- 각 서버의 로그인 처리(Fleet, CORE, Games, Learning, 레거시 937 데이터셋 서버의 `legacy_review_account.py`)는 HTTP 기반이 달라 이 결정으로 합치지 않는다.
- Fleet의 `site_auth`는 `rosy_account.principal`과 `rosy_account.site_users`를 계속 import한다. Account가 Fleet을 import하지 않는 방향은 시험으로 고정되어 있고, 반대 방향의 정리는 이 결정에 넣지 않는다.
- Fleet 내장 Account 구성(`--account-config`)과 `vault.*` 권한은 남긴다. 제거는 현장 수용과 원장 확인 뒤 별도로 정한다.
- Harbor의 Rosy 로그인 연동은 D-955의 후속 단계에 남는다.
