# Rosy World

Rosy World는 번들의 지도·사진·OMX 셀과 현장에서 연결한 관측을 표시한다. 기본 주소는 `http://127.0.0.1:8140/`이다. 아래 실행 방식 중 하나를 사용한다.

실행 기록이 포함돼 있으면 `http://127.0.0.1:8140/?view=run`으로 바로 재생한다. `--recording-map`으로 실행 당시 지도 사본을 함께 묶을 수 있다. 기록의 버전과 좌표계가 이 지도와 일치해야 한다.

## Pinky 시뮬레이션 조종

격리 `remote_sim.py cmd` 실행 안에서 `python3 tools/sim/world_play.py --world <생성한 Gazebo 월드 폴더> --web <빌드한 World 번들> --out <새 작업 폴더>`를 실행한다. 실행기가 Gazebo와 자체 시뮬레이션 CORE를 시작하고 `WORLD_PLAY_READY`를 기록한다. 기본 포트는 시뮬레이션 호스트의 로컬 `18141`이다. 등록된 시뮬레이션 호스트에 SSH 로컬 포워딩을 건 뒤 `http://127.0.0.1:18141/?view=play`를 연다.

**조종 시작**을 누르고 방향키나 화면 버튼을 누르는 동안 Pinky가 움직인다. CORE가 속도 명령을 판정한다. 키를 놓으면 World가 0 속도를 보내고, 연결이 끊기면 CORE의 기존 워치독이 정지시킨다. **C2로 초기화**는 이 실행이 소유한 Gazebo와 CORE를 다시 시작한다. 같은 실행 ID와 증가한 초기화 번호로 구분한다.

- **Windows 앱** — 번들 폴더에서 `powershell -NoProfile -ExecutionPolicy Bypass -File .\install-windows.ps1`을 실행한다. 현재 사용자 로그인 시 `Rosy World` 작업이 자동 시작된다. `Stop-ScheduledTask -TaskName 'Rosy World'`로 종료한다. 설치를 해제하려면 정지 후 `Unregister-ScheduledTask -TaskName 'Rosy World' -Confirm:$false`를 실행한다.
- **Docker 앱** — 번들 폴더에서 `docker compose up -d --wait`를 실행한다. `docker compose down`으로 종료한다. Linux에서 관측 파일 생산기의 UID/GID가 1000과 다르면 `ROSY_WORLD_UID`와 `ROSY_WORLD_GID`를 해당 값으로 지정한다.
- **터미널 실행** — 번들 폴더에서 다음 명령을 실행한다.

```text
python serve.py
```

`/healthz`는 웹 앱 준비 상태를 반환한다. Rosy Cam과 MuJoCo 등은 각 실행 환경에서 번들의 `data/`에 관측 파일을 쓴다. Docker의 웹 서버는 같은 폴더를 읽는다. 주소 뒤에 `?view=r08`을 붙이면 배치 자료가 있는 번들에서 R08 3D 지도를 바로 연다. 연결된 관측기가 없어도 번들의 지도·사진·셀을 열 수 있다. 기록이 포함된 번들은 기록도 재생한다.

## 현장 활성 지도

**지도 → 현장 활성 지도**에서 Fleet 위치와 차로, 지도 버전, 활성 시각, 브리지 수신 시각을 확인한다. **지도 위치**에서 ID를 선택하면 그 위치를 지도에서 강조한다. World 브리지는 Fleet의 활성 지도를 30초마다 확인한다. 지도는 로봇 연결 상태와 별도로 갱신한다. 마지막 지도 조회가 45초에 이르면 서버가 지도 미수신 상태를 반환한다. 화면은 보이는 동안 10초마다 갱신하며 유효 시간이 끝난 지도는 즉시 숨긴다. 브라우저 탭에 돌아오면 새 응답을 기다리는 동안 이전 지도를 숨긴다.

**보관 차로 그래프**, 기록 재생, CAD 설계 배치는 번들에 묶인 지도 자료를 사용한다. 실시간 공장 3D의 바닥과 장비 모델은 보관 자료를 바탕으로 한다. 현장 관측에서 S3 정차를 확인하려면 같은 지도 버전에 결속된 Fleet 정차 근거가 필요하다.

### World 활성 지도 HTTP 계약

