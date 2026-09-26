## D-192 하드웨어 런타임은 이미지에 들어간다 — UART4·LiDAR 드라이버·DYNAMIXEL SDK·rosylib·io unit을 굽고, 기본은 CORE-only와 무동작이다

**Status:** Proposed (2026-09-24). 구현과 host 시험은 끝났다. 아래 "실기 수용 확인"이 통과하면 Accepted로 바꾼다.
D-161(CORE-only 기본 target, 단일 `cmd_vel` 발행자), D-169(v1 장치 표면), D-181(편입 조건), D-189(unit 샌드박스,
해시 고정 Python 런타임, 이미지 안 probe)를 유지한다. 새 장치는 열지 않는다. D-189가 열어 둔 "rosy-io·rosy-navigation은
이미지 overlay에 없다"를 닫는다. 번호: D-190·D-191은 PR #26(main `7a55ee1b`)의 몫이고, 이 브랜치는 그 위로 rebase했다.
독립 리뷰(CRITICAL·HIGH 없음)의 MEDIUM 1·LOW 7을 같은 브랜치에서 반영했다(아래 "리뷰 반영").

**Context:** release `2026.09.23-005`와 응급 조치를 올린 `rosy-pinky-e4us`(2026-09-24)에서 CORE는 `CORE_READY`까지 갔다.
공식 Pinky Pro처럼 하드웨어를 돌리는 데 필요한 것은 이미지에 하나도 없었다. 장치에서 본 것:

| # | 결함 | 장치 증거 | 원인 |
|---|---|---|---|
| H1 | 모터 버스가 없다 | `/dev/ttyAMA4`, `/dev/rosy-motor` 없음 | udev `99-rosy-motor.rules`(KERNEL `ttyAMA4` → `rosy-motor`)는 이미지에 있었다. `config.txt`에는 `dtoverlay=uart4-pi5`가 없었다. overlay는 장치에서 돌리는 `configure-uart-pi5.sh`만 넣었고, 이미지는 그 스크립트를 부르지 않았다 |
| H2 | LiDAR 드라이버가 없다 | `/dev/ttyAMA0` 있음(RPLIDAR C1). `ros2 pkg prefix sllidar_ros2` 실패 | `bringup/package.xml`이 `sllidar_ros2`를 exec_depend하고 launch가 `sllidar_c1_launch.py`를 include한다. 예전 Docker 경로(`deploy/robot/Dockerfile` ~107행)만 `SLLIDAR_COMMIT=34300099…`를 clone해 빌드했다 |
| H3 | 모터 SDK가 없다 | `import dynamixel_sdk` 실패 | Docker 경로의 `requirements-io.txt`(`dynamixel-sdk==3.8.4`)를 이미지가 깔지 않았다 |
| H4 | 배터리 라이브러리가 없다 | `import rosylib` 실패 | `battery_publisher.py`(`from rosylib import Battery`)와 `led_server.py`(`rosylib.LED`)가 쓰는 이름이다. 공급사 원본은 `pinkylib`이고 공급사 이미지에만 설치된 비공개 라이브러리라 재배포할 수 없다 |
| H5 | io unit이 없다 | `rosy-io`·`rosy-navigation` 없음 | 릴리스 트리에는 있지만 `build-native-payload.sh`가 overlay에 복사하지 않았다(D-189 열린 항목) |
| H6 | `CORE_READY`가 늦다 | `rosy-boot-status`가 ~9 s·~20 s 뒤 30 s 주기. CORE는 ~23 s에 준비됐는데 표시는 53-55 s | 다음 주기까지 아무도 다시 판정하지 않는다. 장치에 아래 unit을 넣자 SSH가 붙는 순간(t+45 s, 이전 t+67 s)에 `CORE_READY`가 보였다 |

**버스별 공급사 증거(`pinky_pro-main` live, 2026-09-21 조사 문서 §3.4·§6):**

