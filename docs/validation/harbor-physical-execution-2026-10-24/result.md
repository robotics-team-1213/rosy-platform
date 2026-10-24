# D-856 물리 실행 원장 진행 기록

## 현재 범위

HTTP v1.307의 FULL은 소스58에서 마감했으며 [별도 기록](../harbor-arm-job-http-2026-10-24/result.md)을 따른다. 이 문서는 그 뒤의 내부 준비·최초 전송 의도·장치 결과 투영·물리 종료 원장과 SDK dispatcher를 기록한다. SDK 클래스는 내부 시험까지이며 app의 관측 credential HTTP와 Harbor ARM에는 아직 연결하지 않았다.

준비 원장은 common migration7에서 별도 physical attempts를 추가한다. 고정 step/action/attempt·canonical grant/digest·owner journal/session·준비 시각을 저장해도 parent READY와 claims CLAIMED를 유지한다. 반복 호출은 현재 설치·capability·승인·fence·전체 점유와 기존 grant를 다시 검사하며 ID/만료를 갱신하지 않는다. grant TTL은 기존 Fleet 관례의 1~60초 범위와 설치 관측 창을 함께 검사한다. site-stop은 PREPARED→HOLD, SUBMITTING→UNKNOWN으로 바꾸며 점유를 보존한다.

최초 전송 의도는 migration8의 immutable observation record와 기존 parent/event/claim을 한 transaction에 기록한다. 승인 이후 준비 context에 결속된 두 표본으로 object-at-source, 모든 참여 팔의 전체 링크 구역 이탈·정지·빈 그리퍼를 검사한다. caller의 목록은 진입 시 tuple로 고정한다. 직렬화·임시 기록 뒤 최종 시각으로 역행·grant 만료·capability·표본 freshness를 다시 검사한 뒤에만 parent RUNNING/attempt SUBMITTING/claims DISPATCHING을 commit한다. 이것은 SDK가 동작을 접수했다는 증거가 아니다.

장치 결과 투영은 기존 순수 receipt 검사를 재사용해 원래 grant의 owner journal/attempt/digest/fence와 성공의 네 phase를 대조한다. 동일 watermark의 다른 결과는 거절하며 created delivery flag는 중복 판단에서 제외한다. 성공도 전체 claims를 HELD로 보존한다. 정지 뒤 늦은 성공은 원장에 남기면서 HOLD/UNKNOWN을 보존한다. 이 투영은 물리 종료 판정이나 업무 완료가 아니다.

내부 물리 종료는 별도 POST_ACTION 두 표본을 성공의 영속 시각 이후에 요구한다. 최초 전송 표본과 ID/sequence가 달라야 하며 전체 participant의 정지·구역 이탈과 object-at-target을 검사한다. 최종 시각·현재 capability/fence·정확한 HELD claims를 대조하고 immutable physical receipt·원래 owner/generation의 전체 claim 해제·GOAL_CONFIRMED·event를 원자 기록한다. 동일 증거의 재호출은 과거 receipt만 읽으며 뒤의 새 owner 점유를 건드리지 않는다. 다른 증거와 action 성공 없는 clearance는 해제하지 않는다. physical receipt는 Harbor 업무 완료를 의미하지 않는다.

## 고정 소스와 원격 증거

pytest는 모두 공식 remote runner로 각 committed SHA에서 실행했다. 아래 로그의 기준은 `C:/Users/SERIGGG/AppData/Local/Temp/`다. 각 실패는 공식 known_failures로 분류했으며 수정 전/후를 다른 소스 기록으로 보존한다.

