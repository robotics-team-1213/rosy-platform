# ROSY 워크트리 순차 처리 계획

브랜치마다 상태 확인·검토·검증·착지·정리를 따로 기록한다. 활동이 확인되거나 미해결 결함이 있으면 원본을 보존하고 다음 독립 후보로 넘어간다. 오래된 순서나 파일 수만으로 완료를 판정하지 않는다.

## 이번 처리 결과 — 2026-10-19 03:21 KST

후속 요청에서 사용자가 원본 브랜치·복구본을 남기고 작업 폴더만 제거하는 방식을 선택했다. 추가19개 작업 폴더 정리 결과와 보존 범위는 `worktree-cleanup-followup-2026-10-19.md`, `worktree-retirement-manifest-2026-10-19.md`에 기록했다. 아래는 앞선03:21 처리 당시의 기록이다.

- 로컬 main 착지 11개, 워크트리·브랜치 정리 완료 확인 11개(이번 세션 직접 6개, 다른 세션 정리 확인 5개). 원본 커밋 이력은 모두 보존한다. 푸시·장치 적용은 실행하지 않았다.
- `fleet-prune`는 5라운드 모두 선행247·영향19901 passed / NEW0이었으나, 시험 중 동료 main 착지가 계속되어 도구가 최대5회 후 중단했다. HEAD `ae52e13d94ac737556ded28471aef971cf430e57`과 원본·수정·로그를 보존했고 미머지·미삭제 상태다. 추가 자동 재시도로 제한을 우회하지 않았다.
- 나머지 19개는 아래 사유로 보존했다. `host-uv`는 소스 시험 통과와 별개로 AI PC의 uv 부재 때문에 전환 전제를 충족하지 않는다. 실제 설치·장치 적용은 실행하지 않았다. 최종 미리보기는 제거 가능0개이며, 잠금·미커밋·다른 세션의 새 활동도 보존했다.
- 안전/활성화 결함, 과거 커밋 크기 위반, 검사기 호환 문제, 넓은 고유 변경은 아래 사유대로 보존·보류한다. 잠금·미커밋·새 활동은 정리하지 않는다. 아래 최초 조사와 과거 실행 기록은 당시 상태이며 이 요약과 최신 후속 기록이 현재 상태다.

## 목표와 범위

### 31개 검토 후보의 현재 판정

| 상태 | 워크트리 | 근거·다음 조건 |
|---|---|---|
| main 착지·정리 완료 11 | fleet-device-authority, pr-path, git-workflow-docs, sim-il-adr, real-dispatch-adr, account-learning-profile, wt-auth-route-split, work-approval, wt-omx-sim-9a5dea, device-power-port, sim-teacher | 원본/착지 SHA의 main 조상 관계 및 경로·브랜치 부재 확인. 직접 정리6, 다른 세션 정리 확인5 |
| 동시 main 착지로 관문 중단 1 | fleet-prune | canonical clock 회귀 수정 및 독립 검토 완료. 5라운드 모두 선행247·영향19901 passed / NEW0이나 main이 계속 움직여 최대5회 후 STOP. HEAD commit ae52e13d94ac737556ded28471aef971cf430e57 보존. 최신 main3c9254a526에는 착지하지 않았으며 삭제하지 않음 |
| 운영 전제 미충족 1 | host-uv | 소스 영향 시험664 passed이나 AI PC에 uv가 없어 새 환경 생성 전환 불가. 설치·적용 없이 원본과 수정 보존 |
| 고유 작업·현 작업과 재조정 필요 4 | cal-pr, wt-rules, device-trial, trip-prod-open | 앞의 두 브랜치는 주목적이 main에 있으나 수입 이력의 별도 고유 작업이 남음. 뒤의 두 브랜치는 카메라/TRIP 활성화 및 현재 trip-split 작업과 연계. 통째 중복 머지 금지 |
| 실제 소스 결함·미구현 3 | pre-grasp, camera-evidence, wt-map-lap-9c7d70 | 각각 wait 후 만료 증거, HOLD/resume 후 오래된 증거, 최종 출력 history API/hook 미구현. 안전한 기능 완성·통합 검증 전 보존 |
| 과거 크기 관문 거절 10 | omx-native-pilot, sim-closed-loop, sim-il-int, sim-il-run, policy-gov, camera-calibration, fleet-net-load, webrtc-plan, d769-learned-follow, pinky-lap-goal | 아래 최초 거절 커밋 기록 참조. 후속 커밋으로 과거 위반을 숨기거나 원본 amend/rebase하지 않음. 원본 보존 후 별도 범위로 재구성 필요 |
| 검사기 호환 미해결 1 | size-ratchet | 과거 size_limits 호출 규약과 현재 size_range의 TypeError. 크기 위반 판정으로 오기하지 않음 |

초기 잠금8·이전 이력2·미커밋8·최근 활동12는 위 31개와 별도 보호 대상이다. 새로 생긴 동료 워크트리도 보호하며 총 워크트리 수 변화 자체를 이번 정리 성과로 세지 않는다.

- 사용자가 요청한 범위: 현재 작업하지 않는 워크트리를 찾아 완료할 수 있는 변경은 커밋·로컬 main 머지·워크트리 정리까지 처리한다.
- 이 문서는 조사 결과와 실행 순서 및 아래 실행 기록을 담는다. 사용자의 순차 실행 지시에 따라 검토한 31개 중11개는 착지·정리했고, 1개는 동시 main 갱신에 따른 관문 중단, 19개는 사유별 보류 상태로 보존했다. 푸시는 요청 범위에 넣지 않았다.
- 저장소: `D:/Dev/Robot/Rosy/rosy-platform`.
- 절차의 기준: 저장소 `AGENTS.md` 「같이 하는 깃」, `docs/reference/shared-checkout.md`, 현재 `tools/worktrees.py`와 `tools/land.py`. 실행 시 최신 지침을 다시 확인한다.

## 조사 결과 — 2026-10-18

`tools/worktrees.py status` 기준 워크트리 61개로 상한 60개를 초과했다. 판정은 active 49개, locked 8개, removable 1개, stale-history 2개, landed-dirty 1개다. 미커밋 변경이 있는 곳은 10개다. 아래 분류는 서로 겹치지 않게 61개를 나눴다.

주의할 점:

- 도구의 active는 유휴시간 기준 판정이며 실행 중인 세션을 증명하지 않는다. 반대로 깨끗한 상태도 작업 종료를 증명하지 않는다.
- 프로세스 조사에서 에이전트 프로세스 19개를 발견했지만 명령줄에 워크트리 경로가 없어 소유 작업을 연결하지 못했다. 프로세스가 없다고 판정한 워크트리는 없다.
- 다수 워크트리에 비슷한 약 19시간의 유휴시간이 나타났다. 이것만으로 미사용을 확정하지 않는다.
- 조사 중 main은 `a2cd2227e1`에서 `e57a2c5bb4`로 갱신됐다. 다른 작업이 진행 중이므로 모든 판정은 실행 직전에 갱신한다.
- main의 미추적 `aff1.log`는 보존한다. 조사 당시 origin/main과 이력이 갈라져 있었다. 로컬 머지 성공을 원격 동기화나 CI 통과로 표현하지 않는다.

## 각 워크트리의 처리 절차

