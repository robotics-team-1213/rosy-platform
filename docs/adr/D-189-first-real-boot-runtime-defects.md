## D-189 unit의 샌드박스·HOME·Python 의존성은 제품의 일부다 — 서명 전에 실제로 돌려 보고 통과시킨다

**Status:** Accepted (2026-09-24). release `2026.09.23-005`의 첫 실기 부팅 결과에 대한 결정. D-161(CORE 비특권),
D-174(설치 위치 실행 검증)를 유지하고 그 검사를 unit 샌드박스와 Python 런타임까지 넓힌다.
번호: 처음 D-183으로 썼으나 main(b33a31e6)이 D-177..D-179·D-181..D-186을 가져와 D-189로 다시 매겼다.
D-180은 다른 브랜치 몫으로 비워 둔다.

**Context:** `2026.09.23-005` 카드를 Pinky Pro(Raspberry Pi 5, Ubuntu 24.04 arm64, ROS 2 Jazzy)에 꽂았다.
첫 부팅 개인화는 `PROVISIONED`까지 갔고, 현장 Wi-Fi에 붙었고, 운영자 SSH 키가 동작했고,
`rosy-boot-status`는 `FAILED:rosy-release-recover`를 정확히 보였다(D-174 T0·D-175가 제 역할을 했다).
CORE는 한 번도 뜨지 않았다. 결함 네 개가 차례로 가로막았고, 각각을 장치에서 systemd drop-in이나 pip로
응급 조치한 뒤 재부팅하자 `CORE_READY`, LED heartbeat, LAN에서 CORE API :8080 응답까지 갔다.

| # | 결함 | 증거 | 근본 원인 |
|---|---|---|---|
| D1 | `rosy-release-recover.service`가 `[Errno 30] Read-only file system: '/var/lib/rosy/releases'`로 실패 | journal, `rosy-boot-status` `FAILED:rosy-release-recover` | unit이 `ProtectSystem=strict`인데 쓰기 경로가 하나도 없다. `native_release.py recover`는 저널이 없어도 **매번** `/var/lib/rosy/releases/native-release.lock`을 연다. 저널을 재생하면 `/opt/rosy/{current,previous}`와 임시 링크 `/opt/rosy/.current.new`도 쓴다 |
| D2 | `ImportError: cannot import name 'field_validator' from 'pydantic'`, 이어서 `websockets` 없음 | CORE journal. 장치에 apt `python3-pydantic` 1.10.14, `python3-fastapi` 0.101 | `core_common`·`core_api_web` `package.xml`의 `python3-pydantic`·`python3-fastapi`는 버전이 없다. rosdep은 Ubuntu 24.04 apt 패키지로 풀고, 그것은 pydantic 1이다. `websockets`는 아무 package.xml에도 없다. CI와 WSL 시뮬 박스는 `pip install`로 최신을 깐다 |
| D3 | CORE가 `~/.rosy/rosy.yaml` `stat`에서 `EACCES`로 죽는다 | CORE journal | `rosy-core.service`는 `ProtectHome=true`인데 CORE는 `Path.home()/.rosy`에 설정 오버레이(`core_common/config.py`)·waypoints·docks·audit·배터리 sentinel(`core/node.py`, `services.py`)을 둔다. 서비스 계정의 passwd 홈은 `/home/rosy-core`이고 `ProtectHome=true`는 `/home`을 **읽을 수 없게**(ENOENT가 아니라 EACCES) 만든다. D-174 F6은 `ROS_HOME`만 옮겼다 |
| D4 | CORE가 root 전용 상태를 소유하고 쓸 수 있다 (D-161 위반) | `ls -l /var/lib/rosy`: `provisioning/`·`releases/`·`config/`가 `rosy-core` 소유 | `rosy-core.service`의 `StateDirectory=rosy` + `ReadWritePaths=/var/lib/rosy /run/rosy`. systemd는 `User=`가 있는 unit의 StateDirectory를 **시작할 때마다 재귀적으로 chown**한다. 신원(`provisioning/`), 복구 저널(`releases/`), 부팅 설정(`config/`)이 CORE 것이 되었다 |

응급 조치(장치 drop-in):

