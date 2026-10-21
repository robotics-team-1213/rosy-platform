# OMX 실제 RGB 학습·native 물체 정책 평가 — 진행 증거

## 판정과 완료 조건

현재 목표는 **미달성**이다. 실제 시연 25개와 ACT 10,000 step 학습·재적재는
완료했지만, 학습 정책의 새로운 Gazebo 물체 과제 20회 중 최소 18회 성공은
아직 입증되지 않았다. 원격 단위 시험, offline MAE, 관절 goal 성공은 물체 과제
성공 수에 합산하지 않는다. 본 문서는 진행 중인 증거이며 최종 수용 보고서가 아니다.

현재 확정된 실제 learned 물체 성공은 **0/35회**다. 최초 고정 평가 0/20회와
별도 engineering 사전 과제 0/15회를 구분한다. 후속 사전 과제가 통과하기 전에는
새 정식 20회 평가를 시작하지 않는다. Calibration은 이 분모나 물체 성공에 넣지 않는다.
최신 bounded 모델의 사전 과제도 실패로 종료됐고 cleanup은 확인됐다.

최신 clean checkpoint의 실제 과제 `4c893c74b5b0`는 66 candidate/intent/UUID와
66 terminal4/code0 뒤 `bounded policy capture limit`로 종료됐다. 1,000건의
카메라 audit 중 원본 receipt tuple은 652개였다. 새 입력 선택 재시도가 진단 한도를
소진했다. 마지막 선택 입력 나이 34.204ms, 추론 11.250ms, 제출 전 47.707ms,
제출 90.231ms였고 owner 검증은 통과했다. Actor 160.244s, root 223.523s,
HOLD/cleanup true, attach/lift/stable 성공 없음이다. XY 0.229265m/Z 0.010000m는
`incomplete_trial_observation`이다. policy-result SHA256: `87cec786e6a516dc0effe31fc7b4a484d24c81ce310d188ce0e1cfde1810ab44`.
Policy revision: `accdc288e3a61874156aa67dc34fa52e48e50fb86677182382dab9759c9e5e2c` (유지).
진단 기록만 600s/10ms 재시도와 600 outer cycle을 수용하는 60,600건으로 제한한다.
모든 원 SHA와 두 timestamp를 보존하며 RGB를 audit에 복사하지 않는다. 500ms 신선도,
0.04rad 제한, 600s budget, owner lease와 controller tolerance는 유지한다.
수정 전 원격 회귀는 예상한 2FAIL이다. 수정 후 관련 네 시험 파일의 원격 검증은
83PASS/1SKIP/0NEW이며 독립 소스 검토에서 blocker가 없었다. Runtime revision: `016fad24a222361f84a368f07fa13b8bff776c75`.
같은 모델의 새 calibration·engineering 과제를 요청했다. 새 물체 성공은 아직 확인하지 않았다.

해당 재검증 calibration `90b0b4371650`는 12추론/0정책goal, PASS/cleanup true였다.
실제 과제 `9447e065dcd2`는 106후보/105intent/105UUID 뒤 106번째 gripper 목표
−0.1196070462rad가 `policy_action_envelope`로 차단되어 HOLD했다. 원 입력 gripper는
−0.0846947208rad였다. 카메라 audit 1,039건/상한60,600건으로 이전1,000건을 넘겨
기록됐으며 이 중단은 진단 cap 소진이 아니다. Actor204.413s/root267.588s,
cleanup true, attach/lift/stable0이며 XY0.229265m/Z0.010000m는 미완료 관측이다.
policy-result SHA256: `7180470f4363f694d691e22fac3fb7b27c0ba26e7e103dec60c48a8dc564d093`.
같은 clean checkpoint는 실제0/2이며 새 정식20회는 시작하지 않았다. 원본 학습 시연과
실행 상태·목표 비교를 진행한다. 기존 owner 범위와 step 제한을 유지한다.

후속 원격 read-only 진단은 종료됐다. 20개 train 원본52,834상태와 비교한 최근접 L2
거리는 실행 index30에서0.05078rad, index60에서0.19807rad, 마지막105에서0.50919rad였다.
Index60의 최근접 시연 gripper 목표는 open1.0rad였다. 마지막 실제 RGB·arm을 고정한
합성 gripper sweep에서 현재 accdc 모델은 입력−0.1~0.4rad에도 약−0.035rad의 closing을
반복했다. 원 입력의 실제 예측은2e-6rad 이내로 재현됐으며 매 입력마다 새 모델을
생성해 queue를 사용하지 않았다. 기존 absolute BEC 모델은 같은 낮은 gripper 입력에서
복원 방향을 냈지만 과거 실제94후보 과제에서0.0418019rad step으로 거절된 이력이 있다.
두 진단은 weights·normalization hash를 검증했고 실제 과제 분모에 추가하지 않는다.
원본·합성 입력 구분과 함께 `omx-clean-bounded-rollout-neighbors-1`,
`omx-clean-bounded-gripper-response-1`, `omx-absolute-gripper-response-1`에 보존한다.
단일 원인 확정이나 실제 물체 성공의 증거로 쓰지 않는다. 안전 제한을 완화한 unchanged
재시도는 하지 않는다.

후속 `absolute_tanh_from_chunk_source_v1`은 구현·검증 단계까지 진행했다.
Implementation source revision: `3f7972f2a6a597cad76ee5df4d1934b428fa16d5`.
같은 batch 원 상태 s와 absolute head a에 s+0.035*tanh((a-s)/0.035)를 학습부터
적용한다. 정답·통계·출력은 absolute이며 source를 다시 더하지 않는다. Source context는
호출 성공·예외 모두에서 제거한다. 부모의 bytes·전체ACTConfig·관절·카메라·limits·
train-only 통계가 일치해야 weights를 적재하며 부모 hash·기존 step·새AdamW를 결속한다.
수정 전 native3FAIL/10PASS, 수정 후 실제ACT13PASS/0SKIP/0NEW와 일반 원격
96PASS/1SKIP/0NEW를 확인했다. 추가 metadata 검증61PASS/0NEW, 부모 불일치·
변조 거절과 warm train/reload의 최종 선택 시험1PASS/12DESELECTED/0NEW를 확인했다.
추가 시험의 최초 실패1건은 정상 integrity 거절의 문구가 예상 regex와 달랐던 것으로,
기존 hash/size 거절 문구에 맞춘 test-only revision: `f509adfba840e2f2a48a128c1d71b300b4032bf7`.
독립 소스 검토에서 실행 경계 blocker가 없었다. 실제 recipe는 기존 BEC revision·
weights·정규화·10k loss 이력을 먼저 대조해 독립 스냅샷으로 고정한다. 실제 추가10k
학습을 요청했으며 새 checkpoint와 물체 과제 성공은 아직 확인하지 않았다.

공식 후속 로컬 main 착지 revision: `dc5db7e1db16637aa200172f6ceee0947d148b19`.
안전·크기·lint, architecture267PASS/0NEW, affected531PASS/14SKIP/0NEW를 확인했다.
일반 suite의 skip은 실제 MODEL ACT13PASS와 부모 guard 선택1PASS를 대체하지 않는다.
처음 착지는 공개 policy revision의 용도를 표시하지 않은 문서 한 줄로 secret scan이
실패했으며, 줄에 `Policy revision`을 명시한 뒤 실제 scanner1PASS/0NEW와 공식 검증을
다시 통과했다. 검사·allowlist는 완화하지 않았다. 실패 로그도 별도로 보존했다.
확정 착지 로그·record는 `official-land-dc5db7e1db`에 즉시 복사했다.
Affected log SHA256: `cfe295cb7d26043f41862259573d9af122d35134d351f327d07af46aa97c07b5`.
Architecture log SHA256: `cc70d81a6038daf3117bd8b7091845a9c485d3e8c09c90d09b8e2ca5c8c9d20f`.
Land record SHA256: `b990f6114e42a855f4fc68cef89325de27fb1f2d9f6931c89833318843c0e262`.
새 실제 학습 study는 `fixed-object-6cdde72b23679868`이다.
Training source revision: `f509adfba840e2f2a48a128c1d71b300b4032bf7`. 실제25개/66,080프레임의
curation과20/5분할을 재확인했다. 부모 weights는 별도 읽기전용0400 스냅샷이며
기존10k loss 이력을 보존했다. 모델 내부 reader 검증과 추가10k 완료는 구분한다.
학습·추론·SIM 호출 주요6파일은 학습 source와 착지 source에서 byte-identical임을
확인했다. 최신 code 착지와 실제 물체 목표 달성은 별개이며 현재0/35를 유지한다.