1. 상태·HEAD·잠금·소유자·진행 중인 git 연산을 확인한다. 해당 워크트리를 가리키는 실행 프로세스, 확인 가능한 소유 세션 상태, 조사 이후 HEAD/파일 변경을 함께 확인한다. 활동 증거가 있으면 보류한다. 연결할 수 없는 세션은 미확인으로 기록한다.
2. 잠금, 최근 활동, 이전 이력, 미커밋 변경이 있으면 아래 보류 절차를 적용한다. 최근 활동은 이번 조사에서 2시간 이내인 것을 우선 보호하는 운영 기준이며 저장소의 삭제 유예시간을 대체하지 않는다.
3. 깨끗한 미머지 후보는 `git log main..HEAD`, 공통 조상 이후 diff, `git cherry main HEAD`로 고유 변경·중복 패치·다른 브랜치 의존성을 확인한다. 패치가 같다는 이유만으로 브랜치를 삭제하지 않는다.
4. 문서도 실제 파일을 읽어 현재 구현·ADR·계약과 맞는지 검토한다. 계획 문서의 머지를 기능 구현 완료로 취급하지 않는다. API/권한/안전 변경에는 해당 계약 검토를 수행한다.
5. 현재 main 체크아웃의 `tools/land.py --dry-run --tests auto`를 대상 워크트리에서 실행한다. 출력한 검증 범위와 충돌을 기록한다. 15파일 초과 또는 FULL이면 분리 가능성부터 검토한다.
6. 필요한 수정은 그 작업 소유 경로로 한정해 검토 후 명시적인 파일/헝크만 커밋한다. 다른 세션의 미커밋은 일괄 커밋하지 않는다.
7. 현재 관문 도구로 `--tests auto` 착지를 실행한다. pytest는 커밋된 리비전을 원격 시험 PC에서 실행하고 known_failures와 비교한다. 노트북 pytest나 테스트 생략으로 대체하지 않는다. NEW가 발생하면 main에서도 확인해 브랜치 실패와 MAIN-RED를 구분한다. 원격 시험 PC가 없으면 규정된 재시도 후 미확인으로 보류한다.
8. 검증된 후보만 관문 도구를 통해 main에 착지한다. main 이동 시 도구의 재검증 절차를 따른다. 다른 세션 파일 때문에 거절되면 그 파일을 그대로 둔다.
9. 처리 후 HEAD가 main의 조상인지, 미커밋·비캐시 ignored 자료·잠금·진행 중 연산이 없는지 다시 확인한다. `worktrees.py prune` 미리보기를 확인하고, 실제 미사용 및 저장소 유예조건을 충족한 것만 `prune --apply`로 정리한다. 전역 sweep에 다른 최근 작업이 섞여 있으면 실행하지 않는다. 직접 재귀 삭제하지 않는다.
10. 브랜치/원본 HEAD/검토한 경로/최종 커밋/원격 시험 로그/착지한 main/정리 결과를 기록한 후 다음 후보로 간다.

### 관문 실행 방법

오래된 워크트리의 `tools/land.py`는 존재하지 않는 `X:/`를 사용해 사전 검사부터 실패했다. 저장소 코드는 바꾸지 않고 현재 main의 관문을 사용했을 때 사전 검사가 실행됐다.

PowerShell에서 대상 워크트리로 이동한 뒤:

```powershell
$env:ROSY_SCRATCH = [System.IO.Path]::GetTempPath()
python D:/Dev/Robot/Rosy/rosy-platform/tools/land.py --main-checkout D:/Dev/Robot/Rosy/rosy-platform --tests auto --dry-run
```

실제 착지 시 `--dry-run`만 제거한다. 이는 테스트 통과를 보장하는 명령이 아니다. 최신 main의 관문이 실행 중 변경되었으면 실행 코드와 검증 대상을 다시 확인한다.

## 1차 처리 순서

아래는 검토 순서이며 작업 중지 확인이나 착지 승인을 대신하지 않는다. 후보가 보류되면 다음 독립 후보로 넘어간다.

| 순서 | 워크트리 | 확인한 범위 | 다음 조치 |
|---|---|---|---|
| 1 | fleet-device-authority | 2커밋, 문서 3파일 | 문서 내용과 소유 세션 활동 확인 후 착지. 현재 관문 dry-run 성공, index/log만 자동 해결 대상으로 표시됨 |
| 2 | pr-path | 1커밋, 문서 3파일 | GitHub PR 전환 **계획**으로 검토. 현재 관문 dry-run 성공, index/log만 자동 해결 대상으로 표시됨 |
| 3 | git-workflow-docs | 2커밋, 11파일 | 최신 공유 체크아웃 절차 및 앞선 PR 계획과 충돌·중복 확인 |
| 4 | sim-il-adr | 1커밋, 3파일 | Proposed ADR 상태·번호·실제 구현과 맞는지 검토 |
| 5 | real-dispatch-adr | 2커밋, 2파일 | D-797 구현을 설명하는 내용이므로 pre-grasp/실제 dispatch 변경과 의존성 확인 후 배치 |
| 별도 | fleet-prune | 1커밋, 4파일 | 현재 관문 dry-run이 `test/architecture/size_ratchet.txt` 수동 충돌로 중단됨. 최신 기준을 보존하며 변경 필요성을 확인한 뒤 해결; 작다는 이유로 우선 착지하지 않음 |

위 문서 후보의 현재 관문 dry-run은 lint 다음 약 18개 시험 파일을 선택했다. 실제 lint·원격 pytest·머지는 아직 실행하지 않았다. dry-run의 충돌 없음은 최종 합친 트리의 검증 증거가 아니다.

## 전체 대기열

### A. 최근 활동 보호 — 12개

`d798-accept`, `gripper-tune`, `host-recovery`, `land-cache`, `learn-omx`, `omx-feedback-fix`, `origin-sync`, `pinky-sd-ready`, `push-batch`, `remote-parallel`, `site-console-video`, `v2-sim-lap`.

조사 당시 최근 2시간 이내 활동이 있었다. `host-recovery`는 main에 반영됐고 깨끗하지만 활동이 약 0.1시간 전이었다. 도구가 소유자 일치로 즉시 삭제 가능하다고 표시해도 현재 세션에서 만든 것으로 확인되지 않아 삭제하지 않는다. 소유 작업의 종료와 이후 유휴상태를 확인한 뒤 다시 분류한다.

### B. 잠금 보호 — 8개

`fleet-ship`, `omx-bounded-commission`, `omx-core-runtime`, `omx-native-feedback`, `omx-preserved-init`, `omx-torque-readback`, `signal-occupancy`, `wt-fleet-budget-a8f123`.

잠금을 해제하거나 정리하지 않는다. `fleet-ship`에는 미커밋 1개가 있다. 나머지도 잠금이 필요한 이유를 확인한 후에만 재분류한다. 이미 main에 반영된 잠금 워크트리도 동일하다.

### C. 이전 이력 — 2개

`learning-delivery`(미커밋 3개), `publication-a0-r1-red-proof`(깨끗함).

그대로 머지·착지하지 않는다. 필요한 고유 변경을 현재 main에서 재구성할 수 있는지 조사하고, 원본 커밋과 미커밋은 보존한다. 원본 보관·삭제는 별도 근거를 확보한 후 처리한다.

### D. 미커밋 보존·내용 확인 — 8개

