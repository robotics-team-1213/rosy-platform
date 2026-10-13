# D-626 holder 이전과 D-627 CORE Drive 조립 검증

2026-10-11. 브랜치 `feat/platform-structure-migration`, 기준 `3927f9a33`, 최종 코드/시험 후보 `5faad3583`. main 착지·push·장치 적용은 수행하지 않았다.

## 소스 결과

| 단위 | 실제 이전/추출 | 커밋 |
|---|---|---|
| M3 API | `middleware/core/api_web` → `middleware/core/api` | `4e3a4f7ff` |
| M4 Pinky | `middleware/apps/device/pinky` → `middleware/devices/pinky` | `7b0a8d965` |
| M5 OMX | `middleware/apps/device/omx` → `middleware/devices/omx` | `9de41f5c7` |
| M6 Nav2 | `middleware/core/navigation` → `middleware/control/drive/planning/nav2` | `291d03a9f` |
| M7 첫 조립 단위 | CORE `drive/line_follow.py`, `drive/docking.py`; 기존 import facade·service attribute 유지 | `1691d395c` |

현재 책임은 [구조 안내](../../reference/core-drive-responsibilities.md), source-only 독립 승인은 [Safety 리뷰](safety-review.md)를 따른다. 이동한 6개 Safety 구현과 Pinky driver/deadman, Nav2 launch/config/package identity가 보존됐다. Docker COPY의 소스 operand와 실제 소비자·CI·harness·프로필 탐색·물리 package-role 표를 수정했다. 설치 목적지와 ROS package/share/entrypoint 이름은 유지했다. 기존 module logs는 이동 커밋에서 R100으로 보존한 뒤 이번 증거를 추가한다.

CORE Drive 조립은 기존 도킹/군집 manager와 provider를 만들고 기존 take/release/mode-exit callback을 돌려준다. `CoreServices`는 공통 객체와 전체 listener 등록 순서를 유지한다. line-follow의 곡률 envelope/floor/센서/복구 배선은 구현을 그대로 옮겼다. `services.py`는 481줄이며 기존 >600 verdict를 제거했다. 새 Safety 모듈 2개와 앵커 4개를 추가했다.

## 원격 검증

로그 정본: X 관리 세션 `2026-10-11--001305--core-responsibility-plan--66d72e`의 `logs/`. 아래 수치는 pytest progress 성공/skip 표시를 센 값이며 다른 행끼리 중복된 시험을 포함한다. 모두 exit 0이고 `known_failures.py`는 0 NEW/0 known이다. 노트북 pytest는 실행하지 않았다.

| 후보 | 로그 | 성공 | skip | 범위 |
|---|---|---:|---:|---|
| `3927f9a33` | `holder-baseline/run-1.txt` | 104 | 0 | 이전 전 구조·Safety·도구 |
| `74a1db355` | `holder-api-green/run-1.txt` | 489 | 13 | API, 물리 구조, Safety, native payload/systemd/dev sync |
| `7b0a8d965` | `holder-pinky/run-1.txt` | 885 | 2 | bringup/profile/description, robot selection, motor/deadman, native/구조 |
| `828e10ed5` | `layout-log-green/run-1.txt` | 98 | 0 | append-only/harness 회귀 |
| `291d03a9f` | `holder-nav2/run-1.txt` | 440 | 0 | launch/limits/footprint/bandwidth/native/구조 |
| `ca7335b07` | `core-drive-baseline/run-1.txt` | 257 | 0 | Drive 추출 전 port/goal/도킹/복구/envelope/Safety |
| `1691d395c` | `drive-final/run-3.txt` | 1675 | 0 | 전체 core_features |
| `1691d395c` | `drive-final/run-4.txt` | 532 | 3 | OMX 전체 adapter/profile 및 owner/fence/G2 호출자 |
| `dbd0dd772` | `drive-final-fixed/run-2.txt` | 272 | 0 | 전체 architecture, 이전 도구/harness/Safety 리뷰 계약 및 wheel 조합 |
| `5faad3583` | `drive-core-green/run-1.txt` | 2575 | 10 | 전체 CORE gateway 및 실제 Linux package build/install 4개 |

설치 검사에서는 원본 소스 대신 임시 복사본에서 CORE/API/Pinky bringup/OMX adapter wheel을 빌드하고 별도 target에 설치했다. checkout 밖의 isolated Python에서 package import, `core.drive` 발견, distribution 위치, 기존 console entrypoint, ament resource/share/package.xml 및 config 파일을 확인했다. ROS 노드나 모터를 실행하지 않았다. OMX agent는 새 CI 소스 경로에서 remote runner가 wheel build/install 및 pip check를 마친 환경으로 시험했다.

13 browser skip과 ROS/선택 환경 skip은 통과로 세지 않았다. 이는 실제 브라우저·Jazzy graph·vendor runtime 검증이 아니다. 설치 검사는 Python package 설치/발견과 metadata 수준이며 Nav2 CMake/colcon 설치 및 실제 ROS 부팅을 검증하지 않는다.

## 발견한 실패와 수정

- API 이전 뒤 `_state`가 frozen `d427_target`을 물리 목표로도 썼다. 회귀 RED 후 optional `layout_target`을 도입해 현재 배치와 소유권 ID를 분리했다. 기존 legacy 잔여 검사도 유지했다.
- 두 번째 이전에서 append-only 검사가 원래 D-427 legacy만 찾으며 이후 holder의 로그 이력을 놓쳤다. 회귀 RED 후 frozen 소유권 경로를 먼저 확인하도록 고쳐 현재/merge-base 비교가 skip되지 않게 했다.
- OMX의 3개 size-verdict 경로, Nav2의 folder→package 선언, CORE 종료 검사 역할 맵의 옛 경로를 정렬했다. budget·패키지명이나 검사 범위를 완화하지 않았다.
- 기존 logger 이름 `core.services`를 유지하자 event scanner가 이를 이벤트로 오인했다. 정확한 `logging.getLogger` 자리만 logger namespace로 분류하고 unknown notify wrapper는 제외되지 않는 회귀를 추가했다.
- 최초 설치 시험의 wheel 목록 평가 순서와 최초 확대 invocation의 이미 이동한 bridge 시험 경로를 바로잡고 재실행했다. 잘못된 실행과 RED 결과도 X 로그에 보존했고 known failure 목록에 넣지 않았다.

최종 lint 0 errors, 기존 freshness/uncommitted snapshot 경고는 별도다. source-only Safety 리뷰는 각 최초 이동/추출 커밋에 trailer로 기록했고 commit-range 검사도 통과했다. append-only skip 경고와 미해결 NEW는 남기지 않는다.

## 완료 범위와 남은 근거

M3–M6 소스 이전과 M7의 첫 Drive 조립 단위, 관련 원격 회귀와 Python 설치 검증을 완료했다. M7의 planning/tracking/recovery 알고리즘 추출, P1의 전체 producer 식별 통일, P2 곡률 개선, P3 복구 수명/budget 개선, M8 인지 정리, M9 세계 상태/행동 예측은 후속 작업이다. 빈 Arm/world 폴더나 새 실행 옵션을 만들지 않았다.

기존 모듈 gate의 과거 evidence는 이번 후보의 수용으로 확대하지 않는다. 새 Nav2/전체 workspace Jazzy colcon·실제 launch, ARM64 signed artifact, 설치 장치 readback/정지, 현장 수용과 원격 CI는 확인하지 않았다. main·배포·운용 writer 변경과 실물 명령은 수행하지 않았다.
