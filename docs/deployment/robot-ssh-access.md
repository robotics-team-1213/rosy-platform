# 로봇 SSH 접속 안내 (D-418)

운영자와 접속을 받는 사람을 위한 안내다. 결정과 이유는
[D-418](../adr/D-418-robot-ssh-access-code-enrollment-temporary-password-team-key.md),
API 계약은 [구현 계획](../plans/2026-10-02-d418-robot-ssh-access.md)에 있다.

- 로봇 계정은 `rosy` 하나다. `rosy`는 비밀번호 없이 `sudo`가 되므로 **SSH 접속은 곧 root 접속이다.**
- 평소에는 키로만 접속된다. 비밀번호 로그인은 꺼져 있고, 공통 기본 비밀번호는 어디에도 없다.
- 아래 명령의 `<robot-ip>`는 로봇 화면이나 관제에 보이는 주소로 바꾼다. 이 저장소는 공개이므로 실제 주소를 문서에 적지 않는다.
- 세 길 모두 로봇의 **administrator 로그인 코드**가 있어야 시작된다. 코드는 로봇 화면(LCD)에 나오거나,
  이미 접속되는 운영자가 로봇에서 `sudo rosy-login-code --role administrator`로 만든다. 코드는 한 번만 쓰인다.

| 길 | 언제 | 회수 |
|---|---|---|
| 1. 화면 코드로 기기 키 등록 (권장) | 자기 PC·노트북에서 오래 쓸 사람 | 기기 라벨 `dev:<이름>`을 지운다 |
| 2. 임시 비밀번호 | 급할 때, 키를 못 쓰는 휴대폰 앱 | 최대 60분 뒤 저절로, 재부팅해도 꺼진다 |
| 3. 팀 키 공유 | 여러 사람에게 한 번에, 짧은 기간 | 팀 라벨 `team:<이름>`을 지운다 |

필요한 것: OpenSSH 클라이언트(`ssh`, `ssh-keygen`; Windows 10/11, macOS, Linux 기본 포함)와 Python 3.10 이상.
도구는 표준 라이브러리만 쓰며 Windows, macOS, Linux에서 같다. Windows에서는 `python`, macOS·Linux에서는 `python3`로 실행한다.

## 1. 화면 코드로 기기 키 등록 (권장)

접속할 PC에서 저장소의 `Rosy OS` 폴더를 열고 실행한다.

```sh
python tools/ssh/rosy_ssh_enroll.py <robot-ip> --label dev:<내-기기-이름>
```

도구가 하는 일:

