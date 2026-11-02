# D-962 Rosy Account 독립 서비스와 개발 모드의 사람 로그인

**Status:** Accepted (2026-11-02, 사용자 승인. 구현·원격 검증·서명 배포·운영 수용은 각각 별도 증거)

## Context

D-757은 단일 사람 신원과 앱별 세션·권한을 정했고 초기 구현만 Fleet auth holder와 SQLite에 두었다. 현재 Account HTTPS도 Fleet 프로세스로 전달된다. Fleet 개발 모드가 중앙 로그인 폼을 숨겨 Learning에서 로그인을 진행할 수 없는 결함이 실제 브라우저에서 관측됐다.

사용자는 Account를 공통 모듈로 분리해 통합관제 PC에 실행하고, Fleet 개발 모드도 익명으로 풀지 않고 사람 로그인으로 사용하도록 구현·배포를 승인했다.

## Decision

1. `operations/account/rosy_account`가 사람 계정·비밀번호·프로필·자원 grant·세션 family·회수·PKCE 발급과 계정 감사를 소유한다. Fleet을 import하거나 Fleet 원장·admission·장치 자격을 필요로 하지 않는다. 기존 구현을 이동·재사용하며 계정 ID·grant·revision을 다시 발급하지 않는다.
2. 통합관제 PC의 별도 Compose 서비스 `account`로 실행한다. Account는 독립 서명 이미지 `rosy-site-account`로 빌드하며 Fleet·Control Unit 서비스·제어/지각 코드나 Fleet 이미지에 빌드·실행 의존하지 않는다. Account 코드와 필요한 foundation Account 계약, 최소 Python 의존성, 기존 정본에서 추출한 로그인·프로필·계정 관리 자산만 포함한다. UID/GID 10001의 비특권 프로세스로 실행하고 설정·키·영속 DB·수명을 Fleet과 분리한다. Docker socket·로봇 자격·Fleet 원장 볼륨을 연결하지 않는다. 기존 세 이미지·네 이미지 서명 후보의 검증과 복구는 유지하고, 새 다섯 이미지 후보는 Account 이미지·SBOM·불변 ID도 서명·검증한다. Account overlay가 꺼져 있어도 서명 이미지 검증은 생략하지 않으며, 켜져 있으면 해당 Account 이미지로만 실행한다. 과거 서명 후보의 Fleet 이미지 공유는 그 후보의 검증된 이미지 목록에만 적용하는 호환 경로다(D-315).
3. 현재 HTTPS issuer와 등록 client/callback, `/api/fleet/auth/*` 프로토콜을 유지한다. Account origin은 Account가, Fleet origin의 업무 API와 receiver 세션은 Fleet이 소유한다. Fleet은 foundation AccountClient로 동일 계정을 검증하고 실제 site scope·grant로 SitePrincipal을 만든다. 중앙 쿠키와 Fleet receiver 쿠키를 구분한다.
4. 기존 SQLite의 Account·브라우저 세션·OAuth 테이블을 하나의 새 Account DB로 일관되게 이관한다. 계정과 OAuth의 원자적 회수 transaction을 나누지 않는다. 기존 활성 authority를 재-bootstrap하지 않는다. writer 중지·백업·참조 및 값 보존 검사·단일 writer 전환 뒤 프록시를 바꾼다. 이후 변경을 옛 백업으로 덮는 복구는 금지한다.
5. D-473의 익명 개발 세션 발급·합성 operator 수락·로그아웃 직후 자동 개발 재접속은 폐기한다. `development`는 개발 연결 환경 표식으로 남고 사람 권한을 만들지 않는다. 개발 모드도 로그인 제공 설정이 있어야 시작하며, 익명 업무 읽기·쓰기는 거부한다. 로그인한 viewer를 operator로 승격하지 않는다. 최초 비밀번호 변경·CSRF·세션 회수·기계 자격의 기존 제한을 유지한다.
6. Account UI는 서버가 사람 로그인을 제공하는지를 따른다. Fleet 연결 모드로 중앙 로그인 폼을 숨기지 않는다. Fleet 정지 중에도 Learning 로그인과 Account 세션 관리가 동작해야 한다.