| 워크트리 | 미커밋 파일 수 | 우선 확인 |
|---|---:|---|
| auto-state | 27 | quarantine 목적과 fixture 변경의 소유자 |
| d427-bulk | 1 | 비캐시 ignored 자료 10개와 미커밋 내용 |
| d427-bulk-check | 1 | detached HEAD, main 반영 상태, ignored 자료 10개 |
| hardcode-paths | 738 | 대량 변경 원인과 소유 작업. main 반영된 HEAD라도 변경을 버리지 않음 |
| learning-plan | 4 | ignored 자료 1개, 후속 학습 작업과 연결 |
| omx-auto-deploy | 2 | 배포 관련 미커밋의 소유자와 완료 상태 |
| omx-native-ready | 84 | main 반영 뒤 남은 대량 변경의 원인 |
| v13-map-labels | 6 | landed-dirty, ignored 자료 1개 |

활동이 끝났다고 확인한 뒤에만 변경 내용을 검토한다. 이미 착지한 워크트리의 새 변경은 정리 공간 확보 후 새 주제 워크트리로 보존하며 옮기는 방안을 먼저 설계한다. 일괄 stash/reset/clean/snapshot으로 처리하지 않는다.

### E. 깨끗한 미머지 검토 후보 — 31개

1차 목록 6개와 나머지를 포함한 전체 후보:

| 묶음 | 워크트리 | 검토·착지 순서의 기준 |
|---|---|---|
| 문서·관문·기준 | fleet-device-authority, pr-path, git-workflow-docs, sim-il-adr, real-dispatch-adr, fleet-prune | 위 1차 순서. 공유 지침과 기준 파일은 현재 main과 대조 |
| 계정·학습 UI | account-learning-profile, wt-auth-route-split | 일부 커밋은 browser 시험/프로필 권한과 연결됨. 현재 main에서 이미 제공되는 동작과 고유 diff를 대조한 뒤 의존 순서 확정 |
| Fleet·호스트 | host-uv, work-approval, trip-prod-open, fleet-net-load | 호스트 설정·권한·TRIP 계약을 검토하고 브라우저/원격 검증 범위 확인 |
| 장치 시험·카메라 | device-trial, camera-evidence, device-power-port, camera-calibration, cal-pr, webrtc-plan | 증거·배포·카메라 변경 의존성 확인. 큰 diff는 분할 가능성부터 검토 |
| OMX·시뮬레이션 | pre-grasp, policy-gov, omx-native-pilot, sim-teacher, sim-closed-loop, sim-il-int, sim-il-run, wt-omx-sim-9a5dea, wt-map-lap-9c7d70 | 안전/계약 검토 후 의존 순서 확정. 하드웨어를 움직이는 시험은 이 정리 작업에서 자동 실행하지 않음 |
| 대형 누적 변경 | d769-learned-follow, pinky-lap-goal, size-ratchet, wt-rules | 각각 main 밖 커밋 수 435/453/15/37, diff 파일 수 257/268/25/576으로 조사됨. 통째 착지 전에 고유 변경·중복·범위를 확인 |

## 완료 기준과 중단 조건

- 각 항목은 `착지·정리 완료`, `main 반영 확인·유예 대기`, `활동 중`, `잠금 보존`, `미커밋 보존`, `중복/대체 확인 대기`, `충돌/검증 실패`, `이전 이력 재구성 대기` 중 실제 근거가 있는 상태와 다음 조치를 남긴다.
- 미사용을 확인하지 못했다면 완료나 활동 종료로 표시하지 않는다. 이번 조사만으로 61개 중 특정 워크트리의 소유 세션 종료가 확인되지는 않았다.
- 충돌을 없애려고 다른 세션의 파일을 치우지 않는다. 새 테스트 실패, MAIN-RED, 원격 검증 불가, 보존 실패, 활동 재개가 나타나면 그 항목의 착지·삭제를 중단하고 독립 항목으로 넘어간다.
- 정리 후 main의 내용, 원본 고유 커밋, 미커밋·ignored 자료가 손실되지 않았음을 확인한다. 삭제 수를 목표로 삼지 않는다.

## 이번 조사에서 실제 실행한 것

- [x] 워크트리 관문 상태/정리 미리보기와 main 상태 확인.
- [x] 잠금·미커밋·최근 활동·이전 이력 분류.
- [x] 프로세스 명령줄의 워크트리 경로 조사. 세션 연결은 미확인.
- [x] 작은 후보 10개의 고유 커밋·경로·패치 중복 여부 조사.
- [x] 현재 main 관문으로 3개 후보 dry-run: 문서 후보 2개 성공, fleet-prune 수동 충돌 확인.
- [ ] 각 후보의 실제 미사용 확인 및 전체 diff 검토.
- [ ] 수정이 필요한 작업의 명시적 커밋.
- [ ] 원격 검증과 로컬 main 착지.
- [ ] 유예·보존 조건을 충족한 워크트리 정리.

계획 자체 점검: 최초 조사한 61개를 12+8+2+8+31개로 분류했고, 조사 증거와 미확인을 구분했다. 제품 코드·기존 문서·git 브랜치는 수정하지 않았다. 이 계획은 조사 시점의 대기열이며 다음 착수 전에 다시 스캔한다.

최종 파일 점검 시 디렉터리 수는 62개로 바뀌었고 `fleet-split`, `host-recovery-publish`, `land-split`이 추가로 관측됐다. 동료 세션에서 생성·정리가 진행되고 있으므로 이 세 항목은 새 활동 보호 대상으로 보류한다. 최초 61개 분류의 수치를 최신 개수로 덮어쓰지 않으며, 다음 실행은 반드시 새 인벤토리에서 출발한다.

## 실행 기록

사용자가 순차 실행을 지시했다. 현재 main `6d20063618`에서 시작했고 미추적 `aff1.log`는 그대로 보존한다.

