# 공통 시간 동기화 구현 검증

- 결정: [D-859](../../adr/D-859-shared-utc-time-synchronization.md).
- 위치: `.worktrees/time-sync`, `feat/shared-time-sync`. 기준 `22081a48da`, 최종 소스 `ce5018413b`.
- 구현: 관제 chrony→Linux 호스트·로봇 계층, Windows W32Time 설치, 읽기 전용 UTC 오차·표본 나이 검사. 기존 설정 백업·구문 검사·재시작 실패 복구와 유지보수 가드를 포함한다. Pinky native runtime에 같은 도구를 넣었다.

## 코드 검증

`tools/remote/remote_pytest.py`로 커밋된 소스를 승인된 시험 PC에서 실행했다. 노트북 pytest는 실행하지 않았다. 시험 전 모델·AI PC의 시험 저장소 여유가 각각 약 70/94GiB이고 사용률이 85/79%임을 확인했다.

| 리비전·회차 | 결과 | 의미 |
|---|---|---|
| `4c78ae27b4` / red | 실패 | 구현 전 소스·native 복사·Windows 스크립트 부재를 확인 |
| `6d495c9de7` / green | 집중 330개 통과 | 공통 시간·native systemd·이미지 chrony·기존 host-state 회귀 |
| `52098937c8` / csv-red | 1개 실패 | 공식 chrony CSV의 ref-id/이름 별도 필드를 반영한 시험이 기존 parser를 거부 |
| `ce5018413b` / final | 739 passed, 39 warnings, exit 0 | 영향 선택 27개 파일 전체. 모델 PC 실행. NEW 0 / known 0 / flaky 0 |

최종 명령:

```text
python tools/harness/rosy_harness.py affected --base 22081a48da --json | python tools/remote/remote_pytest.py --log-dir <scratch>/rosy-time-sync/final --affected-json -
python test/known_failures.py <scratch>/rosy-time-sync/final/run-1.txt
```

로컬 원본 로그는 `%LOCALAPPDATA%/Temp/rosy-time-sync/{red,green,csv-red,final}/run-1.txt`다. 원격 접속 정보가 섞일 수 있는 원본 로그는 공개 저장소에 복제하지 않았다. 경고는 기존 모듈 `last_verified`와 기록 경로 관련 경고이며 새 실패는 없다.

