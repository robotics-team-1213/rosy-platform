# 복구 ACT 모델의 calibration 통과와 engineering HOLD

2026-10-24 KST 결과다. [실제 학습·재로딩을 검증한 모델](../omx-recovered-teacher-training-2026-10-24/result.md)에 사전 고정한 평가를 한 번 적용했다. 실제 runtime source는 commit `8d119665da8f`, 부모 policy revision은 `sha256:30bba42551e85be5007d45fcef6a7e36268bad711d8bd85905ad383113cc1326`이다. **calibration은 통과했고 engineering1회는 실패했다. formal20회는 시작하지 않았다.**

## 사전 고정과 실행 순서

원래 evaluator·동결7개·복구 protocol은 변경하지 않았다. 별도 `evaluate_recovered_teacher.py`와 manifest를 독립 검토한 뒤 실행했다. manifest의60개 source pins와 manifest 자체를 원래 evaluator의 동일 source map에 추가했다. 매 자원 대기와 실제 호출 직전에61개 해시를 검사하며 이후 재기준화하지 않는다. 원격 MODEL 파일 fixture에서 동일 map 보존과6개 위반 거부를 확인했다. 이는 ML·정책 trial이 아니다.

평가 기준은 calibration1회→engineering1회→formal20회/18성공이다. engineering이 실패하면 formal은 시작하지 않으며 실패 대체·추가 optimizer·기준 조정은 없다. AI 역할 검사 PC에서 자원·미종결 actor·저장 공간 조건을 새로 확인했고, 시작 전 두 headroom 관측을 통과했다. 실물 권한은 없다.

## 실제 calibration

위 source commit을 접두사로 쓰는 native ID suffix `5e00180bfe37`은 종료0, `calibration_pass=true`·`cleanup_verified=true`다. 부모 모델을 설치한 검사 PC의 실제 추론 경로에서12개 policy step을 검사했고 정책 목표는0개였다. 이 결과는 모델 로딩·연결의 근거이며 물체 이동 성공률이 아니다.

95개 archive 파일·extraction map·원본 결과·source revision·exit를 byte 단위로 대조했다. main PID0·inactive/dead·빈 cgroup·잔여 cgroup 없음·lock/예약 없음을 확인한 뒤 engineering으로 진행했다.

## engineering1회: HOLD

위 source commit을 접두사로 쓰는 native ID suffix `791f6a0c8160`은 실제 종료1이다. calibration과 같은 부모 모델·고정 evaluation 입력을 사용했다. 초기 자세 준비는 ready로 끝났으며 이후 learned goal170개가 수락됐다. terminal 결과는169개 성공(status4/result0), 마지막1개 실패(status6/result−5)다.

마지막 goal의 JTC 로그는 관절 인덱스3·4에서 위치 오차−0.054164rad·−0.034553rad가 각각 허용0.020000rad를 넘었고, `goal_time_tolerance`를1.010000초 초과해 abort했다고 기록한다. 명령 자체의 최대 변화는0.035rad 범위 안이었다. 작은 출력 변화와 낮은 오프라인 오차가 실제 추종·장기 작업 성공을 보증하지 않는다.

정책 실행기는 native 실패를 그대로 `PermissionError: native learned goal did not succeed`로 보존했고 owner는 hold로 끝났다. admission rejection은 없었고 camera error·worker error도 없었다. object attach/detach 기록은 비어 있다. 기록된 lift0m·xy error약0.22872m는 `incomplete_trial_observation`이며 완성된 물체 작업 평가로 해석하지 않는다.

253개 archive 파일·map·원본 result/exit·같은 source/run을 대조했다. 07:44:18 KST 종료 관측은 main PID0·failed·빈 cgroup·실제 exit1·잔여 cgroup 없음·lock/예약 없음이다. `cleanup_verified=true`와 process cleanup의 잔여 없음도 확인했다. 로컬 coordinator는 원래 규칙대로 `engineering trial failed; formal evaluation not started`로 종료1, 최종 ledger는 HOLD·formal 시작0회다. 이를0/20 성공률이나20회 평가 실패로 기록하지 않는다.

## 확인된 사실과 미해결 원인

독립 검토에서 SQLite command/goal 연결·170개 terminal·마지막 native 코드·동결 owner/ROS action adapter의 실패→HOLD 경계를 대조했다. 실패를 성공으로 승격한 근거는 없었다. 실제 frame170개·관측·명령·native event·제어기 로그를 보존한다.

확인된 중단 원인은 JTC 목표 허용오차 초과다. 추종 오차를 만든 물리 접촉·하중·제어 동역학 또는 학습 정책 rollout 이탈은 아직 구분하지 못했다. 마지막 gripper 값이나 사진만으로 그리퍼 계약 거부·물체 손실을 확정하지 않는다. 다음 진단은 마지막 목표의 실제 관절 추종·속도와 접촉/하중 관측을 함께 대조하는 사전 고정 검사다. 현재 protocol을 수정·재실행하거나 허용치를 완화하지 않았다.

| 보존 근거 | SHA-256 |
|---|---|
| 사전 고정 평가 manifest | `sha256:f28de3b2fe360654ab932ebd171f6124e9f86efc9d6a525e36cb2e08d256608a` |
| 최종 HOLD ledger | `sha256:b04b967855873f3c1ebdc3024fbacec36f28dc68e0040f905e5d00e85cea2703` |
| calibration archive | `sha256:e133ab853611aa49909cddc4ad467eca94989f7847c354a34b5af17c90954a32` |
| calibration map | `sha256:c8b33826b7d718ece737d82e3f061b11b549b9289c0e7656ae52ffcdf2b09d88` |
| engineering archive | `sha256:cc4a105438a4a33d49c86e2f7bc52b1d860252a6a0560d555acbcfee3296c378` |
| engineering map | `sha256:f9d187eaeb8d7a931f0f168284763f066f00b6a042252ee7445bd2375038f28b` |
| engineering 원본 result | `sha256:4228c5f7969db2cc894d05f3d2b82cca40b7590320c5caaa9b80da7123ebcad4` |

Git 밖 `learning-execution-20261023/fixed-budget-teacher-policy-evaluation-8d1196/`에 manifest·ledger·호출 기록·calibration/engineering 원본과 archive/map을 보존한다. 공개 기록에 원본 SQLite·영상·모델 가중치·private 설정·장치 주소는 넣지 않는다.

CE: 미해결 — 허용오차 초과와 안전 종료는 검증했지만 추종 실패의 물리 원인은 미확정이다. 해결 교훈으로 쓰거나 정책·실물·HF 수용을 선언하지 않는다.