| 대상 | 현재 상태 | 증거와 다음 조치 |
|---|---|---|
| fleet-device-authority / docs/fleet-device-authority | 착지·정리 완료 | 원본 `69f67b41a1`. 해시 오인을 명시적 SHA 표기로 수정한 `dc422cc38`와 index 갱신 `3710d6f00` 포함. 최종 main commit `43dc4516ff3fe234834b926d9564b4acb5c36799`. 최종 후보에서 현장 시험 PC 선행 247 passed 및 회귀 472 passed, NEW/known/flaky 0. `run-g2-1.txt`, `run-2-1.txt`, land record `.git/rosy-land/43dc4516ff3fe234834b926d9564b4acb5c36799.json`. 로그는 `%TEMP%/rosy-worktree-reconcile/rosy-land/docs-fleet-device-authority/`. 원본 실패와 UTF-8 실행 환경 정정은 위 기록 참조. main에서 정리 미리보기의 유일한 후보임을 확인하고 `prune --apply`로 해당 워크트리·브랜치 삭제 완료. 푸시 없음 |
| pr-path / docs/github-pr-landing-path | 착지 완료·정리 유예 대기 | 원본 `9edc054148`. 최종 main commit `bb5fcfab0d0fabbe745334e3db8c7b95a2f6babf`. 선행 시험은 현장 시험 PC 247 passed, 최종 회귀는 모델 PC 472 passed, NEW/known/flaky 0. 로그: `%TEMP%/rosy-worktree-reconcile/rosy-land/docs-github-pr-landing-path/{run-g1-1.txt,run-1-1.txt}`. 관문이 소유 세션 차이로 1시간 유예를 적용해 현재 보존. PR 이행 계획만 통합했고 push/reset/remote 설정 변경은 하지 않음 |
| git-workflow-docs / docs/git-workflow-handoff | 착지 완료·정리 유예 대기 | 수동 해결 commit `cc4c261843f6da656cd8a560daf2b3d37132351c`, 최종 main `be0e3379367267232104c78263e216eb2e164c7b`. 최신 main 규칙을 보존하며 문서 연결과 NEW 판정 수정. 상대 링크 45개 확인. 최종 후보의 모델 PC 선행 247 passed, 회귀 1189 passed / 2 skipped / NEW 0. 로그: `%TEMP%/rosy-worktree-reconcile/rosy-land/docs-git-workflow-handoff/{run-g3-1.txt,run-3-1.txt}`. skip 세부 사유는 해당 로그에 출력되지 않았으며 실행된 것으로 계산하지 않음. main 이동을 두 차례 합쳐 총 3라운드 후 착지. 원본/추가 커밋 모두 보존 |
| sim-il-adr / docs/omx-sim-il-loop-adr | 착지 완료·정리 유예 대기 | 원본 `7cfab2e587`。D-787 미작성 예약 두 행을 제거한 commit `a92c20a1c252fa319fd154215919aba6119789f7` 포함. 최종 main `143968a508fbaa99f30ae274107d1da3704271ca`. 모델 PC 선행 247 passed 및 회귀 518 passed, NEW/known/flaky 0. 로그 `%TEMP%/rosy-worktree-reconcile/rosy-land/docs-omx-sim-il-loop-adr/{run-g2-1.txt,run-2-1.txt}`. simulation 전용 Proposed 상태 유지, 런타임 활성화·실물 승격 없음 |
| real-dispatch-adr / docs/real-device-dispatch-opening | 착지 완료·정리 유예 대기 | 원본 `4d218631f5`와 `7ea375fe06`. 최종 main commit `801a3bb88cd5887c15805ac5ee234076a714d78e`. 본문·Log는 Proposed, 코드·profile 활성화 변경 없음. D-797 미작성 예약 두 행만 제거. 모델 PC 선행 247 passed, 회귀 518 passed, NEW/known/flaky 0. 로그 `%TEMP%/rosy-worktree-reconcile/rosy-land/docs-real-device-dispatch-opening/{run-g1-1.txt,run-1-1.txt}`. 실제 dispatch 구현·장치 수용의 완료 증거로 해석하지 않음 |
| fleet-prune / refactor/schemas-ratchet-offset | 충돌 해결·원격 검증 중 | 통합 커밋 commit `56924aff7a7e2ed5ae7fb39895350f31333d94bc`. 핵심 validator는 이미 main과 같아 schemas.py와 size_ratchet.txt의 main 대비 차이 0을 확인. main의 1234줄 기준 보존. 현재 net 변경은 foundation index/log 2파일뿐. 원격 선행 247 passed, NEW 0, 회귀 실행 중 |
| account-learning-profile, wt-auth-route-split | 내용 대체 확인·이력 통합 대기 | 두 후보 모두 main과 가상 병합한 트리가 main과 완전히 같음(net diff 0, 충돌 없음). 기존 변경이 현재 main에 보존됨을 경로별 확인한 뒤 관문으로 이력 통합·정리 가능 |
| pre-grasp / feat/omx-pre-grasp-source-check | 미완료·결함으로 머지 보류 | 원본 commit `9806ffc49dfaa2bedd30b4ef858aa4bf2c969a38`, 4파일 보존. 독립 `rosy_contract_reviewer`의 P2: source_check.py:112의 receipt가 관측 시각/만료를 보존하지 않고 cell_workflow.py:83이 approach 결과를 소비할 때 한 번만 확인함. owner가 파지를 PHASE_WAIT로 보류했다가 재개하면 pick_place_runner.py:296에서 max_age_s를 지난 증거로 grasp를 제출할 수 있음. source proof 성공→grasp 대기→최대 나이 초과→barrier 해제(관측 없음/물체 이동)에서 grasp 제출이 없는 통합 회귀가 필요함. 현재 stub 시험은 이 경로를 다루지 않음. 소스 검토 결과이며 원격 재현·ROS-SIM·실물 시험은 미실행. 실제 owner 호출자는 source 설정을 넘기지 않아 현재 배선도 미완료이나, 선택 기능 미배선 자체를 별도 결함으로 세지 않음. manifest concern은 control이고 해당 경로는 safety_modules/anchor에 없어 trailer 누락 위반으로 판정하지 않음. 미해결 결함이 있어 clean Safety-Review attestation을 붙이지 않음 |
| omx-native-pilot / feat/omx-native-pilot-sim | CLI 회귀·과거 커밋 크기 위반으로 보류 | 원본 commit `d83f8f383751dd6a26ef49cd732df8e39017daaa`. 독립 검토의 P2: probe_pilot_recording.py:104가 argparse에 --inside를 등록하지 않아 README:532의 기존 명령이 실패함. CLI 수준 회귀가 필요함. 별도 사전 검사에서 과거 `95d48a33e8` 커밋의 omx_adapter 10055줄이 상한10000을 넘는다고 거절. 현재 관문은 각 커밋의 정합성을 검사하므로 후속 커밋만으로 이 과거 위반을 덮지 못함. 다른 세션 원본을 amend/rebase하지 않으며, 원본 보존 후 제한을 지키는 분리·재구성에서 CLI 수정도 함께 처리해야 함. 19파일은 runtime/test 8개와 동결 검증 자료11개의 한 관심사로 평가됨. 기존 evidence의 기준은 3bd0be240b, native/현재main 통합 검증과 실물 수용을 대체하지 않음 |
| sim-closed-loop / feat/omx-sim-act-closed-loop | 과거 커밋 크기 위반으로 보류 | `dea9c719c4`가 tools/harness/affected_tests.py를 601줄로 만들어 상한600을 넘었다고 현재 size_range 관문이 거절함. 해당 커밋을 조상으로 갖는 sim-il-int와 sim-il-run도 같은 이력을 포함함을 git ancestry로 확인. 원본을 보존하고 먼저 분리한 이력으로 재구성해야 함. 루트 pytest나 원격 Gazebo로 이 정적 관문을 우회하지 않음 |
| sim-teacher / feat/omx-sim-reach-teacher | 미완료·CLI 회귀/검증 주장으로 보류 | 원본 commit `365f9332ff591bc67af1058fc17840b2be4a9cfe`, 12파일 보존. 독립 검토 P2: run_sim_reach_pipeline.py:44는 --inside에서도 RUN/recordings를 선택하지만 :49에서 복사를 생략하므로 실제 /recordings 자료를 export하지 못함. 내부 실행의 기본 경로 또는 필수 인자 검증과 CLI 회귀가 필요함. 별도 P2: sim_reach_task.py:150이 소수4자리로 반올림하고 임의로 좁은 유효 범위를 허용해 서로 다른 seed가 같은 시작 자세가 될 수 있음. seed/episode 분할만 하는 sim_batch_export.py:148로는 문서의 시작 자세 비중복 주장을 보장하지 못함. 이는 관측 bytes 중복이 입증됐다는 뜻이 아니며 시작 자세 분리의 검증·주장 정합성 문제임. 완전한 폐루프/평가기 파일은 아직 없어 명시적으로 생략되는 부분 파이프라인임. 원격 재현·Gazebo·학습·실물 시험은 미실행 |

조사 중 추가 관측한 `host-report-access`, `land-queue`, `perception-agents-md`, `trip-split`, `updater-split`은 다른 세션의 새 활동 대상으로 보존한다. `omx-feedback-fix`에 새 잠금이 생긴 것도 확인해 보호 대상으로 유지한다.

### 2026-10-19 후속 검증

