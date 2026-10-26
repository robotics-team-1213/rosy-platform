# D-856 중립 팔 owner 실행 검증

## 내부 transaction — commit 11486ce7cd

전체 grant와 opaque object_ref에 결속한 transaction 생성·snapshot·HOLD 복구를 구현했다. source/destination camera evidence나 Cell item/pallet을 만들지 않는다. 이 단계는 ActionRunner/API/Store 종류를 확장하지 않으며 실제 실행 권한을 열지 않는다.

RED commit `8274007b84`는 누락 consumer로 원격 16 failed였다. 첫 구현 `6af88c1158`은 신규·기존 소비자 73 passed였으나 독립 검토가 태그 두 개 삭제에 의한 legacy 성공 복구 우회를 발견했다. commit `e5a53fbc71`의 정확한 RED 1 failed 뒤 수정했다.

수정 commit `11486ce7cde22b0d700e05277772a7b6bb60b4d0`은 원격 **74 passed, skip0, 0 NEW/known/flaky**다. 새로운 중립 transaction, 기존 PickPlaceTransaction, Cell runner, 비활성 kind 거절, OMX transfer provider를 실행했다. 로그는 저장소 밖 `rosy-neutral-transaction-tags-green/run-1.txt`다. 독립 재검토에서 태그 삭제 finding 해소를 확인했다.

새 tag와 grant가 있으면 raw identity/generation/object/sensor·held flag를 검증하고 snapshot만으로 완료를 복구하지 않는다. 새 tag가 없으면 원래 legacy 형식의 object/observation 필수 참조를 요구한다. 정상 Cell/PICK snapshot 생성은 유지한다. 임의로 legacy 필드까지 주입한 자료의 parent kind·grant·durable journal 대조는 실제 owner recovery 연결 전 필수다. 이 helper는 parent 완료나 claim 해제의 권한 근거가 아니다.

## 내부 transaction 단계의 검증 한계

위 transaction 시험은 설치 결속·실제 phase 실행을 검증하지 않았다. 해당 후속 결과는 아래에 기록한다. default owner 거절·shared control admission·stop/fence·재시도 금지·물리 자원 종료는 [owner 설계](../../plans/2026-10-24-neutral-arm-owner-design.md)를 따른다. 실제 Fleet neutral 제출·simulation HTTP·Harbor CargoMove 흐름과 장치 수용의 증거는 아니다.

CE: 해당 없음 — 구현 중 복구 검증 누락을 코드·회귀와 독립 검토로 보완했다.

## 설치 factory와 phase-only IPC — v1.305

feature commit `45173e6f927749910f5b865f790b1154b865282d`는 immutable 설치 결속과 기존 planner/phase/그리퍼 workflow를 연결했다. ARM은 shared control admission과 IPC v2를 요구하고 direct driver에는 추가하지 않았다. factory가 없는 기본 owner는 journal 전에 거절한다. workflow 상태 metadata는 leaf로 옮겨 Store ratchet을 1141→1135로 낮췄다. 기존 PICK/CELL metadata 값은 유지했다.

RED commit `01e3a174cd`는 factory 누락 9 failed였다. 첫 GREEN 요청에서 150 passed/3 failed를 확인했다. 세 실패는 재개방 시험의 같은 generation rearm과 잘못 기대한 그리퍼 예외 타입이었으며, production의 fence·그리퍼 거절 동작을 바꾸지 않고 시험을 고쳤다.

test-only commit `337e42e314`에서 신규·기존 owner/Action API/store/stop/runner/transaction/provider **153 passed, skip0, 0 NEW/known/flaky**를 확인했다. 로그는 저장소 밖 `rosy-neutral-owner-phase-final/run-1.txt`다. 네 phase의 실제 analytic 계획·durable journal과 합성 goal/gripper ports를 실행했다. 그리퍼 다른 물체/응답 실패, 설치 없음, v1, shared control 없음, catalog/object/policy 불일치, stale/calibration/transform, 완료 직전 revision/stop 변경, 중복 송신 금지와 재개방한 원장의 GET을 포함한다.

실제 ROS owner와 장치 동작을 시험한 결과는 아니다. 테스트의 measured-state와 goal/gripper ports는 합성 입력이다. 실제 owner-admitted state 조립과 독립 HTTP 흐름은 후속 통합에서 검증해야 한다. 공개 Fleet producer·등록 kind·물리 자원 종료·Harbor 업무 완료도 아직 미연결이다.

## Fleet의 중립 v2 client

kind→protocol map의 ARM 누락을 commit `2445c09a68`에서 6 failed로 확인했다. commit `fc5d75eecd`는 기존 v2 transport·grant type union·공통 receipt 타입에 ARM을 추가했다. 관련 원격 **15 passed/skip0/0 NEW**와 독립 검토를 확인했다. `rosy-arm-transport-green/run-1.txt`는 submit/get/cancel의 v2 framing, phase summaries 누락 거절과 기존 Cell/digest 경계를 포함한다. 교환 port는 합성 응답이며 실제 UDS/HTTP 통합 결과와 구별한다.

[독립 소스 검토](source-review.md)와 feature의 Safety-Review trailer는 코드 검토 근거이며 물리 안전 수용 attestation이 아니다. 이후 affected 전체 선택의 원격 결과는 별도 기록한다.
