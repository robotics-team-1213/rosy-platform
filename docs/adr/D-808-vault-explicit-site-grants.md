## D-808 Vault 권한은 명시적 site grant로 부여한다

**Status:** Accepted (2026-10-20)

### Context

D-757 Account로 Vault에 로그인하려면 기존 Fleet 권한과 구분되는 접근 권한이 필요하다.
같은 site 접근 자격은 Cam 등 다른 앱도 검증하므로 엄격한 capability 목록을 함께 갱신한다.

### Decision

- `site:<id>`에 `vault.read`, `vault.operate`, `vault.manage`를 허용한다. robot/project 자원에는 허용하지 않는다.
- Vault 조회는 `vault.read`, 작업·대기열·응답·정지는 `vault.operate`, HELD 장부 정리는 `vault.manage`를 정확히 요구한다. 정리 actor는 인증된 `account_id`다.
- 세 권한은 서로 상속하지 않는다. Fleet 권한·기존 role·`accounts.manage`도 Vault 권한을 대신하지 않는다. 읽기가 필요한 사용자에게는 읽기 권한을 별도로 부여한다.
- 기존 계정과 bootstrap에 Vault grant를 자동 추가하지 않는다. 기존 계정 관리 API와 UI에서 관리자가 명시적으로 부여한다.
- 공유 Python 검증, 계정 UI의 선택·프로필 표시, Cam의 서명 자격 검증을 같은 허용 목록으로 맞춘다. 계정 원장·발급·회수·audience 결속은 D-757 경로를 유지한다.
- Vault는 독립 HTTP 클라이언트다. Platform import나 로봇 명령 권한을 추가하지 않는다.

### Consequences

같은 site 자격에 Vault 권한이 있어도 Cam 로그인이 거절되지 않으며, Cam 조작은 계속
`camera.manage`를 요구한다. 이 결정과 Platform grant 지원은 Vault 배포·장치 동작·현장
수용의 증거가 아니다. 실제 주소·키·계정은 공개 문서에 기록하지 않는다.