| 버스 | 공급사 코드 | Rosy 이미지(이 결정 뒤) |
|---|---|---|
| UART4 모터 | `pinky_bringup/bringup.py` 23-24행: `SERIAL_PORT_NAME = "/dev/ttyAMA4"`, `BAUDRATE = 1000000`, `DYNAMIXEL_IDS = [1, 2]`. `dynamixel_driver.py`는 `dynamixel_sdk` 직접 사용, Protocol 2.0. 공급사 이미지의 `config.txt`는 공개되지 않았다 | `dtoverlay=uart4-pi5`(`[all]`), udev가 `/dev/rosy-motor`로 연결, unit은 그 이름만 `DeviceAllow` |
| UART0 LiDAR | `pinky_bringup/launch/bringup_robot.launch.xml` 12-18행: `sllidar_c1_launch.py`, `serial_port=/dev/ttyAMA0`, `frame_id=rplidar_link`, `scan_mode=DenseBoost` | 장치에 `/dev/ttyAMA0`이 이미 있었다(overlay 추가 없음). `sllidar_ros2`를 고정 커밋에서 빌드 |
| I2C-1 ADC | `pinky_sensor_adc/src/main_node.cpp` 16·21행: `/dev/i2c-1`, 0x08. 배터리는 `battery_publisher.py`가 `pinkylib.Battery`로 5 s마다 | `rosylib.Battery`가 같은 공개 프로토콜로 읽는다. 장치 실측 8.665-8.682 V. `dtparam=i2c_arm=on`은 Ubuntu raspi 기본 `config.txt`에 있고 장치에 `/dev/i2c-1`이 있었다 |
| 카메라 | 공급사 ROS 저장소에 실기 카메라 노드가 없다(URDF `front_camera_link`와 Gazebo 브리지뿐). 공급사는 ROS 밖에서 `pinkylib.Camera`(Jupyter, Pinky Studio 스트리밍)를 썼다. 조사 문서 §6.6 | **BLOCKED.** 장치에서 센서가 열거되지 않았다. overlay(`camera_auto_detect`/`dtoverlay=ov5647` 등)는 추측하지 않는다. unit의 `DeviceAllow=/dev/video0`(D-169)는 그대로 둔다 |

**2026-09-26 장치 재검증:** 위 카메라 행의 센서 미열거 판단은 당시 상태다. Pi 5 rev d04170의 같은 OV5647 카메라에서 공급사 SD는 `camera_auto_detect=0`, `dtoverlay=ov5647`(CAM1)로 2592×1944 JPEG를 촬영했다. ROSY SD에도 같은 부팅 설정을 적용한 뒤 `ov5647 11-0036` 커널 probe와 2592×1944 JPEG 촬영을 확인했다. 따라서 CAM1 부팅 설정은 추측이 아니다. 현재 ROSY SD에는 `rpicam-still`, Picamera2 및 PiSP 사용자 공간이 설치되지 않았고 기본 런타임은 CORE-only다. 촬영은 공급사 사용자 공간을 임시로 실행한 진단이며, 제품 영상 발행과 대시보드 스트림의 DEVICE 수용은 여전히 열려 있다. 다른 개체(rev d04171)는 공급사 SD에서도 CAM0/CAM1 모두 센서 probe `-121`로 실패하여 물리 연결 확인이 필요하다.

**Decision:**

1. **US-003 — 런타임 target 직후 한 번 더 판정한다.** `rosy-boot-status-ready.service`(oneshot, root, 같은
   `rosy-boot-status.py`, `RuntimeDirectory=rosy-boot` 보존)를 `After=rosy-runtime.target rosy-core.service avahi-daemon.service`로
   두고 `WantedBy=multi-user.target`으로 켠다. target이 **Wants하면 안 된다**: target이 Wants한 unit은 target에 도달하기 전에
   돌고, 분류기는 그때 target을 activating으로 본다. `Requires=`·`PartOf=`도 두지 않는다 — 순서만 걸므로 런타임이 실패해도 곧바로
   `FAILED`가 보이고, 표시 계층이 런타임을 끌어오거나 붙잡지 않는다. `TimeoutStartSec=10`(멈춘 판정이 `multi-user.target`을
   오래 잡지 않게). `rosy-boot-status.py`는 `/run/rosy-boot/.run.lock`(root, 0600)에 배타 `flock`을 잡고 **사실 수집부터 마지막
   sink까지** 한 번에 한 실행만 한다 — 타이머·`OnFailure=`·ready unit이 겹쳐도 먼저 수집한(activating을 본) 실행이 나중 실행의
   `CORE_READY`를 덮지 않는다(늦게 잠근 실행이 늦게 수집하고 늦게 쓴다). 30 s 타이머는 그대로다. 페이로드가 설치하고 customizer가
   `systemctl --root … enable`, 마운트 검사기가 unit과 `multi-user.target.wants` 링크를 확인한다.