- `GET /api/worlds/real-site/site-map`은 `{"site_map": <지도 스냅샷 또는 null>}`을 반환한다. 지도 스냅샷을 담은 응답에는 서버가 계산한 유효 시간 `fresh_for_ms`(양의 정수 밀리초)가 있다. 화면은 이 값에서 요청을 시작한 뒤의 경과 시간을 빼서 표시 만료를 계산한다. 응답은 캐시하지 않는다. 로컬 루프백과 Fleet 세션을 확인하는 현장 프록시에서 제공한다. LAN에 직접 공개한 독립 실행 서버는 활성 지도 읽기를 거절한다.
- `POST /api/worlds/real-site/site-map`은 브리지의 지도 스냅샷을 받는다. 상태 적재와 같은 권한을 적용한다. 지도 스냅샷 한도는 Fleet 지도 초안과 같은 2 MiB다. 현장 프록시에서는 읽기만 허용한다.
- 지도 스냅샷에는 양의 정수 `version`, Fleet 활성 응답의 64자리 16진수 `sha256`, 활성 시각 `activated_at`(UTC 초 또는 ISO 8601), World 브리지가 조회한 UTC 밀리초 정수 `observed_at_ms`, `map`이 있다. `map`은 `map_id`, `places`(각각 `id`, `x`, `y`), `edges`(각각 2개 이상의 XY 점으로 구성한 `polyline`)로 구성한다. 좌표는 Fleet 지도 프레임의 미터 단위다. `sha256`은 Fleet 원본 지도 본문의 해시다.
- `rosy.world.factory-state.v1`에서 브리지의 `stage`는 `observing`이고 `pinky.s3_in_bounds`는 정차 결속이 없으면 `null`이다. 실제 현장과 검증 번들의 지도 본문 해시가 모두 확인되면 `parity.map_match`로 두 본문을 대조한다. `parity.ok`는 검증 번들과의 비교다.

## 저장소에서 번들 만들기

저장소 루트에서 Python으로 빌드한다. `--inputs`에 `SHA256SUMS.txt`가 있는 읽기 전용 인계 폴더를 지정한다. `--out`에는 인계 폴더와 Git 체크아웃 밖의 새 경로를 지정한다.

```text
python applications/world/build_bundle.py --inputs D:/DevTemp/rosy-world-4080-handoff --out D:/DevTemp/rosy-world-bundle
```

빌더는 표준 라이브러리로 필수 입력 여섯 개의 해시를 대조한 뒤 번들을 만든다. `manifest.json`에 입력 경로와 해시가 기록된다. 다른 장비로 옮긴 뒤 번들 폴더에서 `sha256sum -c SHA256SUMS.txt`로 파일을 확인할 수 있다.

| 번들 경로 | 출처 |
|---|---|
| `index.html`, CSS, JavaScript | `applications/world/web/` |
| `common/` | `shared/web/`의 공용 셸과 Three.js 및 라이선스 |
| `data/site-map.json` | `site-map/world_261026_v7_active.json` 또는 `--site-map`으로 지정한 Fleet 응답 |
| `data/site-map.png` | `site-map/world_261026_v7_map.png` |
| `data/geometry.json` | `isaac/geometry-check.json` |
| `data/calibration.json` | `isaac/calibration/check.json` |
| `data/cell-render.png` | `isaac/isaac-overview.png` |
| `data/cell-photo.jpg` | `isaac/calibration/frames/top.jpg` |

Fleet의 `/api/fleet/site-map/active` 응답을 파일로 보존한 뒤, 빌드 명령에 `--site-map <파일>`을 추가하면 그 벡터 지도 보관본을 표시한다. 인계 자료 여섯 개는 그대로 검증한다. `manifest.json`의 `site_map_override`에 새 지도 파일의 해시가 기록된다. 보관 이미지 `data/site-map.png`는 기존 v7 이미지를 그대로 사용하며, 지정한 벡터 지도와의 정합은 별도로 확인한다.

2026-10-26 현장 CAD 보관본을 포함하려면 `--with-site-cad`를 추가한다. 빌더는 `site-map/261026_World.STL`을 인계 체크섬과 고정된 원본 해시로 검증하고, 압축본 `data/site-cad.stl.gz`를 만든다. CAD는 당시 배치를 보여 주는 별도 보기다. 현재 장치 위치나 현장 실측값과의 정합은 확인이 필요하다.

