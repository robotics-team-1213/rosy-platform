## D-291 Pinky Pro 첫 부팅은 무구동 I/O를 포함하고, 제어 변경은 새 서명 이미지로 SD에 기록한다

**Status:** Accepted (2026-09-26). D-161의 CORE 전용 기본 target과 D-164의 이미지·매체 인수 절차를 이 범위에서 갱신한다.

**Context:** Pinky Pro에서 CORE만 부팅되면 웹은 열리지만 모터 I/O가 없어 Move를 실행할 수 없다. 기존 서명 이미지는 `rosy-runtime.target`에 I/O를 포함하지 않으므로, 소스나 실행 중인 한 장치만 고쳐서는 새 SD의 첫 부팅 동작이 바뀌지 않는다. 카드 여러 장을 만들 때도 각 카드의 장치 신원과 등록 절차는 분리되어야 한다.

**Decision:**

1. 공통 Ubuntu arm64 이미지는 첫 부팅부터 CORE와 `rosy-io.service`를 시작한다. 공장 기본값은 `ROSY_RUNTIME_MODE=core`, `ROSY_IO_DRIVE_ENABLED=false`다. 이 상태의 I/O는 센서·엔코더를 관측하지만 토크를 켜지 않고 `cmd_vel`을 구독하지 않으며 `motor/ready`를 참으로 만들지 않는다. CORE만 종료하거나 릴리스를 전환할 때 I/O도 함께 멈춘다. Navigation은 기본 target에 넣지 않는다.
2. 검증된 장치만 바퀴를 띄운 모터·정지 시험 뒤 `motor` 모드와 `drive=true`를 장치별 `/etc/rosy/runtime.env`에 보존한다. `core`와 `drive=true`의 조합은 I/O 시작 전에 거부한다. 새 보드에 SD를 옮겨 장치 신원이 초기화될 때 옛 구동 승인을 재사용하지 않는다. 부팅은 자율 이동 명령을 만들지 않으며 운전은 인증된 조작자가 `MANUAL` 모드에서 시작한다.
3. 이 변경을 담은 새 이미지의 원본 커밋, ARM64 빌드 실행, checksum, 서명, 정확한 `.img.xz` 파일을 한 릴리스로 묶는다. 이전 커밋의 이미지는 파일이 정상이어도 이 결정의 출하물이 아니다. 이미지에는 장치 신원·Wi-Fi 비밀·Fleet 자격을 넣지 않는다.
4. SD 기록 전 서명과 이미지 해시를 검증하고 물리 디스크 serial·용량·버스·파티션을 재확인한다. 기록 뒤 전체 매체 readback이 일치해야 한 장의 MEDIA 증거로 받는다. 장치별 one-shot provisioning과 receipt는 그 뒤에만 쓴다. 여러 장은 공통 서명 이미지를 재사용하되 카드마다 신원·receipt를 따로 만든다.
5. 이미지 빌드·서명·SD 기록·readback·Pi 부팅·Move 실기·현장 운용은 각각 별도 게이트다. 앞 단계 성공을 뒤 단계의 수용으로 표시하지 않는다.

**Consequences:** I/O는 미승인 카드에서도 장치 버스를 관측하므로 첫 부팅의 장치 상태를 더 빨리 알 수 있다. 모터 토크는 구동 승인 전까지 꺼져 있다. `core`에서 옛 `drive=true`가 남으면 I/O가 시작 실패로 드러나며 자동으로 구동을 허용하지 않는다. 릴리스와 카드 제작자는 이전 이미지의 정상 readback을 새 코드의 증거로 재사용할 수 없다.

**Validation / transition:** `test_native_systemd_contract.py`, `test_bringup_motor_contracts.py`가 무구동 기본값과 잘못 남은 구동 플래그의 거부를 확인한다. 새 ARM64 이미지에서는 `verify-artifacts.sh`와 서명 검증, SD writer의 전체 readback을 통과시킨다. Pi에서는 다른 `boot_id`, CORE/I/O 활성, `motor/ready`와 속도 0을 읽고, Move·deadman·방향·현장 안전은 별도로 기록한다. 서명 이미지나 대상 카드 확인이 없으면 매체 기록을 진행하지 않는다.

**References:** [D-161](D-161-ubuntu-server-native-ros-runtime.md), [D-164](D-164-pinky-pro-flashable-image.md), [D-180](D-180-sd-write-single-authoritative-verify.md), [D-192](D-192-hardware-runtime-in-the-image.md), [D-225](D-225-update-without-reflash-and-faster-card-writes.md).