1. `~/.ssh/rosy_dev_<이름>` 키가 없으면 `ssh-keygen -t ed25519`로 만든다(Windows는 `%USERPROFILE%\.ssh\`).
   passphrase를 물으면 넣거나 비워 둔다. 개인 키는 이 PC 밖으로 나가지 않는다.
2. administrator 로그인 코드를 묻는다. 화면의 코드를 입력한다(입력은 화면에 보이지 않는다).
3. 로봇의 host key를 받아 `~/.ssh/known_hosts_rosy`에 쓴다. 그래서 첫 접속에서도 "이 호스트를 믿겠습니까" 질문이 없다.
4. 공개키를 라벨 `dev:<이름>`, 만료 `--days`(기본 90일, 최대 365일)로 로봇에 등록한다.
5. `~/.ssh/config`에 `Host rosy-pinky-xxxx` 블록을 쓴다(도구 표시 줄 사이만 고치고 나머지는 건드리지 않는다).
   쓰기 전에 `config.rosy-backup-<시각>`으로 백업하고, 쓴 뒤 `ssh -G`로 읽혀 본다. OpenSSH가 읽지 못하거나
   별칭이 다른 주소로 풀리면 이전 파일로 되돌리고 멈춘다. 블록의 줄은 정해진 옵션과 빈 값 없는 값만 허용한다.
6. 로그인 토큰을 logout한다. 토큰은 화면이나 파일에 남지 않는다.

끝에 나오는 명령으로 접속한다.

```sh
ssh rosy-pinky-xxxx
```

- 다시 실행해도 안전하다. 같은 키가 이미 등록돼 있으면 "already enrolled"와 기존 만료일을 보여 주고 config만 맞춘다.
  만료일은 늘어나지 않는다. **갱신**은 라벨을 지운 뒤(`rosy_ssh_share.py revoke --label dev:<이름> --robot <robot-ip>`) 다시 등록하는 것이다.
- 로봇이 `known_hosts_rosy`와 **다른 host key**를 내놓으면 옛·새 SHA256 지문을 보여 주고 멈춘다. 카드를 새로 구운
  경우에만 그렇다. 로봇 화면이나 콘솔에서 `ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub`로 새 지문을 확인한 뒤
  `--accept-new-host-keys`를 붙여 다시 실행한다.
- 별칭(`Host rosy-…`)이 이미 다른 주소를 가리키면 멈춘다. 로봇 주소가 바뀐 것이 맞으면 `--replace`를 붙인다.
- 별칭은 `rosy-`로 시작하는 로봇 이름만 쓴다. 블록은 config의 첫 `Host`/`Match`/`Include` 줄 **앞**에 들어가므로
  `Host *` 같은 앞선 설정보다 먼저 적용되고, 쓴 뒤 `ssh -G`로 사용자·키·known_hosts까지 확인한다.
- `~/.ssh/config`가 심볼릭 링크면 링크는 그대로 두고 링크가 가리키는 파일을 고친다(백업도 그 옆에 둔다).
- 같은 라벨을 다른 키가 쓰고 있으면 409로 멈춘다. 그 라벨을 먼저 지우거나 다른 라벨을 쓴다.
- 옵션: `--key PATH`(이미 있는 키), `--known-hosts`, `--ssh-config`, `--api-port`(기본 8080).

등록된 키 보기와 지우기는 3절의 `list`, 아래 API를 쓴다.

```sh
# 등록된 관리 키 목록 (모든 라벨)
python tools/ssh/rosy_ssh_share.py list --robot <robot-ip>
```

기기 라벨 하나를 지운다.

```sh
python tools/ssh/rosy_ssh_share.py revoke --label dev:<이름> --robot <robot-ip>
```

## 2. 임시 비밀번호 (필요할 때만)

로봇별로 무작위 비밀번호(`rosy-xxxx-xxxx-xxxx`)를 최대 60분 켠다. 사설 대역(10/8, 172.16/12, 192.168/16)에서만,
`MaxAuthTries 3`으로 받는다. 시간이 지나거나 로봇이 재부팅하면 꺼진다. 대시보드 버튼은 후속 작업이며,
지금은 API로 켠다.

먼저 administrator 코드로 토큰을 받는다. 토큰은 화면에 출력하지 말고 변수에만 둔다.

bash (macOS, Linux, Git Bash):

```bash
# Windows Git Bash에서는 아래 python3를 python으로 바꾼다.
R=<robot-ip>
read -rs -p "administrator login code: " CODE; echo
TOKEN=$(curl -fsS -X POST "http://$R:8080/api/v1/auth/pair" -H 'Content-Type: application/json' \
  -d "{\"code\":\"$CODE\",\"label\":\"ssh-password\"}" | python3 -c 'import json,sys; print(json.load(sys.stdin)["token"])')
unset CODE

# 켜기: 응답의 password를 받는 사람에게 전한다 (minutes 1..60)
curl -fsS -X POST "http://$R:8080/api/v1/host/ssh/password" -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"minutes": 30}'

# 상태 보기 / 지금 끄기
curl -fsS "http://$R:8080/api/v1/host/ssh/password" -H "Authorization: Bearer $TOKEN"
curl -fsS -X DELETE "http://$R:8080/api/v1/host/ssh/password" -H "Authorization: Bearer $TOKEN"

# 끝나면 토큰 logout
curl -fsS -X POST "http://$R:8080/api/v1/auth/logout" -H "Authorization: Bearer $TOKEN"; unset TOKEN
```

PowerShell (Windows):

```powershell
$R = "<robot-ip>"
$code = Read-Host "administrator login code" -AsSecureString
$plain = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($code))
$pair = Invoke-RestMethod -Method Post "http://${R}:8080/api/v1/auth/pair" -ContentType "application/json" `
  -Body (@{ code = $plain; label = "ssh-password" } | ConvertTo-Json)
Remove-Variable plain, code
$h = @{ Authorization = "Bearer $($pair.token)" }

# 켜기 (minutes 1..60): 결과의 user, password, expires_at
Invoke-RestMethod -Method Post "http://${R}:8080/api/v1/host/ssh/password" -Headers $h `
  -ContentType "application/json" -Body '{"minutes": 30}'

