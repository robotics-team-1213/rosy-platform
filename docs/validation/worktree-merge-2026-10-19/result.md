# 보관 브랜치 main 통합 — 2026-10-19

## 최신 후속 상태 — 이전 진행 행보다 우선

### 추가 검증·복구 기록

- Station 재실행 FULL의 CORE는 lifespan ordinary-work 미완료와 shutdown_UNDOCKING readback HOLD로 2failed/7230passed/64skipped였다. 안전 root이므로 단순 재실행 성공으로 수용하지 않고 해당 착지를 중단했다. own Station queue PID18212의 identity를 확인해 중단했고,31로그를 station-core-failed-f1388bda88-20261020-011104에 복사·각SHA256 검증했다. 독립 리뷰 후2303ea901f9fd355ea86affc0b1bb76fc3ceb0b4에서 시험 진단만 보강했다(원본 예외 보존·traceback16건 제한, 최신Task/native/async stack). 생산 코드·조건·시간 제한·반복·안전 가드는 변경하지 않았다. 같은 CORE 조합의 원격 진단이 진행 중이다.
- Signed 현재 통합 SHA108399feb6f333fb14d7a3ee10bcf814ce6187a5의 필수 raw3은 pinned-package readiness 후124passed/skip0·exit0·known_failures 비교0이다. 기본 관문249passed도 통과했고 native 전체 회귀가 진행 중이다. Station의 실패를 우회하여 머지한 것은 아니며 Station은 아직 main에 없다.

- 재시작한 Station f1388bda88의 FULL root는 8978passed/1102skipped, 실패0·known_failures 비교0으로 완료됐다. Fleet도5997passed/317skipped였다. 이전 root 실패 로그는 복사본으로 남겨두었으며, 이번 FULL의 나머지 모듈·브라우저 관문은 계속 확인 중이다. 재확인한 기존5bundle은 기록된 SHA256·bundle verify·PACK SHA1 모두 일치했다.

- 2026-10-20 재개 시 이전 native 프로세스3개는 종료됐고 main8d8921ac0e 및 후보 f1388bda88/80f87cd776/d59c8e7636은 그대로였다. Station 부분·실패 로그31파일을 외부 station-interrupted-f1388bda88-20261020-004656에 복사하고 각 SHA256 일치를 확인한 뒤 native 착지 도구를 Station→signed→OMX 순으로 다시 실행했다. 직접 대기열 파일을 삭제하거나 시험 선택·제외 정책을 바꾸지 않았다.

- Station f1388bda88ef32be880c9ebdc929cb750f92b67e의 FULL root는 updater process-group timeout 1failed/8980passed/1099skipped였다. updater와 해당 시험은 현재 main과 동일함을 diff로 확인했다. 같은 커밋에서 test/test_rosy_auto_update_apply.py 전체를 별도 재실행하여 exit0, known_failures 비교0을 확인했다(외부 로그 station-process-group-recheck/run-1.txt). 최초 FULL 실패를 통과로 바꾸지 않으며 native 전체 관문의 최종 결과를 기다린다.

- OMX native24935은 main 통합4b6895d0fe에서 g1249passed, 영향1571passed/27skipped 및 browser3passed였으나 기존 intake fixture의4setup ERROR로 중단됐다. 실패5로그 복사·각SHA256 검증. 같은4b6895d0fe의 별도 actual native는 wrapper5/내부27passed·skip0·exit0이지만 일반 관문 실패를 대신하지 않는다.
- 3b0bc1c617에서 새 helper import의 stub 타입2개와 fixture module-cache 정리를 보완하자 기존 회귀가 실제2failed/74passed를 드러냈다. port가 현재 main의 rejected intake 진단 호출1개를 누락한 것이며 아직 main에 착지되지 않았다. 독립 리뷰 후 d59c8e7636에서 정확한 main 호출을 복원하여 거절 시 snapshot/sequence/freshness는 그대로 두고 bounded immutable 진단만 기록한다. 관련4파일76passed/skip0·comparator0. 새 전체 착지 관문을 다시 확인한다.

- portable native55731 exit0, main8d8921ac0e89277a85c921810ab28218a5741b5c 착지 완료(base2c6db1e166). g1249passed, 영향2368passed/279skipped 및 실제 opt-in Chromium161+40+3+2=206passed.5로그 합2574passed/279skipped, comparator 전부0. same-SHA 필수 raw3도124passed/skip0·비교기0이며 package readiness가 선행했다. 해당 SHA의 native land record5invocations/5logs 확인.
- portable-candidate-8d8921ac0e.bundle742590bytes, SHA256 db898d764ca99a04a03c96555fc26dac2aa952f1b2972417a3401366604032f4. exactref/bundleverify/PACK SHA1 확인. fresh canonical judge removable/소유자일치/clean/ignored0 및 정확한 경계·HEAD·lock·Git 작업·queue 확인 뒤 native no-force remove로 merge-portable-catalog 폴더만 제거했다. 원본·통합 브랜치는 보존했다.