2. **US-004 — UART4는 이미지가 켠다. 쓰는 코드는 하나다.** customizer가 overlay를 풀어 놓은 뒤
   `bash "$UART_CONFIG" --image-root "$ROOT"`로 `deploy/robot/configure-uart-pi5.sh`를 부른다. 판정(`grep -Fqx` + `[all]`/`[pi5]`
   awk)과 편집(끝에 `[all]` 절 추가)은 장치 retrofit과 같은 코드다. 이미지 경로만 다른 것: 파일 위치(`$ROOT/boot/firmware/config.txt`,
   `ROSY_IMAGE_BOOT`가 그 경로인지 확인), udev 재로드 없음, 백업 파일을 남기지 않음, `REBOOT_REQUIRED` 없음, root 확인은 호출자(root
   customizer) 몫. `config.txt`에 들어가는 줄은 정확히:

   ```
   
   [all]
   # Rosy motor bus on Raspberry Pi 5 GPIO12/GPIO13
   dtoverlay=uart4-pi5
   ```

   함께 고친 결함: 이전 편집은 `cp --preserve=mode,ownership`과 `install -o root -g root -m 0644`로 `/boot/firmware`를 썼다. 그곳은
   vfat이고, vfat은 마운트 마스크가 보이는 x 비트를 빼는 chmod(0755→0644)를 EPERM으로 거부한다(`fat_sanitize_mode_change`).
   장치에서도 이미지에서도 실패할 경로였다(장치에서 실제로 돌려 본 기록은 없다). 이제 같은 디렉터리의 임시 파일에 쓰고 rename으로
   바꾼다. 검사기는 같은 규칙(섹션 앞, `[all]`, `[pi5]`, 주석 제거)을 Python으로 읽기만 한다. 시험은 스크립트를 실제 bash로 돌려
   Ubuntu raspi 모양의 `config.txt`에 붙는 바이트, 멱등성, 다섯 가지 섹션 경우에서 스크립트와 검사기의 판정 일치를 확인한다.
3. **US-005 — 하드웨어 런타임 입력은 다른 입력처럼 고정한다.**
   - **`sllidar_ros2`:** `inputs.lock.yaml` `hardware_dependencies`에 `sllidar_ros2_commit: 34300099fadfc772965962dec837bf436706188f`
     (Docker 경로와 같은 커밋), `sllidar_ros2_url: https://codeload.github.com/Slamtec/sllidar_ros2/tar.gz/<commit>`,
     `sllidar_ros2_sha256: 6a57c289a235a37dce0b07ef6fdc3ee003e646140d3fdc982988e7bf652367a7`(2026-09-24 독립 다운로드 2회 일치).
     `rpi_ws281x`와 같은 경로다: `install-pinky-hardware-deps.sh`가 받아 해시를 확인하고 **아카이브 그대로**
     `${ROSY_VENDOR_ARCHIVES:-/usr/local/src/rosy-vendor}/sllidar_ros2-<commit>.tar.gz`로 둔다. `build-native-payload.sh`는
     오프라인 규칙을 지킨다(네트워크 없음): `prepare-vendor-source.sh`가 그 아카이브를 lock 해시와 다시 `sha256sum --check`하고,
     새 `mktemp -d`에 풀고, `package.xml`이 루트의 `sllidar_ros2` 하나뿐인지(다른 패키지·다른 이름이면 거부) 확인한다. rosdep
     `--from-paths`와 colcon `--base-paths`에는 그 디렉터리 `<tmp>/sllidar_ros2` 하나만 `src`와 나란히 넘긴다(리뷰 MEDIUM: 풀어 둔
     트리 옆의 해시 표시는 트리 내용을 증명하지 못했고, 공용 디렉터리 전체를 base path로 넘겼다). 인벤토리에 들어가고, `vendor-ros-packages.txt`로 `ros2 pkg prefix`가 릴리스 prefix 안인지
     확인한다. `required-ros-packages.txt`에 넣지 않은 이유: 그 목록은 `resolve-required-source-paths.py`가 저장소 안 폐포로 푼다.
   - **`dynamixel-sdk==3.8.4`, `pyserial==3.5`:** 별도 io lock이 아니라 `device-python-requirements.txt`에 더했다(순수 휠, 휠당 해시
     하나, cp312 aarch64·x86_64 `--require-hashes --only-binary=:all:` 다운로드로 16개 전부 확인, 폐포는 pyserial 하나). 이유:
     D-189의 런타임 동일성은 **이 파일 하나의** SHA-256을 이미지(`/usr/local/share/rosy/python-runtime.sha256`)와 서명된 릴리스
     (`python-runtime.sha256`)가 공유하고 `native_release.py` activate·rollback이 비교하는 것이다. 파일을 나누면 io 런타임이 그 검사
     밖으로 빠져 OTA가 SDK 없는 이미지에 SDK가 필요한 릴리스를 올릴 수 있다. 한 파일이면 검사 코드를 바꾸지 않고 덮인다.
     `python_runtime.requirements_sha256`은 `a66f224ab570cb08d1c474bdbb1f93899692625cd167a7f6f907fc99690f4176`. 결과: 이 변경 뒤
     릴리스는 이전 이미지에 OTA로 갈 수 없고 재기록해야 한다(D-189 규칙). CI도 같은 파일을 깔므로 host 시험이 같은 SDK를 쓴다.
   - **`rosylib`:** `src/hardware/bringup/rosylib/`, bringup 패키지가 최상위 이름 `rosylib`으로 설치한다(Rosy 코드가 이미 쓰는
     이름). 별도 패키지로 나누지 않은 이유: 제품 소비자는 bringup뿐이고(LED는 벤치 전용), 하네스 모듈·rosdep 키·required 목록을
     하나 더 늘릴 이유가 없다. 두 번째 제품 소비자가 생기면 나눈다. `Battery`는 `pinkylib`의 두 메서드(`get_voltage()`,
     `battery_percentage()`)를 공개 ADC 프로토콜로 구현한다: `/dev/i2c-1`, 0x08, 채널 4 레지스터 0xF8, 포인터 쓰기, 6 ms,
     2바이트 읽기, `raw = (d0<<4) + (d1>>4)`, `V = raw/4096*4.096/(13/28)`(`sensor_adc/src/main_node.cpp`와 같다). 퍼센트는 CORE
     `core_features.power.battery`의 2S 곡선이다. import하지 않고 **복사**한다: io 런타임이 CORE(pydantic을 끌어오는 `core_common`)를
     import하면 안 된다. `test/test_rosylib_battery_curve.py`가 표 동일성과 6.000-8.800 V 7 mV 간격의 보간 동일성을 고정한다.
     `battery_publisher`는 버스 실패 때 아무것도 발행하지 않는다(`sensor_adc`와 같은 fail-closed — 0 V는 "빈 배터리"로 읽힌다).
   - **`LED`는 제공하지 않는다.** `led_server.py`는 고치지 않았다. `from rosylib import LED`가 "the LED is bench-only (D-169);
     rosylib ships no LED driver (D-192)"라는 ImportError로 즉시 실패한다(모듈 `__getattr__`). 조용히 가짜 LED를 주지 않는다.
