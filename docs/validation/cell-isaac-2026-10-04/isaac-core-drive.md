# 2026-10-04 Isaac I1 실측 검증

## 판정

**I1 주행·물리 정지 수용은 HOLD다.** 실제 CORE API에서 주행 명령을 받고 단일 CORE publisher가 출력하는 경로, 명령 갱신 중단 후 CORE 출력의 만료, 유한 프레임 실행의 SDK close 반환·프로세스 종료는 각각 확인했다. 전진 추종과 회전 후 물리적인 정착은 통과하지 못했다. 목표 속도가 0이라는 사실을 실제 정지로 취급하지 않는다.

## 격리와 실행 경로

- 모델 PC의 Isaac Sim 5.1.0.0 / Python 3.11, 별도 검증 환경의 CPU Torch 2.7.0을 사용했다. 렌더러·PhysX는 기존 NVIDIA GPU를 사용했으며 GPU Torch 학습을 검증하지 않았다.
- 기존 모델 checkout·SDK·ML 환경을 보존하고 별도 검증 디렉터리만 사용했다. 실제 로봇과 관제 운영 endpoint에 연결하지 않았다. 실행 중 Gazebo와 예약을 공유하지 않았다.
- 시험 identity는 `rosy_99`, DDS domain 139, localhost 제한이었다. API도 localhost에만 바인딩했다. 임시 operator 인증을 사용했고 인증정보는 이 문서에 기록하지 않는다.
- 실제 `CoreServices`, `RosBridge`, canonical FastAPI 앱을 구성했다. 관찰기는 clock/odom/joint_states/cmd_vel을 구독만 했다. ROS endpoint discovery에서 `/rosy_99/core` publisher 하나를 확인한 뒤 canonical mode/teleop API를 호출했다. readiness·E-Stop·capability·명령 만료 검사를 우회하지 않았다.
- 명령은 전진 `0.05 m/s` 약 3초, 입력 갱신 중단 2초, 회전 `0.4 rad/s` 약 3초, 입력 갱신 중단 2초였다. 프레임·wall timeout·소유 프로세스 정리를 별도로 제한했다.

## 시도별 결과

이 문서의 A01–A07은 이번 I1 시험이다. 이전 무주행 SDK 검증의 `run7`과 구분한다. 원본 로그·JSON·소스 아카이브는 private evidence에 보존하고 주소·계정 경로·토큰을 versioned 문서에 복사하지 않는다.

| 시도 | 변경/관측 | CORE/SDK 종료 | 판정 |
|---|---|---|---|
| A01 | private readback probe가 실제 `velocityCommand` 대신 없는 `velocity` 속성을 요청했다. teleop에 도달하지 않았다. | 둘 다 nonzero, 소유 PID 부재 확인 | 시험 probe 실패; runtime 성공 아님 |
| A02 | 실제 CORE API와 관찰기. odom/joints/clock 각 800개, cmd 1250개. CORE 만료 출력은 약 0.4초 후 zero. 실제 휠 추종 실패. | CORE 0, SDK 15초 close grace 후 강제 종료 -9, PID 부재 | CORE 만료만 확인; 주행·SDK 종료 HOLD |
| A03 | receipt/graph/filter와 USD zero readback 관찰. 실제 Twist 600회, graph 864회, zero readback 46회 모두 0. | CORE 0, SDK native glibc assertion·65초 grace 후 -9, PID 부재 | target zero 확인; 실제 이동·정상 종료 HOLD |
| A04 | 명시적 wheel damping 50. live USD stiffness 0/damping 50 확인. 전진 actual wheel velocity가 목표 +1.7857 대신 약 -0.51 rad/s. | CORE 0, SDK native -11, PID 부재 | damping 변경으로 수용하지 않음 |
| A05 | 원래 NVIDIA articulation compute 실행 후 적용 action/gains/joint mapping만 관찰. wheel indices [0,1], 목표 velocity 전달 확인. 비구동 caster 두 개에 position gain 약 35809.86이 남아 있었다. | CORE 0, SDK native -11, PID 부재 | importer의 passive caster servo 발견; 주행 HOLD |
| A06 | URDF로 비구동 continuous caster identity를 확인하고 그 두 drive의 stiffness/damping/velocity target을 0으로 설정. actual caster gains 0 확인. damping 50은 회전 후 물리 drift·wheel spike가 남았다. | CORE 0, SDK native -11, PID 부재 | passive 설정 확인; 물리 정지 HOLD |
| A07 | passive caster 수정 + 기존 fallback과 같은 damping 1. public runner 1000 frames, CORE 종료 후 SDK 유한 프레임 실행이 자연 종료하도록 bounded wait. | **CORE 0 / SDK 0**, timeout·강제 kill 없음, 두 PID 부재 | finite-frame close 반환·process 종료 PASS; 종료 후 GUI 오류 2건·I1 주행·물리 정지 HOLD |

## A07 실제 관측

