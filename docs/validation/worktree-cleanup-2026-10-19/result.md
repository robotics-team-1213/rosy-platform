# ROSY 워크트리 추가 정리 — 2026-10-19

이전 처리 기록: `worktree-cleanup-plan-2026-10-18.md`(커밋·로컬 main 머지·워크트리 정리11개 완료).

## 현재 결과

- 후속 “나머지도 처리해” 요청으로 비활동·청결 대상9개 폴더를 더 정리했다. 기존23개와 합쳐 본 후속 기록의 제거 확인은32개이며, 새9개의 원본 브랜치와 검증된 복구본은 보존했다. [별도9개 대상·복원·잔여 보호 사유](../worktree-retirement-2026-10-19/remaining.md). 아래23개 내역은 앞선 요청의 결과를 보존한 기록이다.

- 이번 요청에서 작업 폴더23개를 추가 제거했다: 사용자가 선택한 보관 대상19개, 이 세션에서 착지한 fleet-prune·stuck-jpeg-api2개, 동료의 착지가 끝나 정리 조건을 충족한 account-revoke-regression·host-uv2개. 원본 브랜치23개와 정확한 tip SHA는 보존했으며 별도 bundle로도 확인했다. 보관 대상19개의 상세·복구 경로는 worktree-retirement-manifest-2026-10-19.md에 있다.
- 정상 후보2개 모두 로컬 main 착지 완료: fleet-prune9acdf6685c195b2f6dc5d0dbfd132b5651510b3a(선행247·영향19998 passed), stuck-jpeg-api773b543f12fe4d04d2c0443f726d35cca091e43b(선행247·영향4082 passed, 실제 브라우저45 포함). NEW·known·flaky는 모두0. 두 폴더는 각각 1시간 유예 종료 후 judge(full=True)의 removable·dirty0·비캐시 ignored0·잠금 없음과 정확한 SHA·main 조상 관계를 다시 확인하고 native worktree remove로 폴더만 제거했다. 브랜치는 보존했다. 두 작업의 대기열도 종료됐다.
- 추적된 커밋의 보존은 검증됐다. 제거 전 ignored 파일 검사에는 누락이 있었으며 ignored 자료는 bundle 보존 범위에 없다는 한계를 기록했다. 남은 dirty·locked·현재 활동·stale-history는 건드리지 않았다.

## 재조사와 실행 순서

### 최종 추가 정리 확인

- 2026-10-19 06:08 KST 이후 fleet-prune·stuck-jpeg-api 두 폴더 모두 제거·Git 등록 해제와 원본 브랜치 보존을 확인했다. 본 세션의 착지는 위 2개이며 푸시하지 않았다.
- 마지막 재조사에서 동료의 착지가 완료된 account-revoke-regression(fix/account-revoke-restart-regression, commit 06d025f548f15f347d1ce121aa423077d8ca9047)과 host-uv(feat/host-uv, a717d9f3235f457bd1463255dbbb4d5f8afcc6f7)도 정리 가능했다. 두 대상 모두 full 상태 검사·main 조상 관계·착지 기록·정확한 백업 ref를 확인했다. 기본 소유자/유예 판정을 유지했고 대기열·진행 중 작업 표시를 다시 확인한 뒤 폴더만 제거했다. 동료의 커밋이나 시험을 본 세션의 구현·검증으로 계산하지 않는다.
- 추가 복구본: D:/Dev/Robot/worktree-backups/2026-10-19/landed-peer-cleanup-2109.bundle(150879 bytes, SHA256 804af716493d4f22f22a11d540ccee5809851a06598efd4deaaadeafe165e688). 두 원본 ref/SHA, git bundle verify, 전체 PACK checksum 확인. 다른 보관 bundle과 같이 기존 main 객체가 필요한 증분 복구본이다.
- 기존 main의 미추적 aff1.log를 그대로 보존했다. 보류19개 외 나머지4개는 제거 직전에 비캐시 ignored0을 실제 확인했다. 호스트 설치·설정 적용·실물 동작은 수행하지 않았다.
- 최종 전수 확인: 대상23개 폴더 모두 없음·Git 등록 해제, 원본23개 브랜치 tip 일치. 착지한4개는 main 조상·각 SHA의 착지 기록 일치. bundle4개 모두 verify·PACK checksum 통과. 남은 판정은 active28·locked10·stale-history2·landed-dirty1이며 자동 정리 조건을 충족하는 추가 대상은0개였다(동료 작업에 따라 이후 달라질 수 있음).

