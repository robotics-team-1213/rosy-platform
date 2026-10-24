# OMX 실제 SIM 관절·접촉 진단

7관절 관측은 확보했지만 독립 정책 평가는 **HOLD**다. 이 기록은
[합성 transport 검증](../omx-policy-articulation-2026-10-24/result.md) 이후의
별도 실행이며, 진단 수집 종료 EXIT0을 정책 성공으로 해석하지 않는다.

## 고정 입력과 실행 범위

실행 소스는 local main commit `e79c1fe0e2288d55af37de3c7c243f0922c7c525`다.
공식 착지 검사는 guard273PASS, affected628PASS/SDK1SKIP/NEW0이었다.
별도 실제 SDK transport는1PASS/0SKIP이었다.
착지 receipt sha256: `0f5c996da2a5f043b30616fb5f16128a4e94d40fdb5f45474387f06417a16420`.

외부 원본 루트는 `C:/DevTemp/learning-execution-20261023/`, 이하 `BASE`다.
이번 진단 루트 `NATIVE`는 `BASE/articulation-policy-observation-20261024/`다.
고정 계획은 workspace의 `Rosy/docs/superpowers/plans/2026-10-24-omx-articulation-native-once.md`다.
명령은 `NATIVE/run_diagnostic.py --manifest NATIVE/manifest-v3.json --binding-sha256 <아래 manifest 해시>`다.
최대 calibration1회와 instrumented policy1회만 실행했다. 재학습·재시도·formal trial은0회다.
모델 결과 sha256: `50e972da3896575210e204b160fe7a32c978b91690382c942af7e838f78c3d1e`.

| 고정·파생 파일 | SHA-256 |
|---|---|
| NATIVE/manifest-v3.json | `2a896ecda78bf53223a67ef88085ed19e361fa86afe95da62e994ebc5fce782e` |
| NATIVE/run_diagnostic.py | `0b619d7d8be57f3e5a56a8b0086e73ce0749e2e8743c5926af4dd620df6d4f82` |
| NATIVE/analyze_articulation.py | `2b13c5470ba2301907650cbfe9edab2541a2e422388f70d4e7f62f161282ef53` |
| NATIVE/articulation-contact-analysis.json | `b9b048f07e94e8c3647df522676daf71c404cd7b39404d07b4b31650d398bfd7` |

## 실제 결과와 종료

calibration run ID 끝자리는 `7f299cdc736a`, episode는 `8d3af099d633`이며
공통 접두사는 위 실행 소스 SHA와 `-`다. 각각 EXIT0/PASS와 EXIT1/HOLD다.
시작 후 실제 system unit에서 CPUQuotaPerSecUSec=`4s`, MemoryMax=`4294967296`을
읽었다. 총 제한은 각600초다. calibration96파일, episode264파일을 원본과 바이트 대조했다.
각 종료 시 PID0, cgroup 비움, lock·reservation 해제를 확인했다.
episode unit의 최종 `failed` 상태는 EXIT1의 종료 상태다.
증거는 각 `NATIVE/native-diagnostic/<calibration|instrumented-episode>/`의
시작 전후 producer/limit 기록, closure, `latest-fetch.json`과 extraction map에 있다.

| 회수 원본 | SHA-256 |
|---|---|
| calibration archive | `e3100d3b59ff40fa1d9c6aa70831671f00ed10721a13685c162885da71d97557` |
| episode archive | `c90bf2c131512d16de2565ed4722855095897abfa81e46857059404f85f5e492` |
| episode manifest.json | `4d5c7e37b40f2b3384636c2a1267d194ad74f16f3f4181a0868904046b10b8f6` |
| pick-place/policy-articulation.json | `bb4350651f0906b6067a6c8b5542af2149b73f56d0fdcb6f0edef4d42f35c4dd` |
| pick-place/policy-contacts.json | `745b17cfca219bae7c340fa1e89c325414611b63cb4619b56faab7e52bb46b80` |
| episode tracking trace | `91bf01008f37e35cc21b8739092f751f9e2e33ba01896c7a9ea6d78a3034f331` |
| episode native events | `80c3feab49d11f34c9b6c9556046867a2b288ea56c07b6d7ff3dc427df2a9c11` |

정책 명령170개가 수락됐고 terminal170개 중169개가 성공했다. 마지막은
status6/result−5다. JTC는 joint4/5 오차−0.054730/−0.051609rad와 허용값0.02rad,
goal-time 초과1.010초를 보고했다. 물체 lift0, XY오차0.22926149m로 task success=false다.
카메라 accepted2421/rejected1, camera_error 없음, worker_errors=[]다.
허용 오차나 성공 판정을 바꾸지 않았다.

## 관측 범위와 시간·좌표 근거

메시지29487개에서19049개 표본을 저장했고 invalid0/truncated=false다.
publisher 순서의 gripper_joint_1, gripper_joint_2, joint1…joint5와 실제 속도7개,
frame_id=`base_link`를 보존했다. source 범위는0.018…295.360초,
최대 수신 간격117.374318ms, 종료 간격661.329009ms다. 연속 관측을 뜻하지 않는다.
마지막 gripper 두 값의 합은−0.03049239516rad다. FK에 관측한 두 값을 각각 사용했고
이상적인 mimic 값으로 대체하지 않았다. 기존 tracking과 동일한 source stamp1600개에서
공통6관절 값이 정확히 일치했다. 이 비교만으로 접촉 시계를 증명하지 않는다.

접촉과 관절의 시계·좌표 해석은 다음 producer 경로에 근거한다.

