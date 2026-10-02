## D-418 로봇 SSH 접속은 세 길로 연다 — 화면 코드로 기기 키 등록, 필요할 때만 켜는 로봇별 임시 비밀번호, 회수할 수 있는 팀 키 공유

**Status:** Accepted (2026-10-02).
- 사용자가 "화면 코드 등록 + 임시 비밀번호"를 기본으로 고르고, 키 복사로 다른 사람과 공유하는 길도 함께 운용하자고 정했다(2026-10-02).
- 공유는 운영 마스터 키가 아니라 **따로 만든 팀 키**로 한다. 그래야 회수하고 추적할 수 있다.

잇는 결정:
- D-174 F3: 카드 provision의 `ssh_authorized_keys`, 키 전용 로그인, `rosy` 계정 `NOPASSWD`.
- D-193: LCD 일회용 코드로 대시보드 로그인.
- D-361: 화면 코드로 로봇 등록.
- D-176/D-272: 로봇별 무작위 AP 비밀번호는 물리 접근자에게만 보인다.

### Context

- **지금 SSH는 키 전용이다.** 계정은 `rosy`이고 비밀번호 로그인은 꺼져 있다. 공개키는 카드를 만들 때 `provision.json`에 넣은 것뿐이다.
- 운영 개인 키는 운영 PC 한 대(`%LOCALAPPDATA%\Rosy\ssh\rosy-operator-ed25519`)에만 있다. 다른 PC나 다른 사람이 접속하려면 그 키를 손으로 옮기거나 카드를 다시 만들어야 한다.
- 저장소는 공개다. 이미지 기본값에 공통 비밀번호를 두면 누구나 안다. `rosy`는 `sudo`가 비밀번호 없이 되므로 SSH 로그인은 곧 root다.
- 대시보드는 이미 LCD 일회용 코드 → administrator 토큰 흐름이 있다(D-193). CORE는 비특권이고, root 작업은 CORE가 요청 파일을 쓰면 root `.path` 유닛이 처리하는 형태를 쓴다(`rosy-hw-test.path`).

### Decision

**1. 화면 코드로 기기 키 등록 (기본 길).**
- 새 PC나 노트북에서 `tools/ssh/rosy_ssh_enroll.py <robot>`를 실행한다.
  1. 그 기기의 키를 만든다(`ssh-keygen -t ed25519`, 개인 키는 그 기기 밖으로 나가지 않는다).
  2. 운영자가 LCD의 administrator 로그인 코드를 입력한다(D-193 `pair`).
  3. administrator 토큰으로 `POST /api/v1/host/ssh/keys {public_key, label, expires_days}`를 보낸다.
  4. 로봇의 host key 지문(`GET /api/v1/host/ssh/host-keys`)으로 `known_hosts`를 쓴다. 처음 접속에서도 TOFU가 없다.
  5. ssh config에 `Host rosy-pinky-xxxx` 별칭을 쓴다.
  6. 토큰은 끝나면 logout한다.
- 로봇 쪽은 CORE가 요청 파일만 쓰고, root `rosy-ssh-access.path` → `rosy-ssh-access.py`가 검증하고 적용한다.
  - 키 형식 허용 목록(ed25519, sk-ed25519, ecdsa), 라벨 형식, 만료 최대 365일, 관리 키 최대 32개를 검사한다.
- 관리 키는 카드 키와 다른 파일 `/var/lib/rosy/ssh/authorized_keys`에 둔다.
  - sshd drop-in에 `AuthorizedKeysFile .ssh/authorized_keys /var/lib/rosy/ssh/authorized_keys`를 둔다.
  - 각 줄에 OpenSSH `expiry-time=` 옵션과 라벨 주석을 단다. 만료는 sshd가 직접 강제한다.
- 목록 `GET /api/v1/host/ssh/keys`와 회수 `DELETE /api/v1/host/ssh/keys/{label}`를 둔다. 추가와 회수는 `/var/lib/rosy/ssh/history.jsonl`에 남는다.

**2. 로봇별 임시 비밀번호 (보조 길, 필요할 때만).**
- administrator가 `POST /api/v1/host/ssh/password {minutes}`를 보낸다(최대 60분). 대시보드 버튼은 후속이다.
- root 도우미가 하는 일:
  - 무작위 비밀번호를 만든다. AP 비밀번호와 같은 헷갈리지 않는 31자 알파벳에, 그보다 긴 `rosy-xxxx-xxxx-xxxx` 꼴이다.
  - `rosy` 계정에 설정한다.
  - drop-in `/etc/ssh/sshd_config.d/60-rosy-temp-password.conf`(`Match User rosy Address <사설 대역>` → `PasswordAuthentication yes`, `MaxAuthTries 3`)를 쓰고 sshd를 다시 읽힌다.
  - 비밀번호는 LCD와 API 응답(administrator)으로만 보인다.
