## D-530 팀 호스트는 저장소의 역할별 바라는 상태, 호스트별 드리프트 점검, 관제 PC 가드로 사람 없이 유지한다

**Status:** Proposed (2026-10-09, 사용자 목표 "모든 팀 장비가 사람 손 없이 계속 동작하고, 관리 체계는 저장소 하나에서 정의한다". 첫 저장소 조각만 이 브랜치에 구현. 실제 장비에는 아무것도 설치·활성화하지 않았다). D-524(Service Control, `feat/host-control`, Proposed) 위에 선다. 착지 순서는 D-524 다음이 이 ADR이다.

### Context

2026-10-09 읽기 전용 점검(관제 PC, 모델 PC, AI PC, 로봇 두 대)에서 다음을 확인했다.

- 세 PC의 새벽 재부팅(`rosy-nightly-reboot.timer`/`.service`, `/etc/systemd/system`)은 저장소에 없다. 시각은 AI PC 05:58, 모델 PC 06:03, 관제 PC 06:08이고 2분 경고 뒤 재부팅한다. 모델 PC는 디스크의 유닛이 바뀌었는데 `daemon-reload`가 안 된 상태였다.
- 관제 PC의 `rosy-docker-upgrade.timer`(04:30 + 무작위 45분)와 스크립트도 저장소에 없다. `rosy-site-update.timer`(매시)는 옛 저장소 이름을 쓰는 별도 갱신기이고, 저장소의 D-441 `rosy-site-autoupdate.timer`와 같은 일을 두 번 한다.
- [모델 PC 멈춤 대비](../../deploy/site/model-pc-guard.md)는 저장소에만 있다. 모델 PC의 `RuntimeWatchdogSec`는 주석이고 `kernel.panic`은 0이다. 관제 PC에는 `rosy-model-guard.timer`가 없다. 문서상 대비가 실제로는 꺼져 있었다.
- 세 PC 모두 sshd 비밀번호 로그인이 켜져 있다(로봇은 키만). 관제 PC와 AI PC는 오래된 Wi-Fi 여러 개에 자동 연결한다. 관제 PC 로그인 화면은 배터리일 때 절전할 수 있다(`sleep-inactive-battery-type=suspend`).
- AI PC `pinky-v13-training`은 `Restart=no`, 모델 PC `rosy-tensorboard`는 enabled인데 부팅 직후 다섯 번 실패하고 멈춰 있다.
- 로봇은 Tailscale이 없고, 관제 Fleet :8443은 LAN에서만 열린다. 9dfk 부하는 약 9.5, 8kcn은 SPI DMA timeout을 낸다.
- 어떤 유닛도 `WatchdogSec=`를 쓰지 않는다.

손으로 고친 설정은 다음 사람이 모르고, 문서와 실제가 갈라져도 아무도 알리지 않는다. 같은 일이 되풀이되지 않으려면 바라는 상태가 저장소에 있고, 호스트가 스스로 비교하고, 다른 호스트가 밖에서 살펴야 한다.

### Decision

**1. 역할별 바라는 상태는 기존 배포 폴더의 `host-state/`에 둔다.** 관제 PC는 `deploy/site/host-state/`, 모델 PC는 `deploy/model_pc/host-state/`, AI PC는 `deploy/ai_pc/host-state/`, 세 PC 공통은 `deploy/hosts/common/host-state/`다. 새 `deploy/hosts/<role>/` 트리를 만들지 않는다. 그 역할의 다른 배포 파일이 이미 그 폴더에 있기 때문이다.

