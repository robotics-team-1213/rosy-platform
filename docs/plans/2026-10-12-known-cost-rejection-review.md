# 검증된 비용이 있는 판정 형식 오류의 제한 재평가

실제 `VersionedLocalProvider`·`VersionedCliProvider`는 판정 JSON을 검증하다 실패하면 비용을 worker에 전달하지 못했다. 원래 요청과 비용을 검증한 응답도 UNKNOWN으로 저장되어, 같은 사건의 제한 reviewer 경로에 진입하지 않았다. 이 변경은 기존 직접 호출자의 `ValueError` 계약을 유지하는 내부 예외로 이 누락을 보완한다. 새 공개 JSON·receipt·운영 수용 계약은 만들지 않는다.

`contracts.billing`의 공개 `RejectedJudgment`(2026-10-27 이전 내부 `_RejectedJudgment`)는 기존 immutable BoundProfile, 검증된 숫자 비용, 보수적인 unsafe 표시만 담는다. Local은 모델·revision·usage·free-cost envelope를 검증한 다음, CLI는 승인된 transport의 숫자 비용을 검증한 다음 이 오류를 만든다. 검증할 수 없는 billing receipt가 있으면 이 경로를 쓰지 않는다. 깨진 응답 본문·모델 주장은 예외나 원장 receipt·근거·review prior에 저장하지 않는다.

Fleet worker는 예외의 정확한 타입과 현재 BoundProfile·입력·프로파일·비용 한계를 다시 확인한다. 검증된 형식 오류는 REJECTED와 숫자 비용을 같은 기존 원장에 기록한 뒤 같은 사건의 reviewer를 호출한다. reviewer도 기존 역할별/전체 호출·비용·시간·현재성 한도를 사용한다. unsafe는 최종 HOLD로 넘기며 재평가로 해제하지 않는다. 비용·제공자 근거 또는 오류 결속이 불명확하면 UNKNOWN/HOLD와 보수적인 예약을 유지한다. 숫자 비용은 실제 invoice 또는 물리 성공 증거가 아니다.

작업은 등록 worktree `.worktrees/wt-known-cost-a720c9`, branch `feat/known-cost-review`에서만 수행한다. 원격 시험과 로그는 기존 X: 세션의 `logs/known-cost-*`를 사용한다. source commit은 검토/검증 대상이며 main 착지·push·운영 설정·모델/장치 호출은 이 작업에서 하지 않는다. Jev/Laya v2 어댑터, 실제 운영 품질과 설치 증거는 이 보완으로 완료되지 않는다.

## 검증 checkpoint

- `6dbf700f7`: 실제 Local/Claude/OpenCode codec→worker에서 파싱 가능한 잘못된 판정과 깨진 JSON 6건의 RED를 적격 AI PC(여유 메모리 8.8GB)에서 확인했다. terminal exit 1, known_failures 6 NEW. 기존 불명확 비용·제공자 근거/직접 ValueError 호환 검사는 통과했다.
- `ae8650196`: unsafe의 검증된 비용 보존 회귀를 추가했다. 모든 원격 시험 호스트가 연결되지 않아 120초 대기 후 NOT_RUN으로 끝났다. 추가 RED/GREEN은 확인하지 못했다.
- 변경된 결속(input/profile/type/cost) 거절 회귀와 실제 wheel/sdist·기존 worker/codec/원장/P6 영향군의 committed-head GREEN은 원격 호스트 복구 후 확인해야 한다. 확인 전 착지·push하지 않는다. 노트북 pytest와 실제 제공자 호출은 수행하지 않았다.
- Source `a95c5c1cb`: 소유한 5개 구현 파일의 stdlib AST 문법 검사는 통과했다. harness lint는 terminal exit 0, 오류 0·기존 검증 revision 경고 29건이다. 실제 P6 physical-line 필터로 contracts 374/382, providers 255/354, execution 376/449를 확인했다. 부모 deliberation 349/381과 evaluation 386/425도 기존 한도 이내다. root의 독립 소스 검토에서 중요 blocker는 발견되지 않았으나 최신 원격 GREEN은 미확인이다.

모든 기존 P6 기준과 한도를 유지한다. 내부 예외는 기존 계약 holder에, transport 오류 변환은 기존 provider holder에, 제한 재평가는 기존 worker에 둔다. 새 서비스·DB·writer·운영 승인 포트는 추가하지 않는다.
