## D-524 Service Control. 관제는 사이트·AI·모델 Ubuntu의 재부팅과 허용된 서비스만 제어한다

**Status:** Proposed (2026-10-08, 사용자 지시 — 재부팅과 서비스 오류 복구는 관제 안의 관리 API. 이 브랜치에 구현. 2026-10-09 보안 검토 반영. 현장 설치와 실제 재부팅은 아직 하지 않음. 2026-10-10: 설치·보정 작업 「호스트 서비스」가 이 API만 부른다. 수락은 아직 아니다.)

**이름:** Service Control. 화면의 한국어 이름은 서비스 제어. Rosy Fleet 안의 기능이고, 새 앱이 아니다.

## 배경

- 사이트 관제(Rosy Fleet, `console`)가 로봇 모니터링을 이미 소유한다. 호스트를 재부팅하거나 서비스를 세우는 일은 그 관제 안에 둔다. 새 앱·새 로그인·새 서버는 만들지 않는다.
- 대상은 Ubuntu 세 대다. `site`는 관제 PC, `ai`는 AI PC, `model`은 모델 PC다. 로봇은 대상이 아니다.
- 세 계정 모두 일반 비밀번호 없는 sudo가 없다. Fleet은 사이트 PC의 Docker 안(`deploy/site/compose.yaml`)에서 읽기 전용 루트, `cap_drop: ALL`, `no-new-privileges`로 돈다. 컨테이너 안에서는 sudo도 setuid도 쓸 수 없다.
- Fleet은 사이트 PC에만 있다. AI·모델 PC는 같은 경로로 원격 제어해야 한다. 모델 PC 멈춤 감시(`rosy-model-guard`)가 이미 사이트에서 강제 명령 SSH 키로 모델 PC의 `reboot`만 부른다.
- `pkill`에 프로세스 이름을 넘기면 ssh와 관제 프로세스까지 멈출 수 있다.

## 결정

