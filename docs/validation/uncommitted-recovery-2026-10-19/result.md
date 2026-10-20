# 미커밋 변경 검토와 로컬 머지 — 2026-10-19

## 최종 결과: 검증 가능한 변경 커밋·로컬 main 머지 완료

다른 세션과 기존 워크트리까지 확인해 필요한 변경을 복구·검토하고, 검증 중 발견된 문제도 수정한 뒤 로컬 main에 통합했다. Platform 공식 착지는 종료 코드 0으로 완료됐고, root가 main과 검증 tip의 일치 및 복구 대상 14개 커밋의 ancestry를 직접 확인했다.

| 저장소 | 최종 로컬 main | 검증·상태 |
| --- | --- | --- |
| rosy-platform | commit `6ecf921d912e170fd6132697f09d1d5e60615b3e` | 공식 FULL 26개 실행 결과 합계 29,606 passed / 1,944 skipped / 0 failed, NEW·known·flaky 모두 0. 별도 architecture/harness 249 passed. 이번 착지 41커밋. |
| rosy-vault | `c5da5c3` | 기능·후속 수정 포함. 검토한 변경 226 passed / 4 skipped. 이후 다른 세션의 PR 2 머지도 확인. 작업 트리 clean. |
| rosy-ops | `249861b` | 기존 PR 1 MERGED와 config CI 성공, 동일 tree를 확인하고 로컬 main을 fast-forward. 작업 트리 clean. |
| rosy-docs | `2c130ee` | 미처리 변경 없음. 작업 트리 clean. |

Platform FULL의 수치는 실행별 합계이며 고유 테스트 개수가 아니다. 선택된 브라우저 회귀 4개 묶음은 총 850 passed / 0 skipped다. 최종 공식 검증 기록은 `Rosy/rosy-platform/.git/rosy-land/commit 6ecf921d912e170fd6132697f09d1d5e60615b3e.json`에 있으며 invocation 26개와 기준 main `46bb5a840e28f28211c283e22a327bdc59031087`를 기록한다. 다른 세션의 협업 문서, pilot simulation 분리, retired fixture·learning·account·review 복구 및 Pinky 변경도 최종 main에 포함됐다.

Platform main의 추적 파일은 깨끗하다. 미추적 생성 로그 `aff1.log`, 이미 반영된 원본 WIP, 캐시·잠금 파일과 과거 증거는 보존했다. 중복·생성물이나 과거 검증 기록을 현재 결과처럼 바꾸는 수정은 커밋하지 않았다. 복구 대상과 제외 근거는 아래 진행 기록에 남겼다.

스킵은 실행 성공으로 계산하지 않았다. Windows 전용 동작, 실제 LeRobot roundtrip 등 환경 의존 검증에는 제한이 있으며, SD 스크립트는 문법 검사까지다. 실제 SDK·Gazebo 실행, 로봇 구동, 서비스 활성화, 배포 및 push는 수행하지 않았다. D-786/D-788은 Proposed이고 운영·현장 수락은 HOLD다.

로그 누락 추정은 오판으로 정정했다. 원문은 처음부터 보존돼 있었고, 잘못 추가한 동일 복사본만 제거했다. 최종 로그·색인 blob은 추가 전 `8785c97bbb`와 같으며 append-only, 원문·중복 횟수 및 lint를 확인한 상태로 FULL을 통과했다.

## 진행 기록 — 아래는 착지 전 중간 상태

아래의 대기·실패·진행 중 표현은 당시 기록이며, 현재 상태는 위 최종 결과가 우선한다.

중복 제거 검토를 완료했다. 로그·색인의 Git blob은 불필요한 복사본 추가 전 `8785c97bbb`와 정확히 같고(`git diff --exit-code` 0), 실제 append-only 판정은 main·이전 병합본·중복 추가 커밋까지 6개 기준 모두 True다. 독립 검토에서 원래 기록의 전체 block 및 중복 횟수 누락 0, 대상 제목 7개가 각 1회임을 확인했다. 수동 lint는 오류 0·기존 경고 32다. 실제 원문 손실은 없었으며, 잘못 추가한 동일 복사본만 제거했다. 최종 FULL·착지는 계속 진행한다.

