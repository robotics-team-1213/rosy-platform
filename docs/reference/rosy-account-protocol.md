# Rosy Account protocol (D-757)

이 계약은 D-757 구현의 additive API다. 설치·활성화·실제 사용자 수용은 별도 기록한다.
기존 Fleet 로그인/프로필 endpoint는 유지한다. 별도 인증 서버 프로세스를 만들지 않는다.

## 명시적 배포와 최초 전환

`fleet console --tasks-db <persistent-db> --users-file <existing-users> --account-config <protected-json>`으로 연다.
Account 설정이 없으면 OAuth endpoint를 열지 않는다. 최초 전환 전 기존 사람 계정과 기계 principal,
SQLite의 변경 비밀번호·프로필을 재고 조사하고 동일 시점의 DB/설정을 보호된 위치에 백업한다.
사람 계정의 기존 로그인 ID를 `bootstrap_admin_login`으로 명시한다. 첫 사용자 선택이나 새 관리자 생성은 없다.
기존 operator도 이 명시적 선택으로 계정 관리자가 될 수 있다. 기계/복구 principal 설정은 보존한다.

설정 예시의 값은 현장에서 승인한 정확한 값으로 채운다. 아래 주소와 계정은 예시이며 배포 기본값이 아니다.

```json
{
  "issuer": "https://account.example.test",
  "site_id": "example-site",
  "key_id": "account-key-1",
  "private_key_file": "/run/rosy-secrets/account-signing.pem",
  "bootstrap_admin_login": "existing-login",
  "clients": {
    "robot-app": {
      "redirect_uris": ["https://robot.example.test/account/callback"],
      "resources": ["robot:example-robot"]
    }
  }
}
```

설정과 Ed25519 private PEM은 저장소 밖 보호 파일로 제공한다. Linux에서는 서비스 사용자 소유,
group/other 권한 없는 일반 파일이어야 한다. Windows 배포는 운영자가 해당 사용자만 읽는 ACL을 별도 검증한다.
키 원문을 명령행·YAML 사용자 계정·로그에 넣지 않는다. issuer는 실제 HTTPS 이름과 인증서를 확인한 뒤 지정한다.
수신 앱에는 같은 issuer와 등록 client ID, 정확한 callback·resource, 신뢰할 공개 키를 배포한다.
authorize/token/introspect/key endpoint는 issuer의 `/api/fleet/auth/` 아래다. 별도의 기계 자격을 사람 로그인으로 재사용하지 않는다.

최초 전환은 변경 비밀번호/프로필을 보존하고 불변 account_id를 발급한다. 기존 역할은 이 시점에만 명시적인
site 읽기/조작/정책 grant로 옮긴다. 동일 login이 다른 principal로 바뀐 불명확한 비밀번호 이관은 중단한다.
활성화 뒤 DB가 사람 계정의 정본이며 YAML 수정으로 되돌리지 않는다. 이관된 사람의 기존 YAML bearer는 거절하고,
이관되지 않은 기계 principal만 기존 계약을 유지한다. 재시작에서는 `bootstrap_admin_login`을 제거해도 되며
동일 site_id와 persistent DB를 유지해야 한다. 서비스 중 백업 전 DB로 롤백하면 권한 회수가 되살아날 수 있으므로 금지한다.

관리자는 계정 메뉴의 **계정 관리**(`/console/accounts`)에서 발급·권한 변경·정지/재개·초기화·전체 세션 회수를 처리한다.
UI 표시 조건은 동일 site의 `accounts.manage`이며 서버가 매 요청 다시 검사한다. 권한 revision 충돌은 409로 거절한다.
수용 검사는 로그인→앱 업무→결과 조회→권한 회수→기존 앱/쿠키 거절을 실제 배포본에서 별도로 확인한다.

## 신원과 자원 권한

### 공통 프로필 표시 (2026-10-14 보완)

프로필 편집 정본은 Fleet의 `/console/profile` 하나다. 앱별 프로필 저장소를 만들지 않는다.
`POST /api/fleet/auth/userinfo`는 기존 form 경계로 `token` 하나를 받고, 현재 유효한
access token의 계정만 조회한다. 성공 응답은 `account_id`, `login`, `display_name`이며
정지·회수·만료·revision 불일치는 401, 원장 장애는 503이다. grant와 다른 계정 정보는
이 응답으로 확장하지 않는다. 응답은 no-store이며 표시 이름은 권한 판단에 사용하지 않는다.

