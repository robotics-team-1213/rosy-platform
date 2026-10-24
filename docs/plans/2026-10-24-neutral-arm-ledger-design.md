# D-856 중립 팔 원장 provenance와 기존 데이터 보존

**Status:** schema migration과 Cell 소비자 차단 구현·집중/affected 원격 회귀·독립 검토 완료. physical 생성·dispatch는 후속이다. [실행 계약](2026-10-24-neutral-arm-execution-design.md)의 grant 모델을 실제 원장으로 연결하는 단계다.

## 현재 제약

`fleet_cell_jobs`는 공통 mission/request key·actor·scope·fence·상태·resource와 Cell의 job/recipe/cell/process 필수 provenance를 함께 저장한다. 기존 TRIP producer도 이 테이블을 사용한다. `fleet_cell_steps`, events, sheet checkpoint, per-arm job/action/marker가 parent mission을 참조한다. `step_ledger_schema.ensure`는 kind CHECK를 재구성한 뒤 per-arm mirror를 다시 설치한다.

중립 grant의 물리 digest를 recipe/cell/process column에 채우지 않는다. 기존 TRIP이 사용하던 역사적 표현도 이번 migration에서 다시 해석하거나 바꾸지 않는다. 공통 SQLite 실행 원장과 claim은 재사용하고 별도 DB·중계 서비스는 만들지 않는다.

## 제안하는 최소 schema 변경

parent에 `provenance_kind`를 추가한다. 기본값 `legacy`는 지금 존재하는 모든 row의 저장 형식을 뜻하며 Cell recipe 검증을 통과했다는 새 주장이 아니다. 새 `physical`은 중립 물리 실행 형식이다. `job_id`, `recipe_digest`, `cell_digest`, `process_artifact_digest` 네 column만 nullable로 바꾸고 다음 CHECK를 둔다.

- `legacy`: 기존 네 column이 모두 NOT NULL이다. 현재 값·JSON·상태는 그대로 보존한다.
- `physical`: 네 legacy column이 모두 NULL이다. `job_json`에 승인 대상의 엄격한 물리 요청을 저장한다. 물리 참조와 request digest의 검증은 typed creator가 담당한다. 임의 JSON이 physical 실행을 승인하지 않는다.

나머지 공통 column·PK·상태·fence는 유지한다. `job_json`과 별도의 중복 물리 JSON column은 추가하지 않는다. 이 단계에서 테이블 이름을 바꿔 기존 FK·SQL 소비자를 한꺼번에 전환하지 않는다. `legacy` 기본값 덕분에 기존 명시 column INSERT는 동일하게 동작해야 한다. SELECT *를 positional tuple로 푸는 소비자와 INSERT SELECT *는 새 column 전후를 따로 검증한다.

## atomic migration과 실패 조건

SQLite는 NOT NULL 변경에 parent 재구성이 필요하다. schema 변경은 독립 시작 연결에서 다른 writer를 막는 transaction 하나로 수행하고, 이미 transaction 중이면 암묵 commit으로 넘기지 않고 거절한다. FK enforcement 변경이 필요하면 transaction 전 이 연결에만 적용하고 finally로 원상 복구한다. 저장소 연결 기본 정책을 완화하지 않는다.

정확한 table/column 목록과 기존 index·trigger·view SQL을 조사한 뒤 새 parent에 explicit column list로 복사한다. child의 FK 대상 이름은 유지한다. drop/rename 과정에서 mirror trigger나 view가 깨지거나 기존 row를 다시 backfill하지 않도록 의존 정의의 보존·복원 순서를 정한다. FK 검사를 생략하거나 `legacy_alter_table`에 의존해 미검증 성공으로 처리하지 않는다.

원본 row·step/event/claim·per-arm mirror와 JSON·UNKNOWN/HELD/attempt/journal을 비교하고 `foreign_key_check`가 비었을 때만 migration version을 기록·commit한다. 중간 어느 SQL이 실패해도 이전 schema·row·trigger·version이 그대로여야 한다. 재실행은 no-op이며 미래 version을 이전 코드가 읽으면 기존처럼 명시적으로 거절한다. 이 절차의 정확한 SQL 순서는 RED 시험으로 확인한 뒤 구현한다.

## 생성·읽기·복구 경계

schema migration만으로 physical row를 만들거나 ARM_TRANSFER를 registry에 넣지 않는다. 다음 creator는 설치된 catalog/binding/resource policy와 two-person 승인 snapshot을 결속한 물리 요청만 생성한다. request key는 기존 principal scope/CAS/idempotency를 유지한다.