- 각 폴더의 `manifest`가 한 줄에 하나씩 `<정책> <종류> <인자>`를 적는다. 종류는 `file`(설치 경로와 저장소 파일, 바이트 비교), `enabled`/`disabled`/`masked`(유닛 상태), `linger`(설치한 로그인 계정), `wifi-allow`(호스트의 `/etc/rosy/host-state/wifi-allow`에 적힌 연결만 자동 연결)다.
- 첫 내용: 새벽 재부팅 타이머와 서비스(실제 값을 그대로 옮김), 관제 PC Docker 갱신 타이머와 스크립트, 드리프트 점검 유닛, logind(뚜껑·idle 무시), sleep 대상 mask, `tailscaled` enabled, linger, sshd drop-in, 관제 PC 가드 유닛, 모델 PC 워치독과 lockup 재부팅 설정.
- 계정 이름, 주소, SSID는 저장소에 넣지 않는다(D-226). linger 계정은 설치할 때의 `SUDO_USER`를 쓰고, Wi-Fi 허용 목록은 호스트 파일이다.
- 적용은 역할마다 한 명령이다. `sudo python3 deploy/hosts/common/rosy-host-state install <site|model|ai>`. 같은 명령을 다시 돌려도 결과가 같다. `--dry-run`은 root 없이 차이(파일은 unified diff)만 출력한다. 설치는 승인된 사본을 `/usr/local/lib/rosy-host-state/`에 두고, 그 뒤 점검은 그 사본과 비교한다. 호스트가 root로 저장소를 직접 당겨 오지 않는다. 사본을 바꾸는 길은 사람이 설치를 다시 돌리는 것뿐이다.

**2. 드리프트 점검은 각 PC의 `rosy-host-state.timer`(부팅 15분 뒤, 이후 30분마다)가 한다.** 정책은 셋이다.

| 정책 | 설치 | 타이머 | 대상 |
| --- | --- | --- | --- |
| `safe` | 적용 | 바로잡고 기록 | Rosy 소유 유닛·drop-in 파일, Rosy 타이머 enabled, `tailscaled` enabled, linger |
| `report` | 적용 | 기록만, 점검 실패로 표시 | sleep mask, 모델 PC 워치독 |
| `approval` | `--approve <대상>`일 때만 | 기록만(승인 대기로 표시, 실패 아님) | 사이트 방화벽·스택 enabled(`firewall`), Wi-Fi 자동 연결 끄기(`wifi`), sshd 비밀번호 끄기, 옛 갱신기 끄기, D-524 도우미와 그 sudoers 한 줄과 역할 파일 |

- 방화벽·네트워크를 건드리는 줄은 설치가 기본으로 적용하지 않고 보고만 한다. 매니페스트의 `approval=<묶음>` 줄은 `--approve firewall,wifi`처럼 묶음 이름이나 경로·유닛 이름으로 승인한다.
- `--dry-run`은 root 없이 돈다. root만 읽는 파일(예: `0440` sudoers)은 "cannot compare without root"로 표시하고 건너뛴다.
- 승인된 사본은 옆 디렉터리에 다 만든 뒤 한 번에 바꿔 끼운다. 복사 도중 실패해도 이전 사본이 남는다.
- 파일을 덮어쓰기 전에 이전 내용을 `/var/lib/rosy-host-state/backup/<시각>/<경로>`에 저장하고, 보고(`fixed`)에 그 경로를 적는다.

- 세 PC 공통 바라는 상태에 D-524 도우미(`/usr/local/sbin/rosy-host-control`, 원본 `deploy/site/rosy-host-control`), 로그인 계정이 그 도우미만 root로 실행하는 sudoers 한 줄, 역할 파일(`/etc/rosy/host-control/role`)을 넣는다.
- sudoers 파일은 `visudo -c`가 통과해야 설치하고, 실패하면 설치하지 않는다. sshd 파일은 `sshd -t`가 통과해야 reload하고, 통과하지 못하면 이전 내용을 되돌린다. Wi-Fi는 허용 목록이 비었거나 없으면 아무것도 끄지 않는다. 원격 접속을 끊을 수 있는 변경은 `safe`에 두지 않는다.
- 결과는 `/var/lib/rosy-host-state/status.json`과 journal에 남는다. 고친 것, 남은 드리프트, 승인 대기를 따로 적는다.

