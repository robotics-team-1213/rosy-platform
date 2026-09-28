## D-320 로봇 배포 소스는 제품별로 묶고 사이트 배포는 분리한다

**Status:** Accepted (2026-09-28, 소스 디렉터리와 참조 배치에 한정). 설치 경로·이미지 구성·제품 capability·OMX 실물 제어 수용은 별도 검증 게이트다.

**Context:** 현재 `deploy/robot`에는 Pinky Pro 런타임, 설정, 설치와 장치 검증이 있고 `deploy/image`, `deploy/release`, `deploy/sd`도 Pinky ARM64 이미지와 카드 공급 절차에 결합되어 있다. OMX 개발·시뮬레이션 준비는 형제 `deploy/omx`에 있어 두 로봇 제품의 관계가 트리에서 드러나지 않는다. 이 구획을 한 로봇 루트 아래 제품별로 정렬하되, Fleet/Vision 사이트 호스트를 로봇 제품 안으로 넣거나 폴더 이름으로 실행 권한을 결정하지 않는다.

**Decision:**

1. `deploy/robot/`을 로봇 제품 배포의 상위 디렉터리로 유지하고 제품별 소스 루트를 둔다: Pinky Pro는 `deploy/robot/pinky_pro/`, OMX-AI workcell은 기존 이름과의 연속성을 위해 `deploy/robot/omx/`를 사용한다.
2. 현재 Pinky 전용인 이미지 빌드·서명/릴리스·SD 개인화 도구를 `deploy/robot/pinky_pro/{image,release,sd}/`로 둔다. 기존 `deploy/robot/`의 설정·설치·native systemd·검증 파일도 `deploy/robot/pinky_pro/` 아래에 둔다. 실제 공통 소비자와 독립 테스트가 확인되기 전에는 가상의 `shared/` 배포 루트를 만들지 않는다.
3. 기존 `deploy/omx/`의 OCI 빌드·workcell inventory·preflight·시뮬레이션 준비를 `deploy/robot/omx/`로 둔다. 이는 개발/ROS-SIM 준비 경계다. OMX field runtime, final actuator owner, device acceptance를 승인하지 않으며 빈 runtime 폴더를 만들지 않는다.
4. `deploy/site/`는 Fleet·Vision·Caddy의 사이트 호스트 배포로 별도 유지한다. 이미지·소스가 같은 저장소에 있다는 이유로 로봇 런타임과 합치지 않는다.
5. 소스 배치와 설치 산출물 경로를 구분한다. 이번 이동은 Pinky 제품의 기존 `/opt/rosy/deploy/robot/...` 및 이미지에 스테이징되는 `/opt/rosy/deploy/sd/...` 경로를 바꾸지 않는다. Builder가 제품 소스 경로에서 기존 설치 closure를 구성하도록 참조를 명시한다. 설치 경로 변경은 호환·장치 readback 계획이 있는 별도 결정으로 다룬다.
6. 이 결정은 `src/` 패키지 경로·ROS package 이름, CORE의 최종 `cmd_vel`, Fleet의 Mission/Step 소유권, 장치 호스트 위치, 이미지 package closure, 정지·복구 동작을 바꾸지 않는다. 폴더만으로 writer·실행 프로세스·배포 승인을 추론하지 않는다.

**Alternatives:**

- Pinky 런타임만 `deploy/robot/`에 두고 이미지·릴리스·SD·OMX를 형제로 유지하면 제품별 배포 경계가 계속 갈라진다.
- 모든 제품을 하나의 `deploy/robot` 이미지나 런타임으로 합치면 ARM64 Pinky와 amd64 OMX workcell의 다른 ROS graph·장치 권한·수용 게이트를 혼합한다.
- 제품 증거 없이 `deploy/shared/`에 빌더를 일반화하면 단일 소비자용 코드에 재사용 계약을 미리 부여한다.

**Consequences:** 저장소 소스 경로는 제품별 deploy 경계를 드러내며 기존 Pinky 설치 경로는 유지된다. import·Docker build·image builder·SD writer·Harness·문서·계약 테스트의 저장소 경로 참조는 같은 변경에서 갱신해야 한다. Pinky native ARM64 산출물의 내용 동등성과 장치 수용은 이 폴더 이동만으로 통과하지 않는다.

**Validation:** 이전/목표 트리와 활성 경로 참조를 구조 시험으로 고정한다. deploy/release, image, SD, OMX, root host 계약 시험과 docs harness를 실행한다. Windows SOURCE/LOCAL 통과는 native ARM64/Jazzy 이미지 동등성, 서명, 설치/readback, DEVICE/FIELD를 대신하지 않는다.

**Rollback:** 배포 소스 경로 변경과 참조 갱신을 하나의 경로 마이그레이션 커밋으로 유지한다. 실패하면 그 커밋을 revert하고 이전 source path를 복구한다. 이번 결정은 설치 산출 경로를 유지하므로 그 자체로 장치 rollback은 필요하지 않다.

**References:** [D-281](D-281-site-host-placement-and-omx-instance-isolation.md), [D-296](D-296-device-middleware-and-site-orchestration-terminology.md), [D-303](D-303-controller-owned-source-layout.md), [D-315](D-315-source-folder-responsibility-and-runtime-authority.md), [D-317](D-317-control-and-shared-contract-source-boundaries.md), [OMX workstation plan](../plans/2026-09-26-omx-ai-workstation-runtime.md), [implementation plan](../plans/2026-09-28-product-scoped-robot-deployment-layout.md).


### Source paths and installed paths

The accepted decision changes repository source locations only. The Pinky image builder continues to stage the native runtime at `/opt/rosy/deploy/robot/` and SD tools at `/opt/rosy/deploy/sd/`. Release command tooling remains at `/opt/rosy/deploy/release/`, as required by the existing `rosy-release` entrypoint. Builders and installers are responsible for mapping the product-scoped source tree to these existing installed paths.