- 구조 리포트 native33978 exit0, main2c6db1e166414e22901b416dfe76ac006a9f83e5 착지 완료. FULL22invocations28278passed/1943skipped 및 g1249passed, 각22로그 비교기 NEW/known/flaky0 재확인. 원격·기본 환경에서 건너뛴 검사는 성공으로 세지 않는다.
- merged-structure-report-2c6db1e166.bundle717043bytes, SHA256 ab479ae96db4a1a8d9b32f0b50e9f029c0e2f85210055cb65c464056a9abf781. exactref/bundleverify/PACK SHA1·fresh canonical judge(removable/소유자일치/clean/ignored0) 후 native no-force remove로 merge-structure-report 폴더만 정리했다. 브랜치 보존.
- 대기 중인 source 최종 커밋의 추가 경계 검사: Station8838460a3의 secret/provenance/API 문서·protocol102passed, OMX8a18b8af9와 strict80f87cd776의 secret/provenance 각97passed. 모두 skip0·비교기0. Station8838460a3는 approved AI-PC remote_sim의 same-SHA generated IDL Python/C++ wire 및 capture/typed async DDS client를 각각 실제 실행해 exit0. nonce/기한/명시적닫힘·timeout/detach/late reply/parent 교체·음성응답/미발견 서비스를 확인했다. 합성 서비스이며 motion authority/실물 수용이 아니다.

- 교체된 자체 미리보기 두 브랜치의 복구본 superseded-integration-previews.bundle1455386bytes, SHA256 daa9351c68f5dfe53b512299f431bbccf945269c16e9e47d26646599d3ceac11. exact2refs·bundleverify·PACK SHA1 확인. 원본 bd23be5077/fa2f874b4 refs를 보존하며 실제 검토 브랜치의 착지 후 clean 폴더 정리에 사용한다.
- 전체 워크트리 재점검52개: active38, locked12, stale-history1, landed-dirty1, normal removable0. 자체 진행7개는 tracked/untracked/비캐시ignored0이다. 별도 learning-delivery의3문서 미커밋 및 owner불명 v13-map-labels의6파일 미커밋, 잠긴 폴더와 원본 peer3개는 보존한다. 이들 미커밋을 이번 포트에 섞지 않는다.

- raw-tools native42588 exit0, main96ef6ffac4 착지 완료. 재시도에서는 root8856passed/1098skipped를 포함한5개 fresh invocation이 모두 통과했고 나머지 FULL 묶음은 native cache의 검증된 재사용 판정이었다. g1249passed. 과거 실패28로그와 섞어 새 고유 시험 합계를 주장하지 않는다. FULL 경로는 재사용 가능한 affected land-record JSON을 만들지 않는 것이 현재 도구 동작이다.
- raw-tools 복구본 merged-raw-tools-96ef6ffac4.bundle702817bytes, SHA256 d0e19655397d0a2230556b61c03e27fd29a55e002303b5ff22d9115f812d9da3. exactref/bundleverify/PACK SHA1 통과, 기존 공통 객체를 필요로 하는 증분 복구본이다. fresh canonical judge(full=True)/소유자일치·clean/ignored0·lock/Git 작업/queue 확인 뒤 merge-raw-test-tools 폴더만 제거했고 브랜치를 보존했다.
- portable의 e0b41fe413 전체 영향 관문은 원본 fixture SHA2567행의 설명 부재로 release secret guard1NEW였다. main PASS/alone FAIL, 실제 browser206passed를 포함해도 전체 성공으로 세지 않는다. 실패10로그를 별도 복사·각SHA256 검증했다. b354a4c311은 값·시험·scanner를 유지하고 정확한 SHA256 integrity 주석만 추가했다. required raw3+secret guard204passed/skip0·comparator0·독립 리뷰 finding0, native55731 재대기 중이다.
- strict 최초 native78693은 중간 split 커밋에서 obsolete698줄 ratchet을 삭제하지 않아 거절됐다. 새8f11939fc에서 순수 분리와 ratchet 삭제를 한 커밋에 기록했고,7dbec4c99의 source/시험/문서는 기존 검토된fa2f874b4와 동일함을 독립 확인했다. size_range10commits PASS, 같은 새SHA193passed/skip0·comparator0. 이후 portable integrity 수정까지 병합한a3656c8a9f도 raw124passed/skip0·comparator0이다.
- strict native93967은 이동된 legacy layout4문자열의 기존 scan 소유 경로가 controller에 남아 있어 g1에서 거절됐다. 실패4로그 보존·파일별SHA256 확인.80f87cd776은 기존4항목의 경로만 helper로 이동했고 허용 개수·문자열·scan/stale 검사 불변, 독립 리뷰 finding0. 후속 원격213passed/skip0·comparator0, native70891로 재요청했다.
- Station native86120은 실제 fleet_action_claims 쓰기2모듈이 현재 main의 D-750 목록에 없어 g1에서 거절됐다. main PASS/alone FAIL. 실패4로그 보존·SHA256 확인. 독립 검토가 charge_store의 같은 BEGIN IMMEDIATE 예약/검증된 이안과 TaskStore startup migration을 확인한 후8838460a3에서 정확히2writer를 등록했다. guard+충전 관련54passed/skip0·comparator0. 최초 잘못 적은 test_charge_departure.py 경로는 exit4/0tests이므로 검증으로 세지 않는다. native22687 재대기 중이다.
- OMX a48b283c20 focused95passed/skip0·comparator0. 준비된 model-PC LeRobot0.4.4 환경과 표준 /tmp를 명시한 최종 remote_sim native75007은 wrapper5passed·내부27passed/skip0, exit0이다. 초기 기본 환경 부재·긴 AF_UNIX scratch 실패와 pytest를 실행하지 않은 wrapper의 exit0은 성공으로 세지 않았다. 마지막 SDK 사례의 ROS callback teardown 경고2개는 원문에 보존했다. 소스/시험은 독립 검토 승인,8a18b8af9는 기록·index만 추가. native24935 대기 중이다.
- 구조 리포트8ca64328e는 첫 focused30passed와 secret guard 포함96passed/skip0·comparator0, 독립 검토 finding0. Jira 검색 첫50개 한계와 제목 기반 GitHub 중복 검사는 유지하며 외부 게시를 실행하지 않았다. native33978이 main96ef6ffac4를 통합한2c6db1e166에서 전체 관문을 진행한다.