**3. 관제 PC의 `rosy-host-guard`가 다른 호스트를 밖에서 본다.** `rosy-model-guard`를 일반화해 대체한다.

- 대상 목록은 호스트의 `/etc/rosy/host-guard/hosts.conf`다(주소가 있으니 저장소에는 `.example`만). PC는 SSH 강제 명령 키로 `health`, `restart <unit>`, `reboot`만 부를 수 있다(`rosy-host-guard-remote`). `health`는 읽기 전용 응답이고, 감시 유닛은 대상 호스트의 `/etc/rosy/host-guard/units`다.
- **실행은 D-524 도우미 하나뿐이다.** 강제 명령의 `restart`와 `reboot`는 그 호스트의 `sudo -n /usr/local/sbin/rosy-host-control restart-unit <unit>`과 `reboot`를 부른다. 강제 명령은 `systemctl restart`나 재부팅을 직접 하지 않는다. 그래서 다시 시작할 수 있는 유닛과 재부팅 방식(`shutdown -r +10`)은 D-524의 닫힌 집합이 정하고, 운영자 조작(Fleet API)과 자동 회복(가드)이 같은 길과 같은 허용 목록을 쓴다. D-524 5항의 "Fleet은 SSH로 재부팅하지 않는다"는 그대로다. 가드는 Fleet이 아니고, 다른 호스트의 로컬 도우미를 부르는 강제 명령만 쓴다.
- 회복 사다리: 10분마다 점검한다. 연속 N번(기본 3) 나쁘면, 멈춘 감시 유닛이 있을 때 그 유닛을 다시 시작하고, 없을 때 재부팅한다. 다시 시작한 뒤에도 2N번째까지 나쁘면 재부팅한다. 메모리 부족만 나쁠 때는 다시 시작이 도움이 되지 않으므로 N번째에 재부팅한다.
- **높은 부하는 보고만 한다.** 부하가 코어 수의 4배를 넘는 것만으로는 사다리가 오르지 않는다(모델·AI PC의 학습은 정당하게 무겁다). `status.json`에 `load-high`로 남고, 메모리 부족이나 멈춘 유닛이 함께 있을 때만 나쁨으로 센다.
- **재부팅 상한.** 호스트마다 건강한 점검이 나올 때까지 최대 2번(`GUARD_MAX_REBOOTS`)만 재부팅하고, 두 재부팅 사이에 최소 1시간(`GUARD_REBOOT_MIN_GAP_S`)을 둔다. 횟수와 마지막 재부팅 시각은 `status.json`에 저장되어 `rosy-ssh-watchdog`의 `MAX_REBOOTS`·`REBOOT_MIN_GAP_S`와 같은 방식으로 지켜진다. 계속 나쁜 호스트가 시간마다 재부팅되지 않는다.
- **거절은 사실대로 남긴다.** 강제 명령의 다시 시작·재부팅이 0이 아닌 코드로 끝나면(재부팅이 이미 예약됨 3, sudo 없음 등) `actions.jsonl`에 `... refused`와 종료 코드·메시지를 적고, 재부팅 횟수·나쁨 횟수를 성공한 것처럼 바꾸지 않는다. 모든 다시 시작이 거절되면 사다리는 재부팅 단계로 넘어간다.
- 한 호스트의 오류(잘못된 `health` 응답, 짧은 설정 줄)는 그 호스트를 `error`로 표시할 뿐 나머지 호스트 점검과 `status.json` 기록을 막지 않는다.
- 감시 유닛 확인은 D-524의 호스트별 유닛 집합을 따른다. `site` 역할(`/etc/rosy/host-control/role`)은 시스템 유닛(`systemctl is-active`), 모델·AI 역할은 사용자 유닛(`--user`)이다.
- 막지 않는 조건: 그 호스트의 새벽 재부팅 창(설정의 `HH:MM-HH:MM`, 기본은 예약 시각 앞 10분·뒤 20분)에는 점검도 행동도 하지 않는다. 도우미 재부팅은 10분 뒤라서, 10분 뒤가 창 안이면 재부팅을 보내지 않는다. 부팅 1시간 안에는 재부팅하지 않는다. 응답이 없으면 기록만 한다. 커널이 멈춘 경우는 하드웨어 워치독이, 네트워크만 끊긴 경우는 아래 호스트 로컬 층이 맡는다.
- 로봇은 이 가드에 CORE 포트 연결 확인으로만 들어온다. 로봇 회복은 D-412 자동 갱신과 `rosy-*` 유닛이 맡고, 가드는 로봇을 다시 시작하거나 재부팅하지 않는다. 움직이는 로봇을 밖에서 끄면 안전하지 않다.
- 감사: 모든 행동은 `/var/lib/rosy-host-guard/actions.jsonl`에 한 줄씩(시각, 호스트, 행동, 이유) 남고 journal에도 남는다. 호스트별 현재 상태는 `status.json`이다.
- Fleet 보고: 새 쓰기 API는 만들지 않는다. D-524의 `GET /api/fleet/hosts`에 읽기 전용 `guard` 필드로 `status.json`을 붙인다(아래 D-524 개정 제안). Fleet 컨테이너는 `/var/lib/rosy-host-guard`를 읽기 전용으로 마운트한다. 그 전까지는 journal과 파일이 보고다.
- 관제 PC 자신: 모델 PC가 같은 스크립트로 관제 PC를 역방향으로 본다(설정 파일만 다름, 관제 PC의 D-524 도우미가 `site` 역할로 실행). 관제 PC에도 모델 PC와 같은 하드웨어 워치독과 `kernel.panic`을 둔다.
- 호스트 로컬 층: `fix/ssh-self-recovery` 브랜치의 `rosy-ssh-watchdog`(두 로봇에는 이미 설치됨. 2분마다 sshd·tailscale·게이트웨이 확인, ssh → tailscaled → NetworkManager → 재부팅, 부팅 10분 유예, 시간당 재부팅 1회)이 가드 아래 층이다. 이 ADR은 그 파일을 소유하지 않는다. 가드는 연결이 끊긴 호스트를 고치려 하지 않으므로 두 층이 같은 호스트를 동시에 재부팅하려 다투지 않는다.