- `fleet-prune`: 첫 회귀 묶음 10369 passed / 534 skipped, 두 번째 3967 passed / 113 skipped. 후속 묶음 실행 중이며 착지 완료로 세지 않음.
- `account-learning-profile`과 `wt-auth-route-split`: 최신 main에 대한 가상 병합에서도 충돌 없이 main 트리와 동일함을 재확인. 실제 관문 착지는 대기 중.
- `sim-teacher`: D-787은 seed 기반 평가를 요구하며 자세 비중복은 기존 문서의 과도한 주장임을 독립 검토로 확인. 데이터 모델이나 split 변경 대신 기본 녹화 경로와 문구만 수정. RED `7de87d49cd`에서 내부 실행의 기본 경로 사례만 기대한 이유로 실패. 수정 commit `73f8a5f6a805040e2a9a05daad43c0e6b38ff9b6`은 `/recordings`를 사용하고 명시적 경로를 우선함. 관련 pipeline/teacher/batch 3개 시험 파일 원격 exit 0. 독립 검토에서 새 결함 없음. 로그 `%TEMP%/rosy-worktree-reconcile/sim-teacher-{red,green}/run-1.txt`. 최신 main 통합과 전체 영향 시험은 대기 중. Gazebo/학습/실물 검증은 미실행.
- `host-uv`: 원본 commit `f2b4af96d27dcabba48e56c9cb731cad8233bd5c`의 과거 3커밋 크기 검사는 통과. main과 충돌은 common manifest 1곳으로, 최신 recovery 항목과 uv 항목을 모두 보존해야 함. 이미 존재하는 D-800의 오래된 gap 예약도 제거 필요. 독립 검토가 찾은 uvx 누락/잘못된 링크 미검출을 회귀 시험으로 재현함. 최초 RED는 무관한 SIM 패키지 drift 반환값에서 실패하여 시험만 먼저 바로잡았고, `4628ccf8d8`의 재실행은 두 사례 모두 uvx 보고 누락이라는 기대한 이유로 실패. 수정 `b51206ae49`는 설치기가 소유한 bin 링크 전체를 검사하고 승인 정책은 유지함. host-state/remote runner 3개 시험 파일 원격 GREEN 진행 중. 실제 호스트 설치·적용은 실행하지 않음.

충돌이 넓은 16개 후보는 자동 착지하지 않고 모듈별 재조정 대기 상태로 유지한다. 가상 병합의 충돌 파일 수: `cal-pr` 71, `camera-calibration` 18, `camera-evidence` 8, `d769-learned-follow` 17, `device-power-port` 24, `device-trial` 8, `fleet-net-load` 11, `pinky-lap-goal` 17, `policy-gov` 15, `size-ratchet` 12, `trip-prod-open` 8, `webrtc-plan` 20, `work-approval` 6, `wt-map-lap-9c7d70` 6, `wt-omx-sim-9a5dea` 6, `wt-rules` 86. 이는 현재 main과의 정적 비교이며 원본 작업의 완료 또는 실패 판정이 아니다. API/Fleet/CORE 경계 변경은 각 실제 생산자·소비자와 후속 분리 작업의 중복을 검토해야 한다.

- `host-uv` 수정의 원격 GREEN 완료: host-state/remote_pytest/remote_sim 3개 파일 exit 0. main `0c7e8ffe68`을 합친 후보는 commit `64ec4489e3770203651adf77938b3a570dfba1af`. 독립 검토에서 baseline manifest의 모든 행 및 install/copy_approved/check/main 함수 보존을 확인했고 새 결함 없음. D-796/797/800의 오래된 gap만 제거함. dry-run 안전·크기 관문 통과, affected 시험 선택이며 실제 착지는 대기 중.
- `sim-teacher`의 같은 main 통합 후보는 commit `51ea22bb2dfce690b86d9cd333c20bc149ab1914`. 독립 검토에서 경로 수정과 seed 기반 주장 유지 확인, 새 결함 없음. dry-run 안전·크기 관문 통과, batch/hub-sync/protocol/root test가 선택되며 실제 착지는 대기 중.

- 00:29 확인: `pr-path`는 유예 종료 즈음 다른 세션에서 정리된 것으로 관측됨(이번 세션은 해당 prune을 실행하지 않음). 워크트리 경로와 브랜치가 없고 최종 착지 commit `bb5fcfab0d0fabbe745334e3db8c7b95a2f6babf`가 main의 조상임을 확인했다. Fleet 문서에 이어 실제 정리 완료 관측은 총 2개다.
- 두 중복 후보의 main 통합 준비 커밋: 계정 프로필 `ab82eaeec`, 인증 경로 `fb5cd5dfd`. 양쪽 모두 실제 병합 index와 main의 내용 차이 0을 확인한 뒤 커밋했다. 인증 경로의 최초 dry-run은 과거 selector에 full_invocations 필드가 없어 중단됐으나, 최신 main을 병합해 도구를 함께 갱신했으며 아직 실제 착지 성공을 주장하지 않는다.

- `fleet-prune` 첫 회귀 3묶음 모두 완료: 10369 passed / 534 skipped, 3967 passed / 113 skipped, 5521 passed / 317 skipped, 각각 NEW 0. 시험 실행 시간 1575초. 시험 중 main이 이동해 최종 착지 없이 2라운드 시작. main `de60258108`을 합친 후보 commit `e52b3f2a6e73614b614c8ebe10c768d46f624fad`. 원래 두 파일의 net 변경과 현 main의 더 엄격한 제한은 그대로이며 최신 후보 검증을 기다린다.

- `fleet-prune` 2라운드: 선행 247 passed / NEW 0. 회귀 1묶음에서 실패 표시 관측, 상세 결과 대기 중. 새 실패 원인·main 재현을 확인하기 전 착지 성공으로 세지 않음.
- 추가 중복 판별: `work-approval` 원본 commit `d1750832fcfafe241ec5e11f5bba4a9e14943191`의 선택 항목 승인/역할·거절 안내/반응형 시험이 main에 이미 있고, main은 Cell Job과 늦은 응답 격리까지 보강함을 독립 검토자가 실제 UI→route→admission 경로에서 확인함. 원래 로그도 main에 보존됨. 6개 충돌을 최신 main 내용으로 해결한 준비 커밋 `8d7deb64f5b9a8398cb29569d8bfad88a38bf959`의 병합 index는 상대 main `6f55836ad9`와 완전히 같음. 안전/크기 dry-run 통과, 기본 관문 시험 착지 대기. 실제 Chromium은 이번 준비에서 미실행.
- 추가 중복 판별: `wt-omx-sim-9a5dea` 원본 commit `68d3e83e013e3f409e2861fd3081afbbc0e3d42c`의 D-756 ADR·검증 자료 blob과 모든 로그 행이 main에 보존됨. OAuth 4.0.0과 계정 SSO만 별도로 브라우저 실행하는 CI/selector/guard도 main에 있으며, guard의 차이는 최신 streaming Popen mock에 대응한 보강임을 독립 검토로 확인함. 원본 5커밋 크기 검사 통과. 6개 충돌을 main 내용으로 해결한 준비 커밋 `6e50e7470`은 병합 index가 상대 main과 바이트 단위로 같음. 파일 말미 newline도 상대 main과 동일하게 보존함. 기본 관문과 실제 착지는 대기 중이며 CI·실물 수용을 새로 주장하지 않음.

따라서 앞의 넓은 충돌 보류 목록 16개 중 `work-approval`과 `wt-omx-sim-9a5dea`는 정적 중복 확인을 마치고 이력 보존 착지 대기열로 이동했다. 나머지 14개는 모듈별 재조정 대기다.