4. **ADC 소유: 하나의 트랜잭션은 한 번에 한 프로세스만.** MCU는 레지스터 포인터 하나를 가진다. 읽기는 포인터 쓰기, 대기, 읽기의
   세 단계이고, 두 프로세스가 섞이면 서로의 채널을 읽는다. `bringup_robot.launch.py`는 `sensor_adc`를 띄우지 않는다(확인) —
   `rosy-io`에서 ADC를 읽는 것은 `battery_publisher` 하나다. 그러나 `rosy-navigation`(`hardware.launch.py`)은 같은 bringup에
   `enable_line_follow`로 control의 `ir_adc_node`(채널 0-2)를 더할 수 있다. 결정: **Rosy의 모든 0x08 독자는 자기 `/dev/i2c-1`
   descriptor에 `flock(LOCK_EX)`를 잡고 트랜잭션 전체(IR은 세 채널 한 주기)를 끝낸 뒤 푼다.** `rosylib.Battery`와 `ir_adc_node`가
   그렇게 한다. flock은 inode 단위라 서로 다른 프로세스가 따로 연 descriptor끼리도 배제된다. 벤치 전용 C++ `sensor_adc`도 채널
   트랜잭션마다 같은 flock을 잡는다(리뷰 반영). 그래도 `ir_adc_node`와 함께 돌지 않는다 — 둘 다 `ir_sensor/range`를 발행한다 —
   그리고 어떤 하드웨어 launch도 띄우지 않는다(`test_ir_source_exclusivity`, `test_adc_ownership`).
   구독 방식(`battery_publisher`가 `sensor_adc`의 `batt_state`를 받기)을 고르지 않은 이유: 그러면 `sensor_adc`가 제품 그래프에 들어와야
   하는데, 그것은 `ir_adc_node`와 같은 `ir_sensor/range`를 발행하므로 이미 금지된 조합이다.