- raw-tools: 최초 f1ffd2154 전체 관문은 공개 BASE 전체 SHA를 secret guard가 탐지하여 실패했다. coordinator timing도 1회 실패 후 alone/main 통과했다. 실패28로그는 별도 복사·파일별 SHA256 검증했다. BASE를 같은 객체의 unique10자리로 바꾼96ef6ffac4는 관련177passed/skip0·comparator0·독립 리뷰 finding0. 전체 native 재요청42588 실행 중이며 기존 검증 재사용은 native 판정에 따른다.
- portable: 최초 native63535는 잘못된 journal heading으로 pytest 전에 실패했다.9095c6527는 heading·gate 변화·생성 index를 수정했고 lint0errors32warnings. 최종 필수3개 raw suite124passed/skip0·comparator0. 이전125는 추가 binding 회귀를 포함한 다른 선택이다. native88414가 raw 뒤 대기 중이다.
- Station: 원본4개 safety commit에 trailer가 없어 직접 착지는 거절됐다. 실제 독립 CORE/Drive/Fleet/Vision 리뷰 후 발견한3건을 수정했다. Fleet38passed, 활동기록29passed, ROS native grid7+AMCL10+static14=31건 exit0/skip0. 독립 검토된 최종 코드를8개 자체 port로 재생성하고 각 safety commit에 실제 검토 근거를 연결했다.48c32b501의 제품 코드·시험·설정은 검토한bd23be5077와 동일하며 API 이력 충돌 표식만 제거했다. safety9commits·lint0errors32warnings·diffcheck 통과. native86120 대기 중이다. 운영/실물 수용은 아니다.
- strict signed source: 순수 controller 역할 분리143passed와 AST 동등성·독립 리뷰 후 retained proof/strict 실행을 이식했다. 초기4RED, 실제 signed import의 의존성 누락 및 과거 build 회귀를 수정했다.0dbc66c10e의 원격193passed/skip0·comparator0·독립 리뷰 finding0. 최종 journal fa2f874b4를 native78693으로 요청했다. T4/reader supervision은 별도 범위다.
- OMX executor: 현재 main에는 pilot_sim 분리가 이미 착지해 과거10,077줄 blocker를 그대로 적용할 필요가 없다. 자체 fix/retired-omx-executor에서 준비된 #83 및 fixture/후속 리뷰 수정을 현재 nested 경로·watchdog·G2 clock lifecycle에 맞추고 있다. 독립 소스 리뷰 진행 중이다. 원래 peer 폴더는 수정하지 않았다.
- 구조 리포트: #66의 calculator·시험·optional manual Jira CLI를 이식했다. workflow는 현재 정책에 맞춰 GitHub job token만 사용하며 Jira secret 단계는 포함하지 않았다.8ca64328e의 원격30passed/skip0. 실제 GitHub/Jira 게시·workflow 활성화는 하지 않았다.
- 새로 main에 들어가고 clean/idle인14폴더는 canonical 판정·복구 bundle 검증 뒤 이미 제거했다. newly-merged-clean-14.bundle692991bytes, SHA2568f71fd6613fbdcf58fa6c5cb7343213b8a231e8b1e99b7b88fe378b03c071303.14개 브랜치는 보존했다. 아래 과거 session 번호·상태는 그때의 기록이며 최신 완료를 뜻하지 않는다.

사용자의 “머지까지해” 지시에 따라 직전에 폴더를 정리한9개 브랜치의 남은 변경을 검토·통합한다. 원본 브랜치와 remaining-clean-held-9-complete.bundle은 보존한다. 초기 검토 main은 a804896e58fbef93cd3ef98d210f175b367d9822이며 동료 착지로 계속 움직일 수 있다. main 미추적 aff1.log는 보존한다. 푸시·운영 배포·호스트 설치·실물 동작은 범위에 없다.

## 남은 이력 후속 처리 — 추가 지시

사용자가 나머지도 처리하도록 지시했다. 새 기준 main6ecf921d912e170fd6132697f09d1d5e60615b3e에서 기능별로 이식하고 검증·착지한다. 아래의 이전 최종 확인은 앞선4건의 완료 시점 기록이다.