Study `fixed-object-6cdde72b23679868`의 실제 추가10,000step과 전체 validation·
checkpoint 재적재는 완료했다. 실제 history10,000개의 첫100평균 정규화L1 loss0.0147409435,
마지막100평균0.0087995281이다. 전체13,246프레임 MAE0.005778079426253098rad,
상수 baseline0.29584911500909206rad, limit위반0, 재적재 일치이며 `offline_only`다.
부모BEC의 기존10k와 이번추가10k를 구분한다. 이전 delta 모델 MAE0.00404918rad보다
크다. 새 모델의 실제 물체 과제 성공은 아직 미확인이다.
Policy revision: `fa953bf0ae64134ca2f6e7299adf5f5c9b04af8f10e13b4341532d567ae34ebc`.
Dataset revision: `a70d61a690a7fb10bfdef48a05a80d81999146c6b02d6fe861e82cf4e9541117`.
Weights SHA256: `a12b15619f1e27e6b1389dae899de6c5ce39456f8c86713614e1051902d72e23`.
Normalization SHA256: `0b5092f410c5a36eea190d308e0fb216eccd9c724de28c843ccc1eedbf345f69`.
Additional10k history SHA256: `8dc465f72b02694421852ead75fd80cb47b14e036a09b48e699fca064330d05b`.
ACTConfig SHA256: `183fbe61c0971a1f0b16a2611e3da8ac787f7d90a1208aae564ea45ffaf74423`.
Store finalized snapshot1개·공식전달bundle 검증·전체launcher EXIT0을 확인했다.
연결된 supervisor의 새 calibration은 배포 READY 뒤 자원 예약에서 거절됐다.
공유 시험의 메모리 예약으로 기존6CPU/8GiB 여유 기준에 미달했다. Durable status는
intent null·unit not-found·NOT_RUN이며 물체 과제는 미시작이다. 동료 작업과 기준을
유지하고 자원 여유·미실행 상태를 재확인한 뒤 새 calibration을 요청한다.
원래의 자원 거절과 미실행 영수증은 보존한다.
사전 물체 과제가 통과해야 같은 checkpoint/runtime의 새정식20회를 시작한다.

직전 noise 모델 과제 `869a6d818862`는 candidate/intent 109개, ROS UUID/terminal 성공 108개 뒤
gripper readback 0.4211009741rad와 target 0.3807023764rad의 차이
0.0403985977rad가 기존 0.04rad 제한을 넘어 HOLD했다. 마지막 intent에는 UUID가 없다.
SIM DetachableJoint 부착 보조의 attach가 확인됐지만 최대 lift 17.898mm로 기준 30mm에
못 미쳤고 release·안정 유지가 없었다. XY 오차 0.242214m, Z 오차 0.007898m는
`incomplete_trial_observation`이며 놓기 정확도가 아니다. 실제 과제 성공은 0/1이다.
policy-result SHA256: `f73746f1f5537cccf6b0137224514959469f2f0c63db80ea6de67e427f7dc924`.
이 단일 실행으로 state noise의 인과 효과를 확정하지 않는다.

후속 실험 source revision: `938791127b432cdb1e1e6dd578955e661fd41a38`.
기존 owner 제한을 유지하며 새 `joint_delta_tanh_from_chunk_source_v1` action head를
학습·재적재·byte 추론에 동일 적용한다. 정확한 0.035rad bound는 normalization hash에
결속하고 원 절대 target은 보존한다. 범위 밖 target의 학습 잔차는 제거하지 않는다.
수정 전 MODEL 실제 ACT 검사3FAIL/6PASS, 수정 후9PASS/0SKIP/0NEW, 일반 원격
검사78PASS/0NEW를 확인했다. 독립 소스 검토에서 blocker가 없었다. 새10,000step
학습·재적재·Store 검증은 완료했고 물체 성공은 아직 확인하지 않았다. 사전 과제가 통과해야 새
정식20회를 시작한다. 로그는 `omx-bounded-head-native-red`,
`omx-bounded-head-native-green`, `omx-bounded-head-green`에 보존한다.

이 변경은 공식 `tools/land.py --tests auto --no-prune`로 로컬 main에 착지했다.
Main revision: `0c706e831aa8e01122bcc2dc3a1e0d8faabdbf16`. 안전·크기·lint와 원격
아키텍처267PASS/0NEW, 영향 범위1091PASS/38SKIP/0NEW를 통과했다. 실제 ACT9개는
별도 MODEL 시험에서0SKIP으로 확인했다. 일반 검사의38SKIP을 통과로 바꾸지 않는다.
착지 도구의 임시 로그 경로는 다음 착지에서 재사용된다. 초기 SHA의 원래55경로 검사를
동일0c706e831a로 다시 실행해 `omx-land-0c-reverification/run-1.txt`에 보존했다.
원격 push는 하지 않았다. 새 학습 실행은 `omx-object-training-42a03f4605a8a021`이며
고정한 source938791127b의 bounded head/command_entry/noise0.02를 사용한다.
시작 요청이나 자료 검증 횟수는 학습 완료·물체 성공으로 계산하지 않는다.

## 최신 원본 입력 bounded checkpoint — 실제 과제 대기

학습 source revision: `5f471d5c7913715368bcc10cbed3c7af8267c112`.
`omx-object-training-ad8d25650f879643`에서 원 시연25개/66,080프레임 검증과20/5 분할,
전체 RGB reader 대조, 실제10,000step(seed42750/n_action_steps1), validation13,246프레임과
재적재 일치를 확인했다. MAE0.004049183405391603rad/관절 한계 위반0/offline_only다.
직전 bounded noise0.02 모델의 MAE0.00728356909769362rad보다 낮아졌으나 실제 과제는 미검증이다.

- Policy revision: `accdc288e3a61874156aa67dc34fa52e48e50fb86677182382dab9759c9e5e2c`.
- Dataset revision: `92c27ac0ba0cbff65c318579bb652a83dc3c2e478f50530489a3376ee010fcf4`.
- Normalization SHA256: `2f2a89bb39ba73f513d761323a6da901093ba40ff32de9074bfe1fbf08c63a68`.
- Weights SHA256: `f40f1c59a37f4f2faa957c3f82bbfc973a9a2a12c8b0fd08ca0863a9821b7124` (45,371,416bytes).
- Optimizer history SHA256: `008d1a0688feb2125c9ac442eb83b8c234b3f2237d644dba28d751bf129e7893` (10,000개).

Normalization 전체는 직전 모델에서 training_augmentation만 제거한 것과 동일하다.
Training index도 동일한6,263/52,834 train frames이며 원 target은 유지했다. Synthetic
상태 교란을 사용하지 않았음을 실제 normalization·offline-report에서 확인했다.
DatasetStore 복사·require와 bundle 전송을 완료했고 실제 runner는 exit0으로 종료됐다.
로컬의 모든 artifact 참조 bytes·SHA256을 다시 대조했다. Source91897eadf0의50ms capture
runtime과 같은 checkpoint로 새 calibration·사전 물체 과제 실행을 요청했다.
아직 실제 물체 actor 시작이나 새 성공 결과는 확인하지 않았다.

## 직전 bounded noise0.02 checkpoint — 사전 물체 과제 실패

실제 학습 source revision: `938791127b432cdb1e1e6dd578955e661fd41a38`.
실행 `omx-object-training-42a03f4605a8a021`의 10,000step(seed42750/n_action_steps1),
전체 validation13,246프레임과 재적재 일치를 확인했다. MAE0.00728356909769362rad,
상수 baseline0.29584911500909206rad, 관절 한계 위반0이다. 직전 noise 모델의
MAE0.006948906675814038rad보다 커졌으며 offline_only가 과제 성공은 아니다.

- Policy revision: `cb369406aff1996107a57b3837ca5d780d3722b03f193550556e77563da8bde2`.
- Dataset revision: `e0b17b890f08519cf419bd75e6ed265fbf09ed313ec8d42d8cb7587b72bd0a06`.
- Normalization SHA256: `1cf925271b485ed6db4193052066eb7f9291f54ff1d72ecff0af54c35d7eca6e`.
- Weights SHA256: `4fa0807ff40c1c4cb5bf9396c3367b5f609a1b8322201a90dc837d886acba43d` (45,371,416bytes).
- Optimizer history SHA256: `73894d8a7adc594ebeaaa7afe628ccb4b71a88b3c7d57978a1ae1c4b0f4ffb65` (10,000개).
- Training-index SHA256: `5e23c544256bfbf17189a37bae6ceb06e9d7a6ec78ed6ce948019ea3a383d7f9` (6,263/52,834 train frames).