수신 앱의 기존 session 응답은 `profile`(위 세 필드 또는 null)과 `profile_url`을 추가한다.
URL은 신뢰 설정의 issuer에 `/console/profile`을 붙여 생성하며 서버 응답이나 사용자 입력으로
외부 목적지를 바꾸지 않는다. 프로필 응답의 account_id는 검증한 세션 subject와 같아야 한다.
프로필만 조회 실패하면 이전 사람의 이름을 유지하지 않고 확인 불가로 표시하며,
기존 인증·회수 검사는 그대로 유지한다. 네이티브도 동일 계약을 쓰고 네트워크 조회를
조작·정지 전송 경로에 추가하지 않는다. 표시 이름은 기존 세션 상태 갱신 주기로 다시 읽는다.

Fleet 내 계정의 관리형 프로필 응답은 `grants`를 함께 제공한다. UI는 기존 role을
역할로 표시하고 자원별 실제 capability를 별도 읽기 전용 목록으로 보여준다.
권한 변경은 기존 `accounts.manage` 경로에서만 처리한다.

Account identity는 불변 opaque `account_id`다. login/email은 identity가 아니다.
권한은 `{resource, capabilities}` 목록이다. resource는 `site:<id>`, `robot:<id>`,
`project:<id>` 중 하나이며 wildcard가 없다. id는 영숫자·점·밑줄·하이픈 1~96자다.

| 자원 | 허용 capability |
|---|---|
| site | accounts.manage, fleet.read, fleet.operate, fleet.policy, camera.manage, games.operate, vault.read, vault.operate, vault.manage |
| robot | robot.read, robot.operate, robot.admin |
| project | learning.view, learning.edit, learning.approve, learning.manage, learning.import, learning.publish |

capability는 서로 상속하지 않는다. UI는 관련 읽기 권한도 함께 부여하도록 안내하고,
서버는 요청에 필요한 정확한 권한을 검사한다. 기존 기계/복구 자격의 역할 계약은 유지한다.

D-808: Vault 조회는 `vault.read`, 작업·대기열·응답·정지는 `vault.operate`, HELD 장부
정리는 `vault.manage`를 정확히 요구한다. 정리 actor는 인증된 `account_id`다. Vault 권한은
site 자원에만 부여하며 서로 상속하지 않는다. Fleet 권한·기존 role·`accounts.manage`로
대신할 수 없다. 기존 계정과 bootstrap에 자동 추가하지 않고, 계정 관리 API/UI에서 명시적으로
부여한다. Vault는 독립 HTTP 클라이언트이며 이 grant 지원은 Vault 배포·현장 수용의 증거가 아니다.

## 중앙 계정 관리

### Fleet 설정 안내와 앱 등록 조회

`GET /api/fleet/auth/setup`은 same-origin 사람 쿠키만 허용한다. 활성 계정은 현재
site의 `accounts.manage`, 전환 전 계정은 `policy-admin` 역할을 요구한다. 첫 비밀번호
변경이 필요한 세션은 거절한다. 응답은 no-store이며 `configured`, `issuer`, `clients`
(`client_id`, `redirect_uris`, `resources`)만 제공한다. 키와 서버 파일 경로는 반환하지 않는다.
`configured`는 현재 프로세스의 Authority 설정 적용 여부이고 HTTPS·앱 로그인 수용 증거가 아니다.

Fleet `/console/accounts`에 설정 상태·앱 등록·최초 설치 안내를 함께 둔다. 계정·권한 변경은
아래 기존 API를 유지한다. HTTPS, 보호 키 설치, 앱 등록 변경은 기존 관리자 배포 경로가
수행하며 Fleet에 호스트 root 권한이나 비밀 업로드 API를 추가하지 않는다.

모든 경로는 유효한 변경 완료 사람 쿠키와 해당 site의 `accounts.manage`를 요구한다.
unsafe 요청은 same-origin 검사를 거친다. 오류는 기존 Fleet detail `{code,message}`를 쓴다.

| 경로 | 동작 |
|---|---|
| GET /api/fleet/auth/accounts | 비밀 없는 계정 목록 |
| POST /api/fleet/auth/accounts | login, principal_id, role, password, grants로 계정 발급 |
| PATCH /api/fleet/auth/accounts/{account_id} | revision과 enabled/role/grants 중 변경값; 미지 필드 거부 |
| POST /api/fleet/auth/accounts/{account_id}/reset-password | revision, password; 첫 변경 요구 및 이전 세션 회수 |
| POST /api/fleet/auth/accounts/{account_id}/revoke-sessions | revision; 모든 세션 회수 |

