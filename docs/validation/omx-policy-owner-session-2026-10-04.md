# OMX 정책 owner session 소스·호스트 검증

검증일 2026-10-04. 기준 HEAD `18590782391597a1693b8b19c47606349bc98694`에서
`feat/learning-pipeline-closure`의 로컬 변경을 검사했다. SOURCE/HOST와 wheel 증거이다.

## 변경과 확인

기존 ArmCommandOwner와 SQLite LocalStopController를 이용하는 default-disabled/SIM 전용
OwnerPolicySession을 추가했다. 설치 controller/config SHA, owner session, AttemptIdentity,
짧은 lease, epoch/generation, 관측 sequence/time, action 범위/주기를 대조한다.
카메라가 선언된 정책은 trusted capture metadata와 identity/calibration/shape/frame SHA,
관측 age와 action 생성 시각의 인과관계를 확인한다. callback 처리 후와 실제 submit 직전에
시간을 재검사한다. 실패는 HOLD를 유지하며 자신의 활성 명령 cancel을 요청한다.

독립 리뷰가 재현한 authority callback 지연 중 lease 만료, observe(None) 예외의 HOLD 누락,
action 생성 후 도착한 camera frame의 인과관계 누락을 각각 RED 회귀로 확인한 뒤 수정했다.
최종 독립 targeted **38 passed**, 남은 blocking issue 없음, D-430 소스 리뷰 승인이다.
리뷰어 `/root/policy_registry_review`의 검토 SHA와 최종 파일 SHA가 일치한다.

```
omx_policy.py SHA256 70fe0b86ec4cb48084b7b8061ada4a6e6fbb7ca5be6ea34d36546f36834a8b83
rosy-execution-local 0.1.2 wheel SHA256 44b705729319a1a905feb4a238f77ff027f8de9edb14d882c6116df445c87abf
```

관련 최종 host 회귀 **153 passed**:

```powershell
python -B -m pytest middleware/execution/local/test/ src/products/omx/adapter/test/test_omx_command_owner.py src/products/omx/adapter/test/test_omx_stop_fence.py test/architecture/test_platform_parts.py test/architecture/test_safety_separation.py -q -p no:cacheprovider --basetemp X:/DevTemp/rosy-owner-session-final-causality
```

실제 owner와 stop fence를 사용했지만 action transport, 설치 artifact, authority/camera provider는
HOST fixture이다. fixture의 operator_confirmed rearm은 실제 장치 조작이 아니다.

X 드라이브 소스 복사본에서 wheel을 빌드하고, Python3.12의 별도 target에 contracts와 함께
설치했다. 설치 loader는 pydantic/ROS/학습 framework를 로드하지 않는다.
optional owner module은 명시된 native adapter/foundation 경로와 Pydantic을 사용하고
torch/numpy/PIL/yaml/rclpy/mcap을 로드하지 않는다. 설치 파일과 검토 소스 SHA가 일치한다.
실제 연구 정책 3개의 파일 integrity를 재검증했으며, 승인된 installation binding 부재로
모두 load를 거절했다. 정책 dispatch는 시도하지 않았다.
로컬 증거 `X:/DevTemp/rosy-learning-audit-20261004/owner-policy-session-wheel-audit012.json`.

## 현재 영상 라벨 상태

기존 draft review pack의 76프레임과 객체 검토 이미지 4장, 총 80 SHA를 재검증했다.
44 train / 32 val 제안은 촬영 그룹별로 분리되며 기존 고정 평가 세션 2개를 포함하지 않는다.
프레임 76개 모두 pending; 객체 4프레임/7박스 모두 pending_human이다.
신호등 2 / 로봇 2 / 사람 발 3, 신호등 상태는 둘 다 unknown이다.
원본 MP4 전체 SHA는 이번 감사에서 재검사하지 않았다.
라벨 설계와 후속 학습 비교는 `docs/plans/2026-10-04-recorded-video-label-training-design.md`에 기록했다.
증거 `X:/DevTemp/rosy-learning-audit-20261004/video-review-audit-20261004.json`.
검수된 새 객체/신호 모델의 학습 완료나 성능 수용을 주장하지 않는다.

## 잔여 gate

실제 issuer/권한 승인, camera capture provider/추론 pixel 소비, poll scheduler, ROS 프로세스
wiring, 독립 SIM 과제와 행동 품질, durable rollback/독립 stop readback, Pinky CORE 연결은 미완료다.
cancel 응답은 물리 정지 증거가 아니다. source SHA는 승인/서명 trust를 대신하지 않는다.
실제 3개 정책의 operating qualification을 부여하지 않았다.
기존 SSH 인증 대기 handle은 이번 확인에서 종료됐고 원격 명령 성공 증거가 없다.
모델 PC 전체 recording job 및 새 라벨 검수/학습, DEVICE/FIELD 수용도 남아 있다.
push/merge/deploy/물리 주행/운영 HOLD 해제는 수행하지 않았다. 전체 목표는 ACTIVE이다.