변환 type과 bound 외 모든 normalization 필드는 직전 모델과 동일하다. 원 시연·
선택 index·원 target·train noise0.02/seed42751을 유지했다. 선택 train 시작 frame의
1,953/6,263개는 원 gripper 이동량이0.035rad를 넘으며 clipping 없이 잔차로 남는다.
이 수치는 clean 시작 frame 기준이며 noisy 입력·전체 future chunk 분포가 아니다.
DatasetStore 복사·require와 bundle 전송이 완료됐고 실제 학습 runner는 exit0으로 종료됐다.
로컬에 내려받은 모든 artifact 참조의 byte 수·SHA256을 다시 검증했다.
후속 실행 `omx-policy-candidate-smoke-938791127b-ccbdf33efe96b4cd`의 calibration
`13e7e05307f4`는12추론/0goals/0attempts/cleanuptrue/exit0으로 통과했다.
사전 물체 과제 `9cf05a67d97b`는40candidate/40intent/40UUID 뒤 카메라 원본 만료로
HOLD/exit1/cleanuptrue로 종료됐다. Terminal4/code0은39개이고 마지막 goal은
cancel ACK 뒤 terminal5/code0으로 종료됐다. Attach·lift·stable은0이며 물체 성공은0/1이다.
마지막 capture 선택 나이92.863ms, numerical17.464ms, 제출 직전 원본 나이112.903ms,
submit405.159ms였다. 마지막 GOAL_ACCEPTED의 원 카메라 나이는490.817ms였고,
이후 post-I/O 500ms 검사가 만료를 감지해 취소했다. 시간 제한과 취소 경로를 유지한다.
XY0.229265m/Z0.010000m는 incomplete_trial_observation이며 놓기 정확도가 아니다.
policy-result SHA256: `2d00ea9f5a3b35f241ef4352612b109a15527a8e0b69b056c33b844f6c7431ae`.
새 정식20회는 시작하지 않았다. 같은 checkpoint를 보존하고 제출 경로의 지연 원인을 계측한다.

SIM 계측 source revision: `754c2e2bf553d408a7a00d274dd776f89f5747c2`.
guard·journal prepare/observe/read·native send/submit·post-I/O의 원 호출을 같은 인자로
그대로 실행하고 메모리에서 enter/exit·thread·command 식별자를 기록한다. 종료 뒤
`policy-admission-timings.json`에 저장한다. 모든 FULL commit·durable callback·검사와
500ms 제한은 유지한다. 수정 전 계측 회귀3FAIL, 수정 후178PASS/0SKIP/0NEW와
독립 검토를 통과했다. 중첩 duration을 합산하지 않으며 `returned`를 admission 성공으로
해석하지 않는다. 같은 cb369 checkpoint로 새 calibration·사전 과제 계측을 요청했다.

계측 calibration `1d051a0f8b13`은 통과했고 실제 물체 과제 `632cf5c3265d`도
실패/HOLD/cleanuptrue/exit1로 종료됐다.141candidate/141intent/141UUID,
140terminal4/code0 뒤 마지막 goal은 terminal6/code-5로 중단됐다. 이 실행의 실패는
카메라 만료가 아니다. 컨트롤러 원문은 `State tolerances failed for joint 4`와
위치 오차-0.095309rad/허용0.020000rad, goal_time_tolerance 초과1.01초를 기록한다.
로그의 joint index를 gripper 이름으로 추정하지 않는다. Attach0/lift0.007796m/stable0,
XY0.244500m/Z0.002652m는 incomplete_trial_observation이다. cb369의 물체 결과는0/2다.

| 계측 구간 | 횟수 | 평균 ms | p95 ms | 최대 ms |
|---|---:|---:|---:|---:|
| Full guard |3193|33.262|67.966|201.234|
| Journal prepare |141|18.882|95.291|236.004|
| Native send |141|0.346|0.459|0.508|
| Durable journal observe |3257|11.897|54.057|226.629|
| Post-submission |141|36.647|69.814|202.941|
| Session submit |141|166.917|258.442|388.518|
| Journal read |7164|2.553|11.883|180.291|

중첩 구간을 합산하지 않는다. 마지막 session submit은253.687ms로 정상 반환했고,
실제 controller goal의 후속 도달 실패를 구분한다. Native send가 제출 지연 전체를
차지했다는 가설은 이 실행에서 지지되지 않는다. 원장 지연은 확인됐지만 최종 과제 실패의
원인이라고 단정하지 않는다. 모든 durable 저장·실행 시간·관절 허용 오차는 유지한다.
policy-result SHA256: `ead07c04c67cf5bc33acc43634b97c26a6fb513e624d94e21d6b088c07cd3d40`.
Admission trace SHA256: `abee4664ad392c220fd329068ed7184e940dcb882da8dfd4a1c7f7a9cc4b7686`.

다음 비교는 bounded head를 유지하고 synthetic state noise만0.02에서0으로 뺀다.
원 시연25개·20/5 분할·원 target·선택 index·seed·step 수는 유지한다. 원 입력을 사용하는
bounded ACT의 실제 학습·재적재·replay 검사를 포함해10PASS/0SKIP/0NEW를 확인했다.
비교 학습 source revision: `5f471d5c7913715368bcc10cbed3c7af8267c112`.
새 학습을 요청했고 아직 완료나 실제 물체 성공은 확인하지 않았다.

원장 연결 축소는 제품에 적용하지 않았다. 종료된 실제141명령/3257callback을 원장
복사본에 재생한 ABBA 비교에서 기존 prepare 평균2.324/2.314ms, 단일 transaction
후보8.259/5.876ms였다. 각 복사본의 본 DB를 WAL 없이 다시 열어 모든 사실의 저장과
integrity_check를 확인했다. 이는 ROS 명령 없는 재생이며 실제 과제 분모에 넣지 않는다.
첫 비교는 benchmark의 미닫힌 SQLite 연결 때문에 base DB 자기 검증이 실패해 미채택했고,
연결을 닫도록 고친 `omx-prepare-connection-measurement-2`만 유효한 비교로 보존했다.

호출자의 입력 선택 cap은 원 max_observation_age의1/4에서1/10로 강화했다.
SIM의500ms 계약에서는125ms 대신50ms 이내의 실제 새 capture를 기다린다. 원 sequence·
receipt·RGB를 그대로 보존하고 최종500ms/600초 deadline 검사를 유지한다. 실제 선택 cap과
나이·대기 시간은 step timing에 기록한다. 이 여유는 최종 freshness 통과를 보장하지 않는다.
Capture source revision: `8f728fb5e0aa86fed0951f0256ef622f02670063`.
수정 전 회귀2FAIL, 수정 후114PASS/1SKIP/0NEW와 독립 검토를 통과했다. 이 변경이
controller 도달 오차를 해결했다는 증거는 없고, 다음 native 평가는 noise0 checkpoint와
새 capture runtime을 합친 후보로 평가한다. 학습 모델만의 인과 비교로 주장하지 않는다.

최신 공식 main revision: `91897eadf030de531ac8f37045d38497934979fb`.
실제 `tools/land.py --tests auto --no-prune`가 안전·크기·lint, 원격 architecture267PASS,
영향 범위408PASS/6SKIP/0NEW를 확인한 뒤 착지했다. 완료 로그와 landing record는
`official-land-91897eadf0/{run-g1-1.txt,run-1-1.txt,land-record.json}`에 별도 복사했다.
초기0c706e831a의 재검증도1091PASS/38SKIP/0NEW로 종료됐다. 임시 경로 재사용 중
잘못 복사한 일부 새 로그는 `official-land-0c706e831a/NOT-AUTHORITATIVE.md`로 표시하고
완료 증거에서 제외했다. 현재 원격 push는 없고 실제 물체 성공 조건도 아직 미달성이다.

## 최초 checkpoint — 실패한 고정20회 평가의 데이터

선택한 시연은 batch 7·9·10·11·12·14·15·16에서 각 3개, batch 17에서 1개로
총 25개다. 독립 SIM 정답과 실제 RGB 66,080프레임의 변환·전체 readback을
모델 PC에서 검증했다. 20 train / 5 validation을 분리했고 정규화는 train에서만
계산했다. 최초 학습과 후속 학습 모두 원본 전체 검증부터 수행했다.

| 산출물 | 고정 식별자 |
|---|---|
| 선택 policy revision | `487024ca467ada59c6ac562052f16fcc1848bd70d9f595068793a6e3811de254` |
| Dataset revision | `ccae88060d34dd8b2273f3ae1407524d2b61974474616343f3efc92eacc4cdee` |
| 정규화 SHA256 | `b76fa00fcba81620c252164ecf51fb8b8812bbc9f9aab042a4e8ad3c88cc5b9a` |
| Model weights SHA256 | `b80dc0b03afc8c13036020796b941542d1657a1963e53557962defdd0ce86718` |

모델 PC 실행 `omx-object-training-288fac1ad185df82`는 ACT 10,000 step,
seed 42750, n_action_steps=1을 실제 완료했고 저장 모델 재로딩 예측 일치도
확인했다. main 학습률 0.0001 / backbone 0.00001의 실제 optimizer 그룹을
사용했다. 전체 validation MAE는 0.005564797514183465rad, 상수 예측은
0.29584911500909206rad다. 관절 한계 위반 0, offline 판정은 `offline_only`다.

첫 실행 `omx-object-training-5a2d82ce6eb05697`도 실제 10,000 step과 재적재를
완료했지만 MAE 0.2840533379436038rad로 보존·미선택했다. 두 학습의 curation,
split, 정규화는 동일하며 생성된 dataset revision은 서로 다르다. optimizer
진단은 [별도 보고서](../omx-act-optimizer-2026-10-21/result.md)에 기록했다.