## 기존 결정과의 관계

| 결정 | 관계 |
|---|---|
| D-427 | operations part 안에 Account 소유 모듈을 추가한다. 새 최상위 part는 없다. |
| D-429 | 현재 source manifest와 명시적 패키징 경로를 갱신한다. 과거 경로로 코드를 복제하지 않는다. |
| D-430 | 인증은 장치 실행 권한이 아니다. Fleet admission과 CORE/OMX 최종 제어·안전 경계를 유지한다. |
| D-757 | 단일 신원·세션·회수 계약을 유지하고 초기 Fleet 프로세스 holder만 독립 서비스로 대체한다. |
| D-473 | 익명 개발 세션 발급·자동 접속과 합성 operator 결정을 대체한다. 개발 모드 선택 표식은 유지한다. |
| D-548 | 개발 환경 표식이 사람 인증을 대신하지 않는다. 기기 자체의 개발 표식·안전 가드는 바꾸지 않는다. |

## Consequences

Account의 별도 원장은 전용 서명 Account 이미지의 SQLite 도구로 독립 백업한다. 유지보수 Compose는 기존 `rosy-site_account_state` 외부 볼륨만 사용하며 키·Fleet 볼륨·네트워크를 연결하지 않는다. 마이그레이션한 Account가 정상임을 확인한 뒤에만 일일 백업과 6시간 주기의 신선도·무결성 검사 타이머를 명시적으로 활성화한다. 계정·감사 행은 정리하지 않고 백업 파일만 14개로 제한한다. 새 다섯 이미지 후보에는 유지보수 파일 다섯 개를 모두 서명하고, 과거 세/네 이미지 후보에는 이 파일을 허용하지 않는다. 이 백업은 이후 비밀번호·grant·세션·회수 변경을 덮는 일반 복구를 허용하지 않는다.

Account receiver 모드에서 기존 `service`·`ai_observer` 기계 자격을 유지하며, 읽기 전용 상태 점검에는 `site-users.yaml`의 명시적인 `machine: true`, `role: viewer` 토큰만 추가로 허용한다. 이 표식은 역할이나 grant를 바꾸지 않는다. 일반 사람 Bearer 자격은 receiver에서 계속 거부한다. `machine: false`·비불리언 값·다른 역할·`login`·`password_scrypt`·`policy_admin` 필드와의 조합은 시작 단계에서 거부하며, 같은 principal ID를 사람 `site_logins`에 함께 둘 수 없다. YAML 로더와 직접 전달한 `site_users`에 같은 검증을 적용한다. 호스트의 원자적 사용자 레지스트리 편집 도구도 같은 형식을 검증하고 다른 사용자를 편집할 때 표식을 보존한다. 이 예외는 인증된 viewer 읽기 권한만 유지하며 operator 명령·제안 권한이나 익명 접근을 허용하지 않는다.

Fleet과 Account의 로그·health·백업·복구를 구분한다. 기존 signer·candidate 검증은 계속 적용한다. 호환 import나 같은 이미지 사용은 임시 실행 종속을 의미하지 않으며, 독립 프로세스에서 Fleet import가 없음을 시험한다. 세션·키·이관 보존 시험과 실제 운영의 익명 차단·로그인 진입·서비스 독립성 관측을 분리해 보고한다.

과거 제안자의 현재 권한을 재확인하는 recovery 경로도 새 Account를 따른다. Fleet의 보존된 receiver 세션에서 확인한 서명 신원과 온라인 회수 상태만 사용할 수 있으며, 이전 Fleet DB의 계정 행을 현재 권한으로 읽지 않는다. receiver 세션이 없는 과거 Bearer 제안자는 자동 허용하지 않고 재인증이 필요하다. 중앙 인증 장애·회수 시에도 recovery 권한을 연장하지 않는다.