- D1 `StateDirectory=rosy/releases`, `ReadWritePaths=/opt/rosy`.
- D2 `apt install python3-pip` 후 `pip3 install --break-system-packages --ignore-installed pydantic==2.13.5 pydantic-core==2.46.5 fastapi==0.141.1 starlette==1.6.0 uvicorn==0.52.4 websockets==17.1`. 설치 위치는 `/usr/local`.
- D3 `Environment=HOME=/var/lib/rosy/core`, `StateDirectory=rosy/core`.
- D4 `StateDirectory=`/`StateDirectory=rosy/core`, `ReadWritePaths=`/`ReadWritePaths=/var/lib/rosy/core /var/lib/rosy/maps /run/rosy`. 이어서 부모와 root 전용 디렉터리를 `chown root:root`로 되돌렸다.

**왜 모든 host 시험과 이미지 빌드가 통과했는가:**

1. **샌드박스는 어디서도 실행되지 않았다.** unit 계약 시험은 지시어 문자열이 있는지만 봤다. `ProtectSystem=strict`,
   `ProtectHome=true`, `StateDirectory=`의 효과는 systemd가 namespace를 세울 때만 생긴다. host pytest, colcon,
   이미지 customizer의 chroot 어디에도 systemd가 없다. D-174 F5는 진입점을 설치 위치에서 실행했지만 **root
   chroot에서** 실행했다. 쓰기 금지·홈 없음·다른 사용자라는 세 조건이 빠진 실행이었다.
2. **Python 의존성은 저장소 밖에서 정해졌다.** CI(`ci.yml`, `arm64-rehearsal.yml`)와 WSL 박스는 버전 없이
   `pip install pydantic fastapi …`로 최신을 깐다. 이미지는 rosdep으로 apt 패키지를 깐다. 같은 이름, 다른
   메이저 버전이었다. 시험 환경과 제품 환경이 공유한 것은 패키지 **이름**뿐이다.
3. **이미지는 CORE를 import하지 않았다.** customizer의 진입점 검사는 복구 도구·첫 부팅·표시 계층의 `--help`까지였다.
   CORE는 `ros2 pkg prefix`로 **존재**만 확인했다. `core.node`는 `uvicorn`·`core_api_web.api.app`을 함수 안에서
   늦게 import하므로 플래그만 받는 `--help`로도 닿지 않는다.
4. **D4는 결함이 아니라 설계가 보였다.** `StateDirectory=rosy`는 D-161 시점에 "CORE가 자기 상태를 쓴다"를
   표현하려던 것이다. 공유 부모를 주면 자식 전체가 따라간다는 systemd 의미를 검사하는 시험이 없었다.

**Decision:**

1. **D1: 복구 gate는 자기가 쓰는 곳만 쓴다.** `rosy-release-recover.service`에 `StateDirectory=rosy/releases`와
   `ReadWritePaths=/opt/rosy`. `activate`·`rollback`은 이 unit이 아니라 운영자가 `sudo`로 부르는 wrapper
   (`activate-release.sh`, `rollback-release.sh`)라 샌드박스 밖이다. 셋이 쓰는 경로는 같다: 저널·락
   (`/var/lib/rosy/releases`), 링크(`/opt/rosy/{current,previous}`, 임시 `.current.new`/`.previous.new`).
   `/opt/rosy/releases`는 읽기만 한다.
2. **D2: CORE의 Python 런타임은 해시로 고정한 입력이다.**
   - `deploy/image/device-python-requirements.txt`: 응급 조치 6개(= WSL 시뮬 박스의 검증된 집합)와 그 폐포 8개
     (`annotated-doc 0.0.5`, `annotated-types 0.8.0`, `anyio 4.15.1`, `click 8.5.0`, `h11 0.16.0`, `idna 3.20`,
     `typing-extensions 4.16.0`, `typing-inspection 0.4.4`, 2026-09-24 해석). 휠마다 SHA-256, 컴파일 휠
     (`pydantic-core`, `websockets`)은 cp312 manylinux aarch64(장치)와 x86_64(CI) 두 개. 두 플랫폼 모두
     `pip download --require-hashes`로 14개 전부 받아 해시를 확인했다.
   - `inputs.lock.yaml`의 `python_runtime` 절이 그 파일의 SHA-256을 고정하고, 파일은 `.gitattributes`로 LF 고정이다.
   - `customize-rootfs.sh`는 rosdep **뒤에** 파일 해시를 lock과 대조하고
     `pip install --require-hashes --no-deps --only-binary=:all: --ignore-installed`로 `/usr/local/lib/python3.12/dist-packages`에
     깐다. `/usr/local`이 `/usr/lib/python3/dist-packages`보다 `sys.path` 앞이므로 apt pydantic 1은 남아도 가려진다.
     `--prefix`는 쓰지 않는다(Debian의 posix_prefix는 `sys.path`에 없는 `site-packages`로 간다). 이 때문에
     이미지에 `python3-pip`이 들어간다.
   - CI(`ci.yml`)와 arm64 리허설은 같은 파일을 같은 플래그로 깐다. 시험 도구(`flake8`, `httpx`, `jsonschema`,
     `ext4`, `pyyaml`)는 고정하지 않는다. `httpx`를 먼저 깔고 고정 집합으로 덮는다.
   - `package.xml`의 rosdep 키는 그대로 둔다. 개발 host의 rosdep 경로를 깨지 않고, 이미지에서는 가려진다.
