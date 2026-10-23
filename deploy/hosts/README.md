# PC 자동 복구와 모니터링

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