로그 판정 정정: 원문 7개 기록은 처음부터 모두 있었고 위치만 달랐다. Root가 줄 단위 diff의 42줄 삭제를 실제 기록 누락으로 잘못 판단해 `15bf083c9`에 동일 복사본을 추가했다. 이후 lint가 제목 중복을 잡았고, 같은 본문의 정규화 SHA와 원래 위치를 대조해 오판을 확인했다. 추가 전 `8785c97bbb`도 main·이전 병합본의 실제 append-only 검사를 이미 통과했다. `15bf`가 추가한 정확히 동일한 두 번째 복사본 7개만 제거하고, 원문 block·중복 횟수·제목 고유성 및 lint를 다시 확인한다. 운영 코드와 기존 원문 내용은 바꾸지 않는다.

최신 main과 통합 로그는 기록 순서가 달라 자동 병합이 멈췄다. 이는 원문 손실이 아니었으며 위 정정이 이전의 누락 추정보다 우선한다. 수정 시도는 모두 시험·착지 전에 멈췄다. 최종 FULL·머지는 아직 완료 전이다.

수정 `f3458f244a`의 원래 실패 관련 검사·release guard는 원격 **190 passed / 0 skipped / NEW 0**, 전체 root 테스트를 수집한 상태의 단독 preflight도 **1 passed / 0 skipped / NEW 0**이다. 독립 검토가 커밋과 실제 로그를 다시 확인했다. Import 문제는 전체 수집 단계에서 이미 설치된 wheel의 compiler가 캐시에 남은 것으로 실제 경로까지 재현했고, 테스트만 실제 CLI와 같은 새 프로세스에서 실행해 운영 origin guard와 정확한 소스 경로 검증을 유지했다. 원래 실패한 FULL 세 로그는 `D:/Dev/rosy-scratch/recovery-full-0c87-failed/`에 보존했다. 솔직한 실패·재검증 기록 `6a3f85034`까지 커밋하고 최신 main `46bb5a840e`를 기준으로 정상 FIFO FULL을 다시 시작했다. 최종 전체 통과·착지는 아직 확인 전이다.

첫 FULL 회차는 `0c87e43219`에서 새 실패 15건을 확인해 수정 중이다. Fleet 1건과 manual-sheet 1건은 G2의 의도된 예제 geometry 변경으로 과거 golden 입력이 바뀐 문제다. 기존 golden 해시와 compiler는 유지하고, 원래 `26a148117` 입력 두 YAML을 공용 fixture로 고정하기로 독립 검토했다. 테스트 helper `setup` 이름, 실제 runtime 메서드를 AST로 추출하는 시험 도구의 새 의존성 누락 10건, generic 모듈 주석의 가족 이름도 최소 수정 대상이다. G2 import-origin 실패는 단독 조합에서 아직 재현되지 않아 원인을 추적 중이며, 운영 origin guard는 완화하지 않는다. 실패 회차는 자체 프로세스만 정상 중단한 뒤 최종 수정 커밋으로 FULL을 다시 실행한다. 아직 착지 성공으로 판정하지 않았다.

현재 통합 tip은 `0c87e43219`다. Review 복구 `a718f85013`과 Account 재시도 `5febd43c53`의 공식 착지 기록 및 main ancestry를 확인했다. 통합본의 첫 착지 시도는 최신 main 병합 중 LeRobot exporter 충돌로 시험 전에 멈췄다. 충돌은 인접 helper 추가뿐이었고, `958d507f7f`에서 양쪽 함수를 모두 보존해 해결했다. 독립 검토는 동적 카메라 키 세 곳, Git 체크아웃 출력 금지, 원래 검증·출처·실패 처리가 보존됨을 확인했다. 원격 curation·wrist 169 passed / 2 skipped / NEW 0, 추가한 일반 저장소·linked worktree 출력 거절 사례를 포함한 최신 tip 검증 9 passed / 1 skipped / NEW 0이다. Skip은 실제 LeRobot 환경이 필요한 round-trip이다. 이 상태로 정상 FIFO `land.py --tests auto --queue-timeout 600`을 재시작했다. FULL 시험과 main 머지는 아직 완료 전이다.

