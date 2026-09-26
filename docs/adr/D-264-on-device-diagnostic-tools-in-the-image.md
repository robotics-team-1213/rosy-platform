## D-264 장치 진단 도구는 이미지에 넣는다 — 읽기 도구는 제품 이미지에, 커널 헤더는 디버그 프로필에만

**Status:** Proposed (2026-09-26). 이미지 계층 변경(D-225 1항)이므로 다음 이미지 릴리스에서만 효과가 난다.

잇는 결정: [D-161](D-161-ubuntu-server-native-ros-runtime.md) · [D-165](D-165-pinky-pro-native-hardware-dependencies.md) · [D-192](D-192-hardware-runtime-in-the-image.md) · [D-225](D-225-update-without-reflash-and-faster-card-writes.md) · [D-247](D-247-dashboard-shows-every-board-device.md).

**Context:** 2026-09-25–26 `rosy_18`(네이티브 이미지 release 012) 원격 점검에서 보드 장치를 판정할 도구가 이미지에 없었다.

- I2C 레지스터 하나를 읽으려고 매번 Python 스니펫을 SSH heredoc으로 보냈다. `i2cget`이 없다.
- 핀 mux(램프 GPIO19가 `pwm0`인지)를 보려면 `pinctrl`이 필요했다. 없어서 debugfs를 뒤졌다.
- 부저 핀을 찾는 반분 탐색은 RPi.GPIO 스크립트로 했다. `gpioset`/`gpioinfo`가 없다.
- 카메라 `-121` 판정은 커널 로그뿐이었다. 센서가 붙었을 때 한 장을 찍어 볼 `rpicam-still`이 없다.
- 램프 커널 모듈(`rp1_ws281x_pwm`)을 장치에서 빌드하려고 `linux-headers-<kver>`와 `make`를 임시로 설치했다.
  이것은 이미지 밖 변경이고, 헤더는 수백 MB다.

D-165는 하드웨어 의존을 고정하고 "이미지에 들어가는 것과 하드웨어 승인은 별도"라고 정했다. D-161은 CORE를 비특권으로 두고
장치를 열지 않게 했다. 진단 도구는 root만 쓰는 운영자 도구이고, CORE의 권한을 넓히지 않는다. 그러나 이미지에 들어가는
바이너리는 곧 공격 표면이고, 서명된 이미지의 크기와 카드 기록 시간(D-225)에 더해진다.

**Decision:**

1. **제품 이미지에 읽기 도구 넷을 넣는다.** 모두 잠긴 Ubuntu noble 스위트에서 `apt-get install --no-install-recommends`로
   설치하고, 버전은 `deb-packages.txt`에 남아 검증기가 본다(D-165 4항과 같은 경로).

   | 패키지 | 쓰는 명령 | 용도 |
   |---|---|---|
   | `i2c-tools` | `i2cget`, `i2cdump -r` | 알려진 주소의 레지스터 읽기. `i2cdetect` 전 범위 스캔은 쓰지 않는다(D-247 5항) |
   | `raspi-utils` 계열 중 `pinctrl`을 주는 패키지 | `pinctrl get <n>` | 핀 기능·mux 읽기 |
   | `gpiod` | `gpioinfo`, `gpioget`, `gpioset` | 라인 소유자 확인, 사람 확인이 필요한 부저·램프 시험 |
   | `rpicam-apps`(lite 변형이 있으면 그것) | `rpicam-hello --list-cameras`, `rpicam-still` | 카메라 열거와 한 장 촬영 |

   - noble ports에 해당 패키지가 없거나 Pi 5 카메라 스택(pisp)을 지원하지 않으면 그 행은 넣지 않고 이 ADR에 사유를 적는다.
     다른 출처(PPA, 소스 빌드)로 대신하지 않는다.
   - 실행 권한은 기본 그대로다. 장치 노드 접근은 root 또는 해당 그룹뿐이고, CORE(`rosy-core`)는 어느 그룹에도 추가하지 않는다.
2. **커널 헤더와 빌드 도구는 디버그 프로필에만 둔다.** `linux-headers-<kver>`, `make`, `gcc`는 제품 이미지에 넣지 않는다.
   이미지 빌드에 `debug` 프로필을 두고, 그 프로필의 산출물은 이름과 매니페스트에 `debug`를 달며 제품 릴리스로 승격하지 않는다.
   커널 모듈은 이미지 빌드에서 만들어 넣는다(램프 모듈이 그 예다). 장치에서 빌드하는 것은 디버그 카드에서만 한다.
3. **도구는 판정을 대신하지 않는다.** `rosy-hw-probe`(D-247)가 정식 관측이다. 도구는 사람이 원인을 좁힐 때 쓴다.
   빛과 소리는 도구의 반환 코드가 아니라 사람의 확인이 결과다.
4. **검사.** `verify-mounted-image.py`는 제품 이미지에 네 명령이 있고 `linux-headers-*`, `gcc`, `make`가 없음을 확인한다.
   디버그 프로필은 반대로 헤더가 실행 중 커널 버전과 같은지 확인한다.

**Alternatives:**

- *필요할 때 장치에서 `apt install`* — 현장에 인터넷이 없을 수 있고, 설치한 패키지가 서명 이미지와 어긋난 채 남는다.
  2026-09-26의 헤더 설치가 그 예다.
- *Python 스니펫만 쓰기* — 지금 방식이다. 매번 쓰는 코드가 달라 실수(주소, `I2C_SLAVE_FORCE`, 모드 쓰기)의 여지가 크다.
- *전부 디버그 프로필에* — 제품 장치에서 고장을 볼 때마다 카드를 바꿔야 한다. 읽기 도구 넷은 작고, root 전용이라
  얻는 진단 가치가 표면 증가보다 크다고 본다.
- *헤더까지 제품 이미지에* — 크기(수백 MB)와 기록 시간이 늘고, 장치에서 커널 코드를 빌드할 수 있게 된다. 받지 않는다.

**Consequences:** 제품 이미지가 조금 커진다(패키지 넷, 수 MB 규모로 예상하며 첫 빌드에서 잰 값을 `deploy/logs.md`에 남긴다).
root 셸을 얻은 공격자는 이 도구 없이도 같은 일을 할 수 있으므로, root 전제 아래 새 권한은 생기지 않는다.
디버그 프로필이라는 두 번째 산출물 종류가 생기고, 그 산출물이 제품으로 섞이지 않게 하는 검사가 필요하다.

**Validation / Transition:** (1) 잠긴 noble 인덱스에서 네 패키지의 존재와 크기를 확인해 이 ADR의 표를 확정한다.
(2) `customize-rootfs.sh`에 설치를 넣고 `verify-mounted-image.py` 검사와 host pytest를 추가한다.
(3) 새 이미지로 기록한 장치에서 `i2cget -y 0 0x28 0x00`(BNO055 칩 ID, 기대 `0xa0`), `pinctrl get 19`, `gpioinfo`, `rpicam-hello --list-cameras`를 한 번씩 돌려
`docs/validation/`에 남긴다. 그때 Accepted로 올린다.

**References:** D-161, D-165, D-190, D-192, D-225, D-247.