3. **D3: HOME을 쓰는 서비스는 자기 state 디렉터리를 HOME으로 받는다.** `rosy-core`: `HOME=/var/lib/rosy/core`,
   `StateDirectory=rosy/core`(0750). CORE 상태는 `/var/lib/rosy/core/.rosy/`에 모인다. `rosy-io`·`rosy-navigation`은
   지금 `Path.home()`을 쓰는 노드를 띄우지 않지만(`startup_calibration_node`의 `~/.local/state/control/…` 기본값은
   `control/robot.launch.py`에서만 뜬다) 같은 함정을 닫는다: `HOME=/var/lib/rosy/{io,navigation}`,
   `StateDirectory=rosy/{io,navigation}`.
4. **D4: `/var/lib/rosy`는 root 부모다. 각 unit은 자기 하위 디렉터리만 소유한다.**
   - `rosy-core`: `StateDirectory=rosy/core`, `ReadWritePaths=/run/rosy`. `/var/lib/rosy`·`/var/lib/rosy/maps`를 뺀다.
   - 지도를 쓰는 것은 CORE가 아니다. `POST …/save_map`은 CORE가 경로(`ROSY_MAP_OUTPUT_DIR`, 기본 `/var/lib/rosy/maps`)를
     정해 slam_toolbox `SaveMap`을 부르고, **파일은 `rosy-navigation`(User `rosy-io`) 안의 slam_toolbox가 쓴다.**
     CORE는 저장된 pgm을 다시 읽어 `map_id` 체크섬만 만든다.
   - 새 `tmpfiles-rosy-state.conf`(`/etc/tmpfiles.d/rosy-state.conf`):
     `d /var/lib/rosy 0755 root root`, `d /var/lib/rosy/maps 2750 rosy-io rosy-core`(setgid 그룹이라
     `UMask=0027`로 쓴 지도도 CORE가 읽는다), 005를 돌린 카드를 위해 `Z provisioning|releases|config - root root`.
     이미지도 같은 소유로 만든다.
   - `rosy-io`·`rosy-navigation`의 `ReadWritePaths=/var/lib/rosy/commissioning`은 이미지가 만들지 않는 경로다. 없는
     `ReadWritePaths`는 unit을 226/NAMESPACE로 죽이므로 `-` 접두(선택)로 바꿨다.
5. **가드 A — 정적 샌드박스 계약(`test/test_native_systemd_contract.py`).** 모든 `deploy/robot/native/*.service`를
   systemd처럼(빈 대입은 초기화) 파싱한다.
   - `StateDirectory=rosy`나 공유 부모(`/var/lib/rosy`, `/var/lib`, `/opt`, `/etc/rosy`)를 쓰기 경로로 가진 unit 금지.
   - root가 아닌 unit의 쓰기 집합은 root 전용 상태(`provisioning`, `releases`, `config`)의 조상도 자손도 될 수 없다.
   - `ProtectSystem=strict` unit마다 **코드에서 뽑은 쓰기 경로 목록**(`DECLARED_WRITES`, 코드 위치 주석 포함)이
     StateDirectory·LogsDirectory·RuntimeDirectory·ReadWritePaths로 덮여야 한다. 목록에 없는 strict unit은 실패한다.
   - 목록이 코드와 어긋나지 않게, unit의 프로그램 소스를 grep해 절대 경로 리터럴, `"var" / "lib" / …` 조립, `Path.home()`을
     찾고 각각이 쓰기나 읽기(`DECLARED_READS`)로 분류돼 있어야 한다.
   - `ProtectHome=true`인 비 root unit은 쓰기 집합 안에 `HOME`을 둔다.
   - `-` 없는 `ReadWritePaths`는 unit 자신·tmpfiles·이미지·Requires한 unit 중 하나가 만들어야 한다.
   - 이 시험들은 005의 unit 파일에서 9건 실패하고 수정본에서 통과한다(적색→녹색 확인). 설치 배치 시험은 복구를
     실제로 돌려 쓴 파일이 unit 쓰기 집합(`var/lib/rosy/releases/`, `opt/rosy/`) 밖에 없음을 확인한다(저널 재생 경로는
     symlink가 되는 host에서만, WSL에서 통과).