Batch 8은 teacher 3/3 성공 뒤 의존 파일 6개 drift로 전체 제외했고, batch 13은
teacher 2/3 성공 뒤 joint-state stale로 전체 제외했다. 이 두 batch와 선택분의
합계는 **31 시작 / 30 teacher 성공 / 25 학습 편입**이며 생애 전체 실행 수가 아니다.
실패 원문·제외 사유를 보존한다. Teacher 위치·lift 지표는 학습 정책 지표가 아니다.

추가 MODEL-PC 수치 진단 `omx-selected-step-margin-1`은 같은 선택 weights와
원래 validation split의 Episode마다 균등한 64개 frame, 총 320개를 평가했다.
실제 reader state/action을 원본과 대조하고 PNG hash도 검증했다. 모델을 수정하거나
명령을 실행하지 않았다. 원본 PNG와 reader의 손실 인코딩 RGB를 따로 비교했다.

| 수치 진단 | Reader RGB | 원본 PNG |
|---|---:|---:|
| 표본 MAE (rad) | 0.0052625402 | 0.0052403915 |
| 현재 state 그대로 예측한 MAE (rad) | 0.0082721692 | 0.0082721692 |
| 예측 target과 현재 state 차이가 0.04rad 초과 | 56/320 (17.5%) | 59/320 (18.4375%) |
| 최대 관절 차이 (rad) | 0.0466811657 | 0.0466764569 |

이 계산에서 원시연 target도 7/320개가 0.04rad를 넘었다. 이는 표본 frame의 state와
target 비교이며 실제 명령 승인 시점의 판정과 구분한다. 낮은 offline MAE만으로
0.04rad 실행 단계 조건을 만족한다고 주장할 수 없다. Native 실패는
초기 실행의 관측/lease 신선도 실패와 후속 admission 거절을 구분하며, 이 추가
진단만으로 실제 단계 제한 실패를 확정하지 않는다.

진단 결과 SHA256: `2dafffb7427e73112cbae28153a3f10e922fe9b59f37406df156ce26cfceb363`.

## 실제 native 연결 검증과 실패 보존

초기 calibration은 원 관측 500ms 제한 또는 1초 lease 만료로 종료됐다.
정책 원장의 최초 저장을 권한 발급 전에 수행하되 binder의 원본 재검증을 유지해
초기 결속을 약 1.4초에서 약 0.22초로 줄였다. 이후 wall 계측은 세션 잠금 대기
177–263ms, 전체 guarded 추론 경로 안의 numerical 단계 11–14ms를 관측했다.
이는 numerical 단계가 순수 CNN 시간이라는 뜻은 아니다.

Private actor의 명목 watchdog 주기를 20ms에서 100ms로 조정한 c5afc6f9 runtime은
calibration 실제 추론 12회·정책 명령 0회·attempts 0·정리 완료·exit 0으로 통과했다.
최종 확인한 원 입력 나이는 최대 479.089ms였다. 명목 주기는 실제 정지 반응 시간의
상한이 아니다. 일반 runtime 기본값은 그대로다.

첫 고정 campaign `omx-learned-campaign-bdd38d664bc0340d`는 위 checkpoint와
runtime, 성공 기준을 고정했고 **20 시작 / 20 종료 / 20 정리 확인 / 0 물체 성공**으로
종료됐다. 20개 canonical 결과와 수집된 원문이 일치하고 archive·extraction map의
SHA256 40개를 재검증했다. Fetch receipt는 `OBSERVATION_NOT_ATOMIC`이며 파일
시스템의 원자 snapshot이라고 주장하지 않는다.

| 전체 20회 기록 | 확인값 |
|---|---:|
| 물체 과제 성공 | 0/20 (목표 18/20 미달) |
| 반환되어 기록된 candidate | 114 |
| durable command intent | 106 |
| 실제 accepted goal UUID | 100 |
| terminal 상태 4 / code 0인 관절 goal | 95 |
| terminal 상태 5인 관절 goal | 3 |
| cancel ACK 후 terminal 미기록인 관절 goal | 2 |
| 원 joint 관측 신선도 실패 | 17회 |
| 원 camera 관측 신선도 실패 | 2회 |
| lease 만료 실패 | 1회 |

실패 종료 시 독립 관측의 lift·stable 값은 모두 0, XY 오차 229.265131mm,
Z 오차 10.000000mm다. 모두 `incomplete_trial_observation`이며 놓기 후 오차나
해제 후 안정 시간으로 해석하지 않는다. 관절 goal 95회 성공을 물체 성공으로
합산하지 않으며, cancel ACK만 있는 2개를 terminal 완료로 바꾸지 않는다.

완료 원장 SHA256: `2fac17fce6a55b82199a1a4ef5323c3b9f525bc182f17b709198f84be7c6160f`.
고정 campaign SHA256: `fa612239c771a2e9442cd6ec5f689143c291ca879bd98233e8e555e8e9d6b660`.

아래는 첫 4회의 상세 사례이며 전체 20회의 시작·실패 원문을 보존한다.

- Trial 1: 실제 관절 goal 24개 완료 뒤 25번째 goal 수락, 이후 원 관측 신선도
  검사로 취소됐다. 마지막 goal 수락은 원 관측 후 448.757ms, cancel ACK는
  519.135ms, 최종 CANCELED는 548.532ms다.
- Trial 2: 첫 goal 성공 후 두 번째 intent가 저장됐으나 goal UUID·event 없이
  원 관측 신선도 검사에서 거절됐다. 두 번째 candidate 생성 시 원 관측은 이미
  342.609ms였다. Intent만 있다고 실제 goal 전송을 주장하지 않는다.
- Trial 3: lease 만료로 기록된 candidate·정책 goal 0회 종료됐다.
- Trial 4: 원 관측 신선도 검사로 종료됐다. 4회 모두 실행 정리가 확인됐다.

Trial 4 수집 이후 로컬 관리 명령이 Windows 명령 길이 제한으로 실패했다.
원격 프로그램을 SSH stdin으로 보내도록 관리 스크립트를 수정하고, 종료·정리·소스
결속을 확인한 자기 캐시만 정리했다. 데이터·모델·원장·root release는 보존했다.
원 HOLD ledger를 별도 보존하고 같은 campaign의 5회차부터 중복 시작 없이 재개했다.
앞선 별도 b7a36cc348e899b0은 디스크 부족으로 배포 단계에서 실패했고 과제 시작은 0이다.

후속 비교 후보 a2422cff50은 policy actor 자식에만 OMP/OpenBLAS/MKL thread 1을
설정하고 실제 torch thread 수를 기록한다. 기존 cohort에는 적용하지 않는다.
현재 quota 측정은 10초 동안 100 period 중 3회 throttling, 누적 throttled_usec
287256을 보였지만 torch가 단독 원인이라는 증거는 아니다. 효과는 별도 native
calibration과 고정 campaign에서 확인해야 한다.

해당 a2422cff50 calibration은 6개 candidate 기록 후 원 joint 관측 신선도 실패로
종료됐다. 실제 torch thread는 1, interop은 24였고 정책 goal·물체 과제 시작은 0이다.
이어 초기 설치 파일 검사를 관절 intake lock 밖으로 옮긴 4dddf3fc2d는 원격
86 PASS / 1 SKIP / 0 NEW였지만 실제 calibration은 10개 candidate 후 현재 joint
관측 신선도 실패로 종료됐다. 기록된 원 입력 나이는 103.51–270.48ms였으며,
이 수치로 종료 시 현재 관측 신선도까지 통과했다고 주장하지 않는다. 두 실행 모두
정리가 확인됐고 실패 원문은 각 `omx-policy-candidate-smoke-<revision>-<nonce>`에 보존했다.

후속 967dfc3415는 idle calibration을 검증된 설치 metadata의 0.8초 정책 주기에
맞춘다. 다음 capture 전에 대기하고 매 cycle 시작 시각과 최소 간격을 receipt에 기록한다.
기존 빠른 calibration 실패는 추가 부하 시험 결과로 보존한다. watchdog과 lease 갱신은
각 10Hz, 모든 신선도·최종 admission 검사는 유지한다. 실제 loop를 실행하는 회귀
테스트는 이전 코드에서 간격 위반으로 실패했고, 수정 후 원격 관련 검사 52 PASS /
0 NEW를 확인했다. 이 idle calibration 통과만으로 submit·journal·이동 중 관측이나
실제 물체 성공을 주장하지 않으며 별도 engineering 물체 과제로 검증한다.
실제 967dfc3415 calibration은 9개 candidate 후 원 관측 신선도 실패로 종료됐다.
정리 확인은 true, 물체 과제 시작과 정책 goal은 모두 0이다. 마지막 기록의 추론
전체 시간은 464.37ms였고 설치 검사 112.60ms, 초기 lock 대기 146.64ms,
capture 68.21ms, 최종 lock 대기 42.82ms, 최종 검사 78.90ms가 포함됐다.
따라서 운용 주기 일치만으로 해결됐다고 판단하지 않는다.