5. **무동작 하드웨어 모드가 `rosy-io`의 기본이다.**
   - `bringup`에 `drive_enabled` 파라미터(launch 기본 `true` — 개발·시뮬·compose·`rosy-navigation`은 그대로 구동). `false`이면:
     드라이버는 재부팅·속도 모드·profile·**0 goal 기록과 되읽기 확인까지만** 하고 torque를 켜지 않는다(LED도 켜지 않는다);
     초기 0 RPM 쓰기를 건너뛴다; `cmd_vel`을 구독하지 않는다; `motor/ready`는 false로 남고 lease를 갱신하지 않는다.
     Present Velocity/Position은 torque와 무관하게 읽히므로 `odom`, `joint_states`, TF는 그대로 나온다. 종료 때의 0 goal·torque off는
     무해하다.
   - **torque를 끈 이유:** 공급사와 Rosy bringup 모두 시작할 때 torque를 켜고 0 RPM을 쓴 뒤 `cmd_vel`을 구독한다. "명령이 없을 때만
     torque-on 허용"은 이 노드에서 성립하지 않는다 — 시작 시 goal을 쓰고, `cmd_vel`을 듣는 한 CORE가 API 요청으로 발행하는 순간 바퀴가
     돈다. 무동작의 보장을 발행자의 선의에 맡기지 않고 액추에이터에서 끊는다. CORE는 여전히 유일한 `cmd_vel` 발행자다(D-161) —
     무동작 모드에서는 그 토픽의 구독자가 없을 뿐이다.
   - `rosy-io.service`: `Environment=ROSY_IO_DRIVE_ENABLED=false`를 `EnvironmentFile=/etc/rosy/runtime.env` 앞에 두고
     `drive_enabled:=${ROSY_IO_DRIVE_ENABLED}`를 넘긴다. EnvironmentFile이 Environment를 이기므로, 구동은
     `/etc/rosy/runtime.env`에 `ROSY_IO_DRIVE_ENABLED=true`를 적는 명시적 root 행위다. 첫 부팅이 쓰는 runtime.env에는 이 키가 없다.
     값은 정확히 `true`·`false`만 받는다: `ExecStartPre`가 그 밖의 값(`yes`, `1`, `True`, 빈 값, 미설정)이면 78로 unit을 멈춘다.
     launch_ros는 `yes`·`1`·`True`를 참으로 읽어 구동하므로, 틀린 값은 무동작이 아니라 **기동 실패**로 닫는다. 노드의
     `drive_enabled`는 `read_only` 파라미터다 — 돌고 있는 노드에 `ros2 param set`으로 torque를 켤 수 없다.
     배터리 발행자는 켠다(`enable_battery:=true`, ADC는 v1 표면).
   - 모드 개념 정리: `ROSY_RUNTIME_MODE`(`core|motor|hardware`)는 Docker 경로 `runtime-mode.sh`가 compose 프로필을 고르는 스위치이고,
     네이티브에서는 CORE가 읽는 설정 값(capabilities/내비게이션 readiness 기본값)일 뿐 unit을 켜고 끄지 않는다. 네이티브에서
     하드웨어를 켜는 스위치는 unit이다: 기본 target은 CORE-only, `rosy-io`는 손으로 시작, `rosy-navigation`은 두 승인 파일이 있을 때만
     조건이 맞는다. 두 unit은 서로 Conflicts다. 이 ADR은 `ROSY_RUNTIME_MODE`를 바꾸지 않는다.
   - `rosy-navigation.service`: 첫 부팅 runtime.env에는 `ROSY_NAVIGATION_BACKEND`·`ROSY_MAP`이 없어 `${…}`가 빈 launch 인자가
     된다. `Environment=`로 `localization`, `/var/lib/rosy/maps/site.yaml` 기본값을 둔다(runtime.env가 여전히 이긴다).
6. **두 unit은 이미지에 설치하되 켜지 않는다.** 페이로드가 overlay의 `/etc/systemd/system`에 복사하고, customizer의 enable 목록에는
   없다. D-189 규칙(쓰기 집합, `HOME=/var/lib/rosy/{io,navigation}`, `bash --noprofile --norc -c`, `PYTHONNOUSERSITE=1`)은 이미 unit에
   있고 `test_native_systemd_contract.py`가 모든 `*.service`에 건다. `rosy-io`의 프로그램 소스 스캔(`src/hardware/bringup`)에는
   `rosylib`이 자동으로 들어간다.
7. **가드 — 이미지 안 io probe(`deploy/image/probe-io-runtime.py`).** CORE probe 뒤, 검사기 전에 chroot에서 `rosy-io.service`처럼
   (`setpriv` rosy-io, `HOME=/var/lib/rosy/io`, `env -i`, `bash --noprofile --norc`, `PYTHONNOUSERSITE=1`, runtime.env·ROS·릴리스
   source, `python3 -B`) 실행하고 실패하면 빌드를 멈춘다. 장치를 열지 않는다. 확인하는 것: `dynamixel_sdk`·`serial`이 `/usr/local`에서
   import, `rosylib.Battery`의 두 메서드와 `rosylib.LED` 거부, `bringup.bringup`·`battery_publisher`·드라이버·probe import,
   `sllidar_ros2`(`sllidar_node`, `sllidar_c1_launch.py`)·`bringup`·`navigation`(unit이 여는 launch 파일)이 릴리스 install 안에서
   해석, 두 unit이 설치되고 어떤 `*.wants`에도 없으며 D-189 규칙 문자열을 가짐, udev 규칙. CORE probe의 고정 집합 검사(16개,
   `/usr/local`)도 새 두 휠을 덮는다. 마운트 검사기는 overlay·udev·ready unit·io unit(설치, 미활성)·`sllidar_ros2` 인벤토리와 파일을 본다.

