# D-427 wave 5 개별 검증 게이트 기록 (2026-10-04)

소스 이전 이후 실제 실행한 게이트와 미검증 범위를 기록한다. 이 문서는 앞선 서명·SD 오프라인 검증 기록을 보충하며, 이전 실패를 성공으로 바꾸지 않는다.

입력은 작업마다 다르다. 신규 overlay·Gazebo·Cam 입력은 `109b340654f6`, Docker 이미지와 native·SD 후보의 소스는 `1722ca6ec6d7`이다. 기존 WSL 설치는 `1792877e72da`로 빌드했으며 여섯 source-part Git tree가 `1722ca6ec6d7`과 동일함을 비교했다. 이후 peer 변경을 기존 ARM64 산출물의 내용으로 간주하지 않는다.

| 게이트 | 실제 결과 | 입증 범위 |
|---|---|---|
| CORE 개발 overlay 묶음 | PASS, pack만 | 실제 CLI 출력 205개 안전한 일반 파일, 422310 bytes. Python/core와 공유 웹 자산 포함. 적용·기기 실행 미실행. |
| ament share와 CORE executable | PASS, WSL 호스트 | core/control/omx_adapter/description/navigation/pinky_pro share 존재. 실제 `ros2 pkg executables core` 결과 `core core`. |
| Gazebo 패키지 빌드 | PASS, 호스트 compile | 실제 gz_sim 단일 패키지 빌드 EXIT0, 21분 29초. 기존 Jazzy 의존성 사용, BUILD_TESTING=OFF. 시뮬레이션 성공으로 간주하지 않는다. |
| 두 Pinky 기동·telemetry | PASS, AMD64 Docker; WSL 실패 원본 유지 | 후속 Docker에서 모델 2개·각 odometry 64개·증가 clock 10개, native EXIT0·cleanup PASS를 독립 확인했다.  처음 두 실행은 120초 안에 모델·odometry·clock을 관측하지 못했다. ament 순서를 바꾼 세 번째 실행은 launch가 signal 11로 종료됐다. 검증한 Python 경로 후보와 stock ROS2를 사용한 네 번째 실행도 120초 기준을 충족하지 못했다. 네 실행 모두 자체 프로세스 정리 PASS, 남은 자체 프로세스 0, 발행 명령 0. |
| Gazebo lane smoke | NOT_RUN | 두 모델 기동·telemetry와 별도 범위다. lane·camera·실기 검증을 실행하지 않았다. |
| Cam JVM 단위 시험 | PASS, 330건 | 실제 `testDebugUnitTest` EXIT0, 실패·오류·skip 0. 첫 명령은 PowerShell 인자 분리로 시험 실행 전에 실패했고 로그를 보존했다. 기기 설치·카메라 실사용 검증은 별도다. |
| 이동 패키지 launch lookup | PASS, 12개 share·27개 파일 | 실제 설치 share에서 모든 Python/XML 실행·보조 파일을 조회했다. 첫 검사에는 안내 문서 6개도 포함했고 설치하지 않은 2개 때문에 FAIL로 종료했다. 원본을 보존하고 후속 조회는 안내 문서 전체를 제외했다. launch action 실행은 하지 않는다. |
| Robot·Pilot·Fleet browser suite | 전체 재검증 FAIL 1건, 해당 패널 후속 PASS | 원본 109는 231 passed/21 failed, e886은 295 passed/19 failed로 종료됐다. 기존 실패 목록 분류도 각각 NEW 21·19, EXIT1이며 예외를 추가하지 않았다. 별도 수정 후 Dashboard 전체 79건·등록 절차 6건·헤더 3건·panel/waypoint 4건·카메라/G2 2건·대기 navigation 1건을 실제 통과했다. 727b60c63f36 전체 재검증은 314 passed/1 failed, native EXIT1, NEW 1로 종료됐다. 유일한 실패는 카메라 fullscreen 종료와 owned controls 복원 시점을 같은 것으로 간주한 시험 경합이었다. 동일 DOM 복원 조건의 5초 bounded wait를 추가했고 실제 해당 패널 전체 21건이 통과했다. 이 후속 시험을 전체 315건 PASS로 합산하지 않는다. loopback fixture와 전용 X 캡처를 사용한다. |
| Cam APK assembleDebug | PASS | 실제 6분 8초, 37 tasks. 독립 ZIP 516개 CRC, manifest/resources, DEX 11개 검사. 입력 133개는 Git과 대응: 4개 바이트 동일, 129개 UTF-8 줄바꿈 차이만 존재. debug signing만 수행. 인증서 암호학적 검증·release signing·설치·기기 runtime 미검증. |
| Fleet·Vision Docker 이미지 | PASS, AMD64 build | 실제 각각 EXIT0, 59.14초·35.51초. 로컬 이미지 생성만 수행. registry push·site 배포 없음. |
| CORE·IO Docker 이미지 | PASS, AMD64 build | 실제 각각 EXIT0, 124.09초·99.11초. 빌드 중 기존 CORE import/UI 및 IO share/web probe 통과. ARM64 OCI 성공으로 간주하지 않는다. |
| CORE·IO ARM64 Docker 이미지 | FAIL, 로컬 실행 환경 | 기반 이미지 `/bin/bash` 실행부터 exec format error. 동일 digest의 bash/true는 정상 ELF header(machine 183, ARM64)이며 network none의 `/bin/true`도 EXIT255. 제품 소스 명령까지 도달하지 못했다. 자체 진단 컨테이너 정리 EXIT0. kernel/binfmt 변경 없음. |
| 개별 wave4b/4c/4d/4e native·SD checkpoint | NOT_ESTABLISHED | 최종 결합 `1722ca6ec6d7`/035 증거와 구분한다. 중간 SHA별 실행을 찾지 못했으며 최종 결과로 소급 PASS 또는 ARTIFACT_EQUIVALENT를 부여하지 않는다. |