동일 설치 파일의 합성 Python 경쟁 진단 `omx-hash-contention-1`은 실제 물체
평가와 분리했다. 2회 반복·각 12개 측정에서 1MiB 해시 읽기의 중앙값은
495.60/498.97ms, 8MiB는 99.34/110.35ms였다. 경쟁 thread가 없을 때는
각 약 11/12ms였다. 모든 측정에서 전체 파일 SHA를 확인했다. 이 측정은
실제 ROS 경합의 원인 확정이나 신선도 상한 보장이 아니다.

dc2ae11177은 공통 파일 검증의 읽기 단위만 8MiB로 바꾸며 경로 containment,
전체 SHA·최종 크기 검사를 유지한다. 검증당 일시 block 메모리는 약 2MiB에서
16MiB로 늘 수 있다. 빈 파일·8MiB 경계·그 뒤 17바이트 tail의 끝 변조와 크기
오류를 포함한 원격 관련 검사 72 PASS / 1 SKIP / 0 NEW와 독립 코드 검토를
마쳤다. 선택 checkpoint는 동일하다. 실제 dc2ae11177 calibration은 12회 추론 /
0 policy goals / cleanup true로 통과했다. 입력 나이 중앙값 262.65ms·최대 492.71ms,
cycle 시작 간격은 0.931–1.298초였다. 신선도 여유가 작으므로 실제 이동 중
성공으로 확대 해석하지 않는다. 이어 실행한 engineering 물체 과제 1회는 8개
candidate 후 원 관측 신선도 실패로 종료됐다. 정리 확인은 true, lift·안정 시간은
0이며 incomplete 관측이다. 따라서 실제 learned 물체 시작은 기존 20회와 이 1회를
합한 21회, 물체 성공은 0회다. 이 사전 과제를 새 정식 20회에 합산하지 않는다.
결과 수집 뒤 디스크 여유 약 7.88GiB가 로컬 관리 스크립트의 임시 8GiB 기준보다
작아 추가 시작도 차단됐다. 해당 HOLD와 과제 실패는 서로 구분해 보존한다.

후속 98b548e36b는 private actor의 poll 검사 간격만 100→200ms로 바꾼다.
이는 기존 250ms 허용 범위 안이지만 명목 watchdog 간격은 100ms 늘어난다.
Lease 갱신 100ms와 500ms 신선도·원 timestamp·모든 admission 검사는 유지한다.
관련 원격 검사 60 PASS / 0 NEW 및 독립 코드 검토 후 실제 calibration
12회 / 0 goals / cleanup true로 통과했다. 입력 나이 중앙값은 192.55ms, 최대
295.27ms였다. 실제 사전 과제는 38개 candidate 후 원 camera 신선도 실패로
종료됐다. durable intent 38개·accepted UUID 37개·terminal 4/code 0인 goal 37개를
확인했고 마지막 intent는 UUID·event가 없다. Lift·stable은 0, incomplete 관측이며
cleanup true다. 전체 learned 물체 시작은 22회·물체 성공은 0회다.

종료 뒤 합성 진단 `omx-gil-interval-1`은 같은 8MiB 읽기와 실제 마지막 frame의
PNG 메모리 인코딩을 Python thread 경쟁 유무·전환 간격 5/1ms 조건에서 비교했다.
경쟁이 있는 2회 반복의 해시 중앙값은 5ms 조건 100.73/104.25ms, 1ms 조건
33.99/34.62ms였고 PNG는 약 11.63ms에서 3.54–3.60ms였다. 각 조건 16개 표본의
전체 해시와 PNG 복원 pixels를 확인했다. 합성 경쟁·메모리 인코딩 결과이며 실제
파일 저장 시간·ROS 원인 확정·명령 성공 증거가 아니다.

후속 1eb43e374f는 private actor의 Python 전환 간격만 1ms로 설정하고 이전 값과
실제 값을 receipt에 기록한다. 이 값은 scheduling 지연 상한이 아니며 actor의
모든 Python thread에 적용돼 전환 비용이 늘 수 있다. Poll 200ms·renewal 100ms·
원 timestamp·모델·모든 guard와 PNG 저장 순서는 유지한다. 원격 관련 검사
56 PASS / 1 SKIP / 0 NEW와 독립 코드 검토 후 별도 native calibration을 시작했다.
실제 calibration은 12회 / 0 goals / cleanup true로 통과했고 입력 나이 중앙값
179.06ms·최대 268.94ms, 전환 간격 실제 1ms·이전 5ms를 확인했다. 원본 수집의
SSH 180초 timeout 후 같은 run을 다시 조회해 종료·PASS를 확인하고 fetch만
재시도했다. 복구 스크립트의 receipt pointer 읽기 오류도 새 실행 전에 중단됐으며
포인터를 해제해 archive·map SHA와 94개 추출 파일·108,085,807bytes를 대조했다.
두 HOLD 원문을 별도 보존하고 같은 calibration을 재시작하지 않았다.

이후 실제 engineering 과제는 13개 candidate 뒤 원 camera 신선도 실패로 종료됐다.
물체 lift·안정 시간은 0이고 incomplete 관측이며 실행 정리를 확인했다.
전체 learned 물체 시작은 23회·물체 성공은 0회다. 1ms 설정의 실제 해결을
주장하지 않으며 후속 계측에서 capture 이후 제출 구간을 확인한다.

디스크 관리는 peer cache·원본 증거 삭제 대신 자체 시작 기준을 조정했다.
새 deploy 전에 home/state 여유가 4GiB와 다음 작업 allowance(새 release 2GiB,
재사용 1GiB)의 합 이상인지 확인하며 완료·fetch·자기 소스 cache 정리 뒤
4GiB 기준을 다시 확인한다. 이는 작업 중 남는 용량이나 최대 사용량 보장이
아니며 부족하면 HOLD·원 receipt를 보존하고 deploy/start를 자동 재시도하지 않는다.

019b96ade9는 capture 뒤 PNG 저장·제출 직전 원 입력 나이·실패한 submit 시간과
stop 이후 traceback 위치를 기록하는 계측 수정이다. 원격 57 PASS / 1 SKIP /
0 NEW 뒤 calibration 12회 / 0 goals / cleanup true로 통과했다. 실제 사전 과제는
82개 candidate / 82 durable intent / 81 accepted UUID 후 원 joint 관측 신선도
실패로 종료됐고 cleanup true다. 마지막 intent에는 UUID가 없으며 traceback은
durable intent 뒤 전체 guard를 재수행한 다음의 `_source`를 가리킨다. 마지막
원 입력 나이 344.245ms에 submit 180.701ms가 더해졌고 PNG 저장은 2.860ms였다.
Lift·stable 0, incomplete 관측이며 전체 learned 물체 성공은 0/24회다.

같은 실행의 47→56 PNG 파일 구간 10.030초 관측에서 cgroup CPU 사용량은
20.063 CPU초, quota throttling 증가는 0이었다. 이 구간에 quota가 원인이었다는
증거는 없으며 전체 실행이나 다른 부하 구간의 scheduling 상한을 보장하지 않는다.
81개 완료 goal에 약 97.9초가 걸렸고 attach·lift는 아직 없었다. 신선도 해결과
별개로 600초 전체 예산에서 정책의 물체 과제 진행률도 계속 확인해야 한다.

후속 fb8d68a4dc는 수치 추론 전에 원 입력 나이가 설치 신선도 예산의 1/4 이하인
실제 capture를 선택한다. 초기 파일 검사부터 고정한 전체 capture 대기 예산은
설치 신선도 예산과 같으며, 두 잠금을 풀고 새 실제 관측을 기다린다. Guard 실패는
그대로 전파하고 선택 뒤 모델은 한 번만 호출한다. 생성된 candidate나 queued ACT
결과의 원시각을 바꾸지 않으며 기존 제출·durable intent·후속 검사를 유지한다.
이는 계산·제출 여유를 확보하는 보수적 입력 선택이며 end-to-end 500ms 보장이 아니다.
회귀는 이전 코드에서 새 관측 선택·관측 미갱신 중단의 두 경우가 실패했고 수정 뒤
관련 원격 104 PASS / 3 SKIP / 0 NEW였다. 437b01089b는 잠금·검사가 최초 대기
예산을 소진한 경우 새 관측이어도 계산하지 않는 검사를 추가했다. 실제 native
calibration은 12회 / 0 goals / cleanup true로 통과했고 최종 입력 나이 최대
330.291ms였다. 실제 물체 사전 과제는 102개 candidate 뒤 camera source stale로
종료됐고 cleanup true다. 재capture 대기는 13 cycle에서 관측했고 선택 시 원 입력
나이는 모두 124.026ms 이하였다. 마지막은 선택 시 107.018ms, 수치 추론 32.390ms,
후속 lock 대기 62.903ms와 전체 검사 98.630ms였으며 제출 직전 310.753ms에
submit 193.156ms가 더해졌다. 실패 위치는 submit 내부 final_submit의 첫 전체
검사 뒤 camera source 검사다. Lift·stable 0, incomplete 관측, 전체 물체 성공
0/25회이며 새 정식 20회는 시작하지 않았다. 입력 선택만으로 해결됐다고 주장하지 않는다.