- 시간이 지나면 `rosy-ssh-password-expire.timer`가 drop-in을 지우고, 비밀번호 필드를 `*`(어떤 비밀번호도 맞지 않음)로 되돌리고, sshd를 다시 읽힌다.
  - 재부팅하면 무조건 꺼진다. 부팅 때 정리 단계가 있다.
- 공통 기본 비밀번호는 어디에도 두지 않는다.

**3. 팀 키 공유 (키 복사 길).**
- `tools/ssh/rosy_ssh_share.py create --name <team-name>`이 공유용 묶음을 만든다.
  - 공유 전용 ed25519 키를 **passphrase로 잠가** 만든다.
  - 묶음(zip): 잠긴 개인 키, `config`(로봇 별칭), `known_hosts`(로봇 host key), `README.md`(받는 사람용 한국어 안내).
- 같은 명령이 1의 API(또는 운영 키 ssh)로 각 로봇에 그 공개키를 라벨 `team:<name>`, 만료와 함께 등록한다.
- passphrase는 묶음과 다른 경로로 전한다(메신저와 구두 등).
- 회수는 `rosy_ssh_share.py revoke --name <team-name>`이다. 모든 로봇에서 그 라벨을 지운다.
- 운영 마스터 키는 공유하지 않는다.
- 묶음과 개인 키는 저장소에 넣지 않는다. 운영 PC의 `X:\DevTemp`나 사용자가 고른 곳에 둔다.

**4. 바뀌지 않는 것.**
- 카드 provision 키, `rosy` 계정, `NOPASSWD`는 그대로다. 그래서 2와 3의 접속도 root와 같다. 2가 시간 제한, 사설 대역, administrator 전용인 이유다.
- 대시보드 로그인 흐름(D-193)과 토큰 수명은 그대로다.

### Alternatives

- **공통 기본 비밀번호.** 저장소가 공개라 누구나 안다. 기각.
- **로봇별 비밀번호를 항상 켜기.** 같은 망의 누구에게나 무차별 대입 표면이 생기고, 누가 들어왔는지 모른다. 사용자가 고르지 않았다. 기각.
- **운영 마스터 키 복사로 공유.** 한 번 퍼지면 회수하려면 모든 로봇의 카드 키를 바꿔야 한다. 팀 키로 대신한다.
- **SSH 인증서(사이트 CA).** 로봇과 사람이 늘면 유리하다. 지금은 과하다. 후속으로 둔다.
- **Tailscale 같은 VPN.** 다른 네트워크에서 접속할 때 필요하다. 이 ADR 범위 밖이며 별도로 붙일 수 있다.

### Consequences

- 새 기기는 명령 하나와 LCD 코드로 접속을 얻는다. 기기마다 라벨이 남고 따로 회수된다.
- 급할 때는 휴대폰 SSH 앱으로 임시 비밀번호를 쓸 수 있다.
- 팀 묶음 하나로 여러 사람이 접속한다. 그 사람들은 서로 구분되지 않으므로, 오래 쓸 사람은 1로 자기 기기를 등록하게 안내한다.
- CORE API에 administrator 전용 엔드포인트 다섯 개가 생기고, root 도우미 하나와 path, timer 유닛이 image layer(D-388)에 더해진다.

### Risks

- **R1. 임시 비밀번호가 켜진 동안의 유출과 무차별 대입.** 사설 대역, `MaxAuthTries 3`, 최대 60분, 재부팅 시 해제로 줄인다. 켜고 끈 기록이 history에 남는다.
- **R2. 팀 키 묶음과 passphrase가 함께 새는 것.** passphrase는 별도 경로로 전하고, 만료를 기본 90일로 두며, `revoke`로 회수한다.
- **R3. CORE가 뚫리는 것.** administrator 토큰이 있으면 키를 추가할 수 있다. 이는 D-193 이후 administrator가 이미 가진 권한(모드, 업데이트)의 연장이다. root 도우미가 형식, 개수, 만료를 따로 검사한다.

### Validation

- HOST:
  - 키 형식, 라벨, 만료 검사.
  - 관리 파일의 원자 쓰기와 회수.
  - `expiry-time` 줄 생성.
  - 비밀번호 drop-in의 `Match` 대역.
  - 만료 타이머, 재부팅 정리.
  - PC 도구의 API 흐름(가짜 CORE).
  - 묶음 내용: 개인 키가 잠겨 있고 passphrase가 묶음에 없는지.
  - 각 가드는 변형으로 빨강을 확인한다.
- TWIN: 기기 쌍둥이(D-412)에 sshd를 넣어 다음을 확인한다.
  - 등록한 키로 접속된다.
  - 회수하면 거절된다.
  - 만료가 지나면 거절된다.
  - 임시 비밀번호로 접속되고, 만료 뒤에는 거절된다.
- DEVICE: 두 로봇에서 1·2·3 각각 한 번씩 확인한다.
