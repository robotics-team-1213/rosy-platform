# D-637 남은 플랫폼 폴더 실행 결과

2026-10-11, 브랜치 `refactor/remaining-platform-folders`. [실행 계획](../../plans/2026-10-11-remaining-platform-folders.md), [현행 폴더 책임표](../../reference/platform-folder-responsibilities.md), [이전표](moves.json)를 대조한다.

## 실제 이동과 순서

source·caller·fixture·config·export·설치 입력을 먼저 커밋하고 local main `13b125b746`에 fast-forward했다. 동시에 들어온 traffic-view 시험의 lookup을 `d4988bffba`에서 수정하고 원격 시험·Node 검증 후 다시 fast-forward했다. 이 SHA는 source 착지 snapshot이며 다른 세션이 main을 계속 갱신할 수 있다. 설명은 그 이후 별도 `500c5f94c`로 커밋하고 경계 목록 보완 `ff337deb8`과 함께 원격 검증한 `33729c5140`으로 local main에 반영했다. push·배포·운용 활성화는 수행하지 않았다.

| 범위 | 실제 결과 |
|---|---|
| Decision | 10파일 → `operations/decision/src/rosy/decision`, import `rosy.decision`. 기존 Fleet 배포·transaction/store/provider 유지, `fleet.ai` shim 없음 |
| Console | 기존66 + 동시 추가 inbox1 = 67파일 → `operations/ui/console`. 65개 설치 자산, AGENTS/package.json은 개발 입력. 같은 Fleet 배포·URL·allowlist·CSP·installed `fleet.server.web` 유지 |
| Learning | 214개 기존 파일을 한 번씩 curation/registry/training/evaluation/tools/shared test로 배치. store는 datasets/evalsets/inbox/model 공용 artifact·provenance를 관리 |
| 지원 | JPEG relay → Gazebo scripts (동일 설치 이름·destination·실행 mode); review smoke → curation tools |
| 퇴역 도구 | WSL6파일 → `docs/reference/legacy-tools/wsl`, byte 보존·현재 운영 경로에 재연결하지 않음 |
| 전체 재고 | 299 source/target 고유 쌍, targets 전부 tracked. 현재 manifest89 root와 책임표89행 대응 |

`data/drive/.gitkeep`는 기존 기록 계약 placeholder다. ignored cache·동료 `.omc` 상태·main의 미추적 메모/lock 파일을 삭제하지 않았다. Gazebo launch/scripts는 실제 `gz_sim` install owner이므로 유지한다. 별도 배포 carve 보류는 누락된 폴더 이동이 아니다. 현재 World state와 미래 action-conditioned prediction을 분리했고 빈 미래 holder를 만들지 않았다.

## 검증과 실패 수정

| 커밋/단계 | terminal 결과와 판정 |
|---|---|
| `b641e1378` 초기 큰 회귀 | 148 NEW. lazy dataset imports·source closure·guard metadata·fixture/docs path 문제. known_failures에 추가하지 않았고 착지하지 않았다 |
| `67336ba2b` 이후 수정 | registry↔curation lazy import, exact bootstrap, retained release/서명·dirty guard, functional owner·size 판정·inherited dependency와 원래 corpus 계약을 수정/보존 |
| `10d7dbd2a` 큰 회귀1 | 4214 passed,181 skipped,62 subtests; 0 NEW |
| `10d7dbd2a` 큰 회귀2 | 7217 passed,634 skipped,1 failed. 마지막 실패는 runbook 시험의 옛 CLI lookup이며 `9b6324c48`에서 수정. learning99 suite·Fleet·Safety·signed closure·설치 시험은 통과 |
| `10d7dbd2a` sensing | 34 passed; 0 NEW |
| `13b125b746` 수정 gate | runbook·installed wheel/sdist·harness·module structure·platform parts·functional surface 원격 terminal exit0, known_failures0 NEW, lint 통과 후 local main FF |
| `d4988bffba` 최종 source gate | 원격 Fleet document imports/host control24 passed,0 NEW; Console Node45파일·290 tests passed,0 failed; lint와 local main FF 완료 |

