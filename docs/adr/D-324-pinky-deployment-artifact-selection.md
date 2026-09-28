## D-324 기존 Pinky 배포는 변경에 맞는 가장 작은 산출물을 선택한다

**Status:** Accepted (2026-09-29, 산출물 범위 선택 기준). 서명·설치·장치/현장 수용 게이트는 D-145/D-225 및 해당 device runbook에 남는다.

### Context

Pinky 배포에는 native ARM64 플래시 이미지와 이미 설치된 호스트를 위한 native payload가 있다. 최근 측정된 Actions 실행에서 플래시 이미지 build 단계는 1,619초, 준비·검증·업로드를 합친 전체 실행은 약 30분이었다. Native payload build는 201초, 준비·조립·업로드 포함 전체 실행은 약 5분이었다. 모든 소스 변경에 플래시 이미지를 만들면 약 25분 이상의 추가 대기가 생기며, 문서나 별도 사이트 변경은 로봇 산출물이 필요하지 않을 수 있다.

D-225는 기존 장치의 업데이트에서 카드 재기록을 마지막 수단으로 두고 payload 경로를 이미 정의했다. 하지만 first-device runbook의 첫 단계는 항상 전체 이미지 build로 시작하며 변경 종류와 설치된 기준 릴리스에 따라 선택하는 간단한 사전 판정 절차가 없다.

### Decision

1. 후보 revision과 대상 장치에 설치된 **image manifest의 확인된 `source_revision`** 사이 변경 경로를 `artifact_impact.py`로 판정한다. active payload의 더 최신 `git_revision`을 image 기준으로 혼용하지 않는다. 처음 설치하거나 signed image revision을 확인할 수 없으면 전체 이미지 경로 또는 HOLD를 사용한다.
2. 결과 `none`은 Pinky 장치 artifact가 필요하지 않다는 뜻이다. 문서·시험·CI, Site 배포, OMX 개발 변경은 자체 검증만 수행하고 Pinky 이미지나 payload를 만들지 않는다.
3. 결과 `native-payload`는 ROS workspace source 변경에 기존 native payload workflow를 선택한다. 전송 전에 payload의 `ros-packages.txt`를 대상 이미지의 ROS deb 버전과 비교한다. 불일치나 불명확한 이미지 기준선이면 payload 전환을 중단하고 이미지 경로를 검토한다.
4. 결과 `flashable-image`는 Pinky 이미지 입력, 부팅/호스트 서비스, 보드 설정, 신뢰 앵커 변경 또는 새/미확인 설치 기준에 전체 native ARM64 이미지를 선택한다.
5. 결과 `review`는 미분류 Pinky 운영·릴리스 경로 또는 비교 오류다. 자동으로 산출물 없음이나 payload로 낮추지 않고 명시적 검토 전까지 HOLD한다.
6. 혼합 변경은 가장 강한 영향을 선택한다. 미분류 경로가 하나라도 있으면 `review`가 우선하며, image 영향은 payload보다 우선한다.
7. 이 판정은 release approval이 아니다. unsigned artifact, 오프라인 서명·검증, 설치 후 독립 readback, 물리/현장 게이트는 계속 필요하다. Selector 결과만으로 배포·구동·수용 상태를 주장하지 않는다.

### Consequences

기존 장치의 호환되는 ROS source 변경은 약 5분 payload build 경로를 우선 사용하고, 비장치 변경은 ARM64 작업을 생략할 수 있다. 새 보드, 시스템 기반 변경, 기준선 불명확, ROS deb 불일치는 full image 또는 HOLD로 유지한다. 수치는 실제 두 workflow 실행의 기록이며 향후 빌드 시간 보장은 아니다.

**References:** [D-145](D-145-arm64-unsigned-artifact.md), [D-225](D-225-update-without-reflash-and-faster-card-writes.md), [D-320](D-320-product-scoped-robot-deployment-layout.md), [Pinky release artifact selection](../deployment/pinky-release-artifact-selection.md), [implementation plan](../plans/2026-09-29-pinky-deployment-fast-path.md).