후속 3d26f72b7a는 미승인 후보를 반환하는 private wrapper의 추론 뒤 전체 guard를
기존 owner의 최종 admission에 모은다. Wrapper의 lease identity·갱신 시각 비감소
검사는 유지하고, capture·submit 진입·final_submit·durable intent 뒤·전송 후 전체
검사 경로는 변경하지 않는다. 추론 중 파일 변경·철회가 생겨도 candidate가 반환될
수 있으나 이는 권한 부여가 아니며 calibration 또는 최종 submit은 반드시 거절한다.
기존 caller는 두 경로 중 하나로 이어진다. 계측 이름도 `final_guard` 대신 실제 남은
검사인 `lease_context_check`로 바꿨다. 새 회귀는 이전 코드에서 후보 반환 시 파일
검사로 실패했고 수정 뒤 tamper 후보의 최종 submit이 HOLD·무전송임을 확인한다.
관련 원격 130 PASS / 3 SKIP / 0 NEW와 독립 계약 검토 뒤 별도 native calibration을
준비했다. 첫 시도는 새 release의 6GiB 디스크 사전 기준 미달로 deploy 전에 HOLD였고
실제 시작은 0회다. 원문을 보존한 뒤 자체 종료 run이 참조한 staged weight 중복
15개만 원본 local tar·MODEL checkpoint SHA·실제 종료/정리/비활성 상태를 재대조해
퇴거했다. 현재 입력과 미참조 입력은 제외했고 intent·퇴거 marker를 보존한다.
마지막 3개 적용 뒤 여유 공간 6,532,743,168bytes를 확인하고 기존 staging으로
같은 준비 원장을 재개했다. 이 중복 정리가 실제 시간 여유나 물체 성공을 확보했는지는
아직 미확인이다. 실제 calibration은 12회 / 0 goals / cleanup true로 통과했고
최종 입력 나이 중앙값 162.955ms·최대 213.447ms였다. 이어 실제 물체 사전 과제
1회는 366 candidate·366 durable intent·365 accepted UUID와 terminal status4/code0
후 실패 종료됐다. 마지막 intent에는 native event·UUID가 없고 cleanup true다.
Lift·stable 0, incomplete 관측이며 전체 성공은 0/26회다. Actor 449.978초·전체
514.050초에 종료됐으며 600초 기한 도달은 아니었다. 표면 오류는
`local_stop_or_authority_closed`다. 마지막 source 대비 예측 joint1 차이는
0.041170955rad, 제출 직전 나이와 submit 합은 약 300.399ms였다. 최종 native
readback은 보존되지 않아 0.04rad step fence 거절인지 확정하지 않는다. Stop 원장은
정리 단계의 `SIM_STUDY_FAILED`만 보여 선행 외부 stop의 증거도 찾지 못했다.

71e213bb40은 private admission의 최초 False 분기와 그때 사용한 실제 readback,
command·원 candidate 시각·계산 delta를 메모리에 한 번 기록하고 HOLD 이후 저장한다.
실제 승인 기준이나 모델 출력을 바꾸지 않는다. 관련 원격 55 PASS / 1 SKIP /
0 NEW를 확인했다. 기존 실행에 없던 값을 사후 복원한 것으로 표시하지 않는다.

다음 학습 후보 1dda28aa86의 `command_entry` 표본 규칙은 원 command/goal 쌍마다
팔 target-state 차이 0.035rad 이하·그리퍼 0.04rad 이하인 최초 원본 frame을 선택한다.
전체 25개 자료에서 7,828개 명령을 모두 포함할 수 있음을 MODEL 읽기 전용 조회로
확인했다. 전체 관절에 0.035rad를 요구한 검토안은 2,425개 명령을 놓쳐 채택하지 않았다.
검증된 SIM truth와 고정 6관절을 요구하고 명령 누락은 실패한다. 원본 arrays·목표·시각·
chunk 순서·20/5 split·train 전체 정규화·전체 RGB 검증과 validation은 유지한다.
선택 indices/config는 DatasetManifest 파일 목록·변환 SHA에 결속한다. 그리퍼의
학습 margin과 최종 readback 승인은 보장하지 않는다. 원격 35 PASS / 2 SKIP /
0 NEW와 독립 검토 후 같은 원본으로 새로운 10,000 step 학습 준비를 시작했다.
기존 checkpoint와 26회 실패 이력은 보존하며 새 모델의 품질·실제 과제 성공은 미확인이다.

추가 MODEL 진단 `omx-selected-command-starts-1`은 모델을 바꾸지 않고 validation
Episode당 unique accepted command의 첫 post-acceptance frame 64개씩, 총 320개를
비교했다. 원본 RGB의 MAE는 0.00567470rad, 현재 state 예측은 0.01115009rad,
예측 이동량 중앙값은 0.02799722rad, 정답은 0.03062123rad였다. 예측 63/320개와
정답 81/320개가 같은 frame의 state 대비 0.04rad를 넘었다. 이 수치도 실제 최종
admission이나 물체 성공 판정이 아니다. 반복 label이 느린 진행의 원인이라는 가설을
이 결과만으로 확정하지 않는다. 결과 SHA256:
SHA256: `12e809d1e30fccd7927b63b58652800392b8be65b3a07872e916f5c63891a40c`.

최초 20회 archive와 extraction map 총 40개, 1,771,298,280bytes는 두 번째
호스트에서도 전체 SHA·크기를 검증했다. 부분 전송·39/40 확인·빠진 map 1개 복구
원문과 최종 40/40 대조를 보존했고 보관 디렉터리 23개의 fsync도 완료했다.
종료·정리·unit 비활성·WAL 없음과 archive의 원본 byte 일치를 확인한 뒤 AI의
각 이전 run에서 설치 weights 복사본과 execution journal 복사본만 퇴거했다.
원본 byte는 로컬 raw·로컬 archive·두 번째 호스트 archive에 보존한다. 처음 1·2회와
후속 3–20회 퇴거는 별도 proof이며 두 번째 호스트 copy 작업의 `ai_evictions=0`과
구분한다. 후속 18회 퇴거에서 여유 공간은 5,870,911,488→7,507,722,240bytes였다.
이전 run은 재시작하지 않으며 canonical 결과·계측·원 fetch receipt·퇴거 marker는 유지한다.

추가 종료 진단 18개 job의 archive/map 36개, 1,597,119,409bytes도 MODEL-PC에
전체 SHA·크기 검증 및 디렉터리 fsync를 마쳐 보관했다. 검토·dry-run 후 각 job의
설치 weights와 journal 중복본 두 파일만 퇴거했다. 적용 proof는
`omx-ended-diagnostic-retirement-abcf20716b4a.json`이며 18개 모두 `RETIRED`다.
원본 byte의 로컬 raw·로컬 archive·MODEL archive와 canonical 결과는 유지한다.
AI 여유 공간은 7,124,279,296→8,763,068,416bytes였다. 이 작업은 실패나 실행 수를
제외하지 않으며 최신 3d26 실행과 최초 formal20은 이 추가 목록에 포함하지 않는다.

재학습 `omx-object-training-623a57360955be00`은
source `1dda28aa86b3ba989d81836fc0894a133109e37c`와 `command_entry` 표본 선택으로
실제 MODEL-PC에서 수행했다. 기존과 같은 25개·66,080프레임의 curation·전체 reader
readback과 20/5 분할을 확인하고 10,000 step·재로딩 검증을 완료했다. 전체 validation
MAE는 0.006172654422396879rad로 이전 모델보다 높으며 물체 성공을 뜻하지 않는다.
선택한 train 시작점은 전체 52,834프레임 중 명령별 6,263개다. 등록 스냅샷 확정·
등록본 재검증·평가용 묶음 전송과 실행 exit 0을 확인했다. 이 후보의 새 calibration은
통과했고 별도 사전 물체 과제는 실패했다. 새 native 성공은 아직 없다.

| 재학습 후보 산출물 | 고정 식별자 |
|---|---|
| Policy revision | `bec662e6e7348ff304b660ac388828434972861b797da15d0e12480637058ed0` |
| Dataset revision | `f810708dfc0915ee5d971c9cc0ae5e5c925a9b56bf36c73096e2672ae1d2dc39` |
| Model weights SHA256 | `02e35787cd9c1b9af71a6240d2eda8006886e8011089641afac4076d6b30ad52` |
| 학습 시작점 SHA256 | `5e23c544256bfbf17189a37bae6ceb06e9d7a6ec78ed6ce948019ea3a383d7f9` |
| 10,000개 loss 이력 SHA256 | `1a5f4e038e48809aba4c0b4e02a7ed85ab2bc6b4ea905a04ef6a4dff4dc8c1f8` |

새 정규화 SHA256은 이전 학습과 동일하다. Loss 첫 100개 평균은 0.4721478450,
마지막 100개는 0.0122491585이며, 이 감소도 실제 물체 성공 판정을 대신하지 않는다.

