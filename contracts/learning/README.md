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

샘플 wire 입력과 거절 예는 `test/test_learning_artifact_contracts.py`에서 검증한다.
OMX 변환기는 `learning/curation/omx/common_episode.py`이다. 기존 시연의 profile
검증과 원본 bytes를 보존한다. 기존 runtime recorder·LeRobot 파일 형식은 유지한다.
Pinky/Pilot 변환기·Fleet join·학습 정책 실제 소비/승격·장치 loader는 아직 남아 있다.