원장 revision이 다르면 409, 권한 부족은 403, 잘못된 본문은 400/422,
저장 불가는 503이다. 마지막 활성 계정 관리자를 없애는 변경은 거부한다.
현재 사용자의 자가 권한 변경으로 관리 권한을 획득할 수 없다. 응답에 비밀번호 해시를 넣지 않는다.

## 앱 연결: authorization code + S256 PKCE

등록된 first-party client만 사용한다. 각 client에는 고정 client_id, 정확한 HTTPS
redirect URI, 대상 resource 목록이 있다. 앱이 보낸 임의 URL을 trust에 추가하지 않는다.
authorization server는 oauthlib의 code grant와 PKCE 검증을 사용하고 S256만 받는다.
implicit/password grant, 동적 client 등록, wildcard redirect를 제공하지 않는다.

| 경로 | 동작 |
|---|---|
| GET /api/fleet/auth/authorize | response_type=code, client_id, redirect_uri, scope(정확한 resource), state, code_challenge, code_challenge_method=S256 |
| POST /api/fleet/auth/token | form-encoded authorization_code 또는 refresh_token grant; public client는 client_id 사용 |
| POST /api/fleet/auth/introspect | form token; 중앙 최신 session family/account revision 검증 |
| POST /api/fleet/auth/revoke | form token; 해당 family 회수, 토큰 원문 비기록 |
| GET /api/fleet/auth/keys | 공개 서명 키만 반환; private key 금지 |

로그인이 필요하면 안전한 로컬 Account 로그인 복귀로 연결한다. authorize code는
60초, 단일 사용이며 client·redirect·PKCE·scope·session family·account revision에 결속한다.
토큰 교환은 transaction으로 code 소비와 발급을 함께 기록한다. state는 client가
브라우저에 결속하여 확인하고, 각 앱은 nonce cookie/PKCE verifier를 서버 또는 native
보안 저장소에 보관한다. 교환 결과는 서버의 HttpOnly/Secure 쿠키 세션으로 옮기며
브라우저 URL에는 access/refresh token을 싣지 않는다. callback 이후 code URL을 지운다.

refresh token은 256비트 이상 난수, DB에는 해시만 저장한다. 매 갱신 시 회전하고
이전 token 재사용은 family를 회수한다. family의 중앙 세션 만료/회수/첫 변경 제한을
넘어 자격을 연장하지 않는다. 동시 refresh는 앱에서 합치며 서버는 원자적으로 한 번만 허용한다.

## 대상 접근 토큰

JWT JWS를 joserfc로 처리한다. algorithm은 Ed25519 (RFC 9864), header는
`alg`, `typ=at+jwt`, 고정 등록 key의 `kid`다. 원격 jwk/jku/x5u header는 받지 않는다.
claim은 `iss`, `aud`, `sub`, `sid`, `jti`, `rev`, `iat`, `exp`, `grants`만 허용한다.
`aud`는 단일 resource이고 모든 grants는 같은 resource만 가리킨다. `sub`는 account_id,
`sid`는 비밀이 아닌 session family, `jti`는 발급마다 고유한 난수 ID, `rev`는 양의 정수다. `iat`/`exp`는 정수 epoch이며
미래 발급·만료·0 이하 수명·300초 초과 수명을 거부한다. role rank로 권한을 확대하지 않는다.

issuer/키/클라이언트 등록은 운영자가 보호된 구성으로 제공한다. signer는 서버 시작마다
키를 재생성하지 않는다. verifier는 배포된 trusted key 목록만 읽고 토큰이 지정한 URL을
fetch하지 않는다. 회전 시 새 공개키 배포→새 서명→구 token 만료→옛 키 제거 순서를 지킨다.

대상 verifier는 최대 10초마다 중앙 introspection을 재확인하여 연결 중 회수 30초
상한을 맞춘다. inactive가 확인되면 즉시 캐시를 지운다. 중앙 장애 때 마지막 검증된
token은 exp까지만 유효하며, 검증 실패 token을 새로 허용하지 않는다. WS도 반복 검사한다.
로그아웃/정지/초기화 이후 모든 앱의 갱신과 새 권한 발급은 거부한다.

공유 수신기의 HTTP 상태줄·헤더 파싱 실패와 응답 읽기 중단(`HTTPException`)도
네트워크 불명으로 처리하며 응답 조각이나 자격 원문을 오류에 노출하지 않는다.
refresh 응답이 불명확하면 이미 소비됐을 수 있는 refresh token을 재사용하지 않도록
로컬 세션을 지운다. 회수 응답이 불명확하면 암호화된 대기열을 유지하고 기존
백그라운드 재시도를 계속한다.

## 운영 활성화와 검증

### 앱 수신 세션