## 실제 설치 내용 비교

생성된 CORE·IO AMD64 이미지에서 실행하지 않은 자체 컨테이너를 만들고 설치 디렉터리를 X 증거 경로로 복사한 뒤 컨테이너를 삭제했다. 각 이미지의 실제 ament package marker는 10개이며 native035의 27개 marker에 포함된다. 이미지의 역할별 부분집합을 전체 native 설치와 동일하다고 표현하지 않는다.

CORE 공유 Python/JavaScript 263개 중 23개는 바이트 동일, 240개는 UTF-8 CRLF/LF 차이만 있다. IO 352개 중 33개는 바이트 동일, 319개는 같은 줄바꿈 차이만 있다. 내용 차이와 native 대응 파일 누락은 모두 0이다. 정규화는 비교에만 사용했으며 서명된 native·SD·Docker 파일을 고치지 않았다. ELF·의존성·기기 runtime의 동등성은 이 검사에 포함하지 않는다.

033 tar의 실제 ament marker도 27개이며 035와 추가·삭제가 없다. `rosy-packages.txt`는 빌드 뒤 `colcon list`로 만든 소스 inventory 28개다. `gz_sim`은 이 inventory에만 있어 실제 설치 marker 27개와 구분해야 한다. mandatory package 확인과 전체 소스 목록은 서로 다른 검증 범위다.

## 실패 진단과 남은 경계

처음 실패 뒤 import/LaunchDescription 생성은 16.79초, action 구성만 하는 검사는 16.17초, xacro 생성은 5.07초에 종료됐다. action 실행이나 로봇 명령은 없었다. 이후 실제 launch 추적은 ros_gz_sim의 Gazebo 리소스 집계에서 ament get_resource/isfile 조회를 반복하는 위치를 보여줬다. ament 검색 순서 변경은 37종 리소스·428개 패키지 provider와 Gazebo export 목록(0개 항목)의 순서가 동일함을 확인한 뒤 해당 프로세스에만 적용했지만, 이 실행의 signal 11 원인은 아직 확정하지 못했다. 개별 구성 검사는 실제 기동 PASS를 대신하지 않는다.

