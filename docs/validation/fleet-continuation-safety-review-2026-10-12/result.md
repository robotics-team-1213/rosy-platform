# Fleet continuation 이력의 독립 안전 검토

## 범위와 판정

CI [38179188613](https://github.com/robotics-team-1213/rosy-platform/actions/runs/38179188613)은 commit `e94a0ae515`까지의 누적 이력에서 안전 경로를 바꾼 아래 열 커밋의 `Safety-Review` trailer 누락으로 중단됐다. 시험 job은 실행되지 않았으며 CI 통과가 아니다. 이력 재작성 없이 D-430 §5와 `tools/harness/safety_review.py`의 기존 독립 소급 검토 `EXEMPT` 방식으로 기록한다. baseline, 안전 경로 분류, trailer 검사와 실패 기준은 그대로다.

2026-10-12 독립 reviewer `/root/robot_pilot_ui`와 `/root/native_games_ui`가 정확한 커밋 diff, D-430, 영향 호출부 및 회귀 단언을 읽고 아래 범위로 승인했다. **중간 스냅샷의 단독 배포 승인이 아니다.** 검토 대상은 후속 수정이 모두 포함된 commit `e94a0ae515`이며, 특히 `f1dfada7f`, `38f51c4c2`, `5f3f033a8`를 빼면 승인이 성립하지 않는다. CORE 최종 제어 권한은 유지한다.

| commit | reviewer | 독립 소급 검토 근거·필수 후속 조건 |
|---|---|---|
| `68e6f973f` | robot_pilot_ui | navigation 전 formation/trip 소유권 재확인, 명시적 Boolean 접수 후에만 goal/lease/yield 기록, 닫힌 production valve 아래 정책 재확인. 이후 stop·continuation fence가 필요하다. |
| `6dd8a3365` | robot_pilot_ui | pending goal과 global/per-robot stop generation으로 늦은 응답 무효화·보상 취소, pending 중 trip 금지. mission readback 회전은 미해결 요청을 자동 재전송하지 않는다. 이후 admission·continuation·취소 오류 처리가 필요하다. |
| `0f1962e90` | robot_pilot_ui | robot별 직렬화, 전송 직전 task 소유권·dispatch generation·정책 재확인, stop을 가로지른 trip/follower arming 거절. 이후 traffic await fence가 필요하다. |
| `8f602794d` | robot_pilot_ui | capability·localization·route·observe·map·bay·cancel await 후 stop token 확인, 자기 pipeline의 traffic cancel 증가만 허용, 다른 goal pipeline 중 follower arming 금지. 이후 unknown bay receipt 보상 처리가 필요하다. |
| `25c036ae8` | robot_pilot_ui | mover 정지 후 bay 전달 오류/취소 시 보상 취소를 시도하며 원래 실패를 보존한다. 접수 이후 UNKNOWN 및 보상 취소 실패 후속 수정이 필요하다. |
| `1b556107d` | native_games_ui | 접수된 mover 뒤 bay 거절을 UNKNOWN으로 유지하려는 변경. **단독 상태에는 RobotApiError import 누락과 `_make_room`만 감싼 보호 범위 결함이 있다.** 다음 두 수정과 함께 검토했으므로 history-only 승인이다. |
| `f1dfada7f` | native_games_ui | 기존 transport 오류 타입 import로 위 분류를 작동시킨다. 권한·명령·정지·lease 설정을 바꾸지 않는다. 전체 continuation 보호는 다음 수정이 필요하다. |
| `38f51c4c2` | native_games_ui | 접수 이후 route/trust cancel·observe·map·bay 전체의 owner 거절을 UNKNOWN으로 전달한다. stop token·취소 확인 뒤에만 queue로 이동한다. claim 유지·재전송 금지·goal 한 번 전송 단언을 확인했다. 보상 취소 실패는 마지막 수정이 필요하다. |
| `cd42d880a` | native_games_ui | 실제 cancel-all generation 겹침만 DispatchCanceled로 분류하며 mover/yielder 재취소·task 태깅을 먼저 한다. Task는 UNKNOWN/overlap을 기록하고 정지 성공을 확정하지 않는다. CancelledError는 결과로 바꾸지 않는다. 마지막 보상 취소 수정이 필요하다. |
| `5f3f033a8` | native_games_ui | 늦게 접수된 goal의 보상 취소 오류가 FAILED로 오분류되지 않도록 NavigationStopped/UNKNOWN을 유지한다. lease를 되살리지 않으며 CancelledError와 pending finally 정리를 보존한다. |

읽은 시험은 Fleet `test_goal_lease.py`, `test_task_service_policy_evidence.py`, `test_trip_runner.py`, `test_mission_dispatcher.py`, `test_task_service.py`, cancel-all 회귀다. Reviewer는 코드·예외 목록을 수정하거나 시험을 직접 실행하지 않았다. 두 검토 모두 후속 수정이 포함된 범위에서 추가 blocker가 없다고 판정했다.

## 실행 근거와 한계

commit `e94a0ae515`의 canonical 원격 pre-push는 적정 Model PC 23.9 cores/8.2 GB와 AI PC 18 cores/7 GB에서 514 + 5601 + 5377 = **11,492 passed**, 각 종료 0·NEW 0이었다. 로그는 공용 증거 세션 `logs/prepush-final/run-1.txt`부터 `run-3.txt`까지다. 실제 Chromium/인증/프로필 143 passed는 [전체 UI 결과](../all-ui-workflows-2026-10-12/result.md)의 별도 소스 증거다.

이는 호스트 회귀와 독립 소스 검토다. 새 기록의 회귀·CI·서명·설치 및 물리 정지·DEVICE/FIELD 수용은 별도 확인해야 한다. 실패한 SHA의 사이트 빌드는 취소했으며 검토 기록을 보완한 후보가 CI를 통과하기 전 배포하지 않는다.