- 현황 재조사:59개. 기존 main 미추적 aff1.log는 보존한다. 잠금·dirty·stale-history·최근 활동을 자동 정리하지 않는다. 삭제는 현재 gateway의 손실 없는 정리 판정을 따른다.
- 최신 main에 D-803 착지 대기열과 FULL 검증 이어받기 절차가 들어왔다. 지난번의 동시 main 변경 문제를 새 대기열을 통해 처리한다. 큐 우회·FULL 면제·pytest 로컬 실행·푸시·호스트 설치·장치 동작은 하지 않는다.
- `fleet-prune`: 이전 최종 HEAD commit ae52e13d94ac737556ded28471aef971cf430e57, 깨끗함·원본 이력 보존 확인. 기존 land 세션은 종료됐고 현재 큐에 동일 브랜치가 없음을 확인한 뒤 최신 main의 land.py로 재요청했다. 세션90817, ticket01792348202756988200-14788.json, 최초 순번7. 앞선 동료 착지를 기다리는 중이다. 안전·크기 사전 검사는 통과했다.
- `stuck-jpeg-api`: docs/stuck-evidence-jpeg-api, 원본 commit bfe4e1f6013546b6fb8ff93da9479b0a3ffe4760. 독립 계약 검토에서 기존 JPEG 응답 구현·소비자·시험은 main에 있고 API 문서 계약만 빠졌음을 확인했다. 문서와 버전 pin 변경은 유효하며 main 전체로 덮으면 목적을 잃는다. 기존 v1.273 예약 사유가 stuck evidence Accept image/jpeg임을 확인. 현재 main에 대한 dry-run은 충돌 없음, 영향 시험과 실제 브라우저 시험을 선택했다. 앞선 작업 후 최신 main에 통합·검증할 후보로 둔다.
- `perception-agents-pr`: commit 2298f5bf8cc46a07aab7f7416451e6619325bdcb. 주목적인 CLAUDE→AGENTS 통합은 main6008aed64a 및 실제 파일/소비 시험으로 확인됐다. 그러나 수입 이력에 여전히 main에 없는 Accepted D-777·Jira CLI/시험/가이드가 남아 전체 중복은 아니다. 기존 wt-rules/cal-pr와 같은 이유로 원본을 보존하고 보류한다. 원격 시험·소스 변경은 하지 않았다.
- `host-uv`: 다른 세션이7fbd984e91로 진행했고 실제 착지 대기열에도 참여 중이다. 현재 작업 대상으로 보호하며 원본·수정·큐를 건드리지 않는다. 지난번 AI PC uv 부재 관측은 당시의 보류 근거이며 현재 작업의 결과를 대신하지 않는다.
- `host-report-access`: clean+main ancestor이나 자기 커밋이 없는 체크아웃으로 현재 도구가72시간 유예를 적용한다. 현재 약4시간이므로 강제 정리하지 않는다.

## 검증과 정리 기록

진행 결과는 이 절에 커밋·시험·착지·삭제를 구분해 추가한다.