이 절이 아래 최초 조사·중간 기록보다 최신이다. Vault와 Ops의 로컬 main 반영은 끝났다. Platform은 복구 커밋을 통합했으며 공식 전체 회귀·착지는 아직 진행 중이다.

최신 검증 커밋은 commit `e698494f3a366218963e714e7d0a5468a6442724`다. 공통 교차·G2 원격 재검증 **339 passed, 0 skipped, NEW 0**을 확인했다(`D:/Dev/rosy-scratch/recovery-final-cross-gapfix/run-1.txt`). 이전 5fb 재검증에서 기능·보안/G2는 통과했으나 중복 ADR gap으로 두 harness 검사가 실패해, 이미 파일·색인이 있는 D-784/D-786/D-788의 예약 5줄만 제거한 후 같은 검증을 재실행했다. 현재 `tools/land.py --tests auto --queue-timeout 600`의 정상 FIFO FULL 착지가 진행 중이다. 아직 main 머지 완료가 아니다.

다른 세션의 추가 착지: Pilot fixture `a27b980c7c`, 학습·OMX `4b2cb988cc`의 공식 기록과 main ancestry를 확인했다. 최초 조사 때의 “학습 구현이 main에 없음”은 당시 상태를 뜻하며, 이후 동시 세션이 복구한 현재 상태를 부정하는 판정이 아니다. 보존 archive는 조사 시점의 원문·근거로 유지한다.