6. **가드 B — 이미지 안 import probe(`deploy/image/probe-core-runtime.py`).** customizer가 릴리스를 `current`로 건 뒤,
   `verify-mounted-image.py` 전에 chroot에서 unit과 같은 조건(`env -i`, ROS와 릴리스 overlay source, `HOME=/nonexistent`,
   `python3 -B`)으로 실행하고 실패하면 이미지 빌드를 실패시킨다. 확인하는 것:
   고정 집합 14개가 정확한 버전으로 설치되어 `/usr/local`에서 import되는지, `pydantic` 메이저가 2인지,
   `core.main`·`core.node`와 그 둘이 함수 안에서 늦게 import하는 모든 모듈(`try` 안의 선택적 import 제외; `uvicorn`,
   `core_api_web.api.app`, 브리지들), 그리고 fleet agent의 `websockets`.
7. **가드 C — 서명 전 부팅(다음 단계, 이 변경 범위 밖).** 아래 "남은 것"에 구체 절차를 둔다.

**Alternatives:**

- `package.xml`에 버전 조건(`version_gte="2"`)을 거는 것: rosdep은 버전 조건을 풀지 않고 apt 후보를 그대로 깐다.
  실패가 빌드가 아니라 부팅에서 나는 것은 같다.
- venv(`--target` + `.pth`)로 격리: `.pth`는 디렉터리를 `sys.path` **뒤**에 붙여 apt pydantic 1이 먼저 잡힌다.
  앞에 붙이려면 `sitecustomize`나 unit의 `PYTHONPATH`를 손대야 하고, `ros2 run` 래퍼가 그것을 덮는다. `/usr/local`은
  Ubuntu가 이미 앞에 두는 위치다.
- apt pydantic 1을 지우는 것: `python3-fastapi` 등 다른 apt 패키지가 끌려 나가고, rosdep이 다음 설치에서 다시 깐다.
- 응급 drop-in을 그대로 제품에 넣는 것: D4의 drop-in은 CORE에 `/var/lib/rosy/maps` 쓰기를 주지만 CORE는 지도를 쓰지
  않는다. 필요 없는 권한이다.
- 공유 부모에 group 쓰기를 주는 것: D-161이 막으려는 것과 같은 결과다.

**Consequences:** 다음 이미지는 D1-D4 없이 `CORE_READY`까지 갈 것으로 기대하지만, 아래 검증 전에는 기대일 뿐이다.
이미지에 `python3-pip`과 PyPI 휠 14개가 들어간다(설치 시점 네트워크 필요, 해시로 고정). 고정 집합을 올리는 것은 lock
파일·`inputs.lock.yaml` 해시·시험의 기대 버전을 한 커밋에서 바꾸는 런타임 변경이다. CI는 장치와 같은 버전으로
시험하므로, 지금까지 최신 버전에 기대던 host 시험이 있다면 드러난다. CORE 상태 경로가
`/var/lib/rosy/core/.rosy/`로 정해졌다.

**남은 것 (열림):**

- **재빌드 이미지 실기 확인.** 새 release로 카드를 구워 drop-in·pip 응급 조치 없이 (a) `rosy-release-recover` active,
  (b) `/var/lib/rosy` 하위 소유(`provisioning`·`releases`·`config` root, `core` rosy-core, `maps` rosy-io:rosy-core 2750),
  (c) `CORE_READY`와 LED heartbeat, (d) :8080 `/api/v1`, (e) 대시보드 설정 저장이 `/var/lib/rosy/core/.rosy/rosy.yaml`에
  남는지, (f) customizer 로그에 `CORE_RUNTIME_PROBE_OK`가 있는지 본다. probe는 이미지 chroot에서는 아직 돌지 않았다 —
  다음 이미지 빌드가 처음이다. WSL 시뮬 박스(Jazzy, colcon 빌드 없는 소스 트리)에서는 돌려 봤다: 상위 6개 고정은
  모두 일치, `core.main`·`core.node`·`core_api_web.api.app`·`uvicorn`·`websockets` import 성공, 실패는 빌드되지 않은
  `interfaces` 메시지 패키지와 폐포 3개였다.