legacy Cell producer·read route·recipe 승인 경로는 physical row를 받아 Cell로 해석하지 못해야 한다. shared start-step의 typed grant 검증·claim/fence·journal transaction을 재사용하되, 기존 Cell checkpoint와 read projection을 그대로 호출해 physical row를 Cell 공정으로 만드는 것은 허용하지 않는다. 실제 callback/SQL 경로를 조사해 공통 부분과 legacy adapter를 나눈다. 새 HTTP read는 creator scope와 physical provenance를 함께 검사한다.

현재 `read_cell_job`은 `dict(row)`를 그대로 반환하므로 새 내부 discriminator를 legacy 응답에 노출하지 않도록 projection을 보존한다. `jobs_by_status`/`unresolved_jobs`, `cell_arm_jobs.single_arm_jobs`, sheet의 `recover_ready`는 parent를 넓게 읽으므로 physical row를 공정 dispatch/checkpoint 대상으로 선택하지 않게 한다. mirror trigger의 job/step JSON 조건도 새 형식을 Cell로 해석하지 않는지 검사한다. 이 소비자 분리를 schema 준비와 같은 변경에서 수행한 뒤에만 typed physical creator를 연결한다.

startup/site-stop의 보존 hook은 physical mission 점유도 유지해야 한다. cancel/resume/reapproval와 성공/공유 구역의 해제 조건은 실행 계약의 물리 종료 증거를 따른다. migration이 이 조건을 구현했다는 주장은 하지 않는다.

## RED와 수용 기준

1. 기존 schema에 Cell·TRIP·부분 실행·UNKNOWN·HELD·sheet·per-arm mirror·events·claims를 넣고 migration 후 전체 legacy 값과 FK/index/trigger 동작을 비교한다.
2. physical row에서 legacy provenance를 모두 비워야 하며 혼합 형식·알 수 없는 kind는 DB가 거절한다. 기존 legacy INSERT·startup·read/recovery 회귀가 유지된다.
3. 실패 주입·재실행·미래 version·이미 열린 transaction·동시 시작 연결에서 부분 migration이나 claim 해제가 없는지 확인한다. 실패 후 정상 migration이 가능해야 한다.
4. 공통 원장·arm mirror·sheet·TRIP·dispatcher·site-stop 회귀를 공식 고정 SHA로 실행한다. 집중 통과와 FULL 결과를 구분한다.
5. 독립 계약/데이터 보존 검토 후에만 물리 creator와 실행 소비자를 연결한다. 스키마 준비만으로 팔 접수·실행·업무 분리가 완료됐다고 기록하지 않는다.

독립 검토는 최소 parent 재구성과 legacy TRIP 보존 방향에 material finding이 없음을 확인했다. discriminator의 명시적 NOT NULL/CHECK, lock 후 version 재확인·마지막 version 기록, FK 정책 복원과 의존 정의 동작 비교, physical 소비자 차단을 SQL 구현의 필수 조건으로 확인했다. 현재 source의 `_MIGRATION_VERSION`은 4이며 새 migration은 이를 기준으로 한다. 기존 초기화의 `executescript`나 version INSERT를 새 atomic transaction 안에 무심코 재사용하지 않는다.

## 구현과 확인

production commit `dda08892c9`에서 version5로 구현했다. 별도 initializer가 parent/child 초기화 transaction을 소유하며 기존 SQL statement 실행 helper를 재사용해 implicit commit을 피한다. Store는 928→876줄로 줄였다. 기존 Cell 읽기에서 새 내부 discriminator를 숨기고, by-ID·목록·복구·checkpoint·단일 팔 stop 소비자가 physical 행을 Cell 공정으로 선택하지 않게 했다.

독립 구현 검토는 동일 column이지만 DEFAULT/enum/union CHECK가 없는 schema의 수용을 지적했다. 두 RED를 확인한 뒤 알려진 legacy/current CREATE문 전체를 대조하도록 고쳤고 재검토에서 finding이 해소됐다. 정확한 schema 표기만 지원하는 제한은 유지한다. 이후 원격 69개, 추가 실패·checkpoint 보존 13개, 기존 소비자 244개 회귀가 각각 통과했다. [소스·실패 이력·한계](../validation/harbor-neutral-arm-ledger-2026-10-24/result.md)를 따른다. 아직 physical creator나 새 실행 종류가 생긴 것은 아니다.
