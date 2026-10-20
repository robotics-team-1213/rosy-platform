# OMX native SSH 자동 배포 구현 계획

> Historical plan recovered on 2026-10-19. Preserve its original decisions and sequence as context; current repository instructions and independently reviewed recovery commits govern execution. This plan is not approval to deploy or activate hardware.

기준: D-786. 사용자는 외부 개발 PC의 에이전트가 SSH로 직접 실행하며 이후 배포까지
자동화하도록 요청했다. root 권한이 없는 현재 호스트는 provisioning 차단을 정직하게
남기되 일반 권한으로 할 수 있는 배포 준비·검증은 모두 수행한다.

## 완료 조건

- root helper는 설정된 AI/model 계정과 고정 run ID만 허용한다. 임의 명령·옵션을
  받지 않고 서비스는 일반 사용자와 고정 namespace/cgroup 제한으로 실행한다.
- 배포 도구는 커밋 source와 SDK 파일을 해시로 묶고 실제 G2 compile/import를 검증한다.
- staging/provision/deploy/start/status/fetch가 한 경로를 쓰며, 이미 배포한 동일
  버전은 검증 후 재사용한다. 불일치한 같은 버전을 덮어쓰지 않는다.
- 실행은 별도 명시적 허가가 있어야 한다. intent 전 실패는 재점검 가능하며 intent 후
  불명 결과는 재시작하지 않고 조회한다. 기존 G2/Fleet/OMX 권한 경로는 유지한다.
- 원격 커밋 테스트, root 경계 독립 리뷰, 실제 SSH staging/doctor/fetch 증거를 남긴다.
  OS 권한이 없다면 실제 격리 task·실물·학습 완료를 주장하지 않는다.

## 작업

1. `deploy/hosts/common`의 좁은 helper와 provisioning installer, 거절·고정 속성
   테스트를 구현한다. 테스트는 root 작업을 mock하며 원격 시험 PC에서 실행한다.
2. `deploy/robot/omx`에 manifest/환경/one-shot job lifecycle을 구현한다. 기존 G2
   runner를 호출하며 새 ROS 또는 장치 명령 경로를 만들지 않는다.
3. `tools/remote`의 SSH 배포 CLI와 private 설정 template을 연결한다. 실제 현재 SDK
   경로로 staging·doctor를 수행하고, 허용된 경우만 provisioning/activation한다.
4. 독립 계약·권한 리뷰와 affected 원격 검증 후 승인된 로컬 병합을 수행한다. push는
   하지 않는다. 실제 실행이 막히면 구체적인 provisioning 산출물과 원인을 보고한다.

## 검증 증거

파일/입력 hash 변조, 다른 역할·계정·run ID, 자원 부족, 중복 시작, sudo 거절과 불명
SSH 결과를 검증한다. source/SDK PASS, helper provisioned, service started, startup
READY, task GOAL_CONFIRMED, real episode, training 결과를 각각 기록한다.