**Alternatives:**

- `config.txt`를 customizer가 직접 편집: 판정 규칙이 두 벌이 된다. 한쪽만 고쳐지는 것이 H1이 생긴 방식이다.
- `sllidar_ros2`를 apt(`ros-jazzy-sllidar-ros2`)나 rosdep으로: 고정한 apt 집합에 없고, Docker 경로가 검증한 것은 이 커밋이다.
  payload 빌더에서 직접 받기: 빌더의 "오프라인" 계약(`test_native_ros_payload.py`)을 깬다.
- 별도 `io-python-requirements.txt`: D-189 런타임 검사 밖으로 빠진다(위 3). 검사를 두 파일로 늘리면 매니페스트나 선언 파일 형식을 바꿔야 한다.
- `rosylib`이 `core_features`를 import: io 런타임이 CORE와 pydantic에 묶인다(모듈 결합 점수표 D-178 방향과 반대).
- 무동작 모드에서 torque는 켜고 `cmd_vel`만 막기: 시작 시 0 goal 쓰기가 남고, 휠이 모터 제동 상태로 잠겨 손으로 굴려 보는 인코더 확인이
  안 된다. 액추에이터를 끄는 쪽이 보장이 단순하다.
- 무동작을 별도 unit(`rosy-io-observe.service`)으로: 같은 샌드박스를 두 벌 유지하고 Conflicts가 셋이 된다.
- ADC를 `battery_publisher`가 `sensor_adc` 구독으로: 위 4.
- 카메라 overlay를 공급사 추정으로 추가: 공급사 ROS 코드에 근거가 없고 장치에서 센서가 열거되지 않았다. D-181 조건 3(실기 기동) 없이
  표면만 바뀐다.

**Consequences:** 이미지가 켜는 것은 늘지 않는다 — 기본 target은 CORE-only, 새로 켜지는 것은 표시 oneshot 하나다. 이미지에
`dtoverlay=uart4-pi5`, `sllidar_ros2` 빌드, PyPI 휠 2개, 설치만 된 io unit 둘이 들어간다. 이미지 빌드는 hardware-deps 단계에서
codeload 아카이브 하나를 더 받는다(해시 고정. GitHub가 아카이브 압축을 바꾸면 해시가 달라져 빌드가 멈춘다 — 그때 다시 확인해
고친다). Python 고정 집합이 바뀌었으므로 이 변경 뒤의 릴리스는 이전 이미지로 OTA 되지 않는다. `rosy-io`를 시작해도 기본은 바퀴가
돌지 않는다. `configure-uart-pi5.sh`의 장치 경로도 vfat-안전 쓰기로 바뀌었다. 장치 표면은 D-169 그대로다
(`test_device_surface_contract.py` 녹색).

**남은 것 (열림):**

- **배터리 곡선의 위쪽.** 실측 8.665-8.682 V는 2S Li-ion 곡선 최고점 8.40 V보다 높아 100 %로 고정된다. 분압비(13/28)나 기준 전압
  보정, 또는 팩 종류(고전압 셀) 가운데 무엇인지는 모른다. 충전 직후가 아닌 방전 중 전압을 여러 번 재어 결정한다. 곡선을 바꾸는 것은
  CORE와 함께 바꾸는 변경이다(동일성 시험).
- **카메라 BLOCKED.** 센서 열거(`libcamera`/`v4l2`) 실기 증거가 생기면 overlay와 노드를 D-181 절차로 연다.
- **`sensor_adc` flock은 링크·실행되지 않았다.** WSL `g++ -fsyntax-only`(Jazzy 헤더 + wiringPi 스텁)는 통과했다. 실제 빌드는 다음 arm64 빌드가 처음이다.
- **`sllidar_node`의 공유 라이브러리.** io probe는 import와 파일만 본다. 드라이버의 실행 의존(`rclcpp`, `sensor_msgs`, `std_srvs`)은
  `ros-jazzy-ros-base`에 있지만, 라이브러리 해석은 실기에서 확인한다.
- **`ROSY_IO_DRIVE_ENABLED`의 첫 부팅 기록.** 첫 부팅(`deploy/image/first-boot`)은 이 키를 쓰지 않으므로 기본은 무동작이다. 구동 허용을
  개인화 bundle로 옮길지는 첫 부팅 담당 변경이 정한다.