최초 Python 검색 순서 후보는 829개 module spec 검사에서 3개 차이를 발견해 적용하지 않았다. 로컬 user package의 psutil·typing_extensions 선택을 보존하는 후속 후보는 실제 835개 module spec 및 순서가 있는 namespace provider 비교에서 차이 0개로 PASS했다. 이는 실행 중인 import 전체의 동등성을 증명하지 않으며, 검증한 입력과 proof 해시를 확인한 자식 프로세스 진단에만 적용한다. 이 진단은 기동·lane acceptance가 아니다.

현재 native035는 로컬 서명·검증 완료 후보이고 SD factory 내용은 별도 오프라인 검증을 통과했으며 unsigned 상태다. 릴리스 발행·자동 활성화·canary/secondary readback·FIELD acceptance는 미완료다. model-watch는 확인한 사이트의 관리자 권한이 필요하며 installer dry-run은 설치 완료가 아니다. peer 안내도 실제 운영 채널로 보내지 못했다.

## 증거 위치

원본과 독립 리뷰는 로컬 `X:/DevTemp/rosy-d427/resume/`에 보존한다: `wave5-core-overlay-pack-result.json`, `wave5-wsl-ament-lookup-result.json`, `wave5-gz-smoke-build-result.json`, 세 시뮬레이션 디렉터리의 `two-pinky-result.json`, `wave5-cam-apk-smoke-result.json`, `wave5-cam-apk-independent-review.md`, `docker-named-gates/result.json`, `docker-core-io-host/result.json`, `docker-install-closure/result.json`, `wave5-docker-install-content-correspondence-result.json`, `wave5-native-installed-ament-vs033-result.json`. 원본 raw byte 비교와 실패 로그를 보존한다.

추가 확인: stock GazeboRosPaths의 실측은 428개 패키지·141.72초(share 조회 합계 132.70초, parse 합계 5.25초, import 5.79초)였다. 120초는 작업자가 정한 호스트 관측 시간이며 원래 계획의 기동 성능 요구가 아니다. 후속 관측 시간을 검토하되 telemetry 조건과 이전 실패 기록을 유지한다.

브라우저 첫 확정 실패는 신호등 빈 상태 문구에 파일명이 들어 있어 기존 assertion과 충돌한 것이다. 실제 033 tar와 033 소스에서도 동일한 문구 및 assertion을 확인했다. 이후 공유 main에는 peer의 해당 문구 수정과 Fleet UI 변경이 반영되어 있어 중복 수정하지 않는다. 현재 109 기준 전체 실행과 최신 소스의 후속 실행은 별도 증거로 남긴다.

## 후속 브라우저 수정과 별도 시뮬레이션 진단

`e886f22065f3` 종료 결과는 295 passed/19 failed, 2765.22초다. 원본 로그와 NEW 19 분류는 동결했으며 이전 109 실패 기록을 덮어쓰지 않았다. 초기화 중 노출된 compatibility shell의 클릭이 app handler 바인딩 전에 사라지는 문제는 import 동안 inert로 보호했다. 실제 module 요청을 지연한 회귀 시험은 수정 전 실패하고, 보호 코드를 제거한 mutation도 같은 이유로 실패했다. 복원 해시를 확인한 뒤 관련 5건과 Dashboard 전체 79건을 통과했다.

Fleet 설치 시험은 실제 화면의 로봇 등록 탭을 선택하도록 6곳의 절차만 보충했다. Cell 작업 링크는 기존 반응형 header grid에 named area로 배치해 implicit row를 없앴고 3개 viewport 시험이 통과했다. 링크·정지·상태·기존 높이 제한을 유지했다. panel fixture는 실제 store.state 메서드와 dom.js 자산 URL을 제공하도록 맞췄고, G2 action 측정은 중첩된 인식 안내 대신 직접 action status를 읽는다. 기존 단언·거부 조건을 완화하지 않았다.