- [gz_ros2_control1.2.20](https://raw.githubusercontent.com/ros-controls/gz_ros2_control/1.2.20/gz_ros2_control/src/gz_ros2_control_plugin.cpp)의 PostUpdate는 `_info.simTime`으로 ROS 시각을 만들어 read/update에 전달한다. 소스 SHA-256 `9fd40cc3a6a0ba16b12081eea63b3735c930071d1e414606142bb967dc7b9557`.
- [gz-sim8.15.0 Contact](https://raw.githubusercontent.com/gazebosim/gz-sim/gz-sim8_8.15.0/src/systems/contact/Contact.cc)는 `_info.simTime`을 AddContacts에 전달하고 outer Contacts header에 저장한다. SHA-256 `1488fa407e506d0e9afeda233c4a122ea278f11081b131aa0f09116ec1f423e7`.
- [ros_gz1.0.24 변환](https://raw.githubusercontent.com/gazebosim/ros_gz/1.0.24/ros_gz_bridge/src/convert/ros_gz_interfaces.cpp)은 outer header와 접촉 좌표·depth를 보존한다. inner Contact header는 복사하지 않으므로 사용하지 않았다. SHA-256 `989df81eb84b0c8b4151b5b8631d880a4cc7b71dbd254e2ea3df88e0472bffbf`.
- [gz-physics7.8.0](https://raw.githubusercontent.com/gazebosim/gz-physics/gz-physics7_7.8.0/bullet-featherstone/src/SimulationFeatures.cc)는 world 좌표 `getPositionWorldOnA()`와 signed depth=`-getDistance()`를 제공한다. SHA-256 `7dcd7d8b549615f78e0e17fa7e0c8f0d2d84be307b44da82b69bf0a6cdd4face`. [gz-sim Physics](https://raw.githubusercontent.com/gazebosim/gz-sim/gz-sim8_8.15.0/src/systems/physics/Physics.cc)가 이 좌표를 직접 복사한다. SHA-256 `5d5c404151f8ae4f7825c43c571dc151c79b9a587c69db35996d7cabbc4e76e1`.

실제 manifest의 라이브러리 해시는 다음과 같다.

- control sha256: `2e059b030a4551482ca43442996a6664d5143783b69972566740acf5756c2cbc`.
- bridge sha256: `f92c93b994583d0704012b10c13da2daaaa44a679d9de766daee8675f196b3ef`.
- physics sha256: `854e7518321980c24a66721a3ff60090acd9eb4ca19872b07ab6fb2e30e426d8`.
- sim sha256: `a348e4d28376de4e59ba58402142d0ce9e2abd7852ab76e721a34bafa569ef19`.

준비 전후·회수 시 producer 해시를 대조했다. 패키지 버전·설치 파일과 upstream 소스의
대응 근거이며 재현 빌드로 바이너리 동등성을 증명한 것은 아니다.

보존 expanded-description.json의 입력5개 해시는 이번 manifest dependency와 모두 일치한다.
그 XML의 world_fixed는 xyz/rpy 모두0이고, 고정 launch는 spawn XYZ/RPY 모두0이다.
launch sha256: `1a24d0e10eda4845e97e78f261498bbe13517cc0492ca6d625b7612a845bb1bd`.
expanded XML sha256: `9d08cceef3ca89e312537e107b9eb728dfc1829039c7f03a5830dd95cbc38aea`.
회수 `pick-place/camera-world.sdf` sha256: `b912e2eac751964f2ca37dfbbce858eb6a78a9b354cbfc8a3287d6d97ab5bf49`.
table pose=(0.05,0,−0.01), box=(0.7,0.7,0.02)여서 상면 Z=0이다.
접촉 frame_id는 비어 있으므로 위 producer·spawn·world 근거로 해석했다.

## 기하 관측의 한계와 다음 확인

양 손가락의 첫 저장 signed-depth 보고 시각은278.808초다. 양쪽 관절 표본
278.800/278.810초에서 명목 STL 최저점−보고 point Z는 약10.0099/9.9934mm다.
첫 양수 depth 보고는 link6 280.584초, link7 280.472초이며 endpoint 차이는 약9.70mm다.
음수 depth는 관통이 아니고 첫 저장 보고는 실제 접촉 시작 시각이 아니다.
접촉 시각과 각 bracket 표본의 차이는 최대8ms이며 양쪽 표본 간격은10ms다.
표본 사이 연속 자세의 경계를 뜻하지 않는다.
STL 계산은 Bullet padding을 포함하지 않아 이 차이를 실제 margin 측정값으로 부를 수 없다.

terminal event에는 host monotonic receipt만 있고 정확한 SIM 시각은 없다.
failed target과 일치하는 마지막 tracking sample294.670초는 대표 표본일 뿐이다.
이후 hold reference나 종료 후 자세를 실패 순간의 정책 target/자세로 대체하지 않았다.
독립 검토2건이 원본·FK·표본 범위와 HOLD 해석을 확인했으며, 시간·좌표 근거를 추가했다.

다음 확인은 고정 geometry의 작은 대조 SIM 실험으로 effective collision envelope를
분리하는 것이다. 이 진단의 실행 예산은 소진됐으며 추가 actor는 실행하지 않았다.
정책 실패 인과, 정책 품질, 양팔 실제 작업, 물리 장치 수용과 실제 HF 전송은 미검증이다.

CE: 미해결 — 관측 누락은 보강했지만 정책 실패 원인은 아직 해결되지 않았다.
해결 교훈을 새로 쓰지 않았고 허용 오차·판정·기존 실패 기준도 완화하지 않았다.