1. **조작은 이름 있는 운영자 API 하나다.** `GET /api/fleet/hosts`는 호스트·동작·유닛 목록이다(운영자). `POST /api/fleet/hosts/{host}/control`은 `require_named_operator`다. site-users 자격, 로그인 세션, 개발 세션만 이름 있는 운영자다. 토큰·site-users·로그인이 없는 사이트에서는 모든 호출자가 `site-console` 운영자가 되므로, Fleet은 site-users나 로그인이 설정됐을 때만 도우미를 만들고 아니면 503 `HOST_HELPER_UNAVAILABLE`이다. 본문은 `{action, unit, operator_confirmed:true}`이고 추가 필드와 `operator_confirmed`가 true가 아닌 본문은 거절한다.
2. **동작은 닫힌 집합이다.** `reboot`, `cancel-reboot`, `restart-unit`, `stop-unit`만 받는다. `pkill`, `kill`, 시그널, 셸 문자열, 프로세스 이름은 `UNKNOWN_ACTION`이다.
3. **재부팅은 10분 뒤이고 한 번만 예약한다.** 도우미는 `shutdown -r +10`만 호출한다. 이미 예약된 재부팅이 있으면(logind의 `/run/systemd/shutdown/scheduled`) 거절한다(409 `REBOOT_ALREADY_SCHEDULED`). 같은 요청을 되풀이해 재부팅을 미룰 수 없다. 도우미는 자기가 예약한 시각을 루트 소유 `/run/rosy-host-control/reboot`에 남긴다. `cancel-reboot`는 그 표지가 지금 예약과 같을 때만 `shutdown -c`를 한다(아니면 409 `NO_HOST_CONTROL_REBOOT`). 각 PC의 야간 재부팅(`rosy-nightly-reboot.timer`)과 unattended-upgrades의 재부팅은 취소하지 않는다. `/run`은 재부팅 때 비므로 표지도 같이 사라진다.
4. **유닛도 닫힌 집합이고 동작은 유닛마다 정한다.** `site`는 `docker.service`, `rosy-site-stack.service`, `rosy-site-firewall.service`이고 셋 다 `restart-unit`만 된다. 방화벽을 세우면 사이트 방어가 빠지고, Docker나 스택을 세우면 Fleet 자신이 멈춰 API로 되살릴 수 없다. `ai`는 Pinky 사용자 유닛 여섯 개(`pinky-backend`, `pinky-frontend`, `pinky-nav2`, `pinky-rosbridge-d12`, `pinky-rosbridge-d13`, `pinky-r2-watch`)이고 재시작과 정지가 된다. `model`은 오늘 허용 유닛이 없다. 학습 프로세스는 systemd 유닛이 아니라 여기서 멈추거나 다시 시작하지 않는다. 다른 유닛과 허용되지 않은 동작은 `UNIT_NOT_ALLOWED`다. 유닛 동작은 `systemctl --no-block`이라 응답이 그 유닛의 재시작을 기다리지 않는다.
5. **실행은 각 호스트의 루트 도우미만 한다.** `deploy/site/rosy-host-control`을 `/usr/local/sbin/rosy-host-control`(root 소유, 0755)에 설치한다. 인자 목록으로만 `shutdown` 또는 `systemctl`을 호출하고 `PATH`를 고정한다. 역할(`site`, `ai`, `model`)은 루트 소유 `/etc/rosy/host-control/role`에서 읽고 환경 변수에서 읽지 않는다. AI 사용자 유닛의 계정은 `/etc/rosy/host-control/units-user`에서 읽고 코드에 적지 않는다. 시험용 출력 스위치는 없다. 시험은 자기 사본과 가짜 명령을 쓴다.
6. **sudoers는 한 줄이다.** `/etc/sudoers.d/rosy-host-control`은 `<로그인 계정> ALL=(root) NOPASSWD: /usr/local/sbin/rosy-host-control`뿐이다. `SETENV`와 `env_keep`은 넣지 않는다. sudo의 `env_reset`이 환경을 지운다.
7. **컨테이너에서 호스트까지는 강제 명령 SSH 키 하나다.** Fleet은 세 호스트 모두, 자기 사이트 PC까지 같은 방법으로 부른다. `/usr/bin/ssh -F /dev/null -i <키> -o BatchMode=yes -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes -o UserKnownHostsFile=<known_hosts> -- <user>@<host> <action> [unit]`을 인자 목록으로 실행한다. 키·known_hosts·대상 목록은 사이트 PC의 `/etc/rosy/fleet-host-control/`(키는 root:10001 0440)에 있고, Fleet 컨테이너만 `/run/rosy-fleet-host-control`로 읽기 전용 마운트한다. Vision도 같은 uid 10001로 사이트 설정 디렉터리를 마운트하므로 키를 그 안에 두지 않는다. 디렉터리가 비어 있으면 503이다. 대상 줄은 `<host> <user>@<호스트 이름>`이고 저장소에는 주소를 적지 않는다. 각 호스트의 `authorized_keys`에는 `from="<사이트 PC 주소>,<Docker 브리지 대역>",command="/usr/local/sbin/rosy-host-control-remote",restrict <키>` 한 줄만 있다. `from=` 목록은 설치 때 `--from`으로 받고 저장소에 적지 않는다. 같은 키가 다른 옵션으로 이미 있으면 설치 도구가 경고하고 그 줄을 바꾼다. 이 강제 명령은 `SSH_ORIGINAL_COMMAND`를 글롭 없이 한두 단어로 나누고, 소문자·숫자·`.@-` 밖의 문자를 거절한 뒤 `sudo -n /usr/local/sbin/rosy-host-control <action> [unit]`을 인자 목록으로 실행한다. Fleet 이미지에는 `openssh-client`만 더한다.
   - 고른 이유: 컨테이너는 `no-new-privileges`라 직접 sudo를 쓸 수 없다. 사이트 PC의 sshd와 모델 PC 감시의 강제 명령 키 방식이 이미 있어 새 데몬·소켓·포트가 없다. 같은 키 하나로 AI·모델 PC까지 한 경로가 된다. 키는 호스트마다 `authorized_keys` 한 줄을 지우면 회수된다. 호스트 쪽 다리 데몬이나 Unix 소켓은 새 특권 프로세스를 하나 더 만들고 원격 PC에는 또 다른 경로가 필요해 고르지 않았다. Docker 소켓을 컨테이너에 넣는 방법은 호스트 루트와 같아 거절했다.
   - 원래 문구 "Fleet은 SSH로 재부팅하지 않는다"를 고친다. Fleet은 이 강제 명령 키로만 SSH를 쓰고, 그 키로는 이 도우미의 허용 동작 밖의 일을 할 수 없다. 사람이나 에이전트가 임의 SSH로 `reboot`를 부르는 것은 여전히 운영 경로가 아니다.