- `policy-gov`: 원본 commit `d03c2802c8eb96cc4b4d29a032cfd8547d6726f4`의 원래 기능은 main에 보존·보강됐음을 독립 검토로 확인. governance 저장소/route/wiring와 core 시험은 byte-identical, main은 API v1.271과 policy_admin 호환·401 로그인 안내를 추가함. 장치 전달은 계속 not_connected. 그러나 크기 관문이 과거 `6b867c45e8`와 `75a8310142`의 fleet 16502→17101 증가 및 후자의 console 11317→11687 증가를 거절함. 중복이더라도 현재 main을 합치는 것만으로 과거 위반을 지울 수 없어 원본 그대로 보존·미머지. 새 runtime/UI 수정은 하지 않음.
- 나머지 후보의 3초 제한 크기 사전 조사: `device-power-port`(18커밋), `wt-map-lap-9c7d70`(8커밋)은 통과. 다른 11개는 제한 시간 안에 끝나지 않아 미판정이며 실패로 세지 않음. `size-ratchet`은 역사적 size_limits.ratchet_problems 시그니처와 현 검사기 인자 수가 달라 TypeError로 중단됐음. 이는 크기 위반 판정이 아니라 검사기 호환 문제로 별도 조사 필요. 보존 중인 원본 도구나 크기 기준은 변경하지 않음.

- `fleet-prune` 2라운드 첫 묶음 상세: 1 failed / 10368 passed / 534 skipped. 실패는 test_vision_preview.py::test_raw_and_annotated_api_are_same_capture_and_admitted_once_each의 raw_available=False. 두 번째 묶음 3967 passed / 113 skipped, 세 번째 실행 중. main commit `6f55836ad958c7a252654e402687abdd17d6d66f`에서 실제 경로 middleware/core/gateway/test/test_vision_preview.py의 해당 node를 원격 단독 실행하면 exit 0이므로 MAIN-RED로 판정하지 않음. 로그 `%TEMP%/rosy-worktree-reconcile/vision-preview-main-repro/run-1.txt`. store의 raw 신선도 2초와 실제 monotonic을 쓰는 기존 시험의 부하 민감성을 조사 중이나 아직 원인으로 확정하지 않음. known_failures 추가·무조건 재실행 면제·운영 stale 기준 완화는 하지 않음.
- `git-workflow-docs`도 다른 세션에서 정리된 것을 확인(경로/브랜치 없음, 착지 be0e337...는 main 조상). 정리 완료 확인은 현재 3개다. `sim-il-adr`, `real-dispatch-adr`는 아직 남아 있으며 유예 대기.
- 계정 프로필 후보는 실제 관문 실행 중. 1라운드 선행 247 passed / NEW 0 후 main 이동으로 2라운드, 후보 ed8327e9dd0a37c85975520be96f30758c66505d의 선행도 247 passed / NEW 0. 최종 영향 시험 및 착지는 대기.
- `camera-evidence` 원본 dc18ae0e8e의 과거 7커밋 크기 검사 통과. 그러나 독립 검토에서 main에 없는 source observation gate·camera evidence 계약/검증·trial identity 동작을 확인해 중복 이력 통합 대상에서 제외함. 추가 readiness 검토 중이며 파일은 수정하지 않음.

- 계정 프로필 후보 착지 완료: commit `ed8327e9dd0a37c85975520be96f30758c66505d`, 2라운드 최종 선행 247 passed 및 영향 시험 272 passed, NEW/known/flaky 0. 내용 차이 0으로 이력만 보존, 자동 선택에 browser opt-in은 포함되지 않음(새 브라우저 실행 증거로 주장하지 않음). 기록 `.git/rosy-land/ed8327e9dd0a37c85975520be96f30758c66505d.json`, 로그 `rosy-land/feat-account-learning-profile/{run-g2-1.txt,run-2-1.txt}`. 인증 경로 후보 실제 관문은 다음 순서로 실행 중.
- `camera-evidence` 보류 사유 확정: 승인된 observation의 Job 변경 이후 무효화를 submit 때만 검사하고 consume 때는 mission/step/사용 여부/만료만 검사함. 유효 관측 승인→HOLD/재개→추가 관측 없이 dispatch에서 첫 grant가 열릴 수 있음. 회귀는 아직 미실행. CELL_TRANSFER는 simulation-only라 실물 동작 결함으로 확대 주장하지 않음. 별도로 TRIP production/device_trial 활성화가 섞였고 이 delta에 장치 수용 자료가 없어 현재 trip 분리 작업과 조정해야 함. 최신 main으로 전부 덮으면 고유 기능을 잃으므로 원본 보존·미머지.

- 시뮬레이션 ADR 유예 종료 뒤 main 관문 preview에서 해당 1개만 removable임을 확인하고 prune --apply 실행. 경로를 .worktrees 절대 경계 안으로 확인했으며 `sim-il-adr` 워크트리·브랜치 삭제 완료. 계정 프로필도 같은 절차로 삭제 완료. 현재 정리 완료 관측은 5개(이 세션 직접 3개, 다른 세션 정리 확인 2개).
- 인증 경로 후보 착지 완료: commit `10117da286c3beecd45cf32ac86a03fd0aa0d97e`, 1라운드 선행 247 passed 및 영향 272 passed / NEW·known·flaky 0. 기존 원본 a36add3cff 이력 보존, 코드 차이 0. 로그 `rosy-land/refactor-account-auth-routes/{run-g1-1.txt,run-1-1.txt}`, 기록 `.git/rosy-land/10117da286c3beecd45cf32ac86a03fd0aa0d97e.json`. 워크트리는 유예 대기. 다음은 작업 승인 UI 이력 통합의 실제 관문.
- `device-power-port`: 독립 검토에서 원본 commit `f0841e99f9c11901c9e107a836bf10bed2dd8023`의 전원 protocol/manager/device/presence/ROS adapter/최종 cmd_vel gate/product profile/D-440/bench 문서가 main과 byte-identical임을 확인. main의 arm command activity, 첫 managed board·perception 변경 시 camera readiness 재검사, shared/power-action.js로 이동한 roster, CORE sleep interlock·명명 운영자 검증을 보존함. 모든 기존 로그 행도 main에 있음. 원본 18커밋 safety_review와 size_range 통과. 24개 충돌을 상대 main 내용으로 해결한 준비 커밋 `c8b9e0374dacb1d7fdee62950451fdbd9c275bb1`은 상대 main과 내용 차이 0, 현재 관문 dry-run 통과. 실제 시험·착지는 대기. D-440 Proposed 및 활성화 금지·bench 후 별도 승인 조건 유지, 물리 전원 cycling 미실행.

- `work-approval` 착지 완료: commit `f1df5036258d25a9f80d95fe1524910869de3304`. 1라운드 선행 247 passed와 영향 272 passed / NEW·known·flaky 0, 원본 기능과 새 main UI 보존 및 내용 차이 0. 로그 `rosy-land/feat-fleet-work-approval-seat/{run-g1-1.txt,run-1-1.txt}`. 브라우저를 새로 실행한 것으로 주장하지 않음. 총 착지 완료 8개, 정리 완료 5개. 다음 실제 관문은 OMX 준비 이력.
- `camera-calibration`은 19커밋 크기 검사 완료 후 보류 확정: 과거 3c7a39c892/b10f47b97f/a19625fb30/2a13a54780/8d26333b34의 fleet·app·ingest·console 증가와 7b5dceb68f 등의 축소 후 ratchet 미하향을 관문이 거절함. 앞의 3초 조사 미판정을 이 결과로 갱신한다. 원본 amend/rebase·기준 상향 없이 그대로 보존함.
- 최신 AGENTS.md D-790 절차를 재확인: safety root 밖 NEW 1~5개는 land 도구가 id별 단 한 번 단독 재실행해 모두 통과하면 LOAD-FLAKY로 별도 기록할 수 있다. 이는 원격 runner의 quarantine 재실행 규칙과 다른 land 전용 절차다. 실행 중 fleet-prune의 시작 버전에도 이 절차가 있음을 확인했다. 수동 main 단독 통과는 착지 면제로 사용하지 않고 자동 관문 결과를 기다린다. flaky_quarantine은 수정하지 않는다.

