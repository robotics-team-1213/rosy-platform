# 학습 산출물 공용 계약 초안

[D-449](../../docs/adr/D-449-learning-artifact-and-owner-binding-contracts.md)의
`rosy-contracts-learning`은 ROS·torch·LeRobot에 의존하지 않는 공용 wheel이다.
Episode·DatasetManifest·PolicyArtifact·PromotionRecord의 구조와 파일 해시를 검증한다.

D-700의 0.1.10은 `incident_rule.validate_rule()`로 실제 Fleet 규칙 선택 JSON을 검사한다. `selected_not_executed`, `action_admissible:false`, `outcome:null`을 유지하며 RULE_ONLY/MIXED·NONE/ANSWER/HOLD/HANDOFF를 구분한다. physical WAIT를 포함한 ANSWER는 reobserve/human으로 변환하지 않는다. 보정·정답·명령·현장 수용을 승인하는 SDK가 아니며 Fleet 기본 원장 사용 때문에 필수 설치 의존성이 됐다. 기존 `fleet[learning]` 설치 이름은 호환한다.

D-727의 0.1.11은 `incident_operation`에 별도 운영 수용·폐기 receipt의 닫힌 구조와 HMAC 검증을 제공한다. 전체 프로파일·모델·보정·독립 평가/정답/한계/coverage·설치·현재 owner epoch와 유효 기간을 결속한다. 원본 평가·현장 증거와 실제 owner admission은 소비자가 별도로 검증하며 receipt 검증 자체는 실행 권한이 아니다.

0.1.12는 D-622 후속으로 `validate_rule()`의 ANSWER에 `REALIGN`을 받는다. REALIGN 선택만 조작 본문의 정렬 JSON SHA-256인 `selection.realign_sha256`을 반드시 가지며 다른 선택에는 이 키가 없다. 기존 `rule_selection/1` 기록은 그대로 유효하다. 자세·각도 원문은 receipt에 복사하지 않고 REALIGN도 물리 ANSWER라 reobserve/human 기준으로 변환하지 않는다.

0.1.13은 고정 OMX SIM 물체 과제에 명시적으로 제공된 `rosy.omx-sim-object-truth/1`을
검증한다. 원본 영상·명령 수락/완료·물체 관측·gripper owner 시계와 신선도·고정 장면을
파일 해시에 연결하고 성공을 재계산한다. 공통 Episode의 `sim_ground_truth`는 이 증거를
모두 보존하며, 기본 operator 기록과 사람 검수·운영 승격 기준은 그대로 둔다.
고정 10Hz 카메라의 기록은 10fps 또는 교사 시연용 5fps만 받는다. 원본 capture/state
시각과 선택한 기록 주기의 간격을 그대로 검증하며, 주기 표기만 바꾼 원본은 거절한다.

[D-854](../../docs/adr/D-854-omx-policy-runner-and-action-space.md)의 `action_space`는 OMX 데이터셋·정책이 선언하는 행동 단위
(`lerobot_norm_v1`, `dynamixel_rad_v1`)와 버전이 붙은 순수 변환기다. 식은 lerobot 0.4.4 `omx_follower`
(`use_degrees: false`) 정규화와 같고, 범위 밖 값은 잘라 맞추되 `convert()`가 잘린 개수를 돌려준다. lerobot
0.4.4 Dynamixel 버스는 `apply_drive_mode = False`라 `drive_mode`를 읽지 않으며, 보정 digest는 `range_min`·`range_max`만 쓴다. `dynamixel_rad_v1`이 설치된 ROS 관절 rad와 같은지는
보증하지 않는다. 다음 wheel 버전은 첫 소비자(정책 실행기)가 붙을 때 올린다.

[D-864](../../docs/adr/D-864-d854-units-trajectory-and-simulator-roles.md)의 `ros_joint_rad`는 CORE·Gazebo·Isaac Sim이 쓰는
ROS 관절 rad(`joint1..5`, `gripper_joint_1`)다. 이 단위로 바꾸려면 `validate_joint_map()`이 받아들이는 관절 대응 판정이 필요하다.
판정은 통과해야 하고, 판정의 팔이 데이터의 팔 정체(`arm_identity()`: rig revision, 두 팔이면 `/arm_a`·`/arm_b`)와 같아야 하며,
판정이 기록한 보정 range digest와 보정 파일의 homing offset·drive mode(0)도 맞아야 한다. 작업대의 보정은 모두 range가 같을 수 있어
팔 구분은 팔 정체가 맡는다. 팔 정체는 운영자가 정하는 이름이라 배선을 바꾸거나 팔을 교체하면 새 이름과 새 판정이 필요하다.
`ros_joint_rad` 선언은 `joint_map_revision`을 더 가진다. 보정과 판정이 둘 다 `null`이면 SIM 데이터이고, 실물 데이터를 바꾼 것이면
`ros_declaration()`이 둘을 채운다.

```python
from rosy.contracts.learning import seal, validate_episode

manifest = seal(metadata)  # schema별 필수 항목이 있는 dict
validate_episode(manifest)             # 구조/canonical revision만
validate_episode(manifest, root=path)  # 실제 상대 파일의 bytes/SHA도
```

`seal()`은 `revision`을 제외한 JSON의 정렬 키·UTF-8·공백 없는 표현에 SHA-256을
적용한다. manifest 자기 참조와 변환 시점 timestamp를 자동으로 추가하지 않는다.
검증 함수는 입력을 바꾸지 않고 복사본을 반환한다. null/unknown을 채우지 않는다.
파일 이름은 정규화된 POSIX 상대 경로이며 실제 root 밖으로 나갈 수 없다.