큰 회귀는 source failure를 고친 증거다. 마지막 좁은 gate는 실제 fixture와 동시 변경의 설치·Node 소비를 다시 검증한 결과이며 전체 CI FULL 성공을 뜻하지 않는다.

`test/test_remaining_platform_installed.py`는 source checkout 밖 wheel·self-contained sdist에서 namespace import와 동일 계약 객체, 65자산 hash, 허용 HTTP 자산200·CSP·없는 파일/경로 탈출404를 확인했다. 브라우저 렌더/클릭 수용 시험과 구분한다. source-loader 고립 검사는 Python `-I`로 curation/registry 상호 소비를 확인한다.

## 독립 리뷰와 보존 경계

[Safety·학습 독립 리뷰](independent-safety-learning-source-review.md), [Decision·Console 독립 리뷰](decision-console-independent-source-audit.md)를 적용했다. CORE 단일 final Base writer, OMX Arm Action owner, Fleet 원장/admission/dispatch, proposal/tool catalog, CSP와 API/wire contract를 유지했다. Native review release의 canonical/retained source token 변경은 관리 unit 필드만 바꾸며 state·release metadata·DB bytes와 rollback을 보존한다. 옛 job의 source signature가 맞지 않으면 쓰기 전에 거절한다.

Ralph는 PRD6개 story·progress·독립 리뷰·terminal 증거로 운영했다. native OMC loop hook은 사용할 수 없어 실행했다고 주장하지 않는다. 세션 상세 로그는 `X:/DevTemp/projects/rosy-platform/2026-10-11--144205--remaining-platform-folders--4d3bb9/`에 있다. `logs/land-source-final`, `logs/land-source-fixture`, `logs/land-source-node`와 `evidence/final-299-moves.json`을 보존했다.

## 남는 검증 경계

폴더·source·호스트 설치 증거만 완료다. SOURCE/LOCAL GO는 해당 범위이며 ROS-SIM·ARM64 ARTIFACT·DEVICE·FIELD는 HOLD다. selection은 harness/setup/conftest/workflow 변경으로 FULL이므로 GitHub CI FULL 증거가 남는다. Chromium 옵트인은 실행하지 않아 skip을 수용으로 집계하지 않는다. Jazzy/ARM64 image·sim·모델 활성화·실물 주행·현장 수용을 실행하지 않았다. World 미래 행동 예측과 후속 Decision 모델 파이프라인은 계획이며 현재 기능으로 표시하지 않는다.


## 설명·계획 최종 확정

설명 첫 후보 `9602e1493`의 원격 gate는 1 NEW로 중단했다. shared learning corpus 이동으로 ROOT/test 검색 대상에 들어온 기존 8개 artifact/runtime integration 시험이었다. 원본 import 12개의 module·level·symbol·alias가 모두 같음을 독립 검토했고, 정확한 8경로와 유지 이유만 frozen metadata에 등록했다. `_IMPORT`, `_found`와 검색 root, 기존 set equality·known_failures는 바꾸지 않았다. 보충 [독립 검토](closing-review.md)를 적용했다.

`33729c5140` 원격 최종 gate는 **537 passed/20 skipped, terminal exit0, known_failures0 NEW**로 끝났고 harness lint0 errors 뒤 local main에 fast-forward했다. architecture·harness·functional ownership·scorecard·문서/provenance·installed wheel/sdist·CLI와 8개 integration 시험을 포함한다. 새 설명 gate에서 Node는 Fleet web을 선택하지 않아 skip했으므로 기존 source Node290 receipt와 분리한다. 독립 terminal readback과 source→설명 ancestor 확인은 `evidence/description-closure.json`에 기록했다.

채택한 폴더 단계1–7와 PRD6개 story의 소스/설명 범위는 완료다. 이 확정 기록 자체도 별도 docs commit의 원격 가드·local main 반영을 거친다. 최신 shared main은 다른 세션에 의해 계속 움직일 수 있으므로 위 SHA는 확인한 착지 snapshot이다. 기존 untracked lock·메모3개와 동료 변경을 그대로 보존했다.