1. Portable catalog와 명시적 legacy 동영상 준비: feat/retired-portable-catalog / .worktrees/merge-portable-catalog를 gateway로 생성했다. 원본 legacy 회귀13cab1e3b8·ccc47f92ea 및 portable 회귀45bd12a2e9의2파일에44d7cfc5c1·62ec9213e4 보정을 포함했다. 현재 ReviewStore 경로와 직접 provenance 검사를 사용하고 없는 source_components 분할 알고리즘은 복원하지 않는다. 시험 커밋2787443475에서 원격 RED를 먼저 확인한다. 이후4c00494b63·e9a2e4c33a·18b06c2172의 생산 변경만 이식하고 기존 main 클래스 바인딩 재검사를 유지한다.
2. Strict signed source handoff는 별도 단위다. 기존 updater·격리 bootstrap을 유지하면서 retained signed archive proof·실행 직전 source 검증·source_expectation·receipt를 최소 이식한다. 원본b6379d5ab8 전체나 이전 reader/workflow 대형 모듈을 그대로 가져오지 않는다. 별도 독립 검토와 실제 임시 서명 build→Updater→격리 import 회귀가 필요하다.
3. 두 host/policy 원본의 주제 구현·CI 이식은 main에 있다. 실제 남은 구조 리포트#66은 native port 후보지만, 원본 Jira secrets workflow와 현재 GITHUB_TOKEN-only 규칙 충돌을 먼저 해소한다. origin-sync에도 해당 변경이 있어 중복을 피한다.
4. Station#92는 feat/port-station-d772(dddd7a2686), OMX owner#83는 fix/port-omx-owner-executor(7a72bce2ae), 수입 안전 검토 provenance는 origin-sync(27ce0af536)에 존재한다. 소유·미커밋·실행 관문 상태를 읽기 전용으로 확인하고 진행 중인 타 작업을 덮어쓰지 않는다. 준비된 결과를 검증·통합할 방법을 확인한다.

### 후속 실행 상태

- 작업 공간: 상한60개로 새 Station 통합 공간 생성이 거절됐다. fresh full 판정으로 clean/merged/idle/ignored0인14개만 선정하고 newly-merged-clean-14.bundle의14개 exact ref·verify·PACK checksum을 확인했다. 692991bytes, SHA2568f71fd6613fbdcf58fa6c5cb7343213b8a231e8b1e99b7b88fe378b03c071303. base a804896e58fbef93cd3ef98d210f175b367d9822가 필요한 증분 복구본이다. 정확한 경계·HEAD·브랜치·Git 작업·queue를 다시 확인한 native remove는14개 전부 성공했고 브랜치는 보존했다. 진행 중 원본 Station·OMX·origin-sync는 변경하지 않았다.
- raw 도구: feat/retired-raw-test-tools / merge-raw-test-tools, 최종f1ffd2154ab73a767135c2a422c030ee5c7280c3. 기존597줄 runner의 이름 있는 VENV 책임 전체를 먼저 순수 추출하고 원본c5605827f3의 고정 pinky-raw profile만 선택 이식했다. 현 uv 필수·xdist/light host·잠금 해제 순서는 유지했다. 원본 최종 shell 경계 시험을 현재실제 base6ec에 맞춰 이식, RED21개 실패 후 native 최종97passed/skip0/NEW0. 독립 최종 검토 finding 없음. native land 세션33727은 새 helper의 unknown→FULL 기준을 그대로 적용해 전체 관문 실행 중이다. 선행249passed, 영향 묶음 중5593passed/317skipped 확인; 전체 통과·착지 완료는 아직 아니다.
- portable: feat/retired-portable-catalog / merge-portable-catalog, 최종e698ddd758c0342a348a609558068f87ccb39136. 원본 상대경로·same-handle/no-follow/bounds/namespace 보안·human pending·클래스경쟁 재검사를 보존했다. 기본선택125개 중124통과/MCAP의존부재1실패를 실제 raw profile로 해결했다. 초기 green 디렉터리의 실행은 잘못 적은 기존 시험 경로 때문에 exit4였으며 검증 증거로 세지 않는다. business1bcc, 환경분리db23, 최종e698 각각 실제 raw125passed/skip0. 마지막 raw-ready 로그도 비교기NEW/known/flaky0이며 독립 로그 검토 완료. native land63535는 raw 도구 뒤2번 대기다. 기본환경의 MCAP skip1은 모듈 AGENTS의 필수 raw profile exit0/skip0을 대신하지 않는다.
- Station: own feat/retired-station-integration / merge-station-retired에 기존dddd8커밋과 main6ec를 통합, v1.288 예약·bump9pins, 기존287/Station278–286 계약·양쪽 provenance155행 보존. 42f78b332 merge 후926dda98d에서 obsolete9개 ADR gap11행을 제거했다. size-range9commits 통과, lint0errors32warnings. native는 원본 안전4커밋의 자체 Safety-Review trailer 부재로 정상 차단됐다. 기존 원본이나 검사를 고치지 않고, 전체 독립 검토·발견사항 수정 후 base056f817652413bcc45fbcf04a86f19b9775c573e에서 새 검토 포트를 재생성할 예정이다.
- Station 검토 수정1: Fleet map revision 전환 후 이전 camera anchor를 새 proof로 재사용하는 P2를6a2147f757의 정확1RED로 재현했다. 8b94cdf30e는 map_id/revision 변경 시 source scope를 retire한다. 첫 GREEN은 새 anchor의 정상 자격 fixture가 부족해1failed37passed였고, 기존 localized 관측 cycle로 보완한8831922784에서38passed/skip0/NEW0. 독립 Fleet 전체+수정 검토 finding 없음. Vision 전체 검토도 finding 없음.
- Station 검토 수정2: AMCL이 cap 검사 전에 지도 전체를 복사하는 P2. 기존 copy 책임을 capture_original seam으로 순수 추출65d8c2329, 실제 C++ 회귀13b9ee57b0에서 copier가 실행되는1failed6passed RED를 확인했다. a8e31f2fc4는 실제 cell 수와 선언 크기를 복사 전에 제한하고 identify와 같은 cap 상수를 사용한다. 승인 시험 PC의 native ROS C++7개 전부 통과/skip0. 실제 AMCL consumer 전체 compile/DDS 검증과 최종 독립 검토는 추가 수행한다.
- Station 검토 수정3: station-undock·station-stop의 D24 command activity 누락. a19ce4c049에 기존 command-route 회귀3행을 추가하고 원격 RED 세션49757 실행 중이다. 생산 매핑 수정·GREEN·독립 재검토는 아직 남았다.
- strict signed source: merge-signed-source / feat/retired-signed-source를 main6ec에서 만들었지만 아직 clean이다. 현재 controller698줄이 ratchet이므로 기능을 더하기 전에 signed layout inventory와 기존 job entry/execution 책임의 분할을 검토한다. 원본 model_code_source406줄·bounds253줄·strict execute 함수만 최소 이식하고, 원본447줄 execution 모듈의 별도 D446 권한 supervision은 가져오지 않는다. installer의 새 trusted helper 목록과 Windows OpenSSL 탐색도 보존해야 한다.
- OMX executor의 adapter10077줄 한도 초과 선행 분할, 구조 보고#66의 Jira secret 정책 조정 및 수입 safety provenance는 아직 처리 중 목록이다. 위 단계가 끝나도 자동으로 완료된 것으로 간주하지 않는다.