OMX rad 목표와 Pinky m/s·rad/s 후보는 profile, owner, 순서·단위가 별도다.
normalization·device/camera/envelope/controller binding은 loader가 실제 설치와
비교해야 한다. 이 패키지는 모델 추론, API, lease, 정지, registry 또는 actuator를
실행하지 않는다. promotion report의 pass와 approval 참조도 진위·권한 수용을
증명하지 않으며 owner admission은 후속 구현이다.

0.1.1 초안은 `cameras`에 identity/calibration fingerprint, source/model RGB shape와
scale을 명시한다. camera_profile_revision의 null을 보존할 수 있지만, 카메라를
사용하는 정책의 L1 이상 승격 기록은 실제 CameraProfile binding 없이 거절한다.

샘플 wire 입력과 거절 예는 `test/test_learning_artifact_contracts.py`에서 검증한다.
0.1.2는 reset_events를 반드시 JSON list로 요구한다. 같은 이름의 key를 가진
object를 목록으로 오인해 받던 검증 오류를 수정했으며 정상 정책 revision은 유지한다.
OMX 변환기는 `learning/curation/omx/common_episode.py`이다. 기존 시연의 profile
검증과 원본 bytes를 보존한다. 기존 runtime recorder·LeRobot 파일 형식은 유지한다.
Pinky/Pilot 변환기·Fleet join·학습 정책 실제 소비/승격·장치 loader는 아직 남아 있다.

0.1.3의 `rosy.contracts.learning.omx.validate_demonstration(path)`는 완성 시연의
rad 목표·시계·간격·skew·원본 해시·RGB PNG CRC와 압축 행을 검사한다.
`validate_profile(doc, root=path)`는 공통 OMX Episode를 원본 manifest/stream에
연결한다. 일반 `validate_episode`는 계속 구조·파일 검증만 수행한다.
DatasetStore와 offline curation은 OMX profile 본문 검증을 호출한다.
DatasetStore는 아직 본문 검증기가 없는 Pinky/Pilot profile을 등록하지 않는다.
원본 task outcome은 operator 기록이며 독립 과제 성공의 인증은 아니다.

0.1.4는 Pinky recording profile과 변환 metadata/sidecar를 추가한다.
`rosy.contracts.learning.pinky.validate_profile`은 원본 session과 변환 파일의
binding, capture/log 시계와 recorded CORE command의 m/s·rad/s 및 dt를 검사한다.
DatasetStore는 Pinky도 등록하며 Pilot은 거부한다. 원본 MCAP↔sidecar 변환 진위와
영상 pixels/scan 내용을 인증하지 않는다. 정책 승격은 Dataset Episode의
profile·robot/environment 호환성을 같은 검증 객체에서 검사한다.

0.1.5의 영상 정책은 camera calibration SHA가 실제로 없으면 null을 보존한다.
이때 CameraProfile도 null이어야 한다. 알려진 profile과 null calibration 조합은
거부하며 null profile은 L1 물리 shadow 승격을 통과하지 못한다. topic identity는
카메라의 물리 identity 인증이 아니다. 계약 wheel은 여전히 stdlib만 사용한다.

0.1.6은 OMX owner receipt provenance를 보존한다. 공통 Episode sources의
`owner-receipts/000000.json`부터 연속 파일과 녹화 sample의 ros_goal_id 전체를
대조한다. 동일 mission/step/action/attempt/workcell/instance/request/epoch/generation/
journal만 단일 상관 pair로 보존한다. Receipt 없는 legacy source는 empty
correlations만 허용한다. schema 구조가 맞더라도 임의 상관 키는 profile 검증에서
거절한다. 이것은 goal/identity 근거 검증이며 receipt 인증이나 독립 과제·정책 실행
검증이 아니다. action outcome unknown과 policy revision null을 유지한다.

0.1.7은 `omx_policy_execution_v1`과 stdlib `omx_execution.validate_profile`을
추가한다. 원본 native intent/callback, policy 설치 byte closure, 기존 Action parent,
실제 ActionAPI v2 receipt/journal identity를 대조한다. observation은 metadata-only이고
raw camera/inference 확인이 없어 status incomplete/task unknown을 유지한다.
기존 demonstration 계약을 바꾸지 않으며 DatasetStore/승격/학습에는 받지 않는다.
body/file 검증은 인증·실행 권한·장치/과제/물리 수용을 부여하지 않는다.
# Incident handoff evidence (D-696)

`incident_handoff.validate_handoff(value, scope, started_at)` validates bounded JSON only.
`tools/incident_model_feedback.py --include-handoff` adds optional
`rosy.incident.model_feedback/2` evidence from one read-only Fleet snapshot;
the default remains `/1`. The recording binder's existing `--model-feedback`
and `--failure-analysis` accept either version and retain `UNREVIEWED`.

`case.handoff` separates the persistent queue, final notification rows and named
claim record. `tables` distinguishes missing storage from present empty storage.
`SENT` means provider acceptance; `CASE_ONLY` claims are recorded names with no
verified identity. Raw names, route/endpoint, provider IDs, links and payloads
are omitted. Source digests and scope binding do not prove provenance by
themselves: independent evaluation must approve the producer artifacts separately.
This evidence does not establish recurrence absence, command absence, model
contribution, independent quality or physical success. No notification or model
is called by this validator or export.

## 단독 판정 모델 역할 근거 (D-698)

`rosy.contracts.learning.incident_profiles.validate_primary_roles(case)`는 새로운
`model_feedback/3`의 단독 primary 프로파일, 선언된 역할 예산과 실제 시도 역할을
검증한다. exporter·recording binder·독립 평가가 같은 JSON 검사를 사용한다.
출처 인증·독립 정답·실제 모델 호출·운영 수용을 승인하지 않는다.

