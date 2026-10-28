# 명시적 FULL 착지 검증 — 소스 근거

2026-10-27. 승인된 explicit-full v3와 후속 addendum의 Task 1/2 소스 준비 기록이다. 작업자는 공식 FULL·착지·push·게시·장치 작업을 실행하지 않았다.

## 고정 소스와 검토

기준은 로컬 commit d57cf1b8f04625382d1ebf76ba2b597cbff13411이다. 독립 architecture·critic 검토가 승인한 source tree ef757dad189b3ae62d4d7011e70f21e283de44b5를 로컬 commit 54f831693da631f4cbe67d5127c7203939f75a14로 기록했다. staged 변경 때문에 Git이 처음 main 병합을 거절했을 때 그대로 보존했으며 reset·stash·history rewrite를 쓰지 않았다.

이후 main commit c2e21981ecee89285647ce2a392aaac76eeee6f3의 Monitoring launcher 15개 경로를 정상 병합했다. source 7개·시험 4개가 승인 소스와 같고 incoming 15개가 main과 같다는 독립 통합 검토 tree 09379a4fe60d88769cad68a9137d17382fc9371d를 로컬 commit 259605fb2cd804db676a478730278dd1d002163a로 기록했다. 뒤의 fixture-only commit 031a640c37·b36e441576에도 생산 소스 7개는 그대로다. 제품 API/ROS IDL·dependency·receipt schema·안전 권한·한도 완화는 없다. concern:other 변경에 Safety 승인을 꾸며 붙이지 않았다.

`full`은 현재 candidate의 fresh subprocess에서 정본 normal FULL과 등록된 ALL browser/chunk/ALONE을 만든다. 프로세스마다 정상 준비를 하고, guard/isolation은 fresh no-cache, 본시험은 기존 exact clean cache만 사용한다. 같은 실행에서 확인한 candidate/main·필수 argv·환경 witness로 기존 main-delta 흐름을 잇는다. bridge가 유효하지 않거나 현재 필수 계획·환경이 맞지 않으면 재준비한다. 재시작은 다시 준비하며, `--no-cache`도 한 번의 준비 뒤 정상 진행한다. `full --no-queue`는 FF/기록 전에 거절한다.

prepare와 turn의 두 save 모두 guarded+tested의 LOAD-FLAKY/NARROW를 확인한다. auto는 기존 허용 착지·cache·성능 bridge를 유지하되 tier=None으로 이전 적격성을 덮어쓰므로 게시 기록을 만들 수 없다. explicit full은 save/FF 전에 멈춘다. isolation 최초·retry는 explicit full에서 과거 cache report를 읽지 않는다. 현재 report 누락·죽은 job·NEW·Safety 미도달은 중단하고, 기존에 허용된 nonSafety 예산 초과는 기록·보고한다. 모든 isolation을 끝냈다고 일반화하지 않는다.

기존 pure pack은 land_selection으로 옮기고 land.pack wrapper를 유지했다. AST가 원본과 같으며 basename 충돌·순서·Path 처리 알고리즘을 바꾸지 않았다. land.py 544줄, helper 152줄로 gateway는 600줄 한도의 95% 미만이다. 1464줄 test_land.py를 늘리지 않고 기존 작은 owner에서 그 fixture를 재사용했다.

## 원격 RED와 fixture 보완

아래 실행들은 서로 다른 SHA와 중첩 범위이므로 합산하지 않는다. 모든 raw를 known classifier에 넘겼고 기존 unrelated theme browser ID 1개는 listed-but-not-failing으로 남았다. quiet 출력의 수치는 `%`로 끝나는 pytest progress 행에서 센 값이며 traceback의 E 표지는 세지 않았다.

| 단계 / 로컬 commit | 실제 결과와 분류 | 외부 증거 폴더 |
|---|---|---|
| 247ee97229 초기 RED | 196P/34F, NEW34. executor GREEN tuple을 문자열로 쓴 fixture TypeError 23건은 기능 RED에서 제외 | red |
| 2b4baf2c88 보완 RED | 197P/33F, NEW33. 미지원 full·eligibility·JSON·guard 반례. missing receipt 3건은 None 구독 대신 명시 assertion으로 보완 | red-fixture-corrected |
| 90bc6573f7 잘못된 -k | 전부 deselect. outer0/known0이어도 통과 근거가 아님 | red-contract-controls |
| 90bc6573f7 정확한 nodeid | 실제 contract assertion 4F/NEW4, setup·Type/Name/Attribute 오류 없음 | red-contract-nodeids |
| b5d4e887ef isolation 첫 입력 | fixture의 추가 Git commit identity 누락 4F. 기능 RED에서 제외 | red-isolation-current-report |
| e4e9bb4bd2 실제 stale-cache RED | 1F/3P, NEW1. 보이는 실제 cache entry의 old candidate/tree·다른 env·same argv complete가 현재 report 누락을 가림 | red-isolation-real-cache |