CORE의 Robot·Pilot 웹은 같은 origin의 `/api/account/login?return=/pilot` 또는
`return=/dashboard`로 시작하고 `/api/account/callback`에서 state/PKCE를 확인한다.
`GET /api/account/session`은 enabled/authenticated/account_id/session_family/revision/resource/capabilities만
반환한다. `POST /api/account/logout`은 same-origin 요청만 받으며 로컬 세션과
중앙 family를 회수한다. 중앙 장애면 로컬 로그아웃 후 암호화된 회수 대기열을
재시도하고 503으로 미완료 사실을 알린다. 재접속을 권한 복구로 처리하지 않는다.

앱 쿠키 `rosy_app_account`는 256비트 opaque 값이며 HttpOnly/Secure/SameSite=Lax,
`Path=/`다. DB에는 쿠키 해시와 암호화된 access/refresh만 둔다. callback의
단기 흐름 쿠키도 동일 속성이며 state·verifier·허용된 로컬 복귀 경로에 결속한다.
unsafe REST와 쿠키 WebSocket handshake는 정확한 same-origin을 요구한다.
CORE의 중앙 계정은 `robot.read`/`robot.operate`/`robot.admin`을 각각 검사한다.
중앙 계정으로 회수와 무관하게 남는 legacy token·enrollment를 발급하지 않는다.

수신 설정은 `auth.account_client_file`이 가리키는 보호된 JSON 파일이다.
필드는 issuer, client_id, resource, callback, public_key_files(kid→PEM 경로),
encryption_key_file(Fernet key 경로), session_db이며 운영 비밀을 기본 설정에 넣지 않는다.
resource는 해당 호스트의 실제 robot identity와 일치해야 한다. 설정이 없으면 기존
명시적 local recovery를 유지하며, 설정이 잘못되면 시작을 거부한다.

Pinky native systemd 배치는 보호된 receiver 설정·키를 `/etc/rosy/account`에 두고
`rosy-core`만 읽게 한다. 세션 DB는 서비스 소유의 영속 경로
`/var/lib/rosy/core/account.sqlite3`에 둔다. `auth.account_client_file`은 기본값이나
모든 로봇에 같은 파일을 복사하지 않고 각 로봇의 실제 overlay에서 지정한다.
개발용 Compose에서 같은 설정을 시험하면 설정 디렉터리를 CORE에만 읽기 전용으로
mount한다. OMX·시뮬 CORE도 동일 설정 계약을 사용하되 각자의 robot resource를
등록한다. 학습/Games는 별도 서비스 소유 DB·암호화 키를 사용한다.

```json
{
  "issuer": "https://account.example.test",
  "client_id": "robot-example",
  "resource": "robot:example",
  "callback": "https://robot.example.test/api/account/callback",
  "public_key_files": {"key-1": "account-public.pem"},
  "encryption_key_file": "session.key",
  "session_db": "/var/lib/rosy/core/account.sqlite3"
}
```

주소·resource·key ID는 설치 대상의 승인 값으로 바꾼다. 공개키와 Fernet 암호화 키는
서로 다른 파일이다. 기존 세션 DB를 두고 암호화 키를 다시 만들지 않는다.

Review 앱은 기존 collaboration 설정에 `account_client_file`과 `account_subjects`
(중앙 account_id→기존 learning user_id)를 명시한다. 기존 connection 소유권은 유지하고
최초 사용한 매핑은 원장에 고정하여 다른 사용자로 바꾸지 못한다. 권한은 해당
`project:<id>`의 중앙 learning capability에서 읽으며 작업 대기열에서도 다시 확인한다.
Account 모드에서는 기존 프로젝트 비밀번호·HF 로그인으로 사람 인증을 우회하지
못한다. HF 연결·동의는 Rosy Account로 로그인한 사람에게 별도로 귀속한다.
수신 endpoint는 `/api/account/login`, `/api/account/callback`이며 복귀는 `/accounts`
또는 `/`만 허용한다. 로그인 후에는 기존 `/api/accounts/session`·logout을 사용한다.

