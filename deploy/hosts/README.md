# PC 자동 복구와 모니터링

## 공통 시간 동기화 (D-859)

관제 PC가 현장 NTP 서버이고 모델·AI·OMX·카메라 호스트와 Pinky는 클라이언트다.
기준과 수용 조건은 [D-859](../../docs/adr/D-859-shared-utc-time-synchronization.md),
전체 기기의 동일한 단일 endpoint 결정은 [D-861](../../docs/adr/D-861-one-identical-ntp-endpoint-for-all-devices.md)다.
실제 서버 이름·주소·CIDR은 호스트에만 둔다. 아래 자리표시자는 운영 값으로 바꾼다.
표시 시간대(예: Asia/Seoul)는 UTC 동기화와 별개이며 바꿀 필요가 없다.

1. **유지보수:** 작업·주행·학습·수집과 현장 컨테이너를 중지한다. `chrony`를 설치한다
   (`sudo apt-get install chrony`). 다른 시간 데몬(`systemd-timesyncd`, `ntp`, `ntpsec`)이
   실행 중이면 운영자가 중지·비활성화한다. 자동 설치가 이 작업을 대신하지 않는다.
   최초 보정과 chrony 재시작은 시계 점프를 일으킬 수 있다.
2. **관제:** 아래 명령으로 먼저 미리 보고, 외부 서버 세 곳의 독립성·도달성과 현장
   CIDR을 확인한다. `render`는 출력만 한다. 기존 방화벽 절차로 승인된 LAN 인터페이스와
   클라이언트 CIDR에서 UDP 123만 허용한다. 인터넷에 NTP 포트를 공개하지 않는다.

   ```bash
   python3 deploy/hosts/common/rosy_time_sync.py render --role site \
     --source <upstream-a> --source <upstream-b> --source <upstream-c> --allow <client-cidr>
   sudo python3 deploy/hosts/common/rosy_time_sync.py install --maintenance --role site \
     --source <upstream-a> --source <upstream-b> --source <upstream-c> --allow <client-cidr>
   ```

3. **각 Linux PC·로봇:** 관제 서버가 먼저 동기된 뒤 같은 도구로 등록한다. 서버는 DHCP가
   바뀌어도 유지되는 승인된 DNS/mDNS 이름을 쓴다. 서로 다른 공용 pool로 우회하지 않는다.
   모든 기기에 같은 `--source` 하나를 사용한다. 두 번째 source와 개별 공용 fallback은 거부한다.

   ```bash
   sudo python3 deploy/hosts/common/rosy_time_sync.py install --maintenance --role client --source <site-ntp-name>
   python3 deploy/hosts/common/rosy_time_sync.py check
   chronyc -N sources -v
   ```

   새 Pinky native runtime에는 `rosy_time_sync.py`가 함께 배포된다. 저장소가 없는 장치는
   `/opt/rosy/native-runtime/rosy_time_sync.py` 또는 승인된 release의 native 사본을 사용한다.
   예전 장치에는 승인된 리비전의 도구를 먼저 복사한다. 이미지/OTA 설치만으로 현장별
   NTP 등록이 끝나는 것은 아니다. 컨테이너·Harbor 앱은 호스트 시간을 공유하며 별도 NTP
   데몬이나 `CAP_SYS_TIME`을 넣지 않는다. OMX는 팔 자체가 아닌 제어 호스트에 적용한다.
4. **Windows 개발 PC:** 관리자 PowerShell 유지보수 창에서 먼저 `-WhatIf`로 확인한다.
   도메인·정책 관리 PC는 스크립트가 거부하며 도메인 관리자가 같은 기준을 연결한다.

   ```powershell
   ./deploy/hosts/common/install-time-sync.ps1 -Server <site-ntp-name> -Maintenance -WhatIf
   ./deploy/hosts/common/install-time-sync.ps1 -Server <site-ntp-name> -Maintenance
   w32tm /query /status /verbose
   w32tm /stripchart /computer:<site-ntp-name> /dataonly /samples:10
   ```

5. **수용:** Linux `check`의 JSON `synchronized=true`와 exit 0, 선택된 시간원, 표본 시각을
   장치별로 기록한다. 보고 오차 상한 50ms·표본 나이 180초 기준을 벗어나면 exit 1이다.
   UDP 차단/해제·재부팅 뒤 다시 확인한다. 실패하면 시간 의존 작업을 재개하지 않는다.
   이 명령은 읽기 전용이며 앱의 자동 차단 기능은 아니다. Windows는 source·최근 성공
   시각·offset을 별도로 관측하고 Linux의 50ms 통과로 간주하지 않는다. 휴대전화·MCU는
   OS/MDM 시간 설정과 원본 capture clock domain을 별도로 확인한다. 앱 설치나 서버의
   수신 시각만으로 모바일 시계까지 맞았다고 기록하지 않는다.