- 통합 브랜치: `feat/recover-omx-clock`, 초기 통합 tip commit `610c96e4da2cbb576fe5b9874765908bd5f6b2b4`. 현재 Account 복구 커밋과 최신 main을 더 합치고 아래 검사 보완을 진행 중이므로 이 SHA는 최종 착지 SHA가 아니다.
- 이 tip에 scratch runtime `1f162132b6`, 출력 guard `6493df59dd`, ledger guard `b7205305c7`, 가이드 네 묶음 `978f135802`, `d7f7a300f8`, `7aa88ef48f`, `b1aac71d9`, 학습 원문 `3819ea7773`, OMX 계약 `cd1cef66a0`, native `bb842ece63`, G2·증거·계획 `fc7a1fafb`가 모두 ancestor임을 확인했다.
- 통합 중 코드 충돌은 없었다. 학습 기록의 `docs/logs.md`와 생성 index 충돌을 해결했고, 통합 전 전체 로그 817,693문자가 줄바꿈 정규화 후 prefix로 그대로 보존됨을 독립 확인했다. 원문 archive 여섯 파일 194,702 bytes의 hash도 보존됐다.
- scratch·학습 여덟 tip의 변경 경로 100건을 통합본의 blob과 대조했다. 병합한 `docs/logs.md`와 생성 `docs/index.md` 두 경로 외에는 모두 원본과 같은 blob이다.
- Account 선행 판정 정정: logout button의 attrs와 명시적 `setAttribute`는 DOM 동작은 같지만, 기존 `test_helper_created_buttons_name_their_kind`는 후자 형태를 요구한다. 다른 세션의 account 착지 회귀에서 이를 확인했다. 원본 WIP의 명시적 kind 설정은 이 소스 검사에 필요하다. 같은 회귀의 secret guard 9건은 두 Git commit ID와 원래 시험 로그 일곱 개의 일치하는 SHA256임을 독립 확인했다. 기존 exact path/line/value provenance 정책으로 다룰 수 있으며, 스캐너 완화는 필요 없다. 해당 브랜치의 진행 중 시험·파일은 수정하지 않았다.
- 초기 통합본의 추가 원격 교차 검사는 235 passed / 1 NEW(secret guard)였다. 미등록 공개 해시 12건을 독립 검증했다: vendored STL 2건, canonical kinematics와 URDF 각 1건, 공식 ROBOTIS xacro 2건, 공식 rclpy Jazzy 소스 3건, 보존 학습 원문 Git 참조 3건이 원본과 일치한다. Account의 9건과 함께 기존 exact line-bound provenance에 등록하는 보완과 현재 커밋 재검증을 진행 중이다. 검사 면제 범위를 넓히거나 원문 해시를 지우지 않는다.
- Account 22경로의 독립 검토는 명령 권한·검증·기록 진실성에 추가 결함을 찾지 않았다. 승인은 위 두 검사 수정과 현재 커밋의 원격 검증을 조건으로 한다. 기존 CORE 로그아웃·영속 revoke queue·Account family revoke 경로를 유지하며 D-807의 설계 수락과 운영 수락은 구분된다.
- 후속 수정 tip은 commit `5fb2d93799243082452df62bd1652fbccc038cad`다. Account 원본과 다른 세션의 수정 `4a5d5eef7f`·실패 기록 `3ee7cc06ae`를 모두 ancestor로 보존했다. 해시 자체를 축약·삭제하지 않고 기존 integrity-context 표기를 사용한 수정이며, 결과 UI와 해시 문서는 검토한 peer blob과 정확히 같다. 자체 출처 등록 `d9dcc9a91`은 기존 121건을 바꾸지 않고 검증된 12건만 추가했다(총 133건, account 중복 등록 없음). 두 독립 검토자가 모든 추가 path/line SHA/value 결합을 확인했다. 이 커밋으로 공통 교차 검사와 G2 원격 시험을 다시 진행 중이다.
- 통합 tip의 lint는 오류 0, 경고 33. 공식 safety-review와 size-range 검사를 통과한 뒤 `tools/land.py --tests auto`로 FIFO 맨 뒤에 다시 진입했다. FULL 선택은 유지했다.
- 앞선 다른 세션의 `docs/port-collab-pipeline`은 `bd3c9fe3e4`, `refactor/omx-pilot-sim-unit`은 `b9828f13bd`로 공식 착지됐다. 각각 main ancestry를 확인했고, 후자는 `.git/rosy-land/commit b9828f13bd7ee8dcd62d055ff049f29294813991.json`에 검증된 invocation 기록이 있다. 이는 아직 대기 중인 통합본의 검증 완료를 뜻하지 않는다.
- 통합 tip의 ancestry를 확인한 뒤 포함된 개별 브랜치의 중복 land는 아직 대기 중인 것만 취소했다. 시험은 중단하지 않았고, 순서를 건너뛰지 않았으며, 원본 커밋·브랜치는 보존했다.
- 집중 원격 시험: 계약 545 passed / 7 skipped, 진단 617 / 13, native 100 / 0, topic 36 / 0, G2 103 / 0, 역사 증거 문서 125 / 0, 학습 archive 142 / 0. 모두 NEW 0. 이 결과는 최종 통합 FULL 결과를 대신하지 않는다.
- G2 종료 시 executor나 clock thread가 정지하지 않으면 clock/context/lock을 보존하고 CLEANUP_HOLD로 끝나도록 고쳤다. 선택적 gripper trace의 steady-clock 샘플 실패도 원래 명령 결과·예외를 바꾸지 않도록 회귀 시험했다. 두 수정은 독립 검토를 받았다.
- Windows 전용 207건은 Linux 원격 시험에서 skip됐다. PowerShell card writer는 구문 검사만 했다. SDK/Gazebo 실시간 실행, 호스트 설치, 장치·팔 동작, 배포 및 push는 수행하지 않았다. D-786/D-788은 Proposed이며 시뮬 acceptance는 HOLD다.

