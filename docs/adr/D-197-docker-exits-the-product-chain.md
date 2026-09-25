## D-197 Docker는 제품 아티팩트 체인에서 퇴역한다 — 제품 경로의 신규 Docker 의존은 지금 금지하고, OCI·Compose 체인은 native payload가 ARTIFACT를 통과하면 한 변경으로 정리한다

**Status:** Accepted (2026-09-24). 폐기 실행은 2항의 트리거 뒤에 온다. 잇는 결정:

- D-161: 제품 런타임은 Ubuntu Server 24.04 arm64 + native ROS 2 Jazzy systemd다. Docker/Compose는 개발·CI 전용이며 제품 이미지에 설치하지 않는다.
- D-145/D-146: ARM64 payload 자동화는 unsigned까지, 검증 뒤에만 오프라인 서명 입력이 된다.
- D-164/D-173: 제품 산출물은 서명된 Raspberry Pi 디스크 이미지이고 첫 카드는 병합 커밋의 서명 이미지를 고정해 굽는다.
- D-179: 벤치 CORE 수정은 설치 트리 위의 읽기 전용 바인드이고 그 장치는 릴리스로 세지 않는다.

**Context:** 2026-09-24 기준 Docker는 세 얼굴로 남아 있다.

1. **제품 런타임 — 이미 없다.** D-161 이후 장치의 release activation(`deploy/robot/native/native_release.py`)은
   `install/.rosy-release` install tree를 검증·교체하며 network와 Docker를 요구하지 않는다.
2. **릴리스 payload 빌드 — 두 체인이 병존한다.**
   - Docker 체인(D-22/D-36 시대): `deploy/release/arm64_release_builder.py`가 `deploy/robot/Dockerfile`의
     `core`/`io` 타깃을 `docker buildx build`로 굽고 `docker image save`로 `rosy-{core,io}.oci.tar`를 만든다.
     수동 워크플로 `.github/workflows/build-arm64-payload.yml`, 검증기 `deploy/release/import_unsigned_payload.py`,
     `deploy/release/bundle.py`의 `REQUIRED_PAYLOAD`(`runtime/compose.yaml` + OCI tar 2개), 장치 적재
     `deploy/release/release_runtime.py`의 `docker image load`, `deploy/release/image_checks.py`의
     `REQUIRED_OCI_ARCHIVES`·`opt/rosy/deploy/robot/compose.yaml`·레거시 `rosy-runtime.service`(Compose unit) 기대가
     이 체인에 묶여 있다. `deploy/robot/verify/device_readback.py`의 CORE 상태 프로브
     (`docker compose ps`·`docker inspect`·`docker exec`)도 같은 세계다.
   - native 체인(D-161/D-164 방향): `deploy/image/build-native-payload.sh`가 native aarch64에서 rosdep/colcon으로
     install tree와 inventory를 만들고 `deploy/image/`의 스크립트는 docker·oci·compose를 참조하지 않는다.
     `deploy/progress.md`의 다음 ARTIFACT gate 전부 이 native 경로를 가리킨다.
3. **개발 — 실수요가 하나 남아 있다.** D-179 벤치 오버레이(`deploy/robot/dev/core_dev_overlay.py`)가
   `docker compose`로 CORE를 돌린다. CI(`.github/workflows/ci.yml`)의 `container: ros:jazzy-ros-base`는
   러너 인프라일 뿐 프로젝트 Dockerfile과 무관하다.

유지비 증거: `deploy/robot/Dockerfile` 히스토리에는 hub arm64 `ros:jazzy-ros-base`의 0-byte(hollow) 파일 결함을
다루는 워크어라운드가 연속 6커밋(`restore-hollow-python.sh`·`restore-hollow-toolchain.sh` 계열) 쌓여 있다. 이 결함은
Docker 경로에만 있고 native 빌드에는 없다. 제품 방향은 native로 넘어갔는데 Docker 체인의 코드와 계약이 반쯤 남아
유지비가 이중으로 나가는 상태다.

**Decision:**

1. **제품 아티팩트 체인은 native뿐이다. 이 결정 시점부터 제품 경로(builder, bundle, 장치 적재, 이미지 layout,
   readback)에서 Docker/OCI 체인에 새 의존을 만드는 것을 금지한다.** Docker/Compose는 개발 워크스테이션과 CI
   호환으로만 존재한다(D-161 재확인).
2. **폐기 트리거는 native payload의 ARTIFACT 통과다.** 고정 base image의 native 다운로드 검증, native ROSY payload
   빌드, 완성 이미지·SBOM·서명 검증이 끝나면 다음을 한 변경에서 정리한다:
   - `arm64_release_builder.py`, `build-arm64-payload.yml`, `import_unsigned_payload.py`와 그 테스트
   - `bundle.py`의 `REQUIRED_PAYLOAD`, `release_runtime.py`의 `docker image load` 경로, `updater.py`의 컨테이너
     manifest 롤백 표현
   - `image_checks.py`의 OCI archive·`opt/rosy/deploy/robot/compose.yaml`·레거시 `rosy-runtime.service` 기대 —
     `verify-mounted-image.py`와 `rosy-runtime.target` 중심의 native layout 기준으로 다시 묶는다
   - `device_readback.py`의 CORE 프로브를 컨테이너 조회에서 systemd/HTTP 상태로 바꾼다
3. **제거 순서 계약: 계약 테스트의 고정 대상을 먼저 옮긴다.** `test_dds_identity_contracts.py`(D-33),
   `test_dds_rmw_contracts.py`, `robot_contracts.py`의 launch closure, `test_control_launch_boundary.py`가
   `deploy/robot/compose.yaml`과 `deploy/robot/Dockerfile`을 고정하는 동안은 그 두 파일을 삭제하지 않는다.
   고정 대상을 `install-pi.sh`와 `deploy/robot/native/` 유닛으로 옮긴 뒤에 삭제한다. 절반만 지우면 계약 스위트가 깨진다.
4. **D-179 벤치의 compose 의존은 native 개발 오버레이가 생길 때까지 남는다.** 단 그 장치는 릴리스로 세지 않는다
   (D-179 그대로). 개발 전용 표면이 제품 회귀를 막는 이중 기준을 영구화하지는 않는다.
5. **CI의 `ros:jazzy-ros-base` 러너 컨테이너는 유지한다.** GitHub Actions 인프라로 이 결정과 무관하다.

**Consequences:**

- 런타임에서 Docker가 이미 없다는 사실은 변하지 않는다(D-161 유지).
- ARTIFACT 통과 전까지 두 빌더가 병존하며 이 기간의 이중 유지비를 명시적으로 수용한다. 새 작업은 native 쪽에만 한다.
- 폐기 후에는 hollow-image 워크어라운드가 더 쌓이지 않는다.
- 2026-09-21의 unsigned handoff import 증거(397bb25 artifact)는 유효한 이력으로 남지만 더는 발행 메커니즘이 아니다.
- 서명·검증 체계(manifest, Ed25519, readback)는 유지되며 바뀌는 것은 payload 표현뿐이다(OCI → install tree).
- `verify-artifacts.sh`의 BUILD_GO는 2항 정리 변경에서 native layout 기준으로 다시 묶인다. 그 전까지 구 layout을
  게이트하므로 native 이미지를 통과시키지 못한다 — ARTIFACT HOLD와 모순되지 않는다.

**See also:** D-246 — 컨테이너는 비안전·선언된 사이드카 워크로드에 한해 남고, 제어·안전 플레인과
제품 payload 경로는 이 결정 그대로 네이티브다.