chrony의 시간원 선택 한도(`maxdistance`, 기본 3초)와 위의 정밀도 수용은 별개다.
상위 NTP가 보고한 root distance가 100ms를 넘을 수 있으므로 선택 한도를 100ms로 줄이면
응답이 정상이어도 시계 보정 자체가 중단된다. 공통 서버로의 보정은 허용하되, UTC 오차
상한 50ms·표본 나이 검사는 유지하며 기준 밖이면 수용 실패로 보고한다. 설정에 같은
서버가 들어 있다는 사실만으로 동기를 판정하지 않고 `chronyc sources`의 선택 표시와
tracking의 stratum/leap 상태를 확인한다.

설치 전 chrony 원본은 `/etc/chrony/chrony.conf.rosy-backup-*`에 보존된다. 구문 오류는
적용 전 거부하고 서비스 재시작 실패는 이전 설정으로 복구한다. 시간원 연결 실패는 새
설정을 유지하되 실패를 반환한다. DNS·UDP 123·관제 시간원부터 고친 뒤 `check`한다.
구성 복구는 유지보수 중 출력된 원본 백업을 `chrony.conf`로 복사하고 chrony를 재시작한 뒤
재검증한다. Windows는 출력된 `.reg`를 `reg import`하고 W32Time 재시작·상태 확인을 한다.
백업은 운영 설정이므로 공개 저장소에 넣지 않는다.

## PC 복구 설치

모델·AI·관제 PC의 복구 기준은 `common/host-state/manifest`가 소유한다.
각 PC는 승인된 저장소 리비전을 설치하고, 이후에는 로컬 사본과 실행값을 점검한다.
Fleet은 결과만 읽으며 root 설치 명령을 실행하지 않는다(D-530).

## PC 설치와 갱신

역할은 `model`, `ai`, `site` 중 하나다. 다음은 모델 PC 예다. 하드웨어 워치독과
커널 오류 후 재부팅을 켜므로 작업을 중단할 수 있는 시간에 설치한다.
`site` 역할은 아래 가드 계정·대상·키 준비를 먼저 마친다.

```bash
python3 deploy/hosts/common/rosy-host-state install model --approve recovery --dry-run
sudo python3 deploy/hosts/common/rosy-host-state install model --approve recovery
sudo /usr/local/sbin/rosy-host-state check
```

이 명령은 기존 역할별 설정도 적용한다. `recovery` 승인은 SSH 복구 스크립트와 타이머,
하드웨어 워치독 로드 유닛, systemd 30초 워치독, 커널 panic 10초와 soft lockup 대응,
읽기 전용 가드 응답을 설치한다. 다른 승인 그룹(방화벽·Wi-Fi·시뮬레이터)은 허용하지 않는다.
하드웨어는 기존 장치를 먼저 사용하고, 없으면 `iTCO_wdt`, `wdat_wdt`를 시도한다.
장치가 없으면 유닛과 설치가 실패하며, 미지원 상태를 숨기지 않는다.

swap 용량과 우선순위, 로컬 SSH 복구 제한(`/etc/default/rosy-ssh-watchdog`), 비밀번호
로그인은 변경하지 않는다. `deploy/site/install-model-pc-guard.sh`는 swap 변경까지
필요한 모델 PC의 별도 유지보수용이다.

재부팅 후 장치 존재, `RuntimeWatchdogUSec=30s`, `kernel.panic=10`,
`kernel.softlockup_panic=1`, 복구·점검 타이머 활성 상태를 다시 확인한다.
이 확인은 실제 장애 복구 시험을 대신하지 않는다.

## 업데이트 상태 확인과 새 PC 연결 (D-805)

모든 PC의 업데이트 경로와 사용자 유닛은 개발 PC에서 한 번에 확인한다. 읽기만 하며, 멈춘 경로나 선언과 다른 유닛이 있으면 exit 1이다. 역할별 사용자 유닛의 기준은 [`services.yaml`](services.yaml)(D-852)이다.

```bash
git fetch origin && python tools/remote/update_status.py
```

`STUCK`은 업데이트 유닛이 실패했거나 6시간 안에 정상 판정(`switched`·`up_to_date`·`idle`·`active`)이 없다는 뜻이다. 2026-10-23에는 관제 PC OMX 도구가 4일(교체된 OpenRB 시리얼), AI PC 상황 서비스가 3일(끊긴 fetch가 남긴 `mirror.git/shallow.lock`) 멈춰 있었다. `OFF`는 타이머가 꺼진 경로이고, 누가 왜 껐는지 확인하기 전에 켜지 않는다.