- actual wheel gains: stiffness 0, damping 약 57.29578; caster stiffness/damping 모두 0. USD에 쓴 gain 1과 SDK의 radian 단위 gain이 다르므로 GUI/USD 값을 tensor gain과 같은 숫자로 가정하지 않는다.
- SDK graph callback 1000회, 실제 Twist receipt 593회, graph/USD wheel-target zero readback 367회 모두 0. `main_finished=true`와 process exit 0을 함께 확인했다.
- CORE 인증 API 전진 28회·회전 29회 수락. 명령 갱신 중단 후 independent cmd_vel은 전진 약 0.411초, 회전 약 0.408초에 0이 됐다.
- 전진 phase x 변화는 약 0.7 micrometers로 추종 실패였다. 회전 phase yaw 변화 약 +0.282 rad는 관찰됐지만, 입력 갱신 중단 다음 2초에 약 +0.402 rad가 더 변했다. 만료 뒤 wheel velocity peak는 약 2.264 rad/s였다. 실제 정지로 수용하지 않는다.
- SDK close 반환과 process 종료는 자연 프레임 종료에서 확인했다. 최종 로그에는 USD context 해제 후 GUI menu callback에서 `AttributeError: NoneType has no get_stage_state` traceback 2건이 있다. runner main으로 전파되지 않은 SDK 내부 진단이며, 무오류 SDK shutdown은 확인하지 못했다. A03–A06의 SDK update 중 SIGINT 후 native 종료 오류까지 해결됐다는 뜻도 아니다.

## 소스와 검증

기준 main은 `2e656ebb35b66c5b4e6348311bca8790c2679aaa`이며 CLI 종료 수정은 `ed8f2a07c8d08e684f6b55b11eac34e2565092dc`다. A06/A07에 사용한 추가 source candidate의 SHA-256은 다음과 같다.

| 파일 | SHA-256 |
|---|---|
| `run_rosy.py` | `02daff97bdf37c2be5a11af6eeb1536ea436b7082da4437bfa61d4d11fe4b594` |
| `drive_runtime.py` | `dfc761295d56bea445a4e578b4e3ec5ed052981da29d72390ca243772e833632` |
| `sdk_entrypoint.py` | `1587f59b8ae7eb2239e425fe91bcc2d077bb08ad53ce9275b89c3262afc02c7e` |
| `command_watchdog.py` | `933bbbeab2195a9d25bcaacc68b0b703c3d4be2c2ddc0b6426381c5fd1baad68` |

원본 `supervisor-receipt.json`에는 전체 runner 파일 hash와 소유 프로세스의 종료/부재 검사가 있다. `drive-observation.json`은 독립 ROS 관측과 API phase 경계, `sdk-receipt.json`은 실제 callback·gain/action·zero readback을 보관한다. SDK exception/native signal을 exit 0으로 바꾸지 않았다.

Host 검증은 `learning/envs/isaac/test` 69 passed / 1 skipped이며 skip은 실제 ROS/xacro overlay가 없는 host 경계다. 신규 gain·passive caster 검사는 먼저 RED를 관찰하고 구현 뒤 통과했다. `known_failures.py`는 신규 실패 0, 변경 Python의 scoped flake8과 diff 검사를 통과했다. host 결과는 I1 물리 수용을 대체하지 않는다.

## 남은 일과 교훈

1. 실제 articulation targets·gains·joint mapping이 전달된 상태에서도 발생하는 contact/solver/inertia 안정성을 모델 commissioning으로 확인해야 한다. contact를 없애거나 robot을 teleport해서 수용하지 않는다. baseline 물리 안정성과 전진 추종을 먼저 확인한 뒤 같은 명령 만료 시나리오를 재검증한다.
2. SDK update 중 SIGINT 경계는 별도의 종료 문제다. 안전한 loop stop 요청과 정상 update 반환 후 종료를 검토하고, 정상·오류·interrupt 결과를 분리해서 확인해야 한다.
3. native SDK가 자동 생성한 drive는 비구동 continuous caster에도 position servo를 만들 수 있다. URDF의 actuator 계약과 실제 applied gains를 모두 읽어 확인한다.
4. 출력 target zero, 관측 pose 정지, 정상 SDK close, process 종료/부재는 각각 다른 증거다. 기록과 수용 기준을 합치지 않는다.

NVIDIA [5.1 joint tuning](https://docs.isaacsim.omniverse.nvidia.com/5.1.0/robot_setup_tutorials/joint_tuning.html)은 velocity drive의 stiffness를 0으로 두고 measured velocity convergence로 damping을 조정하도록 설명한다. gain 숫자만 높이는 것은 수용이 아니며, 이번 damping 50 실험은 실제 정착을 통과하지 못했다. [107.3 articulation stability guidance](https://docs.omniverse.nvidia.com/kit/docs/omni_physics/107.3/dev_guide/guides/articulation_stability_guide.html)도 gain과 timestep의 결합을 함께 평가하도록 안내한다.