재학습 후보는 runtime 5fe39fd8d4에서 calibration 12추론·0정책 명령·0attempts·
PASS·cleanup을 확인했다. 이어진 사전 과제 run `1b3ee9682411`은 9candidate·9intent·
9accepted UUID·9terminal 상태4/code0 뒤 내부 fresh-capture 획득 timeout으로
종료됐다. 원문 camera 수신은 288건·거부0, admission_rejection은 없었으며
lift·안정 시간은 0, XY 오차 0.2292651311m였다. cleanup을 확인했고 새 formal20은
시작하지 않았다. 이전 후보의 0/26과 재학습 후보의 0/1을 모두 전체 분모에 남긴다.

실패한 열 번째 capture의 단계별 timing은 저장되지 않아 어느 구간이 전체 획득
500ms를 소비했는지는 확정하지 않는다. 이 내부 획득 한도와 원 수신→최종 검사
500ms 신선도 계약을 구분한다. 다음 변경은 원본 timestamp·선택 margin125ms·
모든 owner guard를 유지하고 새 입력 대기를 기존 actor의 종료·감시 조건에 연결한다.
source `35bfc824d9`는 callback 없는 기본 동작을 유지하며 실제 actor만 이 경로를
사용한다. 매 retry 전후·추론 후·이미지 저장 후·제출 직전에 원 actor 종료 조건을
재검사하고 callback·guard 오류를 즉시 전파한다. 새 시험 7개의 수정 전 실패를 확인한
뒤 관련 원격 검사 154 PASS / 1 SKIP / 0 NEW와 독립 코드 검토를 통과했다.
이 검사는 아직 다음 native 실행의 성공을 뜻하지 않는다.

이후 runtime35bfc824d9의 calibration도 PASS·cleanup을 확인했으나 실제 사전 과제
run `0dc9741a9f76`은 94candidate·94intent·93UUID·93terminal 상태4/code0 뒤
실패했다. 최초 admission 거절 증거는 `readback_step`이며 joint4의 실제 readback
1.3134999275rad와 target1.2716979980rad의 차이 0.0418019295rad가 0.04rad를 넘었다.
이번에는 단계 제한을 추정하지 않고 실제 비교값으로 확인했다. lift·안정 시간0,
물체 실패·cleanup 완료이며 새 formal20은 시작하지 않았다. 재학습 후보는 0/2이고
이전 후보 0/26과 함께 전체 0/28로 보존한다.

다음 학습 실험 source `c3d05862c1`은 내부 `joint_delta_from_chunk_source_v1` 표현을
추가했다. 같은 chunk의 모든 미래 원 target에서 시작 관측 상태 하나를 빼서 학습하고,
추론 시 그 원 상태를 더해 절대 target chunk를 한 번 복원한다. 원 label·timestamp·
대기 출력의 source는 유지하며 clip이나 owner 제한 변경은 없다. 새 정규화의
`action_transform`은 type·mean·std·absolute_baseline을 결속한다. 필수 legacy 통계를
두지 않아 구 소비자가 모델 생성 전에 실패하며 혼합·미지정 형식은 새 소비자도 거절한다.
절대 train target 평균인 평가 baseline은 delta 정규화와 분리했다.

시험 fixture를 보완한 source `d95d6b418c`의 일반 원격 검사는 73 PASS / 5 SKIP /
0 NEW다. 모델 PC의 실제 ACT 환경에서는 합성 fixture의 학습·재적재·chunk 원점·
대기 출력·결속 reader replay 검사 5개를 생략 없이 통과했다. 앞선 일반 시험의
fixture 누락 2건과 native 시험의 reader 경로 오류 2건은 별도 실패 로그로 보존했다.
실제 ACT 시험도 새 물체 과제 성공이 아니다. 같은 실제 시연 25개의 새로운 10,000 step
학습은 아래와 같이 완료했으며 이 표현의 실제 물체 과제 성공은 아직 없다.

후속 실제 MODEL 실행 `omx-object-training-14d92ea309083414`는 같은 25개·
66,080프레임의 curation·전체 reader readback과 20/5 분할을 확인하고 실제 10,000 step,
checkpoint 재로딩·DatasetStore 등록·등록본 재검증·모델 묶음 전송을 exit 0으로 완료했다.
Curation·분할 해시는 이전 실행과 같고 학습 시작점 6,263개도 동일하다.
원 절대 평가 baseline과 state 통계도 이전 파일과 대조해 같음을 확인했다.
실제 정규화 SHA256: `de4d107ed599eeb8b6c90b48d6dc3559f7a31aed96ce3a66f17b89bfb209a0a1`.
그 파일의 nested 표현과 legacy 필수 통계 부재를 확인했다. 전체 validation 13,246프레임의
MAE는 0.0037910785653385267rad, 상수 baseline은 0.29584911500909206rad,
관절 한계 위반은 0이다. Seed 42750·n_action_steps=1이며 판정은 `offline_only`다.
실제 물체 과제 성공은 아직 확인 전이다.

| 상대 표현 모델 산출물 | 고정 식별자 |
|---|---|
| Policy revision | `5814ad548c19236ce74677679477fcaac38f2d12b351e359d3dd95a3293a681e` |
| Dataset revision | `bbca52f6f53add7c2e51850f5900f2f7015462420ff2dcdcbecb8d039b99e9fb` |
| Model weights SHA256 | `926eeef12d14b96f147c8d3f71b17459974a51786bf72f4b865d1c91ba4c2177` |
| 10,000개 loss 이력 SHA256 | `cf496fbe2d6d0cb9dbfc4c013e5b03ee60100bc063eecb8c468c8937d31162e0` |

새 calibration 배포 준비 `85d66545afb4`는 기존 공용 SDK 환경 경로 부재로
`FAILED_OR_UNKNOWN`을 반환했다. 원 receipt와 HOLD를 보존하며 이 시도에서 calibration·
물체 과제는 시작하지 않았다. 새 모델을 실제 물체 평가 완료로 계산하지 않는다.
원격 상태 디렉터리·staging 부재와 unit not-found/inactive·PID 0을 재대조하고
원 HOLD를 별도 보존했다. 동일 소스의 공식 시험 의존 환경으로 SDK import·고정
profile 검사를 수행해 exit 0·ROS init false·정책 goal 0을 확인했다. 복구 배포
`08e7e2e8a9ce`는 실제 추론 12회·goals 0·attempts 0·cleanup true·exit 0으로 통과했다.

이어 같은 상대 표현 모델의 실제 사전 과제 `c36d124ac1de`는 96 candidate·96 intent·
96 accepted UUID 뒤 camera 원 관측 신선도 실패로 종료됐다. 관절 terminal 상태4/code0은
95개이며 마지막 goal은 cancel ACK 뒤 상태5/code0으로 끝났다. Cleanup true, lift·
stable 0, XY 오차 229.265131mm·Z 오차 10.000000mm이며 `incomplete_trial_observation`이다.
Actor 136.388초·전체 199.021초로 600초 종료는 아니다. 최초 admission 거절 값은 없고
traceback은 전송 후 full guard 경로의 camera source 검사를 가리킨다. 이 모델은 0/1,
이전 모델들의 0/28과 합해 전체 0/29다. 새 formal20은 시작하지 않았다.

마지막 candidate는 선택 시 입력 나이 116.872ms, numerical 57.383ms, 추론 후 owner
잠금 대기 81.292ms였다. 제출 직전 원 입력 나이는 259.618ms, submit은 244.540ms였다.
실제 goal 수락은 원 camera 수신 후 453.209192ms였고 이후 post-I/O 재검사에서 중단됐다.
원 결과 SHA256: `d335a419baa3c46842e0470e4cc16aff04168f8556984a5c2fd55393bd6f50c6`.

후속 source `536e0b5d47`은 numerical 뒤 immutable lease 참조를 한 번 읽어 기존
identity·issued/expiry 비감소 비교를 잠금 없이 수행한다. 초기 capture의 잠금과
`require_live`, 최종 submit·post-I/O full guard는 유지한다. 실제 thread 경합 회귀는
수정 전 잠금 대기로 실패했고 identity·두 시각 rollback 3개는 통과했다. 독립 검토에서
계약 blocker는 없었으며 수정 후 관련 원격 검사는 149 PASS / 1 SKIP / 0 NEW다.
같은 실제 모델의 별도 calibration `1d675c55821a`는 PASS·cleanup true·exit 0이었다.
이어 실제 사전 과제 `727d045efee4`는 113 candidate 뒤 `readback_step`으로 거절됐다.
원장에는 113 intent·112 accepted UUID·112 terminal 상태4/code0이 남았고 마지막 intent에는
UUID나 event가 없다.
그리퍼의 실제 readback 0.3108483553rad와 target 0.2704306543rad의 차이
0.0404177010rad가 기존 0.04rad 제한을 넘었다. 이번 실패의 admission 시 원 입력
나이는 약 205ms이며 camera stale의 반복으로 분류하지 않는다. 마지막 추론은
58.861ms, 제출 직전 입력 나이는 105.772ms, submit은 99.619ms였다. 이는 한 표본의
실측이며 지연 상한이나 일반적인 개선 보장이 아니다. Actor 148.400초 뒤 실패했고
cleanup true, lift·stable 0·동일 incomplete 위치 오차다. 새 모델은 별도 사전 과제
0/2, 전체 learned 결과는 0/30이며 새 formal20은 시작하지 않았다. 원 시연의 가까운
상태와 실제 rollout을 MODEL에서 읽기 전용으로 대조한 뒤 아래 학습 실험을 준비했다.