## 이전4건 최종 확인 결과

2026-10-19 최종 확인 main은 a718f85013201c2992ac5bce90e33a02bd6a1eef다. 자체 통합4건은 모두 native land exit0으로 main에 반영됐고, 검증한 복구 bundle4개와 원본·통합 브랜치를 남긴 채 자체 작업 폴더4개를 제거했다. 원본9개 ref는 모두 원래 SHA를 유지한다. 그중6개 원본 tip이 main 조상이며(2개는 작업 시작 전부터 포함), signed-catalog 원본은 경쟁 수정만 이식했다. 나머지 host/policy 두 원본의 주제 구현은 이미 main에 있지만 혼재된 전체 이력은 미통합이다. 전체9개 이력을 전부 병합했다고 주장하지 않는다.

| 통합 | main 착지 SHA | 영향 시험 통과 | 실제 opt-in Chromium 포함 | 자체 폴더 |
|---|---|---:|---:|---|
| Pilot native fixtures | commit a27b980c7cb780b042ba6a85b5e541d9e533d823 | 838 | 164 | 제거 완료 |
| OMX Learning | commit 4b2cb988cc649681cae2ebd4d8451cc670b6edf8 | 4407 | 1200 | 제거 완료 |
| Account 두 원본 | commit 5febd43c53f58bf9d59a6cb893465f34675f5624 | 21075 | 164 | 제거 완료 |
| 리뷰 클래스 바인딩 수정 이식 | commit a718f85013201c2992ac5bce90e33a02bd6a1eef | 2317 | 206 | 제거 완료 |

각 통합의 선행 공통 시험249passed는 위 영향 시험 수와 별도로 기록한다. 표의 시험 수는 실행별 집계이며 서로 중복되는 테스트가 있다. 모든 native 비교기는 NEW/known/flaky0이다. skip은 실행 성공으로 세지 않는다. Pilot Android JVM111tests 중 skip1과 debug 빌드는 별도 증거다.

마지막 재검사에서 host-recovery-publish 전체 merge preview는116개 충돌 경로, push-batch는107개였다. 고유 커밋은41/42개이고 각 원본의291개 파일이 main의 같은 경로에 없다. 이 숫자는 경로 이동도 포함한다. 실제 미통합 예시는 station_charging 스키마와 시험, D772·D774·D776 Station 계약이다. 이 서로 다른 기능을 옛 topic 이름으로 대량 되돌리거나 blanket ours merge로 버리지 않았다. signed portable-catalog 파이프라인의 별도 미통합 내용은 아래 기록을 따른다.

최종 감사: 자체4개 착지 SHA의 main 조상 관계·land record·복구 bundle exact ref/verify/PACK checksum/SHA256, 원본9개 ref 불변·폴더 부재, 자체 대기표0개를 확인했다. 다른 작업의 표1개는 유지했다. main 상태는 기존 미추적 aff1.log 하나이며 파일을 변경하거나 삭제하지 않았다. 아래의 대기·이전 충돌 개수는 당시 과정 기록이며 현재 결과는 이 절과 표를 기준으로 한다.

