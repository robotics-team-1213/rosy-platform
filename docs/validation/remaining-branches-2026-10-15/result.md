# 남은 브랜치 통합 검토 — 2026-10-15

요청은 남은 작업 착지 후 push다. 아래는 통합 중의 SOURCE 검토이며 착지·push·장치 수용 완료 기록이 아니다.

## 독립 리뷰

Codex `/root/camera_review`가 D-171의 `6c385733e`, `82dadfb76`, `a921f79c4`,
`815007ecd`, `710c99dd7`, `b3e3f9590`, 이동 경로 통합 `df82986e4`를 읽었다.
Float32 값, zero Twist와 Parameter, 토픽·depth, TF 실패, E-stop의
stop→abort→zero→latch 순서를 보존한 SOURCE 추출이라고 승인했다.
정확한 커밋만 기존 safety_review_exempt 원장에 기록한다. 원격 시험과 실제 ROS 검증을 면제하지 않는다.

같은 리뷰에서 SD 카드의 잘못된 mount와 미마운트 파티션을 지우기 전에 검사하지 않는 결함을 발견했다.
`c6f2e89b0`이 대상 디스크·volume root 검사와 조회 실패 거절을 추가했다.
standalone PowerShell 시험은 변경 전 wrong-disk 거절 실패, 변경 후 PASS였다.
실제 writer와 같은 StrictMode 및 정상 mounted boot/Linux root 대조도 PASS다. 실제 카드 쓰기는 하지 않았다.

CI 충돌 해결 `e441a45e2`는 account SSO browser opt-in과 기존 flaky quarantine 절차를 함께 보존했다.
전원 정책 리뷰에서 첫 ON·perception만 복귀 시 ready 보고 누락을 발견했다. 수정·원격 회귀는 별도 기록한다.

## 이력만 남은 브랜치

Codex `/root/arm_learning_arch_plan`의 읽기 전용 독립 비교:

- `refactor/d427-bulk`: `ed2b24c7d`와 main `3c6354898`, `caaa2a586`와 main `2c4cd4eb2`의 patch ID가 같다. 현재 폴더를 이전 구조로 되돌리지 않는다.
- `refactor/size-ratchet-d766`: main `337b1333b`로 squash한 뒤 `e767033de`, `ef277763e`, `54405aada`가 commit별 규칙·merge parent·제품 전체 coverage를 개선했다. 옛 구현으로 덮지 않는다.
- `docs/d476-gazebo-model-pc`: main `f98e69aa2`가 포팅하고 `92304cc82`, `8064b53e0`가 증거를 확장했다. 과거 실패 기록을 성공으로 바꾸지 않는다.
- `quarantine/auto-state-fixtures-20261003`: `harness@test`의 합성 fixture이며 `96a6db34d`가 제품 파일 4,239개를 지운다. 제품 병합 대상이 아니다.

## 그대로 합치면 안 되는 실제 미완료 변경

- `feat/d400-plan2-rosim`: worker 이름·shadow 녹화 sink·Fleet buffer 제외 등 미통합 기능이 있다. 옛 전체 구현은 현재 snapshot provider와 명시적 simulation scan 허가를 잃는다. 현재 소스에 선택 포팅·독립 안전 리뷰·시험이 필요하다.
- `fix/crosswalk-side-structure`: 동일 D-573 rev5에 현재 차로 방향 정렬과 옛 옆 구조물 제외 설계가 충돌한다. 현재 kernel에 조합 관계를 결정하고 시험해야 한다.
- `fix/gazebo-map-lap`: 합성 merge에서 `ForwardEvidence`가 두 번 정의되어 새 producer가 TypeError를 낸다. nominal CAMERA 제한과 D-740 forward arc도 함께 보존해야 한다. 명시적 WIP이며 같은 지도 SIM 수용이 없다.
- `feat/fleet-work-approval-seat`: 현재 D-763 새 작업·trip·Cell 흐름을 유지하며 실제 Mission 승인 UI를 통합해야 한다. 오래된 화면 파일 전체로 대체하지 않는다.

해당 원본 브랜치·미커밋은 보존한다. 새 테스트 실패나 검토 차단을 무시하는 강제 착지·push는 하지 않는다.