# 상태 보기 / 지금 끄기
Invoke-RestMethod "http://${R}:8080/api/v1/host/ssh/password" -Headers $h
Invoke-RestMethod -Method Delete "http://${R}:8080/api/v1/host/ssh/password" -Headers $h

# 끝나면 토큰 logout
Invoke-RestMethod -Method Post "http://${R}:8080/api/v1/auth/logout" -Headers $h; Remove-Variable pair, h
```

받는 사람은 `ssh rosy@<robot-ip>`로 접속하고 비밀번호를 입력한다. 휴대폰 SSH 앱(Termius 등)은 사용자 `rosy`,
인증 방식 password로 넣는다. 처음 접속 때 나오는 host key 지문은 운영자에게 확인받는다
(`ssh-keygen -lf ~/.ssh/known_hosts_rosy`로 볼 수 있다).

- 다 쓰면 기다리지 말고 바로 끈다(`DELETE /password`).
- 비밀번호는 로그, history, 파일 어디에도 남지 않는다. 받은 사람도 적어 두지 않는다.

## 3. 팀 키 공유

여러 사람에게 접속을 줄 때 쓴다. 운영 마스터 키(`rosy-operator-ed25519`)는 **절대 나누지 않는다.**
팀 키는 따로 만들고 passphrase로 잠그며, 로봇마다 라벨 `team:<이름>`으로 등록돼 한 번에 회수된다.

### 만들기 (운영자)

```sh
python tools/ssh/rosy_ssh_share.py create --name <팀이름> --robot <robot-ip> --robot <robot-ip-2> \
  --days 90 --out <저장소-밖-폴더> --contact "<회수 문의처>"