중앙 Account 모드의 Review 쿠키 세 개(`rosy_learning_session`, `rosy_account_flow`,
`rosy_learning_oauth`)는 각각 이름 뒤에 `_`와 SHA-256의 앞 24개 소문자 hex를 붙인다.
해시 입력은 신뢰 설정의 `project_id + NUL + public_origin` UTF-8 바이트다.
브라우저 쿠키는 포트를 구별하지 않으므로 같은 DNS 이름의 다른 프로젝트/HTTPS
origin이 서로의 세션·PKCE·HF 흐름을 덮어쓰지 않게 한다. 요청 Host나 사용자 입력으로
이름을 고르지 않는다. 설정 origin에서 `Secure; HttpOnly; SameSite=Lax; Path=/`를
유지하고 Domain은 지정하지 않는다. 발급·조회·CSRF 결속·삭제는 같은 이름을 쓴다.
중앙 모드는 기존 고정 이름을 fallback으로 읽지 않으며 전환 시 재로그인이 필요하다.
기존 비중앙 collaboration 모드의 이름과 서버의 권한 검증은 유지한다.

중앙 ledger bootstrap은 지정한 기존 admin login과 site_id를 명시해야 한다.
운영 계정을 자동 선택하지 않는다. authority URL·키·client callback·기존 identity와
learning user의 명시적 매핑이 준비되기 전에는 통합 설치 완료라고 표시하지 않는다.
매핑은 email/name 일치로 생성하지 않는다. 단독 로봇 복구와 서비스/카메라 machine
pairing은 사람 SSO와 분리한다.

검증 표는 원격 API/브라우저/native·CI·설치·실계정 수용을 나눠 기록한다.
상세 구현 결과가 없는 endpoint를 활성화됐다고 간주하지 않는다.

### Games와 기존 외부 연결

Games 보드는 `--preview-account-config <receiver.json>`으로 같은 receiver를
사용한다. resource는 `site:<id>`, callback은 `/api/account/callback`이며
HTTPS reverse proxy 뒤의 loopback 서버로 연다. 등록한 HTTPS origin만 쓰기
요청을 허용한다. `/stop`은 `games.operate`를 검사한다. 설정이 없으면 보드는
공개 읽기 전용이며 CLI의 기존 물리 현장 정지·Ctrl+C는 그대로 유지한다.

학습 연결의 소유자는 기존 user_id로 보존한다. 중앙 모드의 개인 연결 사용은
현재 소유자의 `learning.import` 권한을 확인한다. 프로젝트 공유 연결은 해당
generation을 승인한 중앙 subject와 session에 결속하며 매 사용/worker 단계에서
`learning.import`와 `learning.manage`를 다시 확인한다. 기존 공유 연결은 소유자가
한 번 다시 연결해야 한다. 승인 세션의 로그아웃·회수·만료 후에는 공유도 중단된다.
개인 세션과 무관한 무인 프로젝트 위임을 자동 생성하지 않는다.

비공개 데이터셋·모델 저장소의 목록·생성·삭제는 `learning.publish`와 연결에 기록된 저장소 범위가 있을 때만 한다. `learning.import`와 `learning.manage`는 그 경로를 대신하지 않는다. 개인 연결의 생성 네임스페이스는 그 Hugging Face 사용자 이름이고, 프로젝트 연결은 허용 목록의 데이터셋·모델만 다룬다.

HF 연결은 한 번에 `read-repos gated-repos write-repos manage-repos`를 요청한다.
읽기 연결 뒤 관리 연결을 따로 요구하지 않는다. 읽기·쓰기·저장소 관리가 승인된 연결을
보관하며 기존 읽기 전용 연결은 다시 연결해 공급자의 승인을 받는다.

## 명시적인 초기 비밀번호 규칙 (2026-10-19)

운영자가 지정한 대상의 초기 비밀번호 `로그인 ID + !`를 지원한다. 기존 ID와 같은 초기값도
계속 인식한다. 두 값은 legacy 로그인과 Account 최초 이관 모두에서 첫 변경 대상이며,
변경 전 업무 접근 제한을 유지한다. 관리자 생성·초기화에서는 정확한 `ID + !`만
8자 미만 임시값의 예외로 허용하고 항상 `change_required=1`로 발급한다.
그 밖의 임시값은 기존 8~1024자 조건을 따른다.

사용자가 첫 변경 또는 프로필에서 정하는 영구 비밀번호는 8~1024자이며 ID·ID+`!`·현재
비밀번호와 같을 수 없다. 일반 변경의 현재 비밀번호 확인, 같은 출처 검사, 세션 회전·회수,
Account revision과 재시작 후 유지 계약은 그대로 적용한다. 명단은 운영자가 확인한 ID만 사용하며
이 규칙이 기존 모든 사용자의 비밀번호를 자동 초기화하지는 않는다. 실제 초기화는 명시적으로
지정된 대상과 승인된 운영 절차에서 수행한다.

참고: [OAuthlib 서버](https://oauthlib.readthedocs.io/en/latest/oauth2/server.html),
[joserfc JWT](https://jose.authlib.org/en/guide/jwt/).