작업공간 전체를 조사하고 검증 가능한 변경부터 반영했다. 전체 미커밋 정리가 끝난 상태는 아니다. 진행 중인 세션의 변경, 오래된 브랜치의 미검증 변경과 로그는 보존했다. 원격 push는 하지 않았다.

## 반영 완료: rosy-vault

- 저장소: `D:/Dev/Robot/rosy-vault`
- 작업 브랜치: `feat/lerobot-policy`
- 커밋: commit `69a4d03c1a3666ccad2679709d51de0b550455c5`
- 제목: `feat: add LeRobot policy execution and camera tuning profiles`
- 범위: 22파일. LeRobot 정책 실행, 안전 드라이버를 통한 그리퍼 관측, 카메라 보정·복원·시작 점검, 콘솔, CLI, 설정, V-018/V-019와 테스트.
- `main`을 `4fa1d63`에서 위 커밋으로 fast-forward했다. 작업 브랜치와 main의 SHA가 일치함을 확인했다.
- 작업 브랜치에서 전체 시험: **226 passed, 4 skipped, 1 warning**, 종료 코드 0.
- 별도 main 체크아웃에서 커밋된 파일로 전체 시험 재실행: **226 passed, 4 skipped, 1 warning**, 종료 코드 0.
- 실행: `.venv/Scripts/python.exe -m pytest -o addopts= -q`. 별도 main 체크아웃에서도 같은 venv의 Python을 사용했다.
- 4개 skip은 별도 Fleet 통합 환경에 대한 시험이다. 경고는 Starlette의 AnyIO API deprecation이다.
- staged diff의 공백 검사 통과. 신규 camera.py 끝의 불필요한 빈 줄 1개를 제거했다.
- 기존 체크아웃에서 다른 세션의 후속 수정이 생겨 main 전환이 거절됐다. 수정은 건드리지 않고 임시 main 워크트리에서 머지·시험했다. 임시 워크트리는 깨끗함을 확인하고 제거했다.
- 최종 조사 당시 새 미커밋: `AGENTS.md`, `device_core/web/console.html`, `docs/adr/V-019-카메라-보정-프로필.md`, `docs/solutions/`. 이들은 위 커밋과 검증에 포함되지 않는다.
- 로컬 main은 origin/main보다 4커밋 앞선 상태다. 원격 CI, 실제 LeRobot 모델·카메라 및 실물 팔 동작은 확인하지 않았다.

## rosy-platform: 남은 변경과 사전 점검

위치: `D:/Dev/Robot/Rosy/rosy-platform/.worktrees/<이름>`.
공식 `tools/worktrees.py status`, Git 상태·이력·diff, 기존 워크트리 정리 기록을 대조했다.

| 워크트리 | 조사 결과 | 이번 처리 |
|---|---|---|
| main | 추적 변경 없음, 미추적 `aff1.log` | 로그 보존, 커밋 제외 |
| account-docs-resume | 2파일: Pilot 연결 화면, ADR gap 목록. main과 별도 커밋도 있음 | 다른 세션의 account 복구·머지 작업이 동시에 진행돼 보존 |
| auto-state | 27개 상태 항목. fixture 파일 삭제와 대규모 미추적 소스 트리, main과 크게 갈라진 이력 | 일반 제품 변경으로 묶지 않음. 복구 상태 검토 필요 |
| d427-bulk | Fleet CLI 테스트 1파일, 오래된 구조 변경 브랜치 | 현재 구조 기준 이관·검증 필요 |
| d427-bulk-check | detached HEAD, 미추적 `operations/ui/` | 출처·현행 경로 확인 필요, 보존 |
| fleet-ship | 잠긴 워크트리, 미추적 설정 lock 파일 | 기존 작업과 lock 보존 |
| hardcode-paths | 738파일, 대체로 하드코딩된 경로 치환. 이미 머지된 브랜치에 남은 수정 | 제품 코드·공유 도구·과거 증거 문서가 섞여 있어 분할 검토와 현재 main 기준 이관 필요 |
| learning-delivery | 계획 문서 3파일. 공식 도구가 `stale-history` 판정 | D-172에 따라 직접 병합 금지. 필요한 내용만 현재 main에서 재구성해야 함 |
| learning-plan | 로그와 계획 문서 4파일 | 현행 문서 위치·이미 이관된 learning 작업과 대조 필요 |
| omx-auto-deploy | `g2_owner.py`, 신규 `g2_gripper_trace.py` | 안전·명령 소유 경로 검토와 관련 원격 시험 필요 |
| omx-native-ready | status 기준 84항목, 미추적 파일까지 펼치면 89경로. OMX 계약·시뮬·시험·도구 변경 | 이미 머지된 브랜치의 대규모 잔여 변경. 이동된 현행 OMX 경로로 이관하고 독립 안전 검토·원격 시험 필요 |
| v13-map-labels | 6파일, 공식 도구가 `landed-dirty` 판정 | 새 main 기반 워크트리로 이관해야 함. 예전 브랜치에서 계속 작업하지 않음 |
| merge-account-retired | 조사 초기에 274개 staged 항목, 이후 다른 세션 작업으로 깨끗해짐 | 진행 중인 Git 작업 보존 |

