# D-856 World 물리 관측 자료형

소스 commit: `0849ce482533498ef183127cb8f09b18298b14c0`(최초 raw-facts commit `037c29121f`). [승인된 실행 계획](../../plans/2026-10-24-neutral-transfer-closure-and-producer-design.md) 단계1의 raw-facts 부분이다. producer 인증·두 표본 freshness/coverage/목표 pose 판정·claim 해제는 아직 연결하지 않았다.

World에 불변 PhysicalPose/Bounds3/LinkPhysicalState/ArmPhysicalState/TransferObservation을 추가했다. metre/radian 단위, unit quaternion, finite vector, 원래 capture 시각, object origin·frame, model/policy/catalog/bindings와 participant journal/session을 보존한다. 누락 object pose/links와 UNKNOWN gripper/held state를 그대로 표현한다. producer의 list/map을 복사·동결하고 관측 생성 성공을 satisfied/clearance로 승격하지 않는다. 기존 normalized ArmState는 유지한다.

미측정 선속도/각속도는 각각 명시적인 None으로 보존하며 0을 채우지 않는다. 관측된 bounds가 있어도 미측정 속도로 정지를 증명할 수 없다. 후속 Fleet evaluator는 required link의 두 속도 중 하나라도 None이면 정지 기반 완료/해제를 허용하지 않아야 한다.

## 검증

- RED commit `072e268f45`: 공식 원격17 failed/skip0, 누락 모듈을 확인했다. 원본 `rosy-world-transfer-facts-red/run-1.txt`, known17 NEW다.
- source037의 공식 `remote_pytest --sha 037c29121f -- operations/world/test`: **27 passed/skip0**, exit0/known0 NEW. 별도 임시 wheel을 설치한 isolated Python에서 새 모듈·숫자 단위를 확인하며 Fleet/omx_adapter import가 없음을 단언했다. 원본 `rosy-world-transfer-facts-green/run-1.txt`다.
- baseb968→037의 공식 affected 선택 전체 한 invocation: **763 passed/2 skipped/39 warnings**, exit0/known0 NEW. 원본 `rosy-world-facts-037-affected/run-1.txt`다. World·영향받는 Fleet·기존 map/traffic·관련 guard를 포함하며 skips는 수용 증거로 세지 않는다.
- 고정 source037의 독립 계약 검토는 material finding 없음이다. size/safety는각1 commit, exit0였다. 새 API/producer/장치 writer·추가 runtime 의존성을 만들지 않았다.
- 후속 RED commit `afa4804279`는 기존 자료형이 None 속도를 표현하지 못하는 1 failed/skip0를 확인했다. source084의 World 전체는 **28 passed/skip0**, affected 선택 전체는 **764 passed/2 skipped/39 warnings**, 각각 exit0/known0 NEW다. 원본은 `rosy-world-velocity-red`, `rosy-world-velocity-green`, `rosy-world-velocity-084-affected`의 run-1.txt다. source084 고정 독립 검토에도 material finding은 없었다. 037과084 검증은 겹치므로 합산하지 않는다.

이 결과는 내부 자료형과 패키징의 host 검증이다. 실제 관측 producer나 물체 접촉·전체 링크 이탈·정지 시간·실물/현장을 증명하지 않는다. 순서/신선도·인증·collision model coverage와 정책 대조는 다음 Fleet 소비자에 남으며 raw dataclass를 직접 생성해 우회할 수 있는 실행/해제 경로는 없다.

## 다음 입력의 확인

기존 kinematics YAML은 pinned URDF의 관절 기하를 옮긴 값이다. 다음 coverage 구현에는 실제 로컬 `learning/envs/isaac/assets/open_manipulator_description/urdf/omx_f/omx_f.urdf`와 참조 mesh를 사용한다. 정규화 URDF SHA-256은 기존 kinematics source pin과 일치하고 mesh 8개가 존재한다. 모델에는 collision이 있는 link0..link7 외에 collision 없이 1cm visual box를 가진 end_effector_link가 있으므로, collision 개수나 관절 개수만으로 모든 링크의 범위를 단정하지 않는다. 해당 기하를 보수적으로 포함하거나 검토된 모델 규칙을 명시한 coverage를 먼저 검증한다. 이 조사 자체는 형상/퇴피 수용이 아니다.

실물 실행·배포·push·병합은 하지 않았다. CE: 해당 없음 — 자료형/회귀/이 기록이 검증 책임과 불완전 관측의 의미를 보존한다. 과거 e26 G1 timing의 미확정 원인은 기존 기록에서 별도로 유지한다.
