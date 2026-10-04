# Owner 설치 binding 검사 검증

2026-10-04. 기준 HEAD `17d192de8f5d66560887ee71eede46af5d4dc6aa` 이후 변경.
[계획](../plans/2026-10-04-owner-policy-install-binding.md).

## SOURCE / HOST

middleware/execution/local wheel0.1.1은 contracts/learning0.1.6을 사용한다.
고정 policy revision·device/camera profile·owner/controller/envelope·카메라 metadata·
정규화 SHA·행동 순서/범위·stale budget과 주기를 검사하고 파일을 재검증한다.
설치 주기는 정확히 일치해야 하며 action/stale 범위는 설치값 이하여야 한다.
읽은 metadata는 불변 bytes로 보존한다. middleware가 learning registry를 조회하지 않는다.

RED는 skill dependency 경로를 고친 후 새 모듈 부재로 확인했다. 최종 관련
host54passed(새17개·공통 artifact·D-427 boundary), 독립 targeted17passed.
리뷰의 camera True/1 alias와 mutable profile 누락은 RED3건으로 재현 후 수정했다.
canonical JSON bytes 비교는 숫자와 bool을 구분한다.

문서/배치 gate89passed/26기존 last_verified 이력 warnings.
작업/스테이징 diff whitespace 검사가 통과했다. remote CI·ARM64 설치 증거는 없다.

## ARTIFACT / 실제 연구 정책

X 소스 복사에서 execution-local0.1.1과 skill0.1.0 wheel을 빌드했다.
execution wheel SHA-256:
`3f1b6a0fb046615dde65fae3e1fb4fc6db8f5191fb48dc25a7e018eb48b20e33`.
loader source SHA-256:
`63f84f596ab5b668e1cbc6ee1a755dff4050b7ede6ad0cd38ea8e7738a880229`.
Python3.12.14 isolated import에서 실제 wheel을 사용했고 torch/numpy/PIL/yaml/
rclpy/mcap/pydantic 미로드를 확인했다. Requires-Dist는 위 두 contracts wheel뿐이다.

보존된 OMX ACT·Pinky CNN/ridge 정책3개의 canonical/file integrity를 검사했다.
승인된 설치 binding은 없으므로 `load_policy(root, None)`은 세 정책 모두 거절했다.
후보 manifest 값으로 가짜 승인 설치 profile을 만들지 않았다. 기존 거절 원장이나
정책 revision을 바꾸지 않았다. 실제 dispatch는 시도하지 않았다.
증거 `X:/DevTemp/rosy-learning-audit-20261004/owner-policy-install-audit.json`.
긍정 load/recheck 테스트는 합성 HOST fixture다.

## 외부 상태와 남은 gate

origin/main을 fetch해 검토했다. 현재 worktree와 remote main에는 D-442 구체 wire
파일이 없다. 기존 Fleet ActionGrant와 D-390 Pilot seat를 범용 정책 lease로
재해석하지 않는다. 실제 owner process wiring·승격 trust·lease/fence/generation·
관측/행동 stale·HOLD/reset·독립SIM 과제·stop/rollback·DEVICE/FIELD는 남아 있다.
이 loader는 설치 인증/권한 승인기가 아니며 파일의 향후 변경을 막는 lock도 아니다.
추론 loader가 실제 소비할 bytes를 고정하고 재검증해야 한다.

모델 PC SSH 읽기 전용 조회는 Tailscale 추가 본인 인증을 요구했다. 서버가 만든
인증 링크를 사용자에게 전달하고 그동안 로컬 작업을 계속했다. remote command
성공이나 GPU/SIM 실행 증거는 확보하지 못했다. 전체 목표는 active다.