- OMX 준비 후보 착지 완료 commit `d59eda92f19bee9b750d1be8e472890bf81e445f`: 선행 247 passed + 영향 272 passed / NEW·known·flaky 0. 로그 `rosy-land/fix-omx-readiness-followup/{run-g1-1.txt,run-1-1.txt}`. 전원 정책 후보도 `1051105cc0c5e8369d15a2789b5f6506278e6147`로 선행 247 + 영향 272 passed / NEW·known·flaky 0, 로그 `rosy-land/feat-device-power-policy-port/{run-g1-1.txt,run-1-1.txt}`. 두 후보 모두 내용 차이 0의 이력 보존 통합이며 제품·장치 활성화 변경 없음.
- 실제 dispatch ADR 워크트리·브랜치는 다른 세션에서 삭제됐음을 확인했고 원본/착지 801a3bb...의 main 조상 관계를 검증했다. 이로써 정리 완료 확인 6개(직접3/타 세션 확인3).
- 크기 관문의 최초 거절 커밋 추가 확인: `fleet-net-load` c80b10aa50의 localization_service.py 611>600 및 fleet 증가, `webrtc-plan` 34cee8b1cc의 perception package 10075→10137 증가. 해당 거절만으로 착지 불가가 확인되어 뒤의 전 이력을 검사했다고 주장하지 않음. `device-trial` 4커밋과 `trip-prod-open` 3커밋은 크기 검사 통과하나 고유 활성화/현재 작업 중복은 미해결. `cal-pr` 6/33, `wt-rules` 6/37, `d769-learned-follow` 6/435, `pinky-lap-goal` 7/453만 검사한 부분 조사로 미판정이며 완료/실패 판정하지 않음.
- fleet-prune 2라운드의 세 번째 묶음은 5521 passed / 317 skipped. 하지만 첫 묶음의 실패 nodeid가 실제 없는 middleware/media/test_vision_preview.py로 출력돼 D-790 자동 단독 및 main 재확인 모두 exit4로 끝나 최종 STOP. 이 실패를 무시하거나 LOAD-FLAKY로 분류하지 않음. 실제 시험 파일은 middleware/core/gateway/test/test_vision_preview.py.
- 시간 의존성 재현/수정: 물리 preview import를 patch한 최초 진단 bc48adc364는 실제 canonical vision store에 영향을 주지 않아 통과했으므로 RED 증거가 아님. canonical import로 바로잡은 693dae79b4에서 publish20/20초→status23초를 주면 같은 raw_available=False가 원격 재현됨. 수정 c17d0fa8ce는 신선한 짝을 검사하는 API 시험에서 canonical store의 모듈-local clock만 20초로 고정함. 실제 TTL·pairing·rate 로직은 변경하지 않음. API 파일 전체와 explicit-clock frame-pair/만료 시험 파일의 원격 GREEN exit0. 로그 `vision-preview-clock-red-canonical/run-1.txt`, `vision-preview-clock-green/run-1.txt`. main 1051105cc0와 합친 최종 후보 `6bd36ff69`는 foundation index/log, gateway index/log 및 해당 시험 3줄만 net 변경. 독립 최종 검토와 새 영향 시험 대기 중.

- commit `6bd36ff69ed212b3171bf4932377e806bb04304d` 실제 최종 차이의 독립 검토 완료: 새 결함 없음, production clock·TTL·pairing·rate 변경 없음, 로그가 canonical RED만 증거로 인용함을 확인. 광범위 영향 시험은 아직 미실행. reporter의 존재하지 않는 nodeid 문제는 별도로 남으며 수동 main 통과로 이 문제를 면제하지 않음.
- `host-uv` 최신 main 통합에서 ADR Log의 D-798 Proposed/Accepted 중복이 lint에 검출됨. main의 Accepted(사용자 결정) 행을 보존하고 오래된 Proposed 행만 제거한 commit `ebd2da63815cdef035125576823ab7ade3476a44`로 재실행 중. 선행 247 passed, 영향 시험 대기. 기준·권한·ADR 번호를 바꾸지 않았음.
- `wt-map-lap-9c7d70`: 8커밋 safety/size 통과와 별개로 미완성임을 독립 검토 확인. 새 시험은 CommandManager.note_published/published_bounds/invalidate_published를 요구하지만 운영 소스에 구현과 최종 wheels_sent history hook이 없음. sweep 수학·일부 시험은 main과 같으나 관측 generation/window lifecycle은 고유하고, main의 D-740 moving-arc admission/retry 경로와 서로 달라 어느 한쪽으로 덮으면 기능을 잃음. 새 writer-history 구현·최종 평가 결합과 검증 전 원본 보존·미머지. Gazebo·실물은 미실행, Safety-Review 무결함 증명으로 취급하지 않음.
- `device-trial` 원본 9a6cebce3c가 camera-evidence dc18ae0e8e의 조상임을 확인. 따라서 source/identity·프로필 변경은 후속 카메라 준비와 연결해 재조정해야 하며 단독 크기 통과만으로 활성화 수용을 주장하지 않는다.

- host 무결성 guard 보정 commit `461720248864c55c20ff725c5e0dac8485aa23b3`: secret guard 및 host-state 파일 집중 원격 GREEN. 최종 독립 소스 검토도 새 결함 없음. 이후 실제 도구 전환 전제를 읽기 전용 SSH로 확인하니 model uv0.12.22, site uv0.12.24, AI uv 없음이었다. 새 remote pytest/sim은 uv가 없으면 새 환경 생성에 실패하므로 이 후보는 착지 보류. 어떤 호스트에도 설치/설정 적용하지 않았음. 보류 기록 `0462b02d5`를 커밋하고 실행 중 land를 중단했으며 원본/수정은 branch에 보존했다. main에 4617202488이 들어가지 않았음을 확인함.
- 중단한 host land의 원격 작업은 AI PC의 land-1-528879에서 정상 종료(exit0)돼 있었다. HEAD가 정확히 4617202488임을 확인하고 기존 remote_job helper로 로그를 회수함: **664 passed / NEW·known·flaky0**. 기록 `%TEMP%/rosy-worktree-reconcile/host-uv-interrupted-job-recovered.txt`. 이는 수정 소스의 회귀 통과이며 AI PC의 uv 설치나 새 설치기 실제 동작을 검증한 결과는 아님. 완료 rc0·죽은 job PID·잠금 부재와 절대 run 경계를 확인한 뒤 기존 remote cleanup helper로 이 작업의 test worktree/job만 정리 완료. 다른 작업·venv는 손대지 않음.
- SIM teacher 최신 후보 bef5c7171f774b7a0aaf9ee88c350376a8cda69f의 선행 247 passed. 전체 영향(root test 포함) 실행 중이며 성공 착지는 아직 주장하지 않음.