**리뷰 반영(2026-09-24, 같은 브랜치):**

- (MEDIUM) 벤더 해시 고정을 실제로 만들었다 — 위 3의 `prepare-vendor-source.sh`. 시험은 스크립트를 bash로 실제로 돌려 바뀐
  아카이브, 여분 패키지, 다른 이름, 쓰던 목적지를 모두 거부하는지 본다.
- (LOW) `drive_enabled` read-only; `battery_publisher`는 시작 때 버스가 없어도 죽지 않고 타이머에서 다시 열며 그동안 아무것도
  발행하지 않는다(읽기 실패도 핸들을 닫고 다음 주기에 다시 연다); `sensor_adc` flock; ready unit 10 s와 실행 직렬화;
  source-grep 대신 동작 시험(stub rclpy 위의 `Rosy` 노드, fake fd 위의 `_ADCReader`, 호출 순서에 기록된 settle).
- (LOW) 기반 `config.txt` 가드: 장치(`rosy-pinky-e4us`)의 Ubuntu 기본 `config.txt`에는 `enable_uart=1`이 있고 uart0 dtparam은 없으며
  `/dev/ttyAMA0`(LiDAR)과 `/dev/i2c-1`(dialout 0660)이 있었다. uart0 변경은 하지 않는다. 대신 마운트 검사기가 `enable_uart=1`과
  `dtparam=i2c_arm=on`이 Pi 5에 적용되는지(섹션 앞, `[all]`, `[pi5]`) 확인해 다음 기반 이미지가 조용히 빼면 빌드가 멈춘다.
- (LOW) chroot rosdep: `vendor-ros-packages.txt`의 키(`sllidar_ros2`)를 `--skip-keys`로 넘긴다. rosdistro가 그 키를 알든 모르든,
  `-r`의 종료 코드 동작에 기대지 않고 rosdep이 해석을 시도하지 않는다(시험은 customizer의 그 구간을 bash로 실제 실행).
- (LOW) 장치의 `config.txt` 복구: 아래.

**장치 retrofit의 `config.txt` 복구(`configure-uart-pi5.sh`, 장치 경로만):** 스크립트는 처음 한 번 `config.txt.rosy-backup`을 남기고
같은 디렉터리의 임시 파일을 rename으로 바꾼다. vfat의 rename은 전원 차단에 원자적이지 않다(FAT 디렉터리 항목 갱신이 한 번의
쓰기가 아니다). 편집 중 전원이 끊겨 부팅하지 않으면: 카드를 PC에 꽂고 부트 파티션(`system-boot`)에서 `config.txt`가 없거나
비었거나 `.rosy-uart.XXXXXX`만 남았으면 `config.txt.rosy-backup`을 `config.txt`로 복사한다. 그 뒤 장치에서 스크립트를 다시
돌린다(멱등). 이미지 경로는 백업을 남기지 않는다 — 이미지 빌드는 실패하면 버리고 다시 만든다.

**실기 수용 확인(US-004/US-005, 새 카드):**

1. `grep -n uart4 /boot/firmware/config.txt`가 위 네 줄을 보이고, `ls -l /dev/ttyAMA4 /dev/rosy-motor`가 있고
   `rosy-motor -> ttyAMA4`, 그룹 `dialout` 0660.
2. `ls /dev/ttyAMA0 /dev/i2c-1`, 부팅 로그에 `CORE_READY`가 CORE 준비 직후(US-003: SSH가 붙는 시점)에 보임.
3. customizer 로그에 `CORE_RUNTIME_PROBE_OK pins=16`과 `IO_RUNTIME_PROBE_OK`.
4. `systemctl is-enabled rosy-io rosy-navigation`이 둘 다 disabled(또는 static), `systemctl status rosy-runtime.target` active.
5. `sudo -u rosy-io env -i PYTHONNOUSERSITE=1 bash --noprofile --norc -c 'source /opt/ros/jazzy/setup.bash; source /opt/rosy/current/install/setup.bash; python3 -c "import dynamixel_sdk, rosylib; print(rosylib.Battery().get_voltage())"'`가
   8.6 V 안팎(또는 그 순간의 팩 전압).
6. 무동작 모드: `sudo systemctl start rosy-io` 뒤 로그에 `Drive disabled (no-motion mode)`, `ros2 topic hz /<ns>/scan`(~10 Hz),
   `/<ns>/joint_states`·`/<ns>/odom`(~30 Hz), `ros2 topic echo --once /<ns>/battery/voltage`, `ros2 topic echo --once /<ns>/motor/ready`가
   `data: false`, `ros2 topic info -v /<ns>/cmd_vel`의 구독자에 bringup이 없음, 바퀴를 손으로 돌리면 `joint_states` position이 변함(torque off).