8. **감사.** POST는 인가 단계에서 `fleet_api_audit`의 INTENT·RESULT 행(주체, 역할, 경로=호스트, 상태 코드)을 남긴다. 이름 있는 운영자가 있으려면 site-users나 로그인이 필요하고 그때 tasks DB가 필수이므로, 도우미가 켜진 사이트에는 늘 이 행이 있다. 라우트는 도우미 호출 앞뒤로 호스트·동작·유닛·주체·결과를 로그에 남긴다. 각 호스트의 도우미는 역할·동작·유닛·sudo 사용자·결과를 `logger -t rosy-host-control`로 journal에 남긴다. journal의 `by=`(`SUDO_USER`)는 SSH 키가 들어오는 로그인 계정이지 운영자가 아니다. 운영자 이름은 Fleet의 감사 행과 로그에만 있다.
9. **설치 도구는 호스트마다 하나다.** `sudo deploy/site/install-host-control.sh --role site|ai|model [--fleet-key "<공개키>" --from "<사이트 PC 주소>,<Docker 브리지 대역>"] [--units-user <계정>] [--make-fleet-key] [--dry-run]`이 도우미, 강제 명령, 역할 파일, sudoers, `authorized_keys` 줄을 넣는다(`install-model-pc-guard.sh`와 같은 모양). `--make-fleet-key`는 사이트 PC에서 Fleet 키를 만든다. 대상 목록과 known_hosts는 사이트 운영자가 쓴다.
10. **한계.** Fleet 프로세스나 그 키를 빼앗은 쪽은 이 닫힌 집합 전부를 쓸 수 있다. 세 PC를 10분 예약 재부팅으로 되풀이해 다시 켤 수 있고(예약 중에는 한 번만), 사이트의 Docker를 재시작해 Fleet과 Vision을 잠시 멈출 수 있고, AI PC의 Pinky 유닛을 세울 수 있다. 임의 명령, 다른 유닛, 방화벽 정지, 셸은 얻지 못한다. 키 회수는 각 호스트의 `authorized_keys` 한 줄 삭제다.
11. **Vision은 Fleet의 비밀을 볼 수 없다(보안 검토).** `/etc/rosy/site` 전체를 Vision(uid 10001, 휴대폰 프레임을 받는 서비스)에 마운트하면 그 안의 `secrets/`(`robot_credential_key`, `registry_token`, `discovery_token`, `site.key`)가 root:10001 0440이라 읽힌다. 고친 것: (a) 비밀 디렉터리를 설정 디렉터리 밖 `/etc/rosy/site-secrets`로 옮긴다. (b) Vision은 설정 디렉터리에서 `site-cameras.yaml` 한 파일만 읽기 전용으로 마운트한다. (c) 서비스마다 Compose `secrets:`를 자기 몫만 준다(Fleet 8개, Vision 6개, proxy 3개; `registry_token`, `discovery_token`, `robot_credential_key`는 Fleet 전용). `site.key`는 TLS를 끝내는 Vision과 proxy가 쓴다. 기존 사이트는 `deploy/site/migrate-site-secrets.sh`로 옮기고 옛 경로에 심볼릭 링크를 남긴다. Vision이 그 디렉터리를 마운트하지 않으므로 링크가 비밀을 다시 드러내지 않는다. 계약 시험 `test_vision_cannot_reach_fleet_secrets`.
12. **사이트 설정 설치(2026-10-10 개정).** 사용자: "너가 키가 다 있을텐데? 없으면 이번에 만들고 교훈기록해", 선택 "설정 설치 전용 도우미". 도우미에 `install-site-config <이름>`을 더한다. 사이트 역할에서만, 이름은 `fleet-site.yaml`·`site-cameras.yaml` 둘만(`robots.yaml`은 로봇 토큰이 있어 뺀다) 받는다. 원본은 `~SUDO_USER/.rosy/site-incoming/<이름>`이고 그 계정 권한으로 읽는다(심볼릭 링크로 root만 읽는 파일을 끌어오지 못한다). 64 KiB 상한, YAML 검사를 통과해야 `/etc/rosy/site/<이름>`(root, 0644)으로 바꿔 끼우고, 이전 파일은 `/var/lib/rosy-host-control/backup/`에 남긴다. Fleet 키의 강제 명령은 이 동작을 거절한다. 로그인한 운영자(또는 그 계정의 에이전트)만 쓴다. 적용은 Fleet 재시작이 필요하며 그건 기존 `docker` 권한으로 한다.

## 범위 밖

- 관제 첫 화면의 위험 채움과 프로세스 종료 버튼. 재부팅·유닛 버튼은 설치·보정 작업 `호스트 서비스` 하나에만 둔다(D-540 5항). 이 작업은 D-524가 Proposed인 동안에도 운영자 요청으로 있다. 그 화면에도 프로세스 종료와 로봇 재부팅은 없다.
- 세 PC에 실제로 설치하는 일. 이 브랜치는 설치 도구만 싣는다.
- 로봇 재부팅, Docker 컨테이너 이름, 임의 프로세스 종료.
- 모델 PC의 학습 프로세스를 멈추는 일.
- 호스트 감시의 쓰기. `guard`와 `drift`는 `GET /api/fleet/hosts`의 읽기 전용 필드다(D-530). 없거나 객체가 아니면 null이다.

## 검토한 대안

- 관제에서 `pkill` 패턴을 그대로 실행한다. 프로세스 이름 하나로 ssh와 Fleet을 멈출 수 있어 거절했다.
- 에이전트나 사람이 임의 SSH로 `reboot`를 호출한다. 운영 경로는 이 API로 둔다.
- 사이트 PC는 로컬 실행, 원격 PC만 SSH. 컨테이너 안에서 로컬 sudo가 불가능하고 경로가 둘이 되어 거절했다.