**4. `WatchdogSec=`와 `sd_notify`는 로봇 Host Agent부터 쓴다.** Host Agent는 root로 도는 오래 사는 Python 프로세스이고, 막히면 CORE의 lane 명령이 멈춘다. `serve_forever` 루프에서 `NOTIFY_SOCKET`(AF_UNIX, 이미 허용됨)에 `WATCHDOG=1`을 보내는 몇 줄로 끝나므로 비용이 작다. `Type=notify`, `WatchdogSec=30s`로 한다. 로봇 이미지 변경이라 별도 브랜치에서 D-412 릴리스로 낸다. 사이트 스택(`rosy-site-stack.service`)은 `docker compose up -d` oneshot이라 `WatchdogSec`가 뜻이 없다. 컨테이너 healthcheck와 `restart=unless-stopped`가 이미 그 일을 하고, 가드가 바깥을 본다. 모델·AI PC 사용자 유닛은 대부분 남의 서버(ollama, 학습)라 `sd_notify`를 넣을 곳이 없다. 대신 `Restart=on-failure`와 가드의 사다리를 쓴다.

**5. D-524 개정 제안(D-524 파일은 이 브랜치에서 고치지 않는다).**

- 역할을 환경 변수 대신 `/etc/rosy/host-control/role`에서도 읽는다. sudo는 환경을 지우므로 강제 명령에서 `ROSY_HOST_CONTROL_ROLE`이 전달되지 않는다. 호출자가 역할을 고르면 다른 역할의 유닛 집합을 쓸 수 있으니 파일이 맞다.
- `model` 역할에 사용자 유닛을 넣는다: `rosy-ollama`, `rosy-review-v12`, `rosy-review-v13`, `rosy-dataset-review`, `rosy-edge-review`, `rosy-tensorboard`(`restart-unit`만, 학습 유닛 제외).
- `site` 역할 유닛은 시스템 유닛이고 `ai`는 `--machine=<계정>@`이다. 계정 이름을 도우미에 쓰지 않고 역할 파일 옆의 로그인 파일에서 읽는다(D-226).
- `GET /api/fleet/hosts`에 읽기 전용 `guard` 필드(가드 `status.json`)와 `drift` 필드(관제 PC 자신의 `rosy-host-state` `status.json`)를 더한다.
- 읽기 전용 `health` 동작은 도우미에 넣지 않는다. 가드 강제 명령이 이미 root 없이 답한다.