상태 기록을 확보했다면 빌드 명령에 `--recording <파일>`을 추가한다. `rosy.world.recording.v1` JSON에는 `source`, 시간대가 포함된 ISO 8601 `captured_at`, 양의 정수 `map_version`(예를 들어 `"map_version": 7`), `samples`가 필요하다. 각 샘플에는 순서대로 증가하는 음수가 아닌 정수 `offset_ms`, 같은 `frame_id`, `positions`가 필요하다. 각 위치에는 샘플 안에서 유일한 `id`와 유한한 미터 좌표 `x_m`, `y_m`을 넣는다. 화면은 기록의 `frame_id`와 `map_version`이 지도 ID 및 버전과 일치할 때 위치를 표시한다. 검증을 통과한 파일은 `data/recording.json`에 그대로 복사한다.

`build_bundle.py --birdview <촬영 폴더>/ceiling-plane.json`으로 **보관 버드뷰**를 갱신한다. 화면에 촬영 시각이 표시된다. 지정하지 않으면 체크섬이 맞는 2026-11-01 보관 사진을 사용한다. CAD 형상과 차선 윤곽은 STL을 사용하고 유도선, 안전 테이프, 재질 색은 2026-11-01 사진을 참조한다.

선택 입력 `equipment/site-equipment.json.gz`와 `equipment/cell-equipment.json.gz`를 체크섬에 포함하면 지도의 Pinky·C1–C3 충전소와 OMX 셀의 R08 CAD194 형상을 표시한다. 사이트 Pinky는 보관 사진에서 추정한 위치이며, 충전소는 v7 지도와 조립 CAD를 대조한 설계 배치다. R08 모델은 셀 좌표계에서 제공한다. 각 메시 입력은 미터 단위 삼각형과 재질색으로 이루어진 `rosy.world.meshes.v1` JSON의 gzip 압축본이다.

`지도 → 보관 CAD 3D → R08 설계 배치`를 선택하면 R08 모델을 보관 지도에 표시한다. 2026-10-26 STL과 R08 상판의 모서리 세 곳을 맞춘 뒤 네 번째 모서리와 벨트 방향을 대조했다. 배치를 끄면 보관 STL 보기로 돌아간다. 최신 현장 정합 상태는 미확인이다.

`tools/calibration/check_world_registration.py --bundle <번들 폴더> --points <기준점 JSON>`으로 지도 버전과 자료 해시가 같은 후보 배치를 계산한다. 기준점은 셀과 지도에서 각각 미터 단위 XYZ로 기록한다. 모델에 사용한 점과 검사용 점을 구분하고 오차 한계를 먼저 정한다. 보관 CAD 후보 결과를 `equipment/site-registration.json`으로 넣고 체크섬을 추가하면 설계 배치 버튼을 제공한다. 지도 입력을 교체한 번들에서는 설계 배치 버튼을 숨긴다.

## Pinky Gazebo 상태 보기

보관 CAD 보기에서 **Pinky SIM** 표식은 격리된 Gazebo에서 받은 자세와 방향을 표시한다. 관측 파일의 원본 CAD 해시와 프레임을 대조하며, 3초 넘게 이전 관측만 있으면 표식을 숨긴다. 지도에 구워 넣은 Pinky 두 대의 위치는 보관 사진 기준이다.

`observe_pinky.py --binding <실행별 결속 JSON> --out <번들 폴더>/data/pinky-sim.json`은 같은 호스트의 Gazebo ROS 2 도메인에서 실행한다. 결속은 실행 ID, 기체 ID, odom 토픽·프레임, CAD SHA-256, CAD 좌표로 변환할 XY 이동과 yaw를 지정한다. 주행 명령은 World에서 제공하지 않는다. 저장소의 `tools/sim/world_pinky_smoke.py`는 보관 261026 월드에서 **C2 → 칸 앞 P2**까지 제품 CORE의 Nav2 경로를 점검한다.

Gazebo 카메라를 함께 보려면 결속 JSON에 `"camera_topic": "/camera/preview/compressed"`를 넣고 관측기에 `--camera`를 추가한다. 같은 Gazebo 도메인에서 받은 JPEG를 같은 폴더의 `pinky-camera.jpg`에 쓴다. 카메라와 Pinky, Isaac 스위치는 브라우저의 관측 요청과 화면 표시를 제어한다.

## 현장 사진과 MuJoCo 보기

저장소에서 `python tools/capture/world_field_photo.py --site <Fleet HTTPS 주소> --raw --out <새 촬영 폴더>`를 실행한다. 받은 JPEG와 촬영 시각, 해시를 저장한다. `build_bundle.py`에 `--field-original <촬영 폴더>/ceiling-original.json`을 지정하면 **현장 사진**이 원본을 먼저 연다. `--raw` 없이 별도 폴더에 촬영한 `ceiling-plane.json`은 `--field-photo`에 지정한다. `--site-map`에는 확인한 활성 지도 JSON을 지정한다.