PowerShell parser와 `install-time-sync.ps1 -Server site.example.invalid -Maintenance -WhatIf`는 exit 0이었다. 실제 W32Time 변경은 하지 않았다. 독립 검토에서 CSV 열 개수 오류를 찾았고, [chrony 4.5 원본](https://gitlab.com/chrony/chrony/-/raw/4.5/client.c)의 `process_cmd_tracking`과 CSV 출력 처리를 확인해 고쳤다. 재검토에서 남은 주요 지적은 없었다. harness lint는 0 errors였고 기존 경고는 남았다. `git diff --check` 및 D-430 safety range 검사도 통과했다.

## 운영 관측과 남은 수용

읽기 전용 조회 결과 모델·AI PC는 `systemd-timesyncd` 활성, `NTPSynchronized=yes`, chrony 비활성이었다. 관제 PC는 기존 승인 접속 경로로 닿지 않았다. Windows 개발 PC의 W32Time은 중지 상태였다. 로봇용 승인 operator key/known-host 파일은 이 세션 환경에서 찾을 수 없어 로봇 접속을 시도하지 않았다.

**운영 배포·전체 기기 동기 수용은 미완료다.** 관제 PC 접속 복구, 승인된 외부 시간원·현장 CIDR 확정, 실제 워크로드 중지와 유지보수 창 확보 후 관제→클라이언트 순서로 [운영 절차](../../../deploy/hosts/README.md#공통-시간-동기화-d-859)를 실행해야 한다. 기기별 `check`, 선택된 시간원, UDP 차단/복구, 재부팅 후 재동기 증거를 남긴다. 모바일·MCU의 capture clock domain과 Windows offset도 별도 수용한다. 현재 시험은 ARM64 이미지 빌드나 실물 시간 정확도 검증을 대신하지 않는다. main 착지·push는 수행하지 않았다.

CE: 해당 없음 — CSV 출력 가정과 실제 형식의 차이는 최종 회귀시험·주석과 이 기록에 보존됐고, 재조사를 막기 위한 별도 교훈 문서를 더할 판단은 없다.

## 후속 실행: 동일한 NTP endpoint 강제 (D-861)

사용자의 즉시 적용·전체 기기 동일 NTP 지시에 따라 [D-861](../../adr/D-861-one-identical-ntp-endpoint-for-all-devices.md)을 결정했다. Linux client의 복수 source를 거부하며 개별 공용 pool·fallback을 허용하지 않는다. 새 거부 시험이 `8c2687ab6a`에서 실패했고 구현 후 `29002a4845`의 시간 동기·harness 원격 검증은 exit 0이다. 독립 검토에서 주요 지적은 없었다.

관제 PC 접속이 복구됐다. 기존 Ubuntu NTS upstream 다섯 개와 구성을 유지하고 `/etc/chrony/conf.d/60-rosy-ntp-server.conf`에 현장 LAN 및 모델·AI·Windows의 승인된 VPN 주소만 허용했다. 전체망 allow는 없다. `chronyd -p` 구문 검사와 `chronyc accheck`가 성공했다. 실행 중 chrony에 같은 ACL을 적용하고 자동 step 창은 비활성화했다. CORE/Fleet·chrony 재시작, 수동 clock step, upstream 인증 해제는 하지 않았다. 파일은 다음 daemon 시작에도 읽힌다.

공통 endpoint는 관제의 기존 VPN DNS 이름이다. 실제 이름과 ACL은 gitignored `private/network/shared-time-sync.json`에 기록했다. 동일한 이름을 사용한 실제 UDP NTP 요청에서 원래 요청 timestamp 일치, 유효 stratum 및 leap 상태를 확인했다.

| 기기 | 동일 서버 UDP 응답 | 관측 offset (단일 표본) | OS 시간원 적용 |
|---|---|---|---|
| 모델 PC | 성공, stratum 3 | 약 +73ms | 미완료 — 비밀번호 sudo 필요 |
| AI PC | 성공, stratum 3 | 약 +40ms | 미완료 — 비밀번호 sudo 필요 |
| Windows 개발 PC | 성공, stratum 3 | 약 -433ms | 미완료 — 현재 프로세스 비관리자, W32Time 중지 |
| Pinky 두 대 | 미확인 | 미측정 | 미완료 — 모델 PC의 등록 키/별칭 경로에서 No route to host |

이는 연결 검증이며 실제 동기화 완료 또는 50ms 오차 상한 수용이 아니다. 관제의 기존 외부 시간원은 root delay 약 0.25초 수준이 관측돼 현재 엄격한 50ms UTC 상한을 만족한다고 주장하지 않는다. 인터넷 지연/시간원 품질을 추가 확인하고 수용 기준은 약하게 바꾸지 않는다.

모델·AI PC의 `~/rosy-test/maintenance/time-sync/`에 같은 endpoint가 들어 있는 `apply.sh`, 검증된 Python 도구와 설정 미리보기를 준비했다. 실제 값은 공개 저장소로 복사하지 않았다. 각 PC의 관리자 유지보수 창에서 `sudo bash ~/rosy-test/maintenance/time-sync/apply.sh`를 실행해야 한다. 실행 중 시험·학습이나 알려진 런타임을 감지하면 설치를 거부한다. Windows는 gitignored `private/network/apply-time-sync-windows.ps1 -Maintenance`를 관리자 PowerShell에서 실행한다. 현재는 WhatIf만 통과했다.

남은 확인: 관리자 실행 → 단일 source 설정/실제 선택 서버 검사 → 오차·stale 검사 → 로봇 네트워크 복구와 같은 endpoint 적용 → 모바일/MCU별 OS/펌웨어 지원·망 연결 확인. 전체 완료는 이 확인 전까지 HOLD다. CE: 미해결 — 운영 권한·오프라인 기기·관제 UTC 오차 상한의 수용이 남았으며 해결 교훈으로 쓰지 않는다.

### Windows 실제 적용 및 최신 상태

관리자 실행을 실제 진행했다. 첫 실행은 exit 1이었으며 peer는 공통 서버로 설정됐지만 서비스가 Stopped였다. 최초 오류 출력은 수집하지 못해 정확한 실패 명령은 미확정이다. 읽기 전용 `sc.exe qtriggerinfo w32time`에서 DOMAIN JOINED 및 custom-state 시작 트리거를 확인했다. [Microsoft KB2385818](https://learn.microsoft.com/en-us/troubleshoot/windows-client/active-directory/w32time-not-start-on-workgroup)은 작업 그룹에서 Automatic만으로 서비스가 유지되지 않을 수 있음을 설명하고 networkon/networkoff 트리거를 제시한다.

원본 registry 백업·도메인/정책 거부 뒤 `sc.exe triggerinfo W32Time start/networkon stop/networkoff`를 적용하도록 설치기를 고쳤다. 새 검사 조건은 `265febbb5f` 원격 시험에서 실패했고, 수정한 `528962cb8d`는 시간 동기 시험 33개 통과·NEW 0, PowerShell 구문 검사 및 독립 검토 주요 지적 없음이었다.

두 번째 관리자 실행은 **exit 0**이었다. 실행 프로세스가 종료한 뒤 읽기 전용 관측에서 W32Time Running/Automatic, 새 network 트리거, `w32tm /query /status /verbose`의 동일 관제 Source 하나, leap 0, stratum 4, 최근 성공한 동기와 Last Sync Error 0을 확인했다. 초기 Phase Offset 약 -0.51초·Root Dispersion 약 8.28초가 보고돼 Windows의 정밀 오차 수용을 완료했다고 주장하지 않는다. 재부팅·망 단절 복구는 미시험이다. 실제 출력과 registry 백업 경로를 담은 transcript는 gitignored `private/network/windows-time-sync-install.log`에 둔다.

따라서 위 현황 표의 Windows는 이제 **공통 서버 설정·서비스 실행·최근 동기 성공 확인**, 정밀 오차와 재부팅 수용은 미완료다. 모델·AI PC의 설치 파일은 `bash -n`과 배포된 Python SHA256 일치를 확인했으며 비밀번호 sudo 실행이 남았다. 로봇 두 대는 관제 PC에서도 SSH TCP 접속이 timeout이었다.

main 착지는 `tools/land.py --tests auto --queue-timeout 3`으로 요청했지만 다른 작업 두 건이 앞서 있어 3분 후 STOP했다. 대기열을 우회하지 않았고 main 병합·push는 하지 않았다. 소스·결정·운영 증거는 `feat/shared-time-sync`에 보존한다. CE: 미해결 — 전체 기기의 관리자 적용·오프라인 장치·정밀 시간 수용이 남는다. Windows 관측과 트리거 선택 근거는 코드 주석·회귀 조건·이 기록에 남겨 별도 해결 교훈을 늘리지 않는다.

### 이후 진행

위 소스는 후속 통합에서 main에 반영됐고 기존 워크트리는 정리됐다. 모델·AI의 관리자 설치 후 발견한 시간원 선택 오류와 실제 동기 복구는 [별도 후속 기록](../shared-time-sync-source-selection-2026-10-24/result.md)을 따른다. 과거의 설치 대기 상태를 최신 동기 상태로 읽지 않는다.