- **폐포 버전의 근거.** WSL 박스의 폐포는 `anyio 4.14.2`, `click 8.1.6`(apt), `idna 3.6`(apt)이고 나머지 5개는 고정과
  같다. 장치 응급 조치는 `--ignore-installed`로 폐포를 새로 해석했으므로 2026-09-24 해석(`anyio 4.15.1`, `click 8.5.0`,
  `idna 3.20`)에 가깝다고 보지만, 005 카드의 `pip list`는 기록하지 않았다. 재빌드 부팅이 이 폐포의 첫 실기 증거다.
- **005 카드.** 응급 조치로 떠 있는 카드는 재기록을 권한다. 제자리 갱신이면 tmpfiles `Z` 규칙이 root 전용 디렉터리를
  되돌리지만, 응급 drop-in(`/etc/systemd/system/*.service.d/`)과 `/usr/local`의 pip 설치는 운영자가 지운다.
- **배터리 sentinel 경로 불일치(기존).** CORE는 sentinel을 `$HOME/.rosy/battery-shutdown-request.json`에 쓰고
  `rosy-lowbatt-shutdown.sh`는 `/var/lib/rosy/battery-shutdown-request.json`을 본다. 네이티브 이미지에는 그 셧다운
  서비스가 없으므로 이 ADR은 경로만 기록한다.
- **`rosy-io`·`rosy-navigation`은 이미지 overlay에 없다**(`build-native-payload.sh`가 core만 `/etc/systemd/system`에 복사).
  릴리스 트리에는 있다. 하드웨어 슬라이스를 켜는 ADR이 설치 경로와 이 계약을 함께 확인한다.
- **가드 C — 서명 전 부팅.** arm64 러너에서 완성 rootfs를 `systemd-nspawn --boot`로 띄워 `/run/rosy-boot/boot-status.json`이
  `CORE_READY`가 될 때까지(제한 시간 내) 기다린다. 절차:
  1. `finalize-image.sh` 전, 루프 마운트한 rootfs를 읽기 전용 기반 + overlay(`--overlay`나 `--ephemeral`)로 띄워 이미지를 오염시키지 않는다.
  2. 개인화: 저장소의 시험용 provisioning bundle(가짜 신원, Wi-Fi 없음)을 부트 파티션 대신 바인드해 `rosy-first-boot`이
     `PROVISIONED`까지 가게 한다. 이미지에는 남기지 않는다.
  3. 하드웨어: CORE-only가 기본 target이라 모터·라이다·I2C가 필요 없다. `rosy-boot-status`의 ACT LED·avahi는 없는
     장치를 견뎌야 한다(`/sys/class/leds` 부재, avahi 없음).
  4. 네트워크: `--private-network`로 NetworkManager·`rosy-network`의 fallback AP가 실제 무선 없이 실패 없이 넘어가야 한다.
     `network-online.target`이 늦어도 CORE가 뜨는지 본다.
  5. 대기: 컨테이너 안 `boot-status.json`을 폴링하고, 실패면 `journalctl -M`으로 `rosy-*` unit journal을 아티팩트로 올린다.
  - 막힌 점: GitHub arm64 러너에서 nspawn `--boot`(cgroup v2 위임, 권한) 동작 미확인, ARM64 빌드 시간(20-40분)에
    부팅 대기가 더해진다, 시험용 개인화 bundle과 서명 키 처리, `rosy-boot-status`의 LED·avahi 의존 격리.
    이 중 러너 동작 확인이 첫 단계다.

**Validation / Transition:** A는 005 unit 파일에서 적색, 수정본에서 녹색임을 확인했다. B는 이미지 빌드에서만 실행되며
실패하면 빌드가 멈춘다. D1-D4가 닫히는 기준은 위 "재빌드 이미지 실기 확인" (a)-(f) 전부다. 가드 C는 새 ADR 없이
이 ADR의 후속 작업으로 열고, 러너 확인 결과를 `deploy/logs.md`에 남긴다.