**카메라 원본**은 촬영 파일을 그대로 표시한다. **지도 보정 사진**과 **사진 평면 회전**은 지도 좌표에 맞춰 보정한 JPEG를 사용한다. 사진에 보이는 장비와 물체는 촬영 시점의 배치다. 높이와 가려진 면을 복원하려면 서로 다른 위치에서 촬영한 겹치는 원본 사진과 실측 기준이 필요하다.

전체 3D 재구성용 원본은 같은 렌즈로 현장 둘레를 두 높이에서 돌며 촬영한다. 위·옆·비스듬한 사진에 바닥 고정점과 실측 길이가 반복해서 보여야 한다. COLMAP으로 카메라 자세와 장면 점을 맞춘 뒤 질감 메시 또는 Gaussian Splat으로 화면을 만든다. 물리 시뮬레이션은 지도 고정점에 맞춘 간소화 충돌 메시를 사용한다. 현장 사진·보관 CAD·충돌 메시의 정합을 확인한 뒤에만 같은 위치로 등록한다.

실시간 원본 영상은 `world_field_photo.py --site <Fleet HTTPS 주소> --raw --live-jpeg <번들 폴더>/data/field-live.jpg`로 연결한다. **카메라 보기 → Rosy Cam 현장 상단**에서 확인한다.

## Isaac Sim 화면 보기

`http://127.0.0.1:8140/?view=isaac`으로 **Isaac Sim 실시간**을 연다. 이 화면은 Isaac에 붙인 카메라 이미지와 같은 실행의 시뮬레이션 시계·실행 ID를 표시한다. 새 프레임이 늦으면 마지막 화면과 지연 상태를 표시한다.

`tools/sim/run_isaac_world_preview.py --stage <호스트에 스테이징한 USD>`를 기존 격리 `remote_sim.py cmd`로 실행한다. 등록된 Isaac Sim SDK와 GPU 소유권을 확인한 뒤 180초 기본 실행을 시작한다. 콘솔에서 받은 실행 ID로 관제 PC에서 `python tools/sim/pull_isaac_world_preview.py --ssh-host <등록된 SSH 호스트> --run-id <sim-실행 ID> --bundle <실행 중인 번들 폴더>`를 실행한다. 필요한 경우 검증 장면의 벨트 동작은 런처에 `--belt-demo`를 지정한다.

MuJoCo와 Pillow가 설치된 저장소에서 `python applications/world/record_mujoco.py --preset v24-20261114-cad194 --out <번들 폴더>/data/mujoco-top.jpg`를 실행한다. **카메라 보기 → MuJoCo OMX 셀 상단**은 기존 CAD194 A/B 설계 배치와 두 팔의 미리보기 동작을 표시한다. 영상이 지연되면 마지막 프레임을 지연 상태와 함께 표시한다. 연결이 돌아오면 새 프레임으로 바꾼다.

### 학습 실험

운영 World의 **학습 실험**은 Fleet에 등록된 모델 PC Learning 주소의 `/learning/world`를 연다. 프로젝트 사용자는 실행 상태를 볼 수 있다. 시작과 중지는 관리 권한이 필요하다. 실행은 Learning Center가 소유하며 모델 PC의 설정된 CPU ACT 작업을 사용한다. 오프라인 ACT는 시뮬레이터에서 수집한 교사 데이터를 학습한다. 화면에는 스텝과 loss, 완료된 정책의 체크섬을 표시한다.

모델 PC의 신뢰된 OMX Center 설정에 `world_experiment`를 등록한다. `dataset_id`, `dataset_revision`, `scene_sha256`, `dataset_origin` (`mujoco`), `steps`, `batch_size`, `seed`를 지정한다. 데이터는 설정된 버전으로 발행된 `scripted_teacher`여야 한다. 사용자 정책에서 팔 구분이 필요하면 `arm_id`도 지정한다. 설정 전에는 새 실행 버튼을 사용할 수 없다.

MuJoCo로 S3 집기 정렬을 평가하려면 `python tools/sim/world_s3_pickup_train.py --out <새 실험 폴더>`를 실행한다. **학습 실험 → S3 평가 재생**에서 `evaluation.json`과 같은 실행의 `episode-*.json`을 선택한다. World에서 IK와 학습된 보정값을 동일한 평가 조건에 적용한 결과를 비교하고, 에피소드의 화물 자세와 관절 위치를 재생할 수 있다. 파일은 브라우저에서 읽는다. 장면 좌표는 팔 기준 실험용이며 최신 현장 지도에 등록하려면 실측이 필요하다.