새 PC를 붙이거나 장치를 바꿀 때:

1. `private/lab-hosts.json`에 SSH 주소를 넣고, 위 「PC 설치와 갱신」의 host-state를 역할에 맞게 설치한다(`/usr/local/bin/rosy-update-gate` 포함).
2. 업데이트 경로를 D-805에서 고른다. OMX 셀은 `deploy/robot/omx/omx_autoupdate.py`, 네이티브 서비스는 같은 업데이터의 `"kind": "service"`, 모델 PC 코드는 서명 후보(D-446)를 따른다. 타이머 유닛은 관문(`ExecCondition`)을 거쳐야 한다.
3. OMX 셀 설정의 `devices`·`follower_device`는 실제 `/dev/serial/by-id/` 경로로 적는다. 상시 토크 OFF 관측기가 버스를 잡는 셀은 `observers`(`unit`·`device`·`health`)를 함께 적는다. 보드를 바꾸면 이 설정과 관측기 env를 같은 날 고친다.
4. 설치한 날 업데이트를 한 번 직접 실행(`systemctl --user start <unit>`)하고 `update_status.py`에서 `ok`를 확인한다.
5. `private/lab-hosts.json`에 역할을 둔다. 관제 PC는 `site_host`이고, 모델·AI PC는 `sim_hosts`의 `<ssh>=model`·`<ssh>=ai`다. 그 역할의 유닛을 `services.yaml`에 선언한다. `update_status.py`의 `<role>: N declared units, 0 findings`가 연결 완료 기준이다. 유닛을 추가·변경·폐기하면 같은 변경에서 그 항목을 고친다.

## PC별 모니터링 연결

관제 PC에서 기존 `deploy/site/install-host-guard.sh`로 가드 계정을 준비한다.
`/etc/rosy/host-guard/hosts.conf`에 `model`, `ai` 대상을 적고 실제 주소·키는 호스트에만 둔다.
템플릿은 `deploy/site/host-guard.conf.example`이다. 자동화용 SSH는 강제 명령 키를 쓰는
OpenSSH LAN 경로로 연결한다. Tailscale SSH는 `authorized_keys` 강제 명령을 우회하므로
이 감시 키의 전송 경로로 사용하지 않는다.

대상 PC마다 `common/install-guard-remote.sh --site-key "<guard-public-key>"`로 공개키를
등록한다. 계정·접속 범위와 대상 소유자의 동의는 기존 설치 절차를 따른다.
`--approve recovery` 자체는 새 키나 재부팅 권한을 추가하지 않는다.

관제 PC의 가드 계정·대상·키를 준비한 뒤, 다음 명령으로 최신 가드와 타이머도 적용한다.

```bash
sudo python3 deploy/hosts/common/rosy-host-state install site --approve recovery
```

이후 Fleet의 **설치·보정 → 호스트 서비스**에서 세 PC를 각각 확인한다.

- 가드는 10분마다 원격 PC의 `health`(메모리·swap 사용률·CPU 부하)와 `recovery` 캐시를 읽는다.
  관제 PC는 자기 로컬 보고를 사용한다.
- 로컬 점검은 설치 직후 및 30분마다 실제 워치독·커널 설정·SSH 복구의 최근 실행과
  실패 카운터·활성 swap 총량과 사용량을 기록한다. 화면은 30초마다 읽는다.
- 원격 호스트 결과 15분, 복구 설정 결과 35분 초과는 점검 지연이다. 결과 부재·미지원·접속
  실패도 정상으로 표시하지 않는다. 접속 실패·새벽 점검 유예 시 이전 복구 보고를 지운다.
- 설정 누락은 보고만 하며 기존 가드의 재부팅 조건·상한을 바꾸지 않는다.

원본은 각 PC의 `/var/lib/rosy-host-state/status.json`과 관제 PC의
`/var/lib/rosy-host-guard/status.json`이다. 가드가 멈추면 파일의 시각으로 지연을 표시한다.
가드의 상태 디렉터리는 `0751`, 비밀 없는 JSON은 `0644`로 Fleet 컨테이너의 UID 10001이 읽는다.
SSH 키가 있는 `/etc/rosy/host-guard`는 `0750`을 유지한다.
Fleet 자체가 중단되면 이 화면도 사용할 수 없으며, 외부 가용성 감시는 별도다.