Pilot의 조종하지 않는 카메라 보기는 인증된 frame Response를 Blob으로 먼저 소비하고 있었다. 기존 camera-pair 검증기에 Response를 전달하도록 고쳐 metadata 검사를 유지했다. 실제 JPEG가 표시되고 EMERGENCY에서 모드 변경 요청이 없는 기존 시험이 통과했다. 모든 수정은 독립 source/host 리뷰를 받았다. fresh rebase 뒤 수정한 8개 파일의 Git blob은 리뷰한 입력과 동일하다. source/host 수정이 이미 서명한 1722/035에 들어 있다고 표현하지 않는다.

WSL stock Gazebo 리소스 집계 실측은 428개 패키지·141.72초다. 기존 120초는 작업자의 진단 예산이며 원 계획의 기기 성능 한계가 아니다. 후속 360초 실행 중 하나는 두 모델·각 odometry 2개 이상·증가 clock·cleanup PASS를 관측했지만 실제 native WSL returncode를 별도 수집하지 않아 command EXIT0으로 표현할 수 없다. 같은 360초 기준의 직접 returncode 후속 실행은 native EXIT1, 관측 0, cleanup PASS다. 실패 원본을 보존하며 예산을 계속 늘리지 않는다.

별도 AMD64 Docker 진단 이미지의 3개 simulation source-part tree는 1722와 109에서 동일하며 실제 compile은 통과했다. 첫 runtime은 joint_state_publisher 누락으로 EXIT1/관측0/cleanup PASS다. 두 publisher는 description에 이미 선언돼 있으므로 제품 선언 누락이 아닌 진단 이미지의 설치 closure 누락이다. 해당 의존성을 설치한 별도 이미지의 runtime은 Gazebo FileLogger의 recursive Init/createDirectories stack과 SIGSEGV로 실패했다. read-only root와 원래 HOME 아래 기본 logger의 쓰기 경로가 일치하는 것은 원인 추론이며 정확한 실패 pathname은 확보하지 못했다. 다음 진단은 원래 HOME 값을 유지하고 그 .gz 디렉터리만 자체 X 로그 디렉터리에 연결한다. 나머지 root read-only, network none, no device, 무명령, 360초 telemetry 기준과 자체 프로세스 정리 기준을 유지한다. 이 구성의 실제 후속 결과는 아래에 기록한 AMD64 Docker 기동·telemetry 범위에서 PASS다.

추가 증거: `wave5-browser-e886-terminal-result.json`, `wave5-browser-e886-known-failures.txt`, `browser-bootstrap-mutation-red/result.json`, `browser-bootstrap-restored-green/result.json`, `browser-bootstrap-dashboard-full/result.json`, `browser-fleet-task-selection/result.json`, `browser-fleet-header-grid/result.json`, `browser-robot-fixture-alignment/result.json`, `browser-camera-and-action-status/result.json`, `browser-fleet-queued-final/result.json`, `wave5-browser-fixes-rebase-blob-result.json`, `docker-gazebo-smoke/runtime/runtime-result.json`, `docker-gazebo-runtime-deps-local-tag/runtime/runtime-result.json`.

추가 실제 결과: `docker-gazebo-logger-mount/runtime/runtime-result.json`은 native Docker EXIT0, 57.446초, 실제 두 모델·각 odometry 64개·증가 clock 10개·cleanup PASS·정확한 자체 컨테이너 제거를 기록했다. 원래 HOME/.gz만 자체 X 경로로 연결했고 다른 root는 읽기 전용이며 network none과 무명령 기준을 유지했다. 이는 AMD64 호스트의 two-Pinky 기동·telemetry 통과이며 WSL 원본의 native returncode, ARM OCI·lane·카메라·실기·FIELD의 통과를 소급하지 않는다. 독립 actual 리뷰도 이 host 범위를 APPROVE했다. 원래 WSL·Docker 실패 기록은 그대로 보존한다.