- 추가 전체 이력 크기 검사: `cal-pr` 33/33, `wt-rules` 37/37 통과. `d769-learned-follow`와 `pinky-lap-goal`은 각각 435/453개 중 21번째 commit `f11dbe7347e657e0dc5fade22ed54463c09ff507`에서 tools/sim/fleet_trips.py 612줄이 상한600을 넘어 거절되었다. 뒤 이력 전체를 검사했다고 주장하지 않으며 원본을 보존한다.
- `wt-rules` 독립 검토: 직접 목적 D-790 및 4개 후속 수정은 main과 동일/patch-equivalent다. 그러나 수입된 과거 이력의 Accepted D-777(303d7d66de), tools/jira_refs.py·전용 시험·Atlassian 가이드(1d99d960fc)는 main에 없다. main은 D-777을 여전히 예약 중으로 기록한다. 따라서 전체 충돌을 main으로 덮어 이력만 머지하면 고유 의도가 사라진다. 별도 소유 토픽 확인·복구 전 보존·보류한다. 37커밋 크기 통과는 실행 검증을 뜻하지 않는다.
- `cal-pr` 독립 계약 검토: 측정 calibration 목적의 protocol/Fleet/store/routes/overhead bundle/시험/fixture/D-775는 main과 byte-identical하고 main은 비동기 상태 조회 중 승인 잠금 등을 강화했다. 권한은 preview-only이며 주행·CORE 승인으로 확장하지 않는다. 하지만 전체 이력에는 main에 없는 구조/Jira 도구 등 24경로가 있어 전체 브랜치의 중복은 입증되지 않았다. 고유 이력의 별도 소유·보존 여부를 확인하기 전 보류한다. 실제 캘리브레이션·실물·관련 없는 전체 이력 시험은 하지 않았다.
- SIM teacher 착지 완료: commit `bef5c7171f774b7a0aaf9ee88c350376a8cda69f`. 선행 247 passed, 영향 8529 passed / 1090 skipped / NEW·known·flaky0, 1라운드. 로그 `rosy-land/feat-omx-sim-reach-teacher/{run-g1-1.txt,run-1-1.txt}`. 원본 이력과 수정 모두 main에 보존했다. 선택된 skip을 실행한 것으로 주장하지 않으며 Gazebo·학습·실물 수용은 별도다. 정리는 현재 gateway의 유예 판정을 따른다.
- 01:49 KST `wt-auth-route-split` 1시간 유예 완료. 미리보기에서 이 항목 하나만 clean+merged로 선택됨을 확인하고 절대 경로 경계를 검사한 뒤 gateway prune으로 워크트리·브랜치를 삭제했다. 경로/ref 부재와 10117da286의 main 조상 관계 재확인. 정리 완료7개.
- `work-approval`도 1시간 유예 후 미리보기에서 단독 선택됐으나 실행 직전 다른 세션이 먼저 정리했다. 이후 우리 gateway 실행은 removed0이었고 직접 삭제 성과로 세지 않는다. 경로/ref 부재 및 f1df503625의 main 조상 관계를 고정 경로로 재확인했다. 정리 완료8개(직접4/타 세션4). fleet-prune의 앞 두 영향 묶음은 각각 10411 passed / 534 skipped, 3967 passed / 113 skipped로 통과했고 마지막 묶음 실행 중이다.
- `wt-omx-sim-9a5dea`도 동료 세션 정리 후 경로/ref 부재 및 d59eda92f1의 main 조상 관계 확인. 정리 완료9개(직접4/타 세션5). 소스 이력 손실 없이 보존됨을 확인했다.
- `device-power-port`는 1시간 유예 후 단독 PLAN을 확인하고 절대 경로 경계를 검사한 뒤 gateway로 직접 정리했다. 경로/ref 부재와 1051105cc0의 main 조상 관계 확인. 정리 완료10개(직접5/타 세션5). 전원 정책은 main의 기존 disabled 상태이며 실제 장치 전원 동작은 실행하지 않았다.
- fleet-prune 최종 재실행 1라운드는 선행247 및 영향 10411/3967/5523 passed, skipped534/113/317, NEW·known·flaky0으로 모두 통과했다. 하지만 동료 boot-image-sync-reconcile 착지로 main이 ac462fbda3으로 움직여 자동 재통합·재검증한다. 새 후보573153bc50c85d40c1cd22207e83fa52ef50dbbb. 첫 라운드 통과를 새 통합 커밋의 완료 증거로 대신하지 않는다.
- 중단 후 기존 land 세션21125를 그대로 이어받았다. 2라운드도 선행247 및 영향10411/3967/5523 passed, skipped534/113/317, NEW·known·flaky0 통과. 동료 세션의 추가 main 변경48fdd711ae로 3라운드 자동 진입, 후보5b667bf43a66993e6cc38f025c31ba8cac33c771. 중복 원격 작업을 새로 띄우거나 시험을 생략하지 않았다.
- `sim-teacher`는 1시간 유예 후 단독 PLAN을 확인하고 절대 경로 경계를 검사한 뒤 gateway로 직접 정리했다. 경로/ref 부재 및 bef5c7171f의 main 조상 관계 재확인. 착지·정리 모두11개 완료(직접6/타 세션5). 남은 실행 항목은 fleet-prune 한 개다.
- fleet-prune 3라운드도 선행247·영향10411/3967/5523 passed, skipped534/113/317, NEW·known·flaky0 통과했다. 완료 직전 동료 main이7b11775712로 이동해4라운드 자동 진입. 실패를 묵인하거나 main 갱신을 막는 잠금을 임의로 설치하지 않으며, 도구의 최대5라운드 제한을 유지한다.
- fleet-prune 4라운드76eb82ad164737bb84fafd0ca0d747964985ba75도 선행247·영향10411/3967/5523 passed, skipped534/113/317, NEW·known·flaky0 통과. main은3910527e97→84752d3a95→4b2d428d41로 계속 움직여5라운드 진입했다. 이 후보의 마지막 자동 라운드이며, 반복 원인은 시험 실패가 아니라 검증 도중의 동료 main 착지다.
- fleet-prune 5라운드 commit `ae52e13d94ac737556ded28471aef971cf430e57`도 선행247 passed, 영향10411/3967/5523 passed, skipped534/113/317, NEW·known·flaky0. 로그 `rosy-land/refactor-schemas-ratchet-offset/{run-g5-1.txt,run-5-1.txt,run-5-2.txt,run-5-3.txt}`. 하지만 main이3c9254a526으로 다시 움직여 land 세션21125가 exit1, `[land] STOP: main kept moving: gave up after 5 rounds`로 종료했다. 마지막 커밋을 최신 main과 검증·착지한 것으로 주장하지 않는다. main의 동시 착지가 잦아든 뒤 새 관문 실행이 필요한 상태다.
- **최종 확인 03:21 KST:** 완료11개 전부 워크트리/브랜치 부재, 착지 SHA의 main 조상 관계, 착지 기록 및 연결된 시험 로그 존재 확인. 보존20개 전부 이름 있는 브랜치와 깨끗한 워크트리로 존재한다. fleet-prune 원본aab3173d91과 host-uv 원본f2b4af96d2의 보존 조상 관계 확인. main commit `3c9254a52676cfcafaaa764c8eabcae5efa9692b`, 기존 미추적 aff1.log 보존. gateway prune 미리보기 제거 가능0개/전체59개이므로 추가 삭제 없음. 동료 생성·정리가 병행됐으므로 전체 수 차이를 이번 세션 정리 성과로 세지 않는다. 푸시·Gazebo/학습/실물 수용·호스트 설치는 실행하지 않았다.
