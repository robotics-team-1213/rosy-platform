# 잔여 브라우저 회귀의 FULL 검증과 로컬 병합

2026-10-17. [집중 검증 기록](result.md)에 이어 기존 실패 다섯 건과 후속 경합 수정을 검증했다.
이 기록의 완료 근거는 `g1-corrected-full/`의 최종 영수증이다. 앞선 실패 기록은 그대로 보존한다.

## 대상과 결과

- FULL commit: `a9a061446cbdb81f8e2bc9887bb74190928f08ec`.
- 기준 main commit: `55d5b426b9fc8fb8d79768515b47f74d26cc92d8`.
- native 도구가 실제 병합한 main commit: `a9a061446cbdb81f8e2bc9887bb74190928f08ec`.

```text
python -X utf8 tools/land.py --tests auto --main-checkout C:/Dev/Robot/Rosy/rosy-platform --no-prune
```

모델 PC와 AI PC가 커밋된 버전을 실행했다. native 도구는 한 round에서 FULL 26개 묶음을 완료하고,
안전 검토·크기·린트·실패 비교를 통과한 후보를 로컬 main에 ff-only 병합했다. 최종 종료값은 0이다.
FULL 시험 묶음의 벽시계 실행 시간은 2,043초였으며 사전 구조 검사는 별도다.

| 실행 | 완료 묶음 | passed | skipped | failed / errors | NEW / known / flaky |
|---|---:|---:|---:|---:|---:|
| FULL | 26 | 28,248 | 1,909 | 0 / 0 | 0 / 0 / 0 |
| 그중 브라우저 opt-in | 4 | 928 | 0 | 0 / 0 | 0 / 0 / 0 |
| 별도 사전 구조 검사 | 1 | 247 | 0 | 0 / 0 | 0 / 0 / 0 |

브라우저 묶음은 `ROSY_RUN_BROWSER_TESTS=1`로 실행했다. Chromium 외 HTTP·smoke 검사도 포함된다.
표는 각 invocation의 기본 pytest 결과를 합산한다. 중복 선택이 있으므로 고유 시험 개수가 아니며,
subtest 수를 더하지 않는다. 사전 구조 검사와 FULL을 구분하고, skipped를 통과로 세지 않는다.
브라우저 원본 로그 `run-1-23.txt`부터 `run-1-26.txt`는 각각 217, 211, 232, 268 passed였다.
네 로그 모두 skip 0이다.

## 확인한 변경

기존 다섯 실패는 사진과 결과의 첫 화면 배치, 짧은 화면에서 사진 전체 표시,
만료된 저장 토큰 제거, CORE 비상 정지 API 경로, 보정 lease 표시·해제다.
집중 원격 검증은 19 passed와 독립 보정 표시 1 passed, skip 0으로 끝났다.
독립 검토 후 해당 다섯 항목만 `test/known_failures.txt`에서 제거했다.
새 실패나 격리 항목은 추가하지 않았다.

보정 화면은 상태 읽기 중 승인·해제·확인 작업을 차단하고, 로컬 조건 입력은 계속 편집할 수 있게 했다.
실제 포인터를 누른 상태에서 예정된 상태 응답을 보류해 두 폭의 실패를 재현했고,
같은 검사를 포함한 3개 검사(Chromium 두 폭과 Node wrapper)를 수정 후 두 번 실행해 각각 통과했다.
세션·리비전 변경에 따른 동의 무효화는 유지한다.

원격 실행기의 EXIT trap은 자기 잠금을 해제한 뒤 종료 코드를 원자 공개한다.
실제 `mv` 뒤를 보류해 수정 전 종료 코드 143과 남은 잠금을 함께 관찰했다.
수정 후 원격 pytest·sim 실행기 계약 70 passed와 보정 화면 3 passed, 모두 skip 0·NEW 0을 확인했다.
sim 실행기 계약은 실제 Gazebo 실행 증거가 아니다.

최신 main의 G1 검사는 실패한 쌍과 다른 정상 작업을 구분하도록 교정했다.
다른 왼팔 Step 6의 공유 구역 사용을 fake goal 종료 보류로 유지하면 기존 전역 구역 부재 단언이
다섯 번 모두 실패했다. 교정한 검사는 실패한 예약 전후 SQLite 전체 원장이 같고,
실패한 쌍의 실행 식별자·grant·점유가 비어 있으며 실제 owner 제출이 없는지 확인한다.
이후 살아 있는 점유는 미완료 Action의 키·세대·배치와 일치해야 한다.
오른팔 충돌과 구역 충돌을 다섯 번 반복해 총 10 passed를 확인했고,
미연결 orphan 구역 점유를 시험 SQLite 원장에 주입하면 새 단언이 정확히 실패했다.
변형을 제거한 동일 소스에서 G1 sim/layout/timing 27 passed와 Fleet 점유·원장·디스패처 87 passed,
모두 skip 0·NEW 0이었다. 실제 Fleet 점유·해제 소스는 변경하지 않았다.