`tools/land.py --dry-run --no-prune`을 hardcode-paths, omx-native-ready, omx-auto-deploy, learning-plan, learning-delivery에서 실행했다. 미커밋 변경으로 종료 코드 1과 STOP을 반환했다. 이는 테스트 결과가 아니며, 변경 자체가 잘못됐다는 뜻도 아니다. v13-map-labels의 오래된 land.py는 `--no-prune`을 지원하지 않아 인자 오류로 끝났다.

플랫폼 변경은 이번에 커밋하거나 머지하지 않았고 원격 테스트도 실행하지 않았다. 후속 작업에는 main 기반으로 필요한 변경을 옮기고, 명시적 파일 커밋 후 공식 원격 시험·known_failures 비교·land.py 착지가 필요하다. 플랫폼 main과 origin/main의 기존 분기는 ahead 834 / behind 49이며 이번에는 변경하지 않았다.

## 다른 저장소

- `rosy-docs`: main 체크아웃에 미커밋 변경 없음.
- `rosy-ops`: feat/staging-config 체크아웃에 미커밋 변경 없음. 기존 커밋된 브랜치는 이번 미커밋 변경 처리 범위로 합치지 않았다.

실물 실행, 배포, 호스트 설치, 원격 push, 타 세션 변경의 삭제·stash·reset은 하지 않았다. 상태는 동시 세션의 작업에 따라 계속 바뀔 수 있다.

## 추가 요청: 다른 세션 변경을 포함한 복구 진행

사용자가 남은 항목과 다른 세션의 변경도 커밋·머지하도록 명시적으로 요청했다. 아래는 2026-10-19 17:15 KST까지의 중간 기록이며, 대기열 진입은 머지 완료가 아니다.