| 단계·소스 | 로그 폴더 | 결과·공식 분류 |
| --- | --- | --- |
| 준비 RED db889a5d47 | rosy-physical-prepare-red | 9 failed, 9 NEW |
| 준비 8a9dc15851 | rosy-physical-prepare-focus | 67 passed/2 failed, 2 NEW: 기존 migration 기대값 |
| 준비 경계 RED 81feccf384 | rosy-physical-prepare-boundary-red | 12 passed/2 failed, 2 NEW: stop 상태/TTL 관측창 |
| 준비 보완 7892f13ec3 | rosy-physical-prepare-fixed-focus | 74 passed/skip0, 0 NEW |
| 준비 affected 7892f13ec3 run1 | rosy-physical-prepare-789-affected | 4508 passed/187 skipped/1 failed, 1 NEW: work unit의 오래된 small 표시 |
| 준비 affected 7892f13ec3 run2 | rosy-physical-prepare-789-affected | 6372 passed/336 skipped/3 failed, 3 NEW: legacy migration 버전6 기대값 |
| 전송 의도 RED 11c3975825 | rosy-physical-submit-intent-red | 11 failed, 11 NEW |
| 최종 경계 RED 21b44b8b64 | rosy-physical-submit-boundary-red | 11 passed/4 failed, 4 NEW: clock 역행/표본 stale/grant 만료/list 교체 |
| 전송 의도 보완 cf4495bb2a | rosy-physical-submit-fixed-focus | 91 passed/skip0, 0 NEW |
| 전송 의도 부분선택 cf4495bb2a run1 | rosy-physical-submit-cf-affected | 4508 passed/187 skipped/1 failed, 1 NEW: work unit small 표시 |
| 전송 의도 부분선택 cf4495bb2a run2 | rosy-physical-submit-cf-affected | 6387 passed/336 skipped/3 failed, 3 NEW: legacy version 기대값 |
| legacy 기대값 보완 4d2335a8f4 | rosy-physical-submit-legacy-version | 72 passed/skip0, 0 NEW |
| unit 분류 보완 2ddeb967e7 | rosy-physical-work-unit | 46 passed/skip0, 0 NEW |
| 결과 투영 RED 769117c18e | rosy-physical-outcomes-red | 13 failed, 13 NEW |
| 결과 투영 b528f659cd | rosy-physical-outcomes-focus | 73 passed/skip0, 0 NEW; 후속 검토 finding은 별도 보완 중 |
| 결과 경계 RED eadd1892f8 | rosy-physical-outcomes-boundary-red | 13 passed/7 failed, 7 NEW: first-send 이전 receipt/phase와 HOLD 자동활성화 |
| 결과 보완 9f7f1e979e | rosy-physical-outcomes-fixed-focus | 229 passed/skip0, 0 NEW; legacy/version·구조 회귀 포함 |
| 물리 종료 RED 99b8c06e0b | rosy-physical-closure-red | 21 failed, 21 NEW |
| 물리 종료 3b23a23bca | rosy-physical-closure-focus | 101 passed/skip0, 0 NEW |
| 전체 physical stop 대상 RED 0174c68791 | rosy-physical-stop-targets-red | 7 failed, 7 NEW |
| stop 대상 보완 80dde18b85 | rosy-physical-stop-targets-focus | 65 passed/skip0, 0 NEW |
| SDK RED 85cbf4b353 | rosy-physical-sdk-dispatch-red | 14 errors, 14 NEW |
| SDK 경계 RED 33a53ee87b | rosy-physical-sdk-boundary-red | 14 passed/4 failed, 4 NEW: 겹친 dispatcher/지연된 송신 경계 |
| SDK 보완 54f27e6fb7 | rosy-physical-sdk-fixed-focus | 121 passed/skip0, 0 NEW |

준비 affected의 원본 실패 원인은 assertion에 보존했다. work unit이 1000행을 넘어 small 분류를 벗어나 기존 규칙에 따라 표시를 제거했다. 파일 예산·floor·안전 assertion을 완화하지 않았다. legacy 세 시험은 기존 데이터 보존과 구버전 host 거절을 그대로 검사하면서 현재 version8에 기대값만 맞췄다.

소스cf의 selector는 FULL로 승격됐다. `rosy-physical-submit-cf-affected` 실행은 runner의 local_invocations 두 그룹만 실행한 부분 검증이며 FULL 수용 근거로 쓰지 않는다. 종료 exit1이며 run1은 위와 같은 small 표시 1 NEW, run2는 legacy version 기대값 3 NEW다. 해당 보완의 focused72/46과 후속229를 구별한다. 후속 구현까지 고정한 최종 SHA에서 원본 full_invocations 전체23개를 metadata 보존하여 실행해야 한다. 앞선 HTTP58 FULL과 뒤의 소스를 합쳐 전체 통과로 부르지 않는다.

## 독립 검토와 남은 검증

독립 rosy_contract_reviewer가 준비 소스의 TTL 충돌을 지적했고 경계 RED 뒤 보완했다. 최초 전송 의도의 최종 clock/list 교체 두 finding도 RED4를 확인한 뒤 수정·재검토했다. reviewed writer의 LF-normalized SHA256은 `dfa67998c0a77c4c4739a467b07cd355876f9d60febc3dbcf0a7d1e19e55b13e`이며 소스cf의 execution 파일과 대응한다. 이 검토 뒤 KNOWN_WRITERS에 정확한 claim writer만 추가했다. 이후 b528 검토의 receipt/phase causality와 HOLD 자동활성화는 RED7 뒤 보완해 9f에서 추가 finding 없음으로 재검토했다(execution LF hash `4dad91825bc8a10f29667228448d9c7d7acd72a2e6897597d11fc26067bb6e3b`).

