# Isaac 5.1 headless SDK 복구와 CORE 연결

초기 bootstrap 소스는 `97973b01de`, 최종 복구 소스는 `055fd333ce`다. **센서 없는 Pinky 한 대의 헤드리스 기동·ROS 연결과 기존 CORE를 통한 전진·회전·입력 만료 뒤 실제 정지를 관찰했다. 목표 회전 속도 추종이 실패하므로 I1 주행 수용·두 대 Fleet·신호 준수 완주는 HOLD다.** 이전 [I1 주행 기록](../cell-isaac-2026-10-04/isaac-core-drive.md)을 이번 기동 결과만으로 닫지 않는다.

## 범위와 환경

- 모델 PC: Ubuntu 24.04, Isaac Sim 5.1.0.0/Python 3.11, RTX 5080 Laptop 16 GB VRAM, 물리 RAM 15,395 MiB. 외부 ROS는 Jazzy/Python 3.12다.
- 원래 SDK/Lab 환경은 보존하고 작업 소유 디렉터리에 SDK 전용 venv를 복사했다. `python -m pip`가 복사본 prefix를 가리키는지 확인했다. SDK의 Starlette 요구와 설치된 Lab metadata의 요구는 충돌하므로 한 환경에서 충족하지 않는다. SDK dependency closure 밖의 Lab/ML/notebook 패키지를 복사본에서만 제거하고 `requirements-sdk-5.1.txt`의 정확한 SDK 버전을 적용했다. SDK closure 143 packages에서 `pip check` exit 0이며, 원래 Lab/Starlette 설치는 보존됐다.
- SDK에는 외부 ROS/CORE `PYTHONPATH`를 전달하지 않고 내부 Jazzy bridge library를 사용했다. CORE는 기존 ROS workspace의 생성된 `interfaces`와 source archive의 `core_common`, `core`, `core_features`, `core_events`, `core_api_web`, motion/skill/learning 계약을 사용했다. CORE source 모듈 경로를 확인했다.
- 시험 namespace `rosy_98`, DDS domain 138, localhost 제한이다. CORE API도 localhost에만 바인딩했다. 초기 viewer GET에 이어 주행은 임시 operator 인증으로 정식 `/api/v1/mode`의 MANUAL과 `/api/v1/teleop`만 호출했다. CORE가 최종 cmd_vel publisher이며 observer는 ROS 구독만 한다. E-Stop·calibration·readiness를 우회하지 않았다. 실제 로봇·현장 Fleet·운영 enrollment에 연결하지 않았다.
- Isaac은 모두 `--headless`이며 640×480/anti-aliasing 0이다. SDK는 `MemoryMax=4G`, `MemorySwapMax=2G`, `CPUQuota=600%` user scope와 wall timeout 안에서 실행했다. 호스트 busy·예약·살아 있는 작업 잠금과 GPU 사용을 확인하고 자기 잠금만 정리했다. GPU 학습을 동시에 실행하지 않았다.
- Ollama user service는 inactive다. 기존 swap은 44,561 MiB 논리 용량이며, 이 중 zram은 물리 RAM을 압축해 쓰므로 추가 물리 메모리가 아니다. 디스크 swap은 약 36 GiB이고 대부분 미사용이었다. 새 swap을 추가하지 않았다. ZFS ARC live cap은 자동값 그대로이며 root 권한이 필요한 변경은 적용하지 않았다.
- D-568의 `sim` 하한은 Gazebo/Nav2 배치다. 이번 SDK bootstrap은 D-434의 센서 없는 한 대 범위에서 4 GiB RAM/2 GiB swap으로 제한했다. [공식 5.1 최소 사양](https://docs.isaacsim.omniverse.nvidia.com/5.1.0/installation/requirements.html)의 물리 RAM 32 GB 수용을 주장하지 않는다.

## 실제 실행

동일 URDF는 실제 Jazzy xacro로 생성했고, Pinky 17 joints/10 mesh references와 OMX vendor asset hashes를 검사했다. USD/URDF는 source checkout 밖의 작업 소유 artifact다.

```bash
# SDK 전용 Python, 내부 Jazzy bridge, 동일 DDS domain을 준비한 후
python learning/envs/isaac/run_rosy.py \
  --urdf <artifact>/pinky.urdf --output-dir <artifact>/idle-usd \
  --namespace rosy_98 --headless --frames 600
```

| 실행 | 관측 | 결과 |
|---|---|---|
| SDK 단독 120 frames | 늦게 시작한 observer가 실행 창을 놓쳤다 | SDK exit 0, ROS 증거로 수용하지 않음 |
| SDK 단독 600 frames, 메뉴 수정 전 | clock/odom/joints 수신, USD teardown 뒤 GUI menu callback 오류 2건 | SDK exit 0이어도 무오류 종료는 실패 |
| SDK 단독 600 frames, `97973b01d` | clock/odom/joints 각각 400개, clock 증가, cmd_vel publisher 0 | SDK/observer exit 0, SDK `[Error]`·Traceback 없음 |
| 기존 CORE + SDK 600 frames | clock/odom/joints 각 400개, cmd_vel 413개, publisher는 `/rosy_98/core` 하나, 모든 명령 0 | CORE/SDK/observer exit 0; SDK `[Error]`·Traceback 없음 |

CORE `GET /api/v1/robot/state`, `/robot/pose`, `/system/capabilities`는 모두 200이다. state의 pose/velocity evidence가 fresh이고 odom과 연결됐다. 그러나 map은 없고, traffic policy는 DISABLED, line follow는 OFF, camera는 unavailable이다. Nav2 실행 없이 기본 readiness/capability가 ready라고 표시된 항목은 실제 navigation 수용이 아니다. host indicator의 `/run/rosy` 경로 부재 warning과 종료 시 rosout context-invalid 진단도 남았으며 장치 display 수용으로 보지 않는다.

## 초기 물리 정지 실패와 fixed-link 수정

CORE가 zero만 발행한 실행의 마지막 60 odom samples에서 xyz span은 약 1.525/0.895/0.104 mm, yaw span은 **0.10761 rad**였다. 같은 구간 wheel velocity peak는 1.6751/1.8104 rad/s, passive caster rotation은 107.4074 rad/s였다. 무주행 target zero를 실제 정지로 수용하지 않는다. 따라서 이 모델 상태에서 전진·회전 명령이나 두 대 확장으로 완주를 주장하지 않았다.

추가 USD 진단은 실제 rigid bodies와 관절·충돌 prim을 읽었다. 위치 solver iterations는 이미 32, velocity iterations는 1이며 self-collision은 false다. inertia 없는 fixed reference links가 mass 0/default inertia로 각각 rigid body가 된 것을 관찰했다. Wheeled import만 fixed-link 병합을 켠 `8ae521a92d`는 이런 분리된 reference body를 줄이며, OMX의 fixed-base 모델은 기존 import를 유지한다. 병합 비교 실행에서 마지막 60 samples yaw span은 0.000965 rad, caster peak는 0.0025 rad/s로 줄었다. URDF geometry와 wheel radius/contact separation은 바꾸지 않았다.

## 주행·만료·publisher 중단

가져온 바퀴 USD drive는 `acceleration`, damping 0, stiffness 625였다. 기존 velocity 설정의 fallback damping 1에서는 전진이 동작했지만 angular 0.3 명령에도 회전이 거의 없었다. DDS 수신, graph의 angular 입력, 좌우 wheel target ±0.52018 rad/s와 articulation applied target까지 각각 읽어 CORE/graph 전달 실패와 구분했다.

`caa5c7a242`부터 바퀴만 force-type velocity drive로 명시하고 USD type/gain/target readback을 검사한다. 기존 positive imported gain 또는 fallback 1을 유지하고 caster 두 관절은 비구동이다. force drive에서 기본 옵션만으로 전진·회전과 입력 만료 정착이 관찰됐다. [NVIDIA stability guide](https://docs.omniverse.nvidia.com/kit/docs/omni_physics/107.3/dev_guide/guides/articulation_stability_guide.html)의 contact-connected inertia 설명과 부합하는 원인 추정이며, 물리 엔진의 실제 contact inertia를 독립 측정한 것은 아니다.

최종 시험은 공개 `run_rosy.py --headless --frames 2400`이며 gain override, teleport, caster 제거, friction 제거를 쓰지 않는다. 원래 SDK/Lab·장치 URDF와 실제 CORE 제어 계약은 보존한다. SDK 자체 watchdog 확인을 위해 주행 중 **이 작업이 시작한 격리 CORE PID만**, 시작 시각·명령행·domain·작업 전용 config를 확인한 뒤 SIGKILL했다. 이 경우 CORE exit 137은 의도한 장애 주입이며 정상 종료 0과 구분한다.

명령이 끊긴 뒤 실제 odom 속도가 linear 0.005 m/s/angular 0.02 rad/s 미만으로 0.2초 이상 유지되는 첫 시점을 정착으로 판정한다. CORE 만료는 마지막 teleop 요청 기준 0.65초, SDK publisher-loss는 0.9초 안에 정착해야 한다. 정착 후 마지막 0.5초 peak도 검사한다. SIGKILL 직후 cached DDS graph의 publisher entry가 남을 수 있으므로 PID 종료와 새 Twist 수신 중단을 별도 관찰하고, 이미 큐에 들어온 메시지는 장애 주입 뒤 0.1초 창으로 구분한다.

회전 추종은 목표 0.3 rad/s의 ±10% 범위를 요구했으며 현재 약 0.19 rad/s로 실패한다. 전체 observer 통과를 주장하지 않는다. 게인 50/250/1000, articulation sleep threshold 0, velocity solver iterations 16, 긴 회전 실행, physics 240 Hz, fixed-root inertia 이동도 분리 실험했다. 일부 설정은 정착·속도에 개선이 있었지만 추종 기준을 통과하지 못했으므로 소스에 반영하지 않았다. gain을 크게 올리는 것만으로 문제를 닫지 않는다.

최종 `055fd333ce`에서 clock 1423, odom/joints 각각 1422, cmd_vel 1086개를 수신했다. 주행 전 cmd_vel publisher는 `/rosy_98/core` 하나였다. 직진 거리 0.14560 m와 회전 yaw +0.60202 rad는 각각 simulation time 약 3.12초/3.02초 구간의 값이며 wall time 2초와 혼동하지 않는다.

| 관측 | 실제 결과 | 판정 |
|---|---|---|
| 전진 0.05 m/s | 마지막 0.5초 평균 0.049952 m/s | ±10% 추종 PASS |
| 회전 0.3 rad/s | 마지막 0.5초 평균 0.194416 rad/s | ±10% 추종 FAIL |
| 전진 입력 만료 | CORE zero 0.30836초, 실제 정착 0.35178초 | 0.65초 이내 PASS |
| 회전 입력 만료 | CORE zero 0.30110초, 실제 정착 0.34113초 | 0.65초 이내 PASS |
| 주행 중 격리 CORE SIGKILL | CORE zero 없이 SDK 자체 정착 0.57224초, 마지막 linear/angular peak 0.00006433 m/s / 0.00786711 rad/s | 0.9초 이내 PASS |

publisher-loss 구간의 0.1초 유예 뒤 새 Twist는 0개이고, 장애 주입 전 실제 속도는 0.049948 m/s였다. DDS graph에는 중단된 CORE 이름이 남았으므로 graph만으로 생존을 판단하지 않는다. SDK exit **0**, 의도한 CORE exit **137**, 소유 PID 확인 watcher exit **0**이며 observer exit **1**의 유일한 실패 check는 `rotation_tracking`이다. 전체 shell exit 1을 전체 주행 통과로 바꾸지 않는다.

## 헤드리스 종료

GUI menu extension을 기동 뒤 해제하거나 종료 전에 menu data를 비우고 rebuild해도 마지막 시험에서 SDK menu의 `can_close`가 이미 해제된 USD context를 읽었다. 최종 `055fd333ce`는 [Kit의 공식 startup exclusion](https://docs.omniverse.nvidia.com/kit/docs/kit-manual/107.2.0/guide/extensions_advanced.html#app-extensions-excluded-default)을 headless launch config에 전달해 `isaacsim.gui.menu`를 초기 시작 순서에서 제외한다. 후행 URDF importer의 dependency enable에서는 SDK menu가 다시 로드되므로 확장 자체가 전혀 로드되지 않는다고 주장하지 않는다. 그 경우 정상 extension lifecycle을 유지하며 실패했던 runtime menu unload/cleanup 코드는 제거했다. 최종 2400-frame SDK log에는 `[Error]`·Traceback이 없다. 같은 소스의 별도 1-frame 종료 경계 시험도 SDK exit 0, `[Error]`·Traceback 없이 끝났다. GUI 실행에는 적용하지 않는다. SDK 시작 실패 시에도 close를 거친 원래 비정상 종료를 숨기지 않는다.

## 소스 검증과 증거

헤드리스 config, Wheeled fixed-link 병합, force drive/readback, headless menu exclusion 검사는 각각 먼저 RED를 관찰한 뒤 구현했다. 최종 `055fd333ce` 원격 pytest는 **75 passed / 1 skipped**, `known_failures.py` 신규 실패 0이다. skip은 해당 pytest 환경에 실제 xacro overlay가 없는 경계이며 위 실제 URDF 생성은 별도로 수행했다. GUI 모드는 renderer 설정을 강제하지 않고 SDK 실패의 원래 종료 코드를 유지한다.

Raw logs/JSON/SDK freeze는 `X:/DevTemp/projects/rosy-platform/2026-10-11--005034--curved-pinky-pair--452e72/evidence/`에 보관한다. 주소·계정·인증정보가 포함될 수 있는 raw 파일은 공개 저장소에 넣지 않는다.

종료 후 SDK `pip check`를 다시 통과했다. 이 작업의 runtime PID와 Isaac 잠금은 각각 0개이며 격리 CORE API listener도 닫혔다. Ollama user service는 inactive이고 ZFS ARC cap은 자동값 0으로 보존됐다. 마지막 host available RAM은 9,573 MiB, swap은 44,561 MiB 중 1,574 MiB 사용이다. 다른 세션의 프로세스·장치 서비스·원래 모델 PC 설치를 정리 대상으로 삼지 않았다.

| 파일 | SHA-256 |
|---|---|
| `idle-run-3.log` | `44a06d2321d743379775fab0f3339d0411387d0c1dcc42d6cc694da432760e2d` |
| `idle-observation-3.json` | `f427a9f194a7209bd663feaa8808836b2edc98995c183826e7542e2ba9bf29f8` |
| `sdk-freeze.txt` | `535fa8e85675e9b5545fc652af7e6867e84732ff66f5170d2d79f372c8c761ac` |
| `core-observation.json` | `f9d46ae378ae4beb9f75f9762b5c831b3b59ea879a3f09d62139170689214015` |
| `drive-exclude.json` | `f05e51596b79257109b7794c7d7994a1017dae60c460027189773672820fe4a9` |
| `drive-exclude-sdk.log` | `30a380cf2cb49ad41444dab57b66e2ea8fe4c7b97daf5b08538c4b3cd5553541` |
| `core-exclude-loss-ack.json` | `148b7284283a8d2f89232b558ecbac96b4cd31d83b5217f301065f1b0bf5e52b` |
| `drive-exclude-source-sha.txt` | `9b78784e74e6f535ea5330760d79b314fd6f38fd3de0abb8b5c432bae410f5f3` |
| `one-frame-exclude.log` | `5567513fb45ff8a9791a3faf6c96292a638b29b6ee96f09a6d1bcb419cdc81f5` |

실제 map_v2_fleet STL 맵의 Isaac 변환, 센서, 두 대 Fleet, 신호·횡단보도·한 바퀴 완주와 강화학습은 이번 실행에서 확인하지 않았다. map 변경의 로컬 main 병합과 RL 구조 문서는 별도 작업이며, 이 SDK 복구 branch의 main 착지·push·CI 증거를 뜻하지 않는다.
