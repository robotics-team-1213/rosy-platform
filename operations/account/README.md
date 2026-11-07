# Rosy Account

사람 신원·로그인 수단·권한·세션·회수를 맡는 공통 서비스다([D-962](../../docs/adr/D-962-independent-account-and-authenticated-development.md), [공통 서비스 카탈로그](../../docs/reference/common-services.md)). 기계·장치·서비스 자격은 맡지 않는다(D-807).

| 알고 싶은 것 | 볼 곳 |
|---|---|
| HTTP 계약과 권한 표 | [Account 프로토콜](../../docs/reference/rosy-account-protocol.md) |
| 설치·이관·백업 | [site 배포 안내](../../deploy/site/README.md) |
| 현재 검증 상태 | [progress.md](progress.md) |
| 변경 기록 | [logs.md](logs.md) |
| 수정 규칙과 시험 | [AGENTS.md](AGENTS.md) |

## 코드가 있는 곳

| 역할 | 위치 |
|---|---|
| 서버 | `operations/account/rosy_account` |
| 로그인·프로필·관리 화면 | `applications/fleet/web/shared` |
| 수신 앱의 Python 클라이언트 | `contracts/foundation/core_common/protocol/account_client.py` |
| 브라우저 세션 도구 | `shared/web/account-session.js`, `shared/web/account-profile.js` |
| Fleet 수신부 | `operations/fleet/fleet/server/auth/account_receiver.py` |
| Fleet의 호환 import | `operations/fleet/fleet/server/auth`의 같은 이름 파일. 구현은 여기에 없다 |
