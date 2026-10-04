# 학습 산출물 공용 계약 초안

[D-449](../../docs/adr/D-449-learning-artifact-and-owner-binding-contracts.md)의
`rosy-contracts-learning`은 ROS·torch·LeRobot에 의존하지 않는 공용 wheel이다.
Episode·DatasetManifest·PolicyArtifact·PromotionRecord의 구조와 파일 해시를 검증한다.

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
