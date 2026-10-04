# 실제 Pinky 모델의 공통 정책 산출물과 거절 원장

2026-10-04, `feat/learning-pipeline-closure`, 기준 `4bd23be91` 이후 변경.
[계획](../plans/2026-10-04-pinky-policy-artifact.md)의 SOURCE/HOST 단계다.

## 공통 계약과 산출물

계약 wheel 0.1.5는 camera calibration SHA가 실제로 없으면 null을 보존하며,
알려진 CameraProfile과 null calibration 조합은 거부한다. null profile은 계속
L1 물리 shadow 승격을 통과하지 못한다. declared topic identity를 물리 카메라
identity로 인증하지 않는다. stdlib 계약/원장에 numpy·torch·ROS를 추가하지 않았다.

실제 [비교 실행](pinky-behavior-comparison-2026-10-04.md)의 CNN/ridge 파일을
원본 file/3개 Dataset/Episode closure, split·평가 target·train-only 정규화·오차에
대조하고 각 모델을 재로딩해 실제 평가 영상을 다시 추론했다. 같은 NPZ 예측과 일치했다.
hash를 다시 맞춘 다른 weights와 오래된 예측 조합은 RED 재현 후 거부했다.
exporter는 원본 MCAP도 세 세션 모두 직접 재검증하며 예전 pass 보고서를 신뢰하지 않는다.
그 검증기가 실패하면 이전 pass가 있어도 출력이 생기지 않는 RED→GREEN 시험을 추가했다.
각 산출물에 세 새 raw-reverification 보고서를 포함하고 복사 SHA 및 전후 closure를 검사한다.

camera source/model RGB는 320×240/64×48이며 calibration/profile은 null이다.
학습 target은 recorded CORE final velocity, 정책 인터페이스는 base_velocity_candidate다.
원본 profile YAML 해시와 명목 ±0.20m/s·±0.80rad/s를 보존한다. 현장 safety 승인,
설치 profile 또는 envelope 수용을 주장하지 않는다. controller/envelope는 unregistered,
period125ms·observation250ms·action125ms는 아직 집행되지 않은 연구 선언이다.

| 모델 | 최종 PolicyArtifact revision |
|---|---|
| CNN | `fb4fec28bc87b99641e86c8275fd1a9be9859912b165bef9fae649e0528fd7fe` |
| ridge | `7b8e7e19439c904d8d080e4975f7e0cf279dfb9b07bc1def8ceb375839e70091` |

원본 3 Dataset revision은 그대로다. 각 정책의 dataset_revisions는 학습과 평가 출처를
모두 묶으며 이들이 등록·무결성·Pinky profile/robot/environment 검사를 통과했다.
최종 출력은 `X:/DevTemp/rosy-learning-audit-20261004/pinky-policy-{tiny_cnn,rgb_ridge}-v2/`다.
초기 v1은 새 raw 검증 전 exporter 실행 이력으로 보존하고 최종 원장에는 v2만 등록했다.

## 영속 평가와 검사

두 정책을 실제 registry에 snapshot/register하고 assess-pinky를 실행했다.
같은 평가는 idempotent이며 각각 register/assessment 두 event를 유지한다.
별도 CLI 프로세스 재독출에서 단계 unregistered와 reject를 확인했다.
두 정책 모두 expert intent 미확인, m/s baseline 미달, rad/s baseline 미달의 세 이유다.
외부의 합성 signed pass도 bound Pinky reject를 덮어쓰지 못하는 integration 시험이 통과했다.
명목 limit 위반은 두 모델 모두 0이며 이것은 안전·과제 성공 판정이 아니다.

- native Python 3.12 영향 시험: 94 passed, skip 없음. 실제 소형 MCAP/모델 replay 포함.
- Python 3.14 host: 82 passed/12 skipped. MCAP·torch가 없어 native에서 같은 시험을 실행했다.
- 독립 리뷰: 핵심 artifact/training/registry/계약 68 passed, 남은 material findings 없음.
- 독립 read-only 실제 산출물/SQLite 검증: 정책당17개 참조의 SHA/크기, exporter/
  comparison/새 raw verifier source 해시, 3 Dataset와 fresh1595/2673/888프레임 binding,
  각2event·unregistered/reject·세 거절 이유가 일치했다. 큰 원본 decode/model은 재실행하지 않았다.
- ownership/import 구조: 51 passed. 문서/harness: 89 passed/기존 경고 26개.
- lint 0 errors/26 기존 warnings. staged whitespace 검사 통과.
- isolated wheel 0.1.5로 실제 두 artifact의 모든 파일과 null 보정을 검증했다.
  Requires-Dist 없음, torch/numpy/PIL/yaml/mcap/rclpy 미로드.
- wheel SHA-256 `0db1ac37c2493041e2414ca513080e5ffe01f3227438a87ff01f7797e8c566ec`.

실제 readback은 `pinky-policy-registry-readback.json`, 별도 CLI 결과,
`pinky-policy-wheel-validation.json`에 보존했다. owner admission·lease/generation·
stale/reset/HOLD 집행, rollback/stop readback, 독립 SIM 과제/Fleet join, camera 보정과
expert 주행 정답·Pilot Episode·model PC wholejob·DEVICE/FIELD 검증은 미완료다.
로봇 연결·motion/hold 해제·runtime activation·main merge/push·remote CI는 하지 않았다.
전체 목표는 active이며 운영 승격은 거절 상태다.
