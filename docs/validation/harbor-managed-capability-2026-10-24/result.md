# D-856 실제 owner capability와 canonical receipt 검증

소스 commit: `46f56d6b481af9d7af50c29a546d8a5ceb15547a`, API v1.306. [계약 설계](../../plans/2026-10-24-managed-transfer-capability-design.md)와 [독립 소스 검토](source-review.md)를 따른다. 새 Fleet physical producer/claim 해제는 아직 활성화하지 않는다.

## 확인한 범위

공식 원격 runner의 고정 소스 실행은 `contracts/foundation/test/test_arm_transfer_capability_contract.py`, 같은 폴더의 grant contract, `middleware/devices/omx/adapter/test` 전체, Fleet의 arm capability/arm action/cell action transport, root의 managed capability/neutral owner/transfer provider 총 9 targets다. **790 passed, 7 skipped, 2 warnings**, exit0, `known_failures.py` **0 NEW**다. 원본은 저장소 밖 `rosy-managed-capability-green/run-1.txt`에 보존한다. skipped 7건은 수용 증거로 세지 않는다.

실제 UDS와 canonical SQLite identity를 사용하는 capability 조회, 미설치/unmanaged/disabled/다른 owner/세션·저널·scope 교체 거절, read가 누락 identity를 만들지 않음, pre-journal 목표 owner 거절, 실제 snapshot journal을 통한 receipt와 재시작 후 과거 Action 조회를 포함한다. SDK는 capability scope/형식을 대조하고 ARM receipt의 journal 불일치와 404를 unavailable로 유지한다. planner/goal/gripper/measured state는 시험 주입이며 실제 ROS나 장치 동작·현장 안전을 증명하지 않는다.

RED commit `f6c3a7195e`는 35 failed/2 passed/skip0, known35NEW였다. 누락 capability DTO/API/SDK와 목표 owner/receipt/404 소비 경계를 확인한 뒤 구현했다. feature commit의 고정 SHA 독립 재검토는 material finding 없음이며 size/safety 각 1 commit, exit0다. local harness lint는 0 errors/33 warnings였다.

## FULL 실행 중

base commit `7838eb3cad`부터 소스 commit `46f56d6b48`까지 공식 selector는 FULL이다. 원본 `rosy-managed-capability-46-selection.json`의 full_invocations는 23개다. 원격 runner는 FULL JSON에서도 기본적으로 mapped local_invocations 3개를 고르므로, 별도 `rosy-managed-capability-46-full-execution.json`에서 local_invocations를 원본 full_invocations 23개와 완전히 같게 확장했다. mode/full 목록/targets를 유지했고 skip filter를 넣지 않았다.

`tools/remote/remote_pytest.py --sha 46f56d6b48 --affected-json <external>/rosy-managed-capability-46-full-execution.json --log-dir <external>/rosy-managed-capability-46-full`을 실행 중이다. 모든 run-N의 실행/skip/수집 오류/known failure 분류와 최종 runner exit를 확인한 뒤 결과를 기록한다. 현재 집중 결과를 FULL 통과로 표시하지 않는다.

## 다음 단계와 한계

capability는 설치 사실이며 admission/idle/계획 가능성·충돌 검사·자원 해제의 증거가 아니다. World의 현재 ArmState는 표시용 정규화 관절값이며 object_state를 unobserved로 강제한다. 이 값을 물체 배치·전체 링크 퇴피 근거로 사용하지 않는다. physical producer는 별도의 trusted 물리 관측과 승인 snapshot·step/claim을 결속한 후 연다. Harbor의 업무 완료 판정도 독립 관측을 계속 요구한다.

실물 활성화·배포·push·병합은 수행하지 않았다. CE: 미해결 — 이전 e26 G1 timing 실패의 원인은 미확정이다. 이번 source/test/design이 판단을 보존하므로 별도 해결 교훈은 만들지 않았다.