## Isaac 시뮬레이션 상태 보기

보관 261026 트랙을 Isaac Sim에서 열려면 `python tools/sim/build_isaac_site_scene.py --bundle <보관 CAD 번들> --out <새 폴더>`로 두 USD 레이어를 만든다. 두 파일을 같은 디렉터리에 둔 채 `world_261026.usda`를 연다. 트랙·차선·충전 칸·레일·벽은 261026 Gazebo 월드의 자산을 공유한다. R08 CAD194는 상판 모서리로 정합한 시각용 레이어다. 정적 충돌체와 동적 제품 장면은 별도 검증한다.

검사한 R08 A/B 화물 위치 보정본을 `--dynamic-cell <보정본 USDC>`로 지정하면 `world_261026_ab_candidate.usda`도 생성한다. 이 장면은 R08의 기존 물리 장면과 팔 경로를 유지하고 트랙을 셀 좌표에 배치한다. 물리 시동을 검사하는 실험 파일이며 Pinky 주행·벨트 이송·팔 작업의 수용 기록은 별도다.

시뮬레이션과 같은 장비에서 ROS 2 Jazzy 환경을 불러온 뒤, 번들 폴더에서 관측기를 연다. `SIM_DOMAIN`은 해당 시뮬레이션 전용의 0보다 큰 ROS 도메인 번호로 바꾼다. 시뮬레이터도 같은 로컬 도메인에서 실행한다.

```text
python observe_isaac.py --bundle . --run-id RUN_ID --sim-domain-id SIM_DOMAIN
```

관측기는 로컬 Fast DDS에서 `/clock`, `/sim/joint_states`, `/sim/object_tf`를 구독한다. 각 토픽의 발행자 한 개와 같은 시뮬레이션 시각에 맞는 상태가 관측되면 `data/isaac-live.json`을 갱신한다. 브라우저 탭이 보일 때 이 파일을 확인한다. **OMX 셀 → Isaac SIM 상태**에서 실행 ID와 관측 수치를 연다. 기본 장면은 `conformance`다. 실제 A/B 시뮬레이션 발행자를 쓸 때는 `--scene ab --layout-sha256 LAYOUT_SHA256`에 확인한 배치 해시를 넣는다.

관측을 끝내려면 `Ctrl+C`를 누른다. 관측기는 마지막 JSON에 중지 상태를 기록한다. 배포 번들과 체크섬에는 관측 스크립트를 포함한다. 실행 시 생성되는 상태 JSON은 배포 묶음 밖의 데이터다.

## 보관 자료와 검증 범위

가상 작업 전 구간의 증거를 확인하려면 저장소에서 `python tools/sim/factory_flow_receipts.py <실행 폴더>/receipts.json`을 실행한다. C2 출차부터 A/B 적재까지 단계별 기록의 작업·기체·화물·지도 결속과 증거 파일 해시를 검사한다. 각 단계의 물리 판정은 Gazebo 또는 Isaac의 원본 실행 결과에서 확인한다.

S3 정차와 Cell 인수 기록을 확보하면 `python tools/sim/factory_isaac_handoff.py --receipts <실행 폴더>/prefix.json --site-map <실행에 사용한 지도 JSON> --out <실행 폴더>/isaac-intake.json`을 실행한다. 지도에 S3 정밀 정차 기준이 있어야 한다. 정차 관측과 인수 기록이 같은 시뮬레이션 작업에 속하고 해시와 시각이 일치하면 Isaac에 전달할 입력을 쓴다.

- 기본 벡터 지도와 이미지는 2026-10-31 활성 이력이 담긴 `world_261026` v7 보관본이다. 현재 Fleet 활성 지도와 지도 이미지·벡터 정합은 확인이 필요하다.
- 형상 검사는 시뮬레이션 프리셋 `v24-20261114-cad194`와 보관 USD의 시각 배치에 해당한다. 보정 판정은 `unverified`다. 번들은 Isaac 보관 렌더와 당시 실물 사진을 함께 제공한다.
- RTX 4080 장비에서 오프라인 지도·셀·실제 기록을 확인하고, Fleet 활성 지도와 실측 기준점 및 현장 상태 기록을 확보하는 작업이 남아 있다. 보관 USD는 정적 배치다. RTX 4080의 실제 A/B 시뮬레이션과 현장 장치 연결은 별도로 검증한다.