| 원본 대상 | 현재 처리 |
|---|---|
| account-initial-password | 원본958b8f2f11은 이미 main 조상. 추가 병합 불필요 |
| host-report-access | 원본ef7b094bf2는 이미 main 조상. 추가 병합 불필요 |
| pilot-native-fixtures | a27b980c7cb780b042ba6a85b5e541d9e533d823로 main 착지 완료. native 관문 통과, 원본43b3e6dcea는 main 조상. bundle 검증 후 merge-pilot-fixtures 폴더 제거, 원본·통합 브랜치 보존 |
| account-app-landing + auth-service-adr | 5febd43c53f58bf9d59a6cb893465f34675f5624로 main 착지 완료. 두 원본76818bd901/1ddea9def6 모두 main 조상. 최신 WHEP·양쪽 로그·캐시 키 통합 보존. 첫 관문2NEW 수정·독립 재검토 후 전체 재실행 성공. bundle 검증과 full 정리 판정 후 merge-account-retired 폴더 제거, 원본·통합 브랜치 보존 |
| learn-omx | 4b2cb988cc649681cae2ebd4d8451cc670b6edf8로 main 착지 완료. 원본2dd4d009b9는 main 조상. 독립 검토에서 발견한 역할·교정 문제를 실제 RED6으로 재현 후 수정, focused11passed. native 영향 시험4407passed(실제 Chromium1200포함), 선행249passed. bundle 검증 후 merge-learn-omx 폴더 제거, 원본·통합 브랜치 보존 |
| publication-a0-r1-red-proof | 클래스 바인딩 경쟁 수정만 a718f85013201c2992ac5bce90e33a02bd6a1eef로 main 이식·관문 통과. 원본0ef4c1bebf 전체 stale-history와 signed portable-catalog 파이프라인은 미통합. merge-review-binding 폴더 제거, 원본·통합 브랜치와 bundle 보존 |
| host-recovery-publish | 호스트 복구·보고 주제 구현은 main 실제 경로·blob으로 확인. CI 이식bc2239c2f33a78f2bdb76a475015302a0ea01b52 및 협업 문서bd3c9fe3e4ca91ba4cca4f12dd8d92ef9c1fec8c도 동료가 착지. 남은 Station 등 혼재 이력41커밋·116충돌 경로는 별도 미통합, 원본과 복구본 보존 |
| push-batch | 학습 정책 gate의 수집·measured reach·intake·원장·API·CLI·UI·G1 구현은 이미 main. CI ROS 선택기도 동료 이식으로 착지. 관련 없는 혼재 이력42커밋·107충돌 경로는 별도 미통합, 원본과 복구본 보존 |

pytest는 커밋된 SHA를 원격 PC에서만 실행한다. RED 로그는 %TEMP%/rosy-worktree-reconcile/omx-intake-red-collected/run-1.txt, GREEN은 omx-intake-green/run-1.txt. 최초 isolated 실행 omx-intake-red는 소스 시험의 명시 loader 경로 누락으로 collection error였으며 RED 재현으로 세지 않았다. 경로를 보완한 뒤 실제6실패를 확인했다. 카메라 교정 변경은 현재 보수적으로 해당 역할의 세션 전체를 unmeasurable로 남긴다. 프레임별 교정 선택은 구현하지 않았으며 intake/training을 승인하는 관문은 추가하지 않는다.

## 추가 검증과 착지 대기

### 리뷰 수정 main 착지·정리 완료

- native 재시도21844 exit0,1round. base5febd43c53f58bf9d59a6cb893465f34675f5624에 통합한 최종a718f85013201c2992ac5bce90e33a02bd6a1eef와 main 조상 관계, land record sha/base·5개 invocation/log 일치를 확인했다. append-only perception 로그·인덱스2개는 gateway가 자동 조정했다.
- 선행249passed. 일반 영향2111passed/278skipped, 실제 opt-in Chromium161+40+3+2=206passed. 영향 합계2317passed, 비교기5개 NEW/known/flaky0. 초기180분 대기 timeout은 시험 실패가 아니며 이번 재시도 성공과 구분한다.
- merged-review-class-binding-a718f85013.bundle:225591bytes, SHA256e19a31b1771e49a4fcc87c14524b068f73adc2feceeef879a3d6548b31db5530. exact ref·git bundle verify·PACK checksum 일치. 기존 base a804896e58fbef93cd3ef98d210f175b367d9822가 필요한 증분 복구본이다.
- fresh judge(full=True):removable, 소유자 일치, tracked/untracked/ignored0, lock/orphan 없음. 제거 직전 경계·HEAD·브랜치·Git 작업·대기열을 재확인하고 native worktree remove(no force) 성공. 원본 signed-catalog 및 fix/retired-review-class-binding 브랜치는 보존했다. 합성 시험 상태만 사용했으며 운영 사람 라벨은 읽거나 바꾸지 않았다.

### Account main 착지·정리 완료

- 재시도 native 세션99711 exit0, 1round. main base4b2cb988cc649681cae2ebd4d8451cc670b6edf8에 통합한 최종5febd43c53f58bf9d59a6cb893465f34675f5624와 두 원본의 main 조상 관계를 확인했다. .git/rosy-land/commit 5febd43c53f58bf9d59a6cb893465f34675f5624.json의 sha/base·5개 invocation/log 경로가 일치한다.
- 선행249passed. 영향 묶음10596passed/537skipped,4731passed/119skipped,5584passed/317skipped, 실제 opt-in Chromium161passed+3passed. 영향 합계21075passed/973skipped, 비교기5개 모두 NEW/known/flaky0. 첫 실패 실행은 앞서 별도 보존했고 이번 전체 성공으로 덮어 쓰지 않는다.
- merged-account-rollout-5febd43c53.bundle:220379bytes, SHA2566795b56e395048e3d7942cf680b53b1f69b3d67889b1ba3893323552fb6c4c6f. exact ref·git bundle verify·PACK SHA1 일치 확인. 기존 base a804896e58fbef93cd3ef98d210f175b367d9822를 필요로 하는 증분 복구본이다.
- fresh judge(full=True):removable, 현재 소유자 일치, tracked/untracked/ignored0, lock/orphan 없음. 제거 직전 정확한 폴더 경계·HEAD·브랜치·Git 작업·대기열을 재검사한 뒤 native worktree remove(no force) 성공. 원본 두 브랜치와 fix/retired-account-rollout은 보존했다.
- 리뷰 수정 재시도 세션21844가 이제 대기열 맨 앞에서 main5febd43c53을 통합하고 관문을 실행한다. 해당 결과는 별도로 확인한다.

