# D-856 원장 provenance migration 검증

기존 Cell/TRIP 원장을 보존하면서 물리 실행 형식을 구분하는 schema 준비를 검증했다. physical creator·중립 grant 발행·owner 실행·Harbor 공정 변환은 아직 연결하지 않았다.

## 변경과 소스

commit `dda08892c9efb4c88bf7b86c1c0f71906b497bd0`의 production 코드는 version5 parent migration과 기존 Cell 소비자의 physical 행 차단을 구현한다. schema·row 복사·index/trigger/view 복원·step/sheet 초기화·FK 검사·version 기록은 BEGIN IMMEDIATE transaction 하나에 있다. 실패 시 rollback하고 FK ON 정책을 복원한다. 알려진 legacy/current CREATE문 전체와 맞지 않는 schema는 거절한다. 의미가 같더라도 다른 SQL 표기의 DB는 이 migration이 지원하지 않는다.

## 수행한 원격 검증

| 소스 commit | 범위 | 실제 결과 |
|---|---|---|
| `00d9826636` | migration RED | 누락 모듈 9 failed |
| `2da5caf7e1` | 첫 migration·기존 원장 | 65 passed/1 failed: 기존 시험의 version4 기대 |
| `7b393ada52` | 동일 column·제약 없는 schema | DID NOT RAISE 2 failed로 독립 검토 지적 재현 |
| `dda08892c9` | 엄격한 schema 검증·원장·mirror·grant | 69 passed/skip0/0 NEW |
| `30d37a1bd7` | checkpoint·중간 SQL 실패 추가 보존 | 13 passed/skip0/0 NEW |
| `ed89b49b73` | Cell API/복구·다중 팔 dispatch/goal·sheet·TRIP·module 구조 | 244 passed/skip0/0 NEW |

두 version pin은 새 schema version5를 기대하도록 고쳤으며 이전 reader 거절 조건을 약하게 하지 않았다. migration의 실제 데이터 fixture는 이전 v4 schema, Cell/TRIP row, UNKNOWN/HELD claim, 이벤트, per-arm mirror, sheet checkpoint, custom view/trigger/index를 포함한다. rollback·미래 version·열린 transaction·동시 초기화·FK 위반·CREATE VIEW 복원 중 SQL 실패와 재시도도 확인했다. 각 실행은 일부 중복 검사이므로 수를 독립 사례 수로 합산하지 않는다.

로그는 저장소 밖 `rosy-job-provenance-*` 디렉터리에 보존한다. 최종 GREEN은 `constraints-green`, `sql-failure`, `compatibility-final`의 run-1.txt다. 독립 계약 검토가 지적한 약한 schema 수용을 RED 뒤 수정했고 재검토에서 해소를 확인했다. size_range와 safety_review를 통과했으며 현재 변경 경로는 manifest의 safety-tagged 경로가 아니다.

## 남은 범위

migration 이후 영향 선택은 affected이며 전체 선택의 원격 결과는 별도 기록한다. 선행 grant FULL은 commit `8da8bb1593`으로 이 migration을 포함하지 않는다. 실제 physical 생성·요청 scope·승인·fence·owner phase/recovery·모든 claim 해제 입구의 물리 종료 증거와 Harbor 연결은 후속이다. 실물·배포·push는 수행하지 않았다.

CE: 해당 없음 — 정상 구현 중 발견한 검증 누락을 코드·회귀·독립 검토 기록에 남겼다.

## 후속 affected 전체 선택 — commit 635d1e226e

source와 영향 선택을 commit `635d1e226e9344736df427b4be7863f7f48ef61c`으로 고정한 공식 원격 실행이 exit0으로 끝났다. `rosy-job-provenance-affected/run-1.txt`는 **4722 passed/187 skipped/39 warnings/5 subtests passed**, run-2는 **6270 passed/336 skipped/2 warnings**다. 각 보고서의 known_failures 비교는 0 NEW/known/flaky다. skip은 browser·환경 의존 수용을 실행했다는 증거로 쓰지 않는다.

이 소스는 이후 owner transaction/factory/runtime 변경을 포함하지 않는다. 해당 검증은 [owner 기록](../harbor-neutral-arm-owner-2026-10-24/result.md)에서 따로 관리한다.