물리 종료 소스3b23도 원래 owner/generation 해제·proof/receipt/parent/event 원자성·새 owner와 재호출 경합에 대해 독립 검토를 받았고 추가 supported material finding 없음이다. LF hash는 execution `2b8fd7bdbeccd0dbe8d22d6ecea54633736c4cb90f177eddc7461a0042298ce2`, observations `9c982011a8a970400f76f5a7b6b48f898b8bee64a6f59e18ba9b8ca892ca7add`다. 소스/시험 읽기 검토이며 SDK·credential ingress·실물 수용을 대신하지 않는다.

## 전체 participant의 stop/rearm 연결

실제 SDK 제출 전에 기존 stop 설정이 workcell마다 단일 instance만 표현한다는 한계를 확인했다. 같은 workcell에 있는 두 physical arm을 모두 대상으로 삼도록 별도 immutable stop-target pair 목록을 구성했다. 정확한 pair는 중복 제거하고 같은 instance가 다른 workcell로 연결되면 앱 구성 단계에서 거절한다. HTTP estop·intent estop·rearm·한 대상의 rearm 실패 후 전체 rollback과 control 부재의 UNKNOWN 보고가 이 목록을 사용한다. physical-only 구성에도 기본 stop transport를 만든다.

legacy dispatcher·owner recovery·governance·app.state.omx_instances의 mapping은 유지했다. physical owner recovery를 암묵적으로 열지 않았다. app은905→902행으로 줄었으며 ratchet도 같은80dde commit에서902로 낮췄다. safety-tagged task_dispatch_routes를 포함한 [독립 source review와 hash](stop-source-review.md)는 구현 commit의 Safety-Review trailer에 결속돼 있다. source80dde의7개 새 경계와 기존 stop/latch/recovery/task/ARM HTTP를 포함한 원격65 passed/skip0/known0 NEW, 3bd→80dde 두 커밋 size/safety 각각exit0다. Fake stop transport의 호출·fence 검사이며 장치 정지 수용이 아니다.

## 내부 SDK dispatcher

source54f27은 같은 원장의 모든 dispatcher 객체·프로세스가 OS RPC guard를 공유한다. 2초 busy timeout과 FD 해제, thread 재진입과 fork PID 구분을 검사한다. prepare/send/refresh/cancel 때 모든 participant의 simulation is True·정확한 scope/journal identity와 typed managed capability를 새로 읽으며 SQLite 밖에서 호출한다. 전송 의도 뒤 control 조회가 지연돼도 SDK 송신 전에 영속 proof body/hash·RUNNING/SUBMITTING·전체 DISPATCHING claims·현재 fence·clock/grant/capability/동일 facts freshness를 다시 검사하고 DB 연결을 닫는다.

최초 SDK submit은 고정 grant로 한 번만 호출한다. 중복 요청은 상태만 읽고, 이후 refresh는 같은 grant의 GetAction만 한다. 유실·404·교체·재시작은 HOLD/UNKNOWN 점유를 유지한다. cancel도 먼저 보류하고 이미 제출한 grant에만 CancelAction을 요청하며 ACK로 점유를 해제하지 않는다. 다른 journal·production profile·불완전 SDK는 구성 단계에서 거절한다. 실제 app ingress와는 아직 연결하지 않았다.

독립 검토에서 객체별 lock의 겹친 수명 경합과 control 조회 뒤 stale 송신을 지적했고, RED4 뒤 OS guard와 final send 재검사를 추가해 재검토했다. 추가 material finding 없음이다. LF hash는 IO `aa045fd428361de63e376bfc1bb6914d999aa26cd564dec6c866f449c6c69ff0`, dispatcher `5fb23dc9f9d2c72b14a92ef9ee6ac4b3aaeedab77a193fcd684eb7a929fc454f`, execution `ae1a9b8543d6e1bf5a8e499bc34dd011708fd41a47e50537f5ead2a759d021f3`다. source54f27 집중121은 Fake SDK port의 동작·SQLite 비점유·실제 POSIX process guard 검증이다. Native UDS·독립 TCP HTTP·실물 물리 근거와 최종 FULL을 대신하지 않는다.

첫 slice의 UNKNOWN/CANCEL/HOLD 복구는 기존 action/attempt의 사실 조회와 점유 보존까지다. 더 높은 RUNNING/SUCCEEDED receipt가 와도 HOLD를 자동활성화하지 않는다. 명시적 복구/재승인과 실패·취소 후 물리 종료는 별도 후속 계약이며 앱이 새 key나 true flag로 이를 우회하지 못한다.

958d→3b의19개 커밋 size_range와 safety_review는 각각 exit0이다. 후속 변경과 최종 소스는 다시 확인해야 한다. 실물·배포·push·merge는 수행하지 않았다. CE 미해결: 이전 G1 접촉 간격 실패의 원인은 미확정이다. 이번 경계 수정은 source·회귀·본 기록에 근거를 보존하므로 별도 해결 교훈으로 늘리지 않는다.