**6. 사용자 승인이 있어야 하는 접근 변경(목록만, 적용 안 함).**

- 세 PC의 sshd 비밀번호 로그인 끄기(`approval file /etc/ssh/sshd_config.d/10-rosy.conf`). 먼저 각 PC에 키 로그인이 되는 사람이 둘 이상인지 확인한다.
- 로봇에 Tailscale 설치(지금 `rosy-tailscale-join`은 아무것도 하지 않는다). D-418 접근 경로와 로봇 이미지가 바뀐다.
- Fleet을 Tailscale에서 열기(`rosy-site-firewall` 허용 인터페이스 추가). 외부 접근 면이 넓어진다.
- AI PC 적용 전체. 다른 사람과 같이 쓰는 PC라 그 사람의 동의가 먼저다(새벽 재부팅은 이미 돌고 있지만 linger·logind·가드 키·유닛 재시작은 새로 생긴다).
- 관제 PC 옛 갱신기 `rosy-site-update.timer` 끄기. D-441 자동 갱신과 겹친다.
- 가드의 회복 권한: 각 PC의 D-524 도우미, 그 sudoers 한 줄, 강제 명령 키.

**7. 사람만 할 수 있는 일.** BIOS의 "AC 전원 연결 시 켜기"(세 PC), 8kcn SPI 하드웨어 점검, 모델 PC 유선 연결, 관제 PC sudo 비밀번호를 아는 사람의 첫 설치. 이 체계는 sudo 없이 처음 설치될 수 없고, 그 뒤부터 사람 없이 유지된다.

### Consequences

- 손으로 바꾼 Rosy 유닛은 30분 안에 되돌아가고 journal에 남는다. 손으로 바꿔야 하면 저장소를 먼저 바꾸고 설치를 다시 돌린다.
- 문서상 켜져 있다고 믿은 대비(모델 PC 워치독처럼)가 꺼져 있으면 `report` 드리프트로 보인다.
- 관제 PC가 죽으면 가드도 죽는다. 그래서 모델 PC 역방향 가드와 관제 PC 워치독이 필요하고, 둘 다 승인 뒤 설치한다.

### Verification

호스트 pytest(가짜 `systemctl`·`ssh`)로 차이 감지, `safe`만 바로잡기, `approval` 미적용, 사다리(N번 → 재시작 → 2N번 → 재부팅), 새벽 창 안에서 행동 없음을 확인한다. 실제 PC 설치, 재부팅 회복, Fleet 표시는 이 ADR의 증거가 아니며 승인 뒤 각 PC에서 따로 확인한다.

**Related:** [D-226](D-226-document-placement-and-publication-criteria.md), [D-412](D-412-robots-self-update-from-signed-github-releases-when-idle.md), [D-418](D-418-robot-ssh-access-code-enrollment-temporary-password-team-key.md), [D-434](D-434-model-pc-and-site-pc-roles.md), [D-441](D-441-site-stack-automatic-update.md), D-524(Service Control, `feat/host-control`, 미착지), [모델 PC 멈춤 대비](../../deploy/site/model-pc-guard.md).