읽기 전용 MODEL 진단 `omx-relative-rollout-neighbors-1`은 train 52,834개 상태와
실패 과제의 7개 고정 frame을 대조해 exit 0으로 종료됐다. Step110의 실제 그리퍼
0.3789454401rad에서 예측은 0.3382530808rad였다. 가장 가까운 팔 5관절 상태의 거리는
0.055388rad이고 그 시연의 그리퍼 state/target은 0.4137569368/0.3804260884rad였다.
이 이웃 target은 실제 rollout의 정답이 아니며 실제 과제 성능으로 계산하지 않는다.
Teacher는 기존에도 6관절 0.04rad 단계 검사를 수행했고 무제한 그리퍼 시연으로 분류하지 않는다.

후속 source `34967a5996`은 같은 원본·20/5 분할·command_entry 선택으로 train 입력에만
표준편차 0.02rad의 관절별 독립 Gaussian 교란을 주는 회복 학습 실험을 추가했다.
원 RGB·절대 target·frame 순서·시각·train-only 정규화 fit을 유지한다. 전용 generator
seed42751을 쓰고 모든 미래 target에서 같은 noisy 시작 상태를 뺀다. Validation·재적재·
추론에는 교란을 넣지 않는다. 적용 설정은 normalization·offline report 및 DatasetManifest
transformation hash에 결속되며 기본0의 metadata·RNG 소비는 유지한다. 교란 입력은
synthetic이며 실제 관측·추가 시연·SIM truth에 합산하지 않는다. Gaussian은 관절 한계 밖
입력과 0.04rad 초과 target 차이도 만들 수 있고 clipping하지 않는다. 실제 recovery
정답이나 native 성공 보장은 아니다.

일반 RED5개와 실제 ACT RED1개는 수정 전 새 인자 미지원으로 실패했다. 수정 후 일반
원격 72 PASS / 0 SKIP / 0 NEW와 MODEL 실제 ACT 6 PASS / 0 SKIP / 0 NEW를 확인했다.
초기 일반 GREEN 요청의 잘못된 파일 경로는 exit4·실행0으로 보존하고 통과에 넣지 않았다.
독립 코드 검토에서 blocker는 없었다. 실제 시연 25개 전체 재검증·같은 seed42750의
새 10,000 step 학습을 요청했으며 새 checkpoint와 실제 물체 성공은 아직 확인 전이다.

실제 후속 MODEL 작업 `omx-object-training-bb0be7241e7ec64e`는 원 시연25개·66,080프레임의
curation·전체 reader readback과 같은20/5분할을 마치고 optimizer 학습에 들어갔다.
Curation·split SHA256은 이전 실행과 같고 실제 augmentation은 위 std0.02·seed42751·
6관절·train 전용 설정과 일치한다. 이를 제외한 정규화 통계 전체가 이전 파일과 정확히
같음을 대조했다. 새 정규화 SHA256:
SHA256: `841540d39eacba75e78474520326e7bdb39f462d7b9e4d46d009e7db6d7927e7`.
실제10,000개 loss 이력이 저장됐고 SHA256은
SHA256: `5dc7d8502c1892c55a933b31d4835207c62d3c9130533514977dbe4494bb54d5`다.
첫100개 평균2.1346675861·마지막100개 평균0.8952426803이며 교란이 있는 loss를
이전 무교란 loss와 직접 성능 비교하지 않는다. 전체 validation MAE는
0.006948906675814038rad로 무교란 상대 표현 후보의 0.0037910785653385267rad보다
높고 상수 baseline은0.29584911500909206rad다. Checkpoint 재로딩 예측 일치와
`offline_only` 판정을 확인했다. 새 Policy revision:
revision: `746e3b8e7fd8f9b16c7fbc0fd3fdd081fc65d679e6b05108afa5bc073313d109`.
등록본 복사·재검증·모델 묶음 전송과 실행 exit0을 확인했다. 전체 validation13,246프레임·
관절 한계 위반0·n_action_steps=1이다. Runtime source301dc82473의 calibration
`4be4d70b3ecc`는 PASS·exit0·attempts0·cleanup true로 통과했고, 별도 사전 물체 과제
`869a6d818862`를 실행 중이다. 실제 원장에62intent·62accepted UUID가 관측됐으며
이는 실행 중의 비원자 관측값이다. 물체 성공이나 최종 terminal 수로 계산하지 않는다.

| 상태 교란 학습 산출물 | 고정 식별자 |
|---|---|
| 학습 source revision | `34967a59969d90806aa3ec77e694c126bad1426d` |
| Dataset revision | `0360c0bccf2277e094006264a4fc8181f5c79ba8b3fa988d2e47d7b94d89e094` |
| Model weights SHA256 | `e8dec34c5f820ccc819f75f48807d9c8c8a74e8fda2121f190f4afebb2ccb284` |

실제 전송된 weights45,371,416bytes의 전체 SHA256을 로컬에서도 대조했다. 이 증거와
offline 지표를 새 물체 과제 성공에 합산하지 않는다.

최신 main d31ec2747f를 반영한 통합 source `301dc82473`는 공식 selector의 관련55경로를
AI PC에서 실행해 1,085 PASS / 35 SKIP / 0 NEW·exit 0이었다. 실제 ACT가 필요한 생략분을
이 통과에 넣지 않는다. 이후 test-only source `6ce9091ded`에서 모든 관절의 복원된 학습
target을 원본 값과 직접 대조하도록 보강했고 MODEL 실제 ACT 6 PASS / 0 SKIP / 0 NEW·
exit 0을 다시 확인했다. 통합 source의 정식 착지 dry-run은 안전·크기 검사를 통과하고
같은55경로를 계획했으며 실제 병합을 수행하지 않았다. 최종 물체 목표와 착지는 남았다.

이후 main dc8c3cc2bf를 충돌 없이 반영한 통합 source `9bcca8e7bd`는 공식 selector의
관련 55개 경로를 AI PC에서 실행해 1,077 PASS / 34 SKIP / 0 NEW를 확인했다.
안전·크기 검사도 통과했다. 생략한 ML 검사를 통과에 넣지 않으며 실제 ACT의 합성
fixture 5 PASS는 별도 증거다. 새 실제 물체 평가와 최종 main 착지는 여전히 남았다.

당시 main을 병합한 2e33820d21의 공식 selector는 알려진 소비 경로를 따라
affected 48개 경로를 지정했다(확대 사유 없음). 해당 선택을 모델 PC에서 실행해
1,001 PASS / 31 SKIP / 0 NEW를 확인했다. 검사 전 준비 함수의 무실행 반환을
FULL 통과로 계산하지 않으며, 생략한 검사를 통과 수에 포함하지 않는다.

## 유지한 실행·성공 기준과 시험 범위

원 입력·생성 시각, 500ms 관측·action 신선도, 최대 1초 lease, 0.04rad 단계 제한,
0.8초 goal/최소 제출 간격, 600초 전체 예산을 유지한다. 원 모델 출력을 clip·교체하거나
teacher로 대체하지 않는다. Startup HOME은 별도 프로세스로 종료된 초기화다.
실제 accepted UUID와 terminal 상태 4/code 0이 있어야 관절 goal 성공이다.

물체 성공은 독립 관측으로 lift 30mm 이상, XY 오차 10mm 이하, Z 오차 5mm 이하,
실제 gripper open·해제·분리와 10mm/s 이하 속도 2 SIM초를 모두 요구한다.
SIM DetachableJoint 부착 보조를 사용하며 width/position/geometry 증거로 결속한다.
접촉력 센서·실물 집기·랜덤 초기 상태 일반화·Fleet 운영 승격은 입증하지 않았다.

CPU 비교 후보의 원격 검사 66 PASS / 0 NEW와 읽기 전용 코드 검토를 완료했다.
최초 잘못된 test 경로 요청은 exit 4 / 실행 0으로 보존했고 통과로 계산하지 않는다.
이 시험과 calibration은 실제 20회 물체 과제 성공을 대신하지 않는다.

이전 학습 수정과 보고서는 로컬 main c3ae44ae3f에 정식 병합됐다. 후속 private native
runtime과 본 진행 보고서는 아직 최종 착지 전이다. GitHub push·실물 실행은 하지 않았다.
Road-surface 사람 검수는 사용자 우선순위에 따라 OMX 이후로 보류하며 여전히 0/24다.