## 카메라 fullscreen 시험의 후속 확인

`727b60c63f36` 전체 browser 재검증은 실제 `ROSY_RUN_BROWSER_TESTS=1 python -m pytest -q -rfE`로 앞서 열거한 Dashboard·Fleet·Pilot 및 Robot browser 19개 파일을 실행했다. 314 passed/1 failed, 1371.75초, native EXIT1이다. 실제 `test/known_failures.py`도 NEW 1/EXIT1이며 예외를 추가하지 않았다. 원본 로그 SHA256은 `73b00935d6cb0555858c08a29c1863444e910bc698993a4399922b5ce29eb1f2`이다.

실패 node는 `middleware/ui/robot/test/test_panel_copy_evidence_browser.py::test_camera_fullscreen_keeps_owned_stop_feedback_and_record_stop`다. native fullscreen 해제 상태와 앱의 fullscreenchange 복원은 별도 시점이다. X 전용 진단에서 실제 native 해제를 유지하며 앱 이벤트 전달을 250ms 지연했다. 기존 시험은 동일 복원 assert에서 실패했다. 기록은 native fullscreen=null일 때 stop 부모가 div·record stop이 stage 내부인 상태와, 이벤트 처리 후 stop 부모가 ui-topbar·record stop이 stage 외부인 상태를 모두 담는다.

시험에 들어갈 때와 나올 때 같은 소유 DOM 조건을 5초 동안 기다리도록 2줄만 추가했다. 기존 identity·정지 호출 수·안내 문구·녹화 정지·focus 단언은 전부 유지했다. 제품 camera.js는 바꾸지 않았다. 지연 전달 진단은 후속 native EXIT0이며, 복원 callback 자체를 차단한 변이는 5초 wait에서 실제 EXIT1이다. 원본 지연 진단의 초기 entry 경합/teardown 오류도 폐기하지 않고 보존했다.

별도 정상 이벤트 전달의 `ROSY_RUN_BROWSER_TESTS=1 python -m pytest middleware/ui/robot/test/test_panel_copy_evidence_browser.py -q -rfE`는 21 passed, 229.59초, native EXIT0, known_failures NEW 0이다. 입력은 `8753c23d3`와 시험 2줄 수정이며 최종 fixture commit은 `53d4d08eb`(통합 `5132e4dbf`)다. 독립 리뷰는 수정·지연 재현·복원 차단 RED·정상 전체 panel 결과를 APPROVE했다. 전체 315건, CI, 새 ARM artifact 또는 DEVICE 완료를 이 결과로 소급하지 않는다.

현재 fresh readonly 사이트 확인에서 model-watch.timer는 not-found이며 관리자 명령은 권한 부족으로 실패했다. installer dry-run의 설치 승격은 없다. 기존 own canary transport tunnel은 종료됐으며 그 loopback 주소의 connection refused를 로봇 offline으로 해석하지 않는다. 다음 사용 가능한 035 후보 release 조회도 발행되지 않은 것으로 확인했다. 사용 세션 조율과 실제 운영 채널의 peer 안내는 남아 있다.

후속 원본: `wave5-browser-postfix-terminal-result.json`, `wave5-browser-postfix-known-failures.txt`, `browser-fullscreen-boundary-red-v2/event-boundary.json`, `browser-fullscreen-boundary-green/result.json`, `browser-fullscreen-boundary-blocked-red/result.json`, `browser-fullscreen-panel-green/result.json`, `wave5-camera-fullscreen-wait-independent-review.md`. 모든 임시 진단과 원본은 X 증거 경로에 두며 공개 파일에는 실제 주소·계정·키를 넣지 않았다.