### Account 첫 관문 실패와 재검증

- native 세션72916은 main a27b980c7c를 통합한805ce7d116에서 영향 시험2NEW 때문에 exit1로 중단했다. 원인은 helper-created ui-button의 explicit kind 검사와 공개 커밋·로그 SHA256의 설명 없는 표기였다. 실제 실패 위치는 shared/web/test/test_shared_controls.py 및 test/test_release_boundary_guards.py다. 짧은 요약 node id가 middleware/media::로 잘못 축약돼 helper의 alone/main 재실행은 exit4였으며 main-red 또는 flaky 증거가 아니다.
- 첫 실행: 선행249passed, 영향 run-1-1은10593passed/535skipped/2failed; 다른 묶음4731passed/119skipped,5584passed/317skipped, opt-in browser161passed+3passed. 전체 통과로 계산하지 않는다. 원본 로그11개를 외부 scratch account-failed-805ce7d116에 native copy하고 파일별 SHA256 일치를 확인했다. 재실행이 이 실패 증거를 덮어쓰지 않게 보관했다.
- 4a5d5eef7f12dcdc334e317fc82d6532f0bbb040에서 quiet setter와 명시적인 commit/SHA256 표기를 적용했다. 해시 값·scanner·allowlist·baseline은 그대로다. 참조한40자리 두 값은 실제 Git commit임을 확인했다. 원격 focused121passed/skip0, NEW/known/flaky0, 독립 소스 검토 finding 없음. 전체 native 착지를 다시 요청한다.
- 검증 기록 journal을 추가한3ee7cc06a로 Account native 착지를 재요청했다(세션99711, 대기 한도600분). 이전 세션72916은 종료됐다.
- 검수 바인딩 첫 착지 요청 세션65691은180분 대기 한도에 도달해 exit1, 그 요청에서는 merge·pytest가 실행되지 않았다. 앞서 별도로 수행한 RED1failed/GREEN57passed와 구분한다. 같은 검증된 브랜치를 현재 native FIFO에600분 한도로 재등록했으며 순서나 동료 ticket을 조작하지 않았다.
- 검수 재요청 native 세션21844, ticket01792404753130770300-28852.json. 현재 Account 재요청은 세션99711, 검수21844, Learning 최초 요청46922가 살아 있으며 Pilot52890·Account 최초72916·검수 최초65691은 종료됐다. Learning은 현재 main a27b980c7c를 통합한4b2cb988cc에서 선행 관문 뒤 영향·실제 browser 검증 중이다.

### Pilot 착지 완료

- fix/retired-pilot-fixtures가 a27b980c7cb780b042ba6a85b5e541d9e533d823으로 로컬 main에 착지했다. base commit b9828f13bd7ee8dcd62d055ff049f29294813991, 1라운드, native 세션52890 exit0. 원본43b3e6dcea도 main 조상 관계 확인.
- 선행249passed. 영향674passed/163skipped, opt-in Chromium Pilot161passed + OMX SIM3passed. 전체3로그 comparator NEW/known/flaky0, 해당 SHA의 land record3invocations/3logs 일치. 앞서 실제 모델 PC JVM을 검증한81e75d301d 이후 Android source·wrapper 변경은 없었다. 푸시하지 않았다.
- 이 통합 워크트리는 --from 원본 tip에서 생성하고 main merge만 추가한 경우여서, 제거 전 현재 gateway의 보수적 판정도 따로 확인한다. 원본·통합 브랜치와 검증된 복구본을 보존한다. 나머지3개는 아직 착지 완료로 표시하지 않는다.
- Pilot 통합 폴더도 제거했다. 자동 gateway는 브랜치 reflog에 commit으로 시작하는 기록이 없는 merge-only 브랜치를 active/72h로 보수적으로 분류했다. 이 판정을 자동 prune 통과로 바꾸거나 메타데이터를 수정하지 않았다. 본 세션이 만든 동일 owner의 작업이고, 정확한 main 조상·land record·clean/비캐시 ignored0·잠금 없음·진행 중 작업/queue 없음·새 복구본을 확인해, 사용자가 이미 요청한 완료 작업 폴더 정리 범위에서 native remove로 대상1개만 처리했다. 원본fix/pilot-native-fixtures와 통합fix/retired-pilot-fixtures는 모두 보존했다.
- 복구본 merged-pilot-fixtures-a27b980c7c.bundle(108335bytes, SHA256 a9c6ae76321ae5a76c5382a317c8e816c3eeca85cb6ee71c327df96ec9fde89b), 정확한 ref·bundle verify·PACK checksum 통과. 기존a804896e58 객체가 필요한 증분 복구본이다.

### OMX Learning 착지 완료