7. `sudo dynamixel_probe` 또는 `ros2 run bringup dynamixel_probe --device /dev/rosy-motor`가 ID 1·2 ping과 torque 0을 읽음.
8. 구동 확인은 별도 승인 뒤: `/etc/rosy/runtime.env`에 `ROSY_IO_DRIVE_ENABLED=true`, `systemctl restart rosy-io`, 바퀴를 들고 CORE API로
   저속 명령, deadman(0.5 s) 정지 확인.
9. `rosy-navigation`과 ADC 공유: 승인 파일 두 개와 `enable_line_follow` 구성에서 `ir_sensor/range`와 `battery/voltage`가 함께 나오고
   전압이 IR 값으로 튀지 않음.

**2026-09-24 보완 — 버스 UART에는 콘솔이 없어야 한다(release 010, `rosy-pinky-e4us`):** 위 "UART0 LiDAR" 행의 "overlay 추가 없음"은
맞았지만 전제가 하나 빠졌다. Ubuntu raspi `cmdline.txt`는 `console=serial0,115200 ... console=tty1`이고, Pi 5에서 `enable_uart=1`이면
`serial0`이 `ttyAMA0`이다. `/proc/cmdline`에 `console=ttyAMA0,115200`이 있었고 `serial-getty@ttyAMA0.service`(agetty)가 포트를 잡아
`sllidar_node`가 `SL_RESULT_OPERATION_TIMEOUT`, getty를 멈춘 뒤에도 커널 콘솔 때문에 `0x80008004`로 실패했다. 그 항목을 지우고
재부팅하자 getty 없음, `health status : OK`, DenseBoost 10 Hz. 결정: `configure-uart-pi5.sh`(이미지·장치 공통)가 `cmdline.txt`에서
`console=serial0|ttyAMA0|ttyAMA4[,baud]`를 지우고, 시리얼 콘솔이 하나도 남지 않는 일이 없도록 복구 콘솔 `console=ttyAMA10,115200`(Pi 5 디버그 3핀 UART,
로봇 버스 없음)이 없으면 앞에 넣는다(`console=tty1`은 그대로 마지막이라 `/dev/console`). `serial-getty@ttyAMA0`·`@ttyAMA4`를
`/dev/null`로 mask한다 — 나중에 cmdline을 다시 고쳐도 getty는 돌아오지 않는다. `verify-mounted-image.py`는 `cmdline.txt`가 없거나
버스 UART로 콘솔을 보내거나 `ttyAMA10` 복구 콘솔이 없거나 mask가 `/dev/null` symlink가 아니면 빌드를 멈추고, `verify-pi.sh`는 `/proc/cmdline`과 두 getty의 활성·masked 상태를 보고 이유를 적어 실패한다.
실기 수용 확인 2에 `grep -o 'console=[^ ]*' /proc/cmdline`이 `ttyAMA10,115200`과 `tty1`만 보이고 `systemctl is-enabled serial-getty@ttyAMA0 serial-getty@ttyAMA4`가
둘 다 `masked`인 것을 더한다.

**Validation / Transition:** host 시험(2026-09-24 Windows, Python 3.14): `python -m pytest test/test_native_systemd_contract.py
test/test_image_customization_contract.py test/test_native_runtime_installed_layout.py test/test_boot_status_indicator.py
test/test_rosy_motor_udev.py test/test_native_ros_payload.py test/test_device_surface_contract.py test/test_rosylib_battery_curve.py
test/test_dynamixel_driver_safety.py test/test_bringup_motor_contracts.py test/test_ir_source_exclusivity.py
test/test_release_boundary_guards.py test/test_harness_contracts.py test/test_source_encoding.py deploy/image/test src/hardware/*/test -q`.
`configure-uart-pi5.sh`의 이미지 모드와 `prepare-vendor-source.sh`는 Git Bash에서 실제로 실행했고, 표시 실행 잠금의 동시성 시험은
WSL(POSIX)에서 돌렸다. 이미지 빌드(arm64)와 io probe의 chroot 실행은 다음 이미지 빌드가 처음이다. `origin/main`(`7a55ee1b`,
D-190·D-191 포함)으로 rebase한 뒤 하네스 lint는 `0 error(s)`다.

**References:** D-161, D-169, D-181, D-189, D-178,
[Pinky Pro OS 조사](../plans/2026-09-21-pinky-pro-os-research.md) §3.4·§4-6,
공급사 `pinky_pro-main` `pinky_bringup/pinky_bringup/bringup.py`, `battery_publisher.py`, `launch/bringup_robot.launch.xml`,
`pinky_sensor_adc/src/main_node.cpp`.

---
