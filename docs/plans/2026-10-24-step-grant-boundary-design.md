# D-856 공통 step 시작과 Cell grant 검증 경계

**Status:** 독립 설계/구현 검토와 원격 집중 회귀 완료(2026-10-24). [전체 계획](2026-10-24-harbor-rosy-application-action-boundary.md)의 중립 팔 실행 선행 단계다. 공개 사전검사 구현은 [별도 증거](../validation/harbor-neutral-arm-preflight-2026-10-24/result.md)이며, 여기서는 새 kind·wire·dispatch를 열지 않는다.

## 확인한 결합과 사용할 기존 경계

`CellJobStore.start_step`은 `FleetCellTransferGrant.model_validate`로 고정 파싱하고 common identity 대조에서 `parsed.cell_transfer`의 job/step/recipe/cell을 직접 읽는다. 이후에는 이미 `step_action_kinds` registry의 `grant_model`, `body_field`, `body`를 사용한다. `_cell_transfer_body`는 같은 job/step/recipe/cell을 포함한 **전체 payload**를 원장의 고정 입력에서 생성한다. 원장의 직전 중복 검사를 제거해도 이 전체 payload 결속을 유지하면 Cell provenance를 생략하지 않는다.

registry는 이미 종류별 승인·허용 profile·typed grant·phase와 body 변환을 소유한다. 새 callback field나 workflow 프레임워크를 추가하지 않고 이 경계를 사용한다. DB 생성은 아직 Cell 전용이며 이번 변경이 그 문제를 해결했다고 표시하지 않는다.

## 정확한 내부 인터페이스

`step_action_kinds.parse_step_grant(grant: Mapping) -> BaseModel`은 등록된 action_kind의 grant_model로 엄격히 파싱한다. 등록되지 않은 종류와 grant_model이 없는 TRIP는 device Action으로 거절한다. `step_grant_digest`의 Mapping 분기도 이 파서를 재사용한다. BaseModel 분기의 기존 canonical digest 규칙은 유지한다.

`validate_step_grant(parsed, job, step, *, step_index, action_id, attempt_id) -> None`은 다음을 확인한다.

- 저장 step의 kind와 typed grant class, mission/step/action/attempt, workcell/instance, authority epoch와 dispatch generation이 모두 일치한다.
- registry body가 원장의 해당 step inputs로 만든 전체 payload와 typed grant의 body_field가 일치한다. Cell의 job/step/recipe/cell·자세·형상 참조·선택 SKU 검증도 여기서 유지한다.

공통 검증 함수는 Cell payload attribute를 직접 읽지 않는다. Cell body 변환은 기존 registry 항목이 계속 소유한다. `start_step`은 파서와 검증 함수를 호출하되 기존 digest·발행/만료 시각·READY/current step·stop/fence·sheet checkpoint·claim·중복·journal/이벤트 transaction 순서를 보존한다. 새 실행 경로를 만들지 않는다.

## RED·구현·검증

1. registry에 시험 전용으로만 등록한 비활성 physical kind로, Cell 필드가 없는 job/step/grant를 파싱·대조하는 단위 RED를 작성한다. 실제 registry·DB·public kind는 확장하지 않는다.
2. 기존 Cell fixture에서 올바르게 재서명한 recipe/cell/job/step·pose/item/pallet 변경이 모두 거절되는 시험을 둔다. scope/action/attempt/kind 불일치와 TRIP device grant 거절도 확인한다.
3. 커밋 RED를 공식 원격 runner에서 확인한 뒤 최소 경계 이동을 구현한다. CellJobStore의 크기는 줄이고 ratchet을 올리지 않는다.
4. 기존 Cell store/recovery/API·multi-arm ledger·sheet checkpoint·dispatch 회귀를 원격 검증한다. 거절 시 원장과 claim이 바뀌지 않고, admitted/inflight/UNKNOWN 보존이 동일해야 한다.
5. 독립 계약 검토로 기존 payload 결속이 빠지지 않았는지 확인한다. 실제 중립 kind의 생성·DB provenance·owner capability·phase 실행과 Harbor 변환은 후속 별도 계약으로 연결한다.

이번 단계에서는 fleet_cell_jobs의 recipe/cell/process 필수 column을 바꾸거나 다른 digest로 채우지 않는다. 성공한 action 뒤의 업무 관측·GOAL_CONFIRMED·claim 해제 의미도 바꾸지 않는다. 그 경계와 schema migration은 실제 producer/consumer와 데이터 보존 검토가 필요한 다음 단계다.

## 확인한 구현과 증거

commit `9830a33738`의 RED는 경계 함수 누락 12건, 기존 보존 시험 6 passed와 잘못된 enum fixture 1건이었다. item 변조 fixture를 허용되는 `slip_sheet`로 바꿔 실제로 재서명한 유효 모델의 payload 불일치를 검사하도록 고쳤다. 잘못된 enum을 새 허용값으로 구현하지 않았다.

commit `f3213debe8`에서 Cell store/recovery/API·multi-arm ledger·sheet checkpoint·단일 grant digest·release guard를 원격 검증해 **184 passed, skip0, 0 NEW**를 확인했다. commit `1b9ed965ab`의 별도 dispatcher/multi-arm dispatcher·owner identity/transport·API version·release guard 회귀는 **152 passed, skip0, 0 NEW**다. 두 실행에는 중복 검사가 있으며 수를 합쳐 독립 사례 수로 주장하지 않는다.

구현은 공통 검증의 transaction 위치와 기존 registry body를 유지했다. 독립 구현 검토는 typed kind/class·모든 공통 identity/fence·Cell의 전체 payload 결속이 남음을 확인했다. Store는 943→928줄로 줄이고 ratchet을 낮췄다. 검증 로그는 저장소 밖 `rosy-step-grant-boundary-green`, `rosy-step-grant-dispatch`에 보존했다.

이 결과는 새 neutral kind의 실제 DB 생성이나 실행 증거가 아니다. 선행 공개 사전검사 head의 FULL 결과와 이후 이 변경의 집중 회귀는 별도로 관리한다.
