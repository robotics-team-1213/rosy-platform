# D-856 중립 팔 owner 실행 검증

## 내부 transaction — commit 11486ce7cd

전체 grant와 opaque object_ref에 결속한 transaction 생성·snapshot·HOLD 복구를 구현했다. source/destination camera evidence나 Cell item/pallet을 만들지 않는다. 이 단계는 ActionRunner/API/Store 종류를 확장하지 않으며 실제 실행 권한을 열지 않는다.

RED commit `8274007b84`는 누락 consumer로 원격 16 failed였다. 첫 구현 `6af88c1158`은 신규·기존 소비자 73 passed였으나 독립 검토가 태그 두 개 삭제에 의한 legacy 성공 복구 우회를 발견했다. commit `e5a53fbc71`의 정확한 RED 1 failed 뒤 수정했다.

수정 commit `11486ce7cde22b0d700e05277772a7b6bb60b4d0`은 원격 **74 passed, skip0, 0 NEW/known/flaky**다. 새로운 중립 transaction, 기존 PickPlaceTransaction, Cell runner, 비활성 kind 거절, OMX transfer provider를 실행했다. 로그는 저장소 밖 `rosy-neutral-transaction-tags-green/run-1.txt`다. 독립 재검토에서 태그 삭제 finding 해소를 확인했다.

새 tag와 grant가 있으면 raw identity/generation/object/sensor·held flag를 검증하고 snapshot만으로 완료를 복구하지 않는다. 새 tag가 없으면 원래 legacy 형식의 object/observation 필수 참조를 요구한다. 정상 Cell/PICK snapshot 생성은 유지한다. 임의로 legacy 필드까지 주입한 자료의 parent kind·grant·durable journal 대조는 실제 owner recovery 연결 전 필수다. 이 helper는 parent 완료나 claim 해제의 권한 근거가 아니다.

## 남은 실행 범위

immutable 설치 결속, owner-admitted state·같은 clock의 계획/phase 검증, 기존 goal/gripper workflow, phase-only runtime와 v2 연결이 남는다. default owner 거절·shared control admission·stop/fence·재시도 금지·물리 자원 종료는 [owner 설계](../../plans/2026-10-24-neutral-arm-owner-design.md)를 따른다. 실제 neutral 제출·simulation HTTP·Harbor CargoMove 흐름과 장치 수용을 검증한 결과는 아니다.

CE: 해당 없음 — 구현 중 복구 검증 누락을 코드·회귀와 독립 검토로 보완했다.