```

- passphrase를 두 번 묻는다(12자 이상). **비워 두면 도구가 만들어 마지막에 한 번만 보여 준다.**
  passphrase는 어떤 파일에도 쓰이지 않는다.
- 로봇마다 administrator 로그인 코드를 묻는다. 운영 키로 접속되는 로봇이면 `--via-operator-key`를 붙여
  코드를 ssh로 받아 쓸 수 있다(코드는 화면에 나오지 않는다).
- 한 로봇이라도 실패하면 묶음을 만들지 않고, 이미 등록된 로봇을 지우는 `revoke` 명령을 알려 준다.
- 결과: `<out>/rosy-<팀이름>.zip` — 폴더 없이 파일만 든 압축으로, 잠긴 개인 키와 `.pub`, `config`(로봇별 `Host`), `known_hosts`,
  받는 사람용 `README.md`(한국어).
- 함께 `<out>/rosy-<팀이름>.robots.txt`가 생긴다. 비밀이 없는 기록(로봇, host key 지문, 회수 명령)이며 운영자가 보관한다.
  끝에 정확한 `revoke` 명령도 출력된다.
- 같은 이름(hostname)을 내놓는 로봇이 둘이면 멈춘다(별칭이 겹치면 ssh는 첫 블록만 쓴다).
- 생성된 passphrase는 표준 오류(stderr, 터미널)에만 한 번 나온다. 출력이 터미널이 아니면 경고한다.
- `--out`은 저장소 밖으로 둔다. 묶음과 키를 저장소에 넣지 않는다.

### 넘겨주기

- zip과 passphrase는 **서로 다른 경로**로 전한다(예: zip은 파일 전송, passphrase는 구두나 다른 메신저).
- 받는 사람은 zip 안의 `README.md`를 따른다. 요약하면:
  1. 파일들이 `~/.ssh/rosy-<팀이름>/` 바로 안에 오게 푼다. Windows는 **모두 압축 풀기**의 대상을
     `%USERPROFILE%\.ssh\rosy-<팀이름>`로, macOS는 더블 클릭으로 생긴 `rosy-<팀이름>` 폴더를 `~/.ssh/`로 옮기고,
     Linux는 `unzip rosy-<팀이름>.zip -d ~/.ssh/rosy-<팀이름>`. macOS·Linux는 개인 키를 `chmod 600`.
  2. 그 폴더에서(PowerShell은 `cd $HOME\.ssh\rosy-<팀이름>`) `ssh -F config <로봇 별칭>`.
     passphrase는 처음 한 번 묻는다(ssh-agent를 쓰면 이후 생략).
  3. 휴대폰 앱(Termius 등)은 키 파일을 가져오고 passphrase를 넣는다.
  4. 다른 사람에게 다시 넘기지 않는다. 오래 쓸 사람은 1의 기기 등록을 받는다.

### 회수와 확인

```sh
python tools/ssh/rosy_ssh_share.py revoke --name <팀이름> --robot <robot-ip> --robot <robot-ip-2>
python tools/ssh/rosy_ssh_share.py list --robot <robot-ip> [--name <팀이름>]
```

- `revoke`는 로봇마다 `team:<팀이름>`을 지운다. 없는 로봇은 "was not present"로 알려 준다.
- 만료(`--days`)가 지나면 sshd가 그 키를 스스로 거절한다. 그래도 끝난 팀은 바로 `revoke`한다.
- 묶음이나 passphrase가 샌 것 같으면 기다리지 말고 `revoke`한 뒤 새 묶음을 만든다.

## 보안 메모 (ADR D-418 Risks)

- **R1. 임시 비밀번호가 켜진 동안의 유출과 무차별 대입.** 사설 대역, `MaxAuthTries 3`, 최대 60분,
  재부팅 시 해제로 줄인다. 켜고 끈 기록은 로봇의 `/var/lib/rosy/ssh/history.jsonl`에 남는다.
  쓰는 동안만 켜고, 끝나면 바로 끈다.
- **R2. 팀 키 묶음과 passphrase가 함께 새는 것.** passphrase는 별도 경로로 전하고, 만료를 기본 90일로 두며,
  `revoke`로 회수한다. 팀 키를 쓰는 사람들은 서로 구분되지 않으므로 오래 쓸 사람은 기기 등록으로 옮긴다.
- **R3. CORE가 뚫리는 것.** administrator 토큰이 있으면 키를 추가할 수 있다. 이는 administrator가 이미 가진
  권한(모드, 업데이트)의 연장이다. root 도우미가 키 형식, 개수(최대 32), 만료(최대 365일)를 따로 검사한다.

그 밖에:

- **host key 신뢰는 LAN 신뢰와 같다.** 도구는 로봇의 host key를 API(평문 HTTP)로 받아 `known_hosts`에 쓴다. 그래서
  첫 접속의 "믿겠습니까" 질문은 없지만, 같은 망에서 응답을 바꿔치기할 수 있는 사람이 있다면 그 사람의 key가 들어갈
  수 있다. 믿을 수 있는 망에서만 등록하고, 의심되면 로봇 화면이나 콘솔에서
  `ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub`로 지문을 대조한다. key가 바뀌면 도구는 옛·새 지문을 보여 주고
  `--accept-new-host-keys` 없이는 바꾸지 않는다.

- 로그인 코드와 토큰은 출력하거나 저장소·채팅에 남기지 않는다. 도구는 토큰을 출력하지 않고 끝나면 logout한다.
- API는 로봇 LAN의 평문 HTTP다(대시보드와 같음). 믿을 수 있는 망에서만 쓴다.
- `create`는 passphrase를 `ssh-keygen -N`으로 넘긴다(비대화식으로 넘길 다른 방법이 없다). 그 몇 초 동안 같은
  PC의 프로세스 목록에 보일 수 있으므로 공용 PC에서 실행하지 않는다.
- host key가 바뀌었다는 경고(`REMOTE HOST IDENTIFICATION HAS CHANGED`)가 나오면 카드를 새로 구웠는지
  운영자에게 확인한다. 확인 전에는 접속하지 않는다. 로봇 화면이나 콘솔에서 새 지문을 확인한 경우에만
  1의 등록을 `--accept-new-host-keys`와 함께 다시 실행한다.