- Vault 후속 5파일은 다른 세션이 `55b0da0`으로 커밋한 것을 검토하고, 전체 시험 226 passed / 4 skipped 후 로컬 main에 fast-forward했다. 이후 다른 세션의 GitHub PR #2 머지로 현재 main은 `c5da5c3`이고 깨끗하다.
- `rosy-ops`의 staging 브랜치와 origin/main의 tree SHA가 commit `b75f13a9efbf998ed0758027a202dcd61d58024b`로 일치했다. PR #1이 MERGED이고 config CI가 SUCCESS임을 GitHub CLI로 확인했다. 로컬 main을 이미 머지된 `249861b`까지 fast-forward했다. 운영 상태는 HOLD이며 배포하지 않았다.
- `auto-state`의 미추적 4,237파일 전부가 기존 커밋 `f3e0db407f`의 같은 경로와 내용이 같다. 389파일은 blob이 그대로 일치하고 3,848파일은 CRLF를 LF로 정규화하면 일치한다. 그 외 새 내용은 0파일이다. 추적된 두 sample log 삭제는 fixture 브랜치의 복구 흔적이며 main에 제품 코드로 다시 넣지 않는다.
- `d427-bulk-check`의 15 미추적 파일은 모두 Gradle/Kotlin 캐시·잠금·오류 로그다. 제품 소스나 사용자 데이터 변경으로 커밋하지 않는다. `fleet-ship`의 설정 lock과 main의 `aff1.log`도 실행 부산물로 보존한다.
- `d427-bulk`의 CLI 테스트 개선과 `v13-map-labels`의 여섯 파일 책임은 현재 main의 더 최신 구현에 이미 반영됐다. 구체적인 현행 경로·커밋과 학습 계획 원문은 아래 learning 복구 커밋의 검증 문서에 기록했다.
- `account-docs-resume`의 D-802/D-803 gap 제거는 이미 main에 있고 ADR 파일도 존재한다. logout button 수정은 `el()`이 attrs를 `setAttribute`로 적용하는 현재 구현 및 대기 중인 account 복구와 DOM 동작이 같다. 중복 소스 변경을 만들지 않는다.
- 워크트리 상한 60개에 도달해 공식 gateway의 preview와 대상 경로 확인 후 `prune --apply`를 실행했다. 깨끗하고 이미 main에 병합됐으며 충분히 쉰 6개만 제거했다. gateway 기본 동작으로 이들의 이미 병합된 브랜치도 제거됐다. 미커밋·잠김·진행 중 원본은 보존했다.

복구 커밋과 원격 집중 검증:

| 주제 | 커밋 | 확인 결과 / 상태 |
|---|---|---|
| Windows Git 인접 서명 도구 탐색 | `eb58361d8` + `4bb730b67` | 원격 95 passed, Windows 전용 207 skipped. 얕은 Git 경로 회귀를 추가했다. 전체 착지 검증 대기 |
| curation 산출물의 소스 체크아웃 외부 보관 | `8c4d2f984` + `c7cd5014b` | 먼저 실패를 재현한 뒤 원격 175 passed / 30 skipped, NEW 0. 착지 대기 |
| 기록·정책 산출물 경로 검사 | `b7205305c` | 원격 508 passed / 14 skipped, NEW 0. 착지 대기 |
| 개발 절차의 scratch 경로 | `a093d5b24` | 원격 affected 550 passed / 36 skipped. 착지 대기 |
| 학습 가이드 scratch 경로 | `3a61f406b` | 커밋 및 공식 착지 대기 |
| 장치 가이드 scratch 경로 | `57eb1f426` | 커밋 및 공식 착지 대기 |
| 사이트 가이드 scratch 경로 | `23f385d65` | 커밋 및 공식 착지 대기 |
| 학습 계획 원문과 이관 검증 기록 | `3819ea7773` | 원문 194,702 bytes의 blob 일치 확인. 원격 문서 검증 142건, NEW 0. 착지 대기 |
| OMX 계약 타입 분리 | `410a6d755` + `cd1cef66a` | 독립 Safety-Review. 원격 545 passed / 7 skipped, NEW 0. 최초 safety anchor 누락을 수정하고 재검증했다. 공식 전체 착지 검증 대기 |
| OMX 진단·일관된 receipt snapshot | `985a726f22` | 독립 Safety-Review. 원격 집중 시험 exit 0, 13 skipped, NEW 0. 공식 착지 대기 |

하드코딩 경로 WIP의 과거 날짜 증거·로그·ADR 내용 치환과 이를 허용하는 append-only 검사 완화는 복구 대상에서 제외했다. 실제 실행 당시의 증거를 현재 환경 변수 표기로 바꾸거나 감사 규칙을 약하게 만들지 않는다. 원본 미커밋은 그대로 보존한다.

OMX 네이티브 시뮬레이션 helper/배포 도구와 G2 runtime은 별도 후속 복구·독립 검토 중이다. D-786은 Proposed 상태를 유지한다. 이 작업에서는 호스트 설치·서비스 실행·실물 동작을 수행하지 않는다.
