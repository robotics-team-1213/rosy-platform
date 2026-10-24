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
