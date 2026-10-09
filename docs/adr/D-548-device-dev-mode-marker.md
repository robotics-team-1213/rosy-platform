## D-548 로봇 하나를 개발 모드로 열 때는 root가 `/etc/rosy/dev-mode` 파일을 만든다 — 공용 개발 토큰만 열리고, 셸은 열리지 않으며, LCD는 DEV를 띄운다

**Status:** Accepted (2026-10-09, 사용자 결정 "인증을 최대한 줄여 개발 편의를 높이고, 실제 로봇은 로봇별 파일 스위치로". 구현 feat/device-dev-profile. FIELD 별도)

잇는 결정: [D-193](D-193-login-code-and-credential-lifecycle.md) 7(장치 기본값에는 로그인이 없다)을 개정한다 · [D-473](D-473-fleet-console-development-connection-mode.md) 3(개발 세션은 이름 있는 운용자) · [D-418](D-418-robot-ssh-access-code-enrollment-temporary-password-team-key.md)(SSH 접속) · 나중의 중앙 인증은 D-549(Proposed).

### Context

실제 로봇 이미지는 `ROSY_DEPLOYMENT=device`로 나간다. 이 값이면 CORE는 `ROSY_DEV_AUTH`를 무시하고 공용 개발 토큰 `rosy-dev-*`를 거부한다(D-193 7). 개발 연결 모드(D-432)도 `ROSY_DEPLOYMENT=development`를 요구한다. 그래서 개발자는 브라우저·Pilot·스크립트마다 LCD의 8자 코드를 옮겨 적어야 한다. 이 값은 인증만 정하지 않는다. 런타임 활성화(`core/main.py`)와 TLS 정책(`core/api_tls.py`)도 이 값으로 갈리므로, 개발을 위해 값을 바꾸면 장치가 개발 PC처럼 돈다.

Fleet 쪽 `--mission-api`는 `--users-file`이 없으면 시작하지 않았다. 개발 세션은 D-473 3에서 이미 이름 있는 운용자인데도 그렇다.

### Decision

1. **표식 파일.** `ROSY_DEPLOYMENT=device`인 CORE는 `/etc/rosy/dev-mode` 파일이 있을 때만 `config/rosy_dev_auth.yaml`의 세 토큰(`rosy-dev-admin`/`operator`/`viewer`)을 받아들인다. 장치 오버레이에는 늘 카드·페어링 토큰 목록이 있고 목록은 아래 층을 통째로 덮으므로, 세 토큰은 오버레이 병합 뒤 목록 끝에 덧붙인다(이미 같은 다이제스트가 있으면 넣지 않는다). 파일 내용은 보지 않는다. `ROSY_DEPLOYMENT`와 `ROSY_DEV_AUTH`는 바꾸지 않는다. 그 밖의 평문 레거시 항목은 지금처럼 거부한다.
2. **닫힌 실패는 그대로다.** 파일이 없으면 D-193 7과 똑같다. 이미지·카드·OTA는 이 파일을 만들지 않는다. `/etc/rosy`는 root 소유이므로 SSH로 root 권한을 가진 사람만 켤 수 있다. 켤 때는 `sudo touch /etc/rosy/dev-mode && sudo systemctl restart rosy-core`를 쓴다. 끌 때는 `sudo rm /etc/rosy/dev-mode` 하나면 된다. 요청마다 파일을 보므로 지운 즉시 401이다.
3. **로봇을 움직이게만 하고 넘겨주지는 않는다.** 장치에서 공용 개발 토큰은 다음에 403 `FORBIDDEN`이다(`deps.auth_dependency` 한 곳). `/api/v1/host/ssh*` 전부(셸), `/api/v1/auth/enrollment-codes`(표식보다 오래 사는 자격), `/api/v1/host/*`와 `/api/v1/system/tokens*`의 쓰기(네트워크·릴리스·재부팅, 토큰 발급·삭제, 카드 관리자 삭제). 읽기는 열려 있다. 피어 페어링 발급자도 될 수 없다(기존 규칙 그대로). 세 토큰은 `/etc`의 오버레이에 쓰지 않는다. 표식이 있을 때 CORE가 시작하며 메모리에만 둔다.
4. **보이게 한다.** CORE는 기동할 때 경고 로그와 이벤트 `auth.development_mode` `{marker}`(warning)를 낸다. `rosy-face`는 표식이 있으면 얼굴 띠 앞에 `DEV `를 붙이고(띠가 없으면 `DEV MODE`), 상태 카드 줄 앞에도 `DEV `를 붙인다.
5. **Fleet 미션 API.** `--mission-api`는 `--users-file` 대신 살아 있는 개발 연결 모드(D-473: `ROSY_DEPLOYMENT=development` + `--connection-mode development`)로도 시작한다. 그 밖의 Fleet 조건(루프백 밖은 토큰이나 site-users, `--tasks-db`)은 그대로다.

### Alternatives

- **개발 로봇에서 `ROSY_DEPLOYMENT=development`로 바꾼다.** 인증 말고도 런타임 활성화와 TLS가 바뀐다. 장치에서 확인한 결과가 장치 결과가 아니게 되어 기각.
- **개발 전용 이미지.** 개발 로봇마다 카드를 다시 굽고 릴리스 줄이 둘이 된다. 파일 하나로 같은 효과를 얻는다.
- **표식에 만료 시각.** 잊힌 표식을 막지만 코드와 시계 의존이 는다. LCD의 DEV 표시와 요청마다의 확인으로 먼저 간다. 현장 로봇에 표식이 남는 일이 생기면 그때 넣는다.
- **개발 토큰으로 SSH·토큰 관리·네트워크 변경도 허용.** 같은 망 누구나 그 로봇의 셸을 얻거나, 표식을 지워도 남는 관리자 토큰을 만들거나, 카드 관리자를 지워 주인을 잠글 수 있다(2026-10-09 보안 리뷰). 이런 일이 필요한 개발자는 이미 root 권한과 카드 토큰이 있으므로 기각.

### Consequences

- 개발자는 로봇 하나에 한 번 표식을 만들면, 브라우저·Pilot·스크립트에서 `rosy-dev-operator`(또는 admin)로 바로 들어간다. 시뮬과 host 스크립트의 기존 토큰이 실제 로봇에도 그대로 통한다.
- 표식이 있는 로봇은 같은 망의 누구에게나 관리자 API가 열린다. 현장·데모·공유 망 로봇에는 만들지 않는다. LCD의 DEV가 그 확인이다.
- 표식이 없는 로봇의 동작, 이미지 검사, 카드 토큰, 로그인 코드는 바뀌지 않는다.

### Gate

| 항목 | 기준 | 상태 |
|---|---|---|
| SOURCE | `test_auth_pairing.py`(표식 유무, 이벤트), `test_host_ssh.py`(셸 거부), `test_rosy_face.py`(DEV 표시), `test_cli.py`(미션 API) | 이 브랜치 |
| DEVICE | 표식을 만들고 CORE를 재시작하면 `rosy-dev-operator` 200, LCD에 DEV. 표식을 지우면 즉시 401, DEV가 사라짐. SSH·토큰 발급·재부팅 403 | 열림 |