- feat/retired-learning-omx가4b2cb988cc649681cae2ebd4d8451cc670b6edf8로 로컬 main에 착지했다. base commit a27b980c7cb780b042ba6a85b5e541d9e533d823, 1라운드, native46922 exit0. 원본2dd4d009b9도 main 조상 관계 확인.
- 선행249passed. 영향6호출은3125passed/312skipped,82passed,243passed,345passed,426passed,186passed(총4407passed). 마지막4호출은 실제 opt-in Chromium1200passed·skip0이다. 6로그 comparator NEW/known/flaky0 및 exact SHA land record6invocations/6logs 확인. 앞선 focused11/187 검증과 이 수치를 합쳐 고유 시험 수로 계산하지 않는다.
- 이 세션 소유 폴더merge-learn-omx는 canonical judge(full=True)의 removable·dirty0·비캐시 ignored0·잠금 없음, 정확한 main 조상·backup ref를 확인한 뒤 native remove했다. 원본·통합 브랜치는 보존했다.
- 복구본 merged-learning-omx-4b2cb988cc.bundle(150143bytes, SHA256 b3934dbb007cd93e14df96d237a1daf8afbd5d1c54de4785acfbf0412d01cbb2), bundle verify·PACK checksum·exact ref 통과. 기존a804896e58 객체가 필요한 증분 복구본이다. 물리 카메라 정확도·학습 품질·실물 수용·운영 배포는 검증하지 않았다.

- learn-omx: c453ddc0ca의 원격 AI PC focused187passed/2skipped, known_failures NEW/known/flaky0. 로그 omx-integration-focused/run-1.txt. 최종 수정 독립 검토 finding 없음. native land 세션46922, ticket01792393792592402200-10560.json으로 기존 순서 대기 중이다.
- 검수 클래스 바인딩: RED98ae70a563의 거절 YAML 부수효과1failed, GREENa58e7fdaaa의 기존 검수 포함57passed/skip0, NEW/known/flaky0. 94b123f8b의 독립 최종 검토 finding 없음. native land 세션65691, ticket01792393834708608000-1524.json. 운영 사람 라벨은 접근하지 않았다.
- Pilot: 81e75d301dcd9c4a4c576487c3be067ea6d33b9f를 native remote runner로 모델 PC에 전달, launcher 계약2passed/NEW0. 같은 커밋의 git archive를 모델 PC의 별도 /home/rosy/rosy-test/native-pilot-81e75d-hoYuod에 풀고 기존 SDK·wrapper, MemoryMax6G/CPUQuota200%, nice15, timeout600, max-workers1로 JVM111tests·failures/errors0·skipped1 및 debug APK1을 확인했다. Gradle log SHA256 c17cec510b3a57eca7fbf829e4b4db102af6cf8341531c96d602404d8d8fdc06, APK SHA256 3910b82ef61c1a06f0fbf0e9ad84d7a36d53c612aa7c1c872bcaab199f2bc168. 첫 수집 wrapper는 종료 heredoc 개행 문제로 exit1이었으나 Gradle 자체 exit0이었다. 별도 수정된 읽기 전용 수집 명령 exit0으로 XML·BUILD SUCCESSFUL·APK와 hash를 재검증했다. 기본 debug 산출물이며 서명 운영 배포나 실물 설치 증거가 아니다. skip1은 opt-in ShellPageProbe다.
- 공용 대기열 선행6개는 다른 세션 소유다. 앞선 fix/port-fleet-small이 27개 외부 로그 중24번째 시험 묶음을 실행 중인 것을 읽기 전용으로 확인했다. 다른 세션의 표·프로세스·순서를 변경하지 않는다. 현재 네 작업의 준비·focused 검증은 main 착지 완료를 뜻하지 않는다.
- 이후 동료 fix/port-fleet-small 착지로 main이9684c844b3으로 진행했고 CI 이식이 대기열 맨 앞에서 실제 시험 중이다. 자체 네 작업은 기본180분 대기 제한을 유지한다. 아직 자체 main 착지를 확인하지 않았으므로 완료로 표시하지 않는다.
- CI 이식도 bc2239c2f33a78f2bdb76a475015302a0ea01b52로 착지했다. 두 host/policy 원본의 전체 병합 preview는 아직 각각109/99파일 충돌이며, 두 원본 트리에는 현재 main의 같은 경로에 없는294개 파일(Station 수명주기·native map authority·배선 및 시험 포함)이 있다. 이 개수에는 이동된 파일도 포함되므로294개가 모두 기능 누락이라는 뜻은 아니다. 주제 구현이 이미 main이라는 독립 검토와 전체 upstream 이력 통합 여부를 구분한다. 현재 활성 origin-sync/port 작업과 겹치는 변경을 이 두 topic 이름으로 대량 되돌리거나, blanket ours merge로 버리지 않는다.
- 동료 docs/port-collab-pipeline도 bd3c9fe3e4ca91ba4cca4f12dd8d92ef9c1fec8c로 착지했다. 자체 첫 작업은 refactor/omx-pilot-sim-unit 뒤2번까지 진행했다. 자체 대기열의4개 SHA는 순서대로81e75d301dcd9c4a4c576487c3be067ea6d33b9f,commit 052ddf203bf272d5ae41afbd3367bd58a105e042,c453ddc0ca57e0887c0a95acbf18c54e0ba3c302,94b123f8bef6c01ba93e2a51e08dc9f8f1ada640이며, 해당 원격 land native 세션은52890/72916/46922/65691이다. root의 감시 스크립트 종료는 이 native 세션을 종료하지 않는다.