마지막 RED는 full에서만 재시도 후 중단을 요구했다. fresh complete와 기존 auto fallback은 positive로 남겼다. 새 production 수정은 이 RED 뒤에만 반영했다. 기존 G2 SourceRoot 6NEW의 원인·해결이나 부하 귀속을 이 작업으로 주장하지 않으며 G2 소스·시험·timeout·quarantine을 바꾸지 않았다.

## 집중 GREEN

| 소스 / 범위 | 실제 결과 | 판정 |
|---|---|---|
| 259605fb2c selector·소유권 5파일 | 299P/0S | official/outer/known 모두0, NEW0/known0/flaky0 |
| 259605fb2c 도구 8파일 첫 실행 | 224P/10F | NEW10. fake 성공 출력에 시간이 없어 실제 browser vacuity guard가 올바르게 거절 |
| 031a640c37 도구 8파일 | 232P/2F | NEW2. synthetic repo의 pycache ignore 누락과 빈 delta라 실행되지 않은 turn-guard 입력을 보완 |
| b36e441576 해당 두 nodeid | 2P/0S | 모두0, NEW0. 뒤의 묶음과 중첩 |
| b36e441576 최종 도구 8파일 | 234P/0S | official/outer/known 모두0, NEW0/known0/flaky0 |

도구 범위는 test_land_selection·test_land·test_land_browser·test_land_record·test_publish_main·test_land_isolation·test_land_queue·test_land_events이다. selector·소유권 범위는 test_affected_tests·test_browser_scope·test_harness_contracts·architecture/test_safety_separation·architecture/test_platform_parts이다. 299P는 생산 소스가 같은 앞선 통합 SHA의 범위이며 b36에서 새로 실행했다고 쓰지 않는다. 새 source의 전체 FULL이나 실제 Chromium opt-in 실행이 아니다. browser 선택·chunk·vacuity·queue·writer는 test-PC의 fixture 경로에서 검증했다.

모든 새 원격 작업은 qualified-labs wrapper가 직전에 lab disk 30GiB 이상·90% 미만을 확인한 뒤 공식 runner의 committed `--sha`로 실행했다. laptop pytest·site fallback·직접 SSH pytest는 쓰지 않았다. 원시 출력·각 known 판정·outer/child exit와 hash는 `%LOCALAPPDATA%/Temp/rosy-land-explicit-full/`의 각 폴더와 summary에서 보존한다. 앞선 실패·빈 실행을 최종 GREEN에 덮어쓰지 않았다.

기존 fixture는 partial/full 준비 기록에서 browser·ALONE을 뺀 입력, main registry·ALONE·환경 변경, 실제 HEAD 이동·missing/wrong-candidate receipt, LOAD-FLAKY/NARROW 두 writer, 현재 report 누락과 과거 cache 반례를 검증한다. 새 mutation framework나 bad product commit·추가 슬롯은 만들지 않았다. 단순한 tier 문자열을 근거로 적격성을 복구하지 않는다.

## 남은 단계와 교훈

최종 문서 커밋 뒤 전체 D766 범위·generate/lint/diff·공식 dry-run·clean 상태를 확인해 외부 handoff에 결속한다. 여기서 그 최종 검사를 이미 완료했다고 주장하지 않는다. 최종 source 보호 비교와 실제 main 변동은 Root 인계 근거에서 확인한다. 공식 FULL·착지·공개 CI·게시 SHA의 모든 요청 기능 포함·산출물·현장 수용은 별도 단계다.

CE: 기존 교훈 갱신. Root가 검증된 eligibility/report 손실을 기존 land-record 교훈에, UTF-8 예외 뒤 부분 worktree 생성 복구를 기존 Windows 교훈에 반영했다. 독립 delta 검토 후 같은 문서 인계에 포함한다. 이 단위의 재발 방지 코드는 실제 RED/GREEN을 거친 두 save의 적격성 처리와 fresh-only isolation report 경로다.