`camera_contract_review`는 원래 수정과 보정 화면·G1 검사의 계약 범위를,
`remote_job_review`는 실행기를, `camera_evidence_review`는 실행 증거를 별도로 검토했다.
`audit.json`으로 27개 원본 로그의 비교 결과와 검증 소스의 Git blob 동일성을 확인했다.
독립 증거 검토에서도 이 FULL의 커밋·계수·원본 비교와 실제 로컬 main 병합을 확인했다.

## 앞선 실패와 재현

아래 디렉터리는 외부 증거 루트 아래의 상대 경로다.

| 증거 디렉터리 | 관찰과 처리 |
|---|---|
| `land/` | 첫 FULL의 비밀정보 검사가 공개 commit 표기를 탐지했다. 기존 스캐너가 인정하는 commit 문맥만 추가하고 별도 원격 검사를 통과했다. 실패 시도는 중단했고 착지하지 않았다. |
| `corrected-full/` | 첫 FULL은 통과했으나 최신 main 병합 후 보정 이미지 확인 경합이 NEW로 발생했다. 해당 시도는 중단했고 착지하지 않았다. |
| `final-full/` | 보정 체크박스 클릭과 상태 읽기의 경합이 NEW였다. 포인터 재현과 입력 잠금 수정을 추가했다. 해당 시도는 중단했고 착지하지 않았다. |
| `input-unlock-full/` | 원격 작업 종료 코드 공개와 잠금 해제 순서의 경합이 NEW였다. 실행기와 재현 검사를 수정했다. 해당 시도는 중단했고 착지하지 않았다. |
| `completion-publish-full/` | 첫 FULL은 commit `3627db4dc8`에서 28,149 passed / 1,909 skipped, 브라우저 opt-in 928 passed / skip 0이었다. round 2는 구조 검사만 실행했고 main 변경으로 예정된 FULL은 실행하지 않았다. 최신 main 병합 후보 commit `214cc6eadc`의 후속 FULL 23개 묶음은 모두 실행됐으나 G1 검사 1 NEW로 native exit 1, 미착지였다. pilot 브라우저 3 passed도 그 실패를 해소하지 않는다. |
| `g1-claim-diagnostic/` | 진단 메시지만 추가한 버전의 다섯 통과는 원래 결함의 결정적 재현이 아니다. |
| `g1-claim-held-red/` | 정상 Step 6 점유를 유지하자 기존 단언이 다섯 번 모두 실패했다. |
| `g1-claim-correlated-green/` | 보강 중 대기 점유의 빈 목록을 null로 가정해 각 실행의 두 경우가 모두 실패했다. 성공으로 세지 않는다. |
| `g1-claim-correlated-verified/` | 실제 빈 목록 표현으로 고친 두 경우를 다섯 번 반복해 총 10 passed였다. |
| `g1-claim-orphan-red/` | 미연결 구역 점유 주입이 새 상관관계 단언에서 실패했다. 변형은 제거했다. |
| `g1-claim-regression-green/` | 변형을 제거한 commit `a9a061446c`에서 G1 27 passed와 Fleet 87 passed, skip 0·NEW 0이었다. |

중단된 시도의 뒤쪽 묶음은 실행·수집 상태가 서로 다르며 완료 수용 근거에 합산하지 않는다.

## 원본과 범위

외부 증거 루트는 `C:/DevTemp/browser-regressions/recheck-20261017T051307Z/`다.
완료 실행의 `request.json`, `selection.json`, `runner.txt`, `exit.json`, `audit.json`은
`g1-corrected-full/` 아래에 있다. `audit.json`은 각 원본 로그의 합계·SHA-256·실패 비교와
커밋별 소스 동일성을 기록한다. 원본 로그는 `g1-corrected-full/land/fix-browser-regressions-ready/`다.

| 증거 파일 | SHA-256 |
|---|---|
| `g1-corrected-full/audit.json` | `9ff4b7875d1ee62b14d6d624358f6d911ebe26e432568f5f7dca23bdef8cea08` |
| `g1-corrected-full/runner.txt` | `1c04304c38b6920533738944d98d7b05c659547e2760e95a00e9d1c59e87f4b5` |
| `g1-corrected-full/selection.json` | `d5e190ccdcd729dd2a3c8b4fba4c197f64a8b744d97d54ac7efc8a305dc2d593` |
| `g1-corrected-full/exit.json` | `9d4d0468f366bd9b35335172ebb8ec6fd501c2aa3171e2d53a3a7a97179b6aa6` |
| `g1-corrected-full/request.json` | `b5c69925f7ae19067887ed7fc0d4992e152cf19752ad5494f4609f7c65037f77` |

호스트의 커밋된 소스·실행기 계약·합성 입력을 사용한 UI와 ROS-free G1 검사 범위다.
실제 카메라 원본, 독립 바닥·마커 측량, 로봇별 odom 오차, 실제 사람의 검수 라벨,
모델 성능, 실제 Gazebo·ARM64 장치·현장 수용 또는 D-598 활성화의 증거로 확장하지 않는다.
이번 작업은 로컬 main 병합이며 push·배포·로봇 조작을 수행하지 않았다.
