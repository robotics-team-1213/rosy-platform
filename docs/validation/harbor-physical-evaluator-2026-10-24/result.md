# D-856 Fleet 두 표본 물리 검사

소스 commit `205cd087675df4748e981c75559b4f74e942bea3`. [실행 계획](../../plans/2026-10-24-neutral-transfer-closure-and-producer-design.md) 단계1의 내부 정책/관측 검사다. HTTP ingress·producer 자격 저장·현재 claim/fence transaction·실행 producer·Harbor ARM은 아직 연결하지 않았다.

World는 원본 관측을 소유하고 Fleet의 `physical_transfer_evidence.validate_transfer_observations`가 설치 정책과 durable attempt context를 대조한다. 함수는 DB·장치·시계를 열지 않고 전달된 server 시간으로 검사한다. 성공 시 반환값은 None이며 receipt·동작 권한·claim 해제가 아니다. 이후 coordinator가 현재 claims·owner·dispatch control/fence와 proof freshness를 같은 SQLite transaction에서 다시 확인해야 한다.

## 검사 범위

- 정책은 불변/closed 자료형으로 frame·object origin·source/target object pose·허용 오차·catalog/bindings·인증 producer ID/evaluator·전체 participant·모델/보정/변환·구역/여유와 정지/age/표본 간격을 고정한다. canonical digest는 이 값 전체를 포함하고 geometry link 집합을 정렬한다. 앱이 제출하는 정책이나 public DTO가 아니다.
- context는 durable action/attempt, phase, 경계 시각과 참가자 journal/session을 제공한다. PRE_DISPATCH는 READY claim 취득 이후 source, POST_ACTION은 durable 성공 이후 target을 확인한다. 함수가 durable 기록을 직접 조회하거나 그 존재를 증명하지는 않는다. 후속 coordinator가 해당 context를 자신의 원장에서 만들어야 한다.
- 서로 다른 evidence ID·증가 sequence인 정확히 두 관측을 요구한다. 각 관측의 object/link/gripper 원본 capture 시간이 모두 경계 이후·현재 이전·age 이내여야 하며 첫 관측의 마지막 capture와 두 번째 첫 capture 사이에도 최소 간격을 둔다.
- 모든 참가자 identity/revision과 정확한 전체 링크 집합을 대조한다. 실제 pinned URDF/mesh profile의 9개 링크를 줄이거나 미검토 모델로 바꾼 descriptor는 World 생성 invariant가 거절한다. 실제 설치는 여전히 asset loader의 bytes 검증 결과를 사용해야 한다.
- 각 링크는 선속도/각속도가 측정돼 있어야 하고 norm이 한계 이하여야 한다. None은 정지로 채우지 않는다. 여유를 더한 모든 공유 구역과 엄격히 떨어져 있어야 하며 경계 접촉도 거절한다. 이 첫 profile은 모든 참가자의 gripper OPEN/held NONE을 요구한다. 다른 참가자가 든 물체·부착물의 보수적 bounds는 아직 검토되지 않아 허용하지 않는다.
- object 위치는 명시적 model origin 기준의 거리, 방향은 q/-q 동치와 두 quaternion norm을 고려한 각도로 확인한다. grasp/EE 목표를 object 목표로 바꾸지 않는다. raw pose는 수정하지 않는다.

인증된 producer ID 인자는 향후 credential ingress가 제공할 신원이다. body의 producer_id만으로 인증하거나 global sequence/replay·evidence ID 충돌을 저장하는 구현은 아직 없다. 정책·관측 자료형의 생성 성공만으로 관측을 신뢰할 수 없다.

## 검증과 검토

- RED commit `1f2f07263d`: 원격25 errors/skip0, known25 NEW. 실제 asset fixture를 읽은 뒤 evaluator 누락 모듈로 실패했다. 원본 `rosy-transfer-evidence-red/run-1.txt`.
- 최초 source `a904c8682e`: Fleet 검사·holder import·World 전체가63 passed/skip0, exit0/known0 NEW였다. 원본 `rosy-transfer-evidence-green/run-1.txt`. 이 결과만으로 누락된 수용 조건을 닫았다고 보지 않는다.
- 최초 source a904 affected 전체2 invocations는 각각 **4499 passed/187 skipped/39 warnings/5 subtests**, **6310 passed/336 skipped/2 warnings**, 각 exit0/known0 NEW로 종료했다. 원본 `rosy-transfer-evidence-affected/run-1.txt`, `run-2.txt`. 이 원본 결과는 검토 보완 전 소스의 기록이며 최신205 검증과 합산하거나 대신하지 않는다.
- a904 고정 독립 검토는 P2 두 건을 찾았다. 허용된 quaternion norm 오차가 작은 tilt를 가렸고, 직접 생성한 축소 geometry descriptor가 전체 coverage로 수용될 수 있었다. 회귀 RED commit `b7cd0a9ff6`에서 원격4 failed/skip0, known4 NEW로 모두 재현했다. 원본 `rosy-transfer-evidence-review-red/run-1.txt`이며 혼합 node-ID 실행의 표시에 따른 `operations/world::` ID도 원본 그대로 보존한다.
- source205에서 World descriptor 생성 invariant와 norm을 고려한 각도 계산을 보완했다. 같은 SHA 독립 재검토는 두 finding 해소·추가 material finding 없음으로 종료했다. source 구간 size/safety 3eed→a9042 commits, a904→2052 commits 각각 exit0다.
- source205의 focused GREEN은 **67 passed/skip0**, exit0/known0 NEW다. Fleet 검사·holder import·World 전체를 포함하며 `rosy-transfer-evidence-review-green/run-1.txt`에 보존한다.
- source205의 공식 affected 선택 전체2 invocations가 종료했다. run1은65 targets **4587 passed/189 skipped/39 warnings/5 subtests**, run2는 Fleet 전체 **6312 passed/336 skipped/2 warnings**, 각각 exit0/known0 NEW다. 원본 `rosy-transfer-evidence-205-affected/run-1.txt`, `run-2.txt`. skips는 수용 증거로 세지 않고 집중 검사와 합산하지 않는다. 원격34244·63132와 이전53459 모두 종료 상태다. 최초 a904 결과와205 결과는 소스와 selector 목록이 다르므로 구별한다.

이 검사는 주입한 물리 사실에 대한 host 검증이다. 실제 관측의 bounds 정확도·물체 센서·부착물·현장 진입자·실물 팔 퇴피를 수용하지 않는다. 배포·push·병합·실물 실행 없음. CE: 해당 없음 — 두 검토 finding의 원인과 수정은 source·회귀·이 기록에서 직접 확인된다. 이전 e26 G1 timing 원인 미확정은 기존 기록에서 별도로 유지한다.