- `size-ratchet` 재검토: b8fdf1725c23ed682a3518ab99042fef3e6d82a7의 초기 이력은 historical ratchet_problems가7인자인데 현재 range checker가8인자를 넘겨 TypeError가 난다. 그러나 정확한7인자 과거 규칙과 git tree를 읽기 전용으로 적용하면 첫 거절 bf8f8ef961에서 fleet31902→31942, app981→982, trip_runner898→901의 실제 down-only 위반이 확인된다. 후속 eccf666f07의 상한 인상은 과거 위반을 해소하지 않는다. 검사기 호환만 고쳐 착지할 수 있는 후보가 아니므로 소스·규칙·이력을 바꾸지 않고 보존했다. pytest 및 첫 거절 뒤 전체 이력 검사는 하지 않았다.
- `stuck-jpeg-api` 준비: 최신 main 자동 병합은 충돌이 없었고 net 변경은 원래7경로와 모듈 로그·생성 index4경로뿐이다. 명시적4파일 stage 후 net11경로 일치·whitespace 검사·unstaged 없음 확인. 원래 API v1.273 목적과 현재 main 내용을 보존했다. 실제 원격 영향·브라우저 검증은 아직 대기다.
- 준비 커밋 f598a4b32af35caf1f466090a55ca36bc47d28c2의 실제 net11경로를 독립 재검토했고 새 결함 없음. 로그는 시험 대기를 명시하며 원래7경로를 임의로 바꾸지 않았음을 확인했다.
- 별도 보관 정리 제안: 미머지이지만 청결·비잠금·착지 큐 미참여인19개를 worktree-retirement-manifest-2026-10-19.md에 정확한 ref/SHA로 확정했다. 2.5MB 증분 bundle을 만들고 별도 bare 저장소에서19개 ref 복원과 실제 객체 연결을 검증했다. 원본 브랜치를 보존하고 작업 폴더만 제거하는 범위는 사용자 선택을 기다리며 아직 삭제하지 않았다. 원본 commit-graph 캐시의 무관한 누락 문제와 캐시 없이 검사한 복원 데이터의 누락0개 결과도 함께 기록했다.
- 사용자가 “브랜치·복구본을 남기고 폴더만 제거”를 선택했다. 위19개를 canonical 상태 검사와 각 경로/SHA/브랜치/청결/잠금/git 연산/착지 큐 검사 후 네 묶음으로 하나씩 제거했다. 전부 네이티브 git worktree remove가 force 없이 성공했고, 삭제 직후와 최종 검사에서 원본 브랜치/SHA가 그대로이며 작업 경로만 사라졌음을 확인했다. bundle 유효성과 별도 복원 ref19개도 재확인했다. 기존 보류 변경은 main에 억지로 합치지 않았다.
- 사전 검사 정정: canonical scan만으로는 ignored 내용을 읽지 않는다. 19개 제거 전 native status로 tracked/일반 untracked 청결은 검사했지만 ignored 자료 검사는 완결되지 않았다. 커밋·원본 브랜치·bundle19개 일치 보존은 검증됐으며, ignored 자료는 bundle 보존 범위에 들어 있지 않다. 원래 기록 중 비캐시 ignored를 검사했다는 문구는 정정한다. 이후 남은 작업의 집계는 judge(full=True)로 다시 확인한다.
- 임시 폴더 외의 보관본 D:/Dev/Robot/worktree-backups/2026-10-19/held-branches-183823.bundle도 만들었다.19개 ref/SHA 일치와 git bundle verify, 별도 검증 저장소에서 실제 unbundle 및 pack 전체 checksum까지 확인했다. 원본 Git 저장소와 main 객체를 유지하는 조건의 증분 복구본이다.
- 착지 대기 재개 정보: fleet-prune native 세션90817/PID14788, ticket01792348202756988200-14788.json; stuck-jpeg-api native 세션65953/PID21276, ticket01792348890990592500-21276.json. 두 후보 모두 사전 safety/size 검사 통과 후 대기열7번/9번에서 대기 중이다. 앞선 feat/remote-pytest-parallel의 FULL 이후 재검증이 길어 아직 차례가 오지 않았다. 기본180분 대기 제한을 유지한다. 각 시작 시각은18:30:02/18:41:30 UTC이며, 대기 제한 도달 시 각각21:30/21:41 UTC 부근에서 도구가 중단할 수 있다. 다른 세션의 큐·프로세스는 중단하지 않는다.
- 앞선 큐가 진행돼 현재4번/6번이다. host-uv는 동료 세션의 진행 중 항목으로 계속 보호한다. 그 전환이 뒤 검증 환경에 영향을 주므로 AI 시험 PC에서 command-v/기존 표준 경로를 읽기 전용 SSH로 다시 확인했고 UV_MISSING이었다. host-uv a717d9f323의 실제 remote_pytest/remote_sim은 새 환경 생성 시 uv를 요구하고, 보류 기록0462b02d5 이후 해당 runner 변경은 없었다. 설치·설정 적용은 하지 않았으며, 우리 후보는 실제 관문 결과로 판정한다. 기존 venv에서 시험이 통과해도 새 환경 생성 준비를 증명하는 것으로 쓰지 않는다.
- fleet-prune 착지 완료:commit 9acdf6685c195b2f6dc5d0dbfd132b5651510b3a, base a717d9f3235f457bd1463255dbbb4d5f8afcc6f7, 큐 대기 약75분 후1라운드. 선행247 passed, 영향10432/4018/5548 passed, skipped534/113/317. 로그 rosy-land/refactor-schemas-ratchet-offset/run-g1-1.txt 및 run-1-{1,2,3}.txt. 원본 aab3173d91의 main 조상 관계와 실제5파일 net 변경 범위를 확인했다. 기존 source clock 시험 수정은 유지되며 운영 TTL은 바꾸지 않았다. 원격 pytest 통과를 AI PC uv 설치나 실물 수용으로 주장하지 않는다.
- stuck-jpeg-api 착지 완료:commit 773b543f12fe4d04d2c0443f726d35cca091e43b, base9acdf6685c195b2f6dc5d0dbfd132b5651510b3a, 큐 대기 약86분 후1라운드. 선행247 passed, 일반 영향4037 passed/207 skipped, opt-in 실제 브라우저14/14/13/4 passed(합45, 해당 묶음 skip0). 각 로그의 known_failures 비교 NEW·known·flaky0. 로그 rosy-land/docs-stuck-evidence-jpeg-api/run-g1-1.txt 및 run-1-{1,2,3,4,5}.txt. 원본bfe4e1f601의 보존 조상 관계·착지 기록·실제11경로 net 변경 범위를 확인했다. 새로운 endpoint나 권한을 추가한 구현이 아니라 기존 JPEG 응답 계약 문서화와 version pin 정렬이다.
- 완료된 두 후보의 추가 보관본도 D:/Dev/Robot/worktree-backups/2026-10-19/ 아래에 만들었다: landed-fleet-prune-9acdf6685c.bundle, landed-stuck-jpeg-api-773b543f12.bundle. 각각 정확한 branch/SHA와 git bundle verify·pack 전체 checksum을 확인했다. 현재 full 상태 검사에서 두 폴더 모두 dirty0·비캐시 ignored0이며, 기본1시간 유예가 끝나는20:44:57/21:07:40 UTC 이후 상태를 다시 확인한다. 브랜치를 지우는 전역 prune 대신, 손실 없는 기본 조건이 맞는 해당 폴더만 제거해 사용자가 고른 브랜치 보존 방식을 유지한다.
