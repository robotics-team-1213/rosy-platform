# ROSY Calibration

셀의 보정을 한 곳에서 보고 돌리는 앱이다([D-951](../../docs/adr/D-951-rosy-calibration-application.md)). 첫 화면은 실측 요청이다(아래 「화면」). 이 문서는 앱의 경계와 보정 순서의 정본이다.

## 경계

- 화면: 이 폴더(`applications/calibration/`). 엔진의 결과 파일과 API를 읽고, 보정 실행을 요청한다.
- 엔진: 셀 도구 `deploy/robot/omx/cell_*`. 실제 측정, 판정, 결과 파일은 여기에 있다.
- 에이전트 절차: `.claude/skills/rosy-calibration/SKILL.md`.
- 팔이 움직이는 단계는 [D-911](../../docs/adr/D-911-omx-native-reviewed-operating-envelope.md) 감독 시험이다. 사람이 스위치 옆에 있는지를 동작마다 확인한다. 현장은 착지한 main만 돌린다([D-932](../../docs/adr/D-932-field-runs-one-landed-revision.md)).

## 보정 순서

| 단계 | 엔진 | 결과 | 팔 동작 |
|---|---|---|---|
| 1. 장치 | `omx_devices.py scan`, `omx_cameras.py inventory` | 역할별 장치, 문제 0 | 없음 |
| 2. 높이 | `cell_depth.py` | 테이블 평면, 깊이↔색 정렬, 각 팔 판(FK 0), 면 높이 | 없음 |
| 3. 카메라 모델 | `cell_frame.py learn` / `check`([D-933](../../docs/adr/D-933-arm-s-cell-coordinate-frame-markers.md) 마커) | 카메라 자세, 마커 위치 | 집게 마커를 FK 점에 보인다(감독) |
| 4. 면 | `cell_depth` 결과 → 각 팔 설정의 `surface_z` | 면별 높이(FK) | 없음 |
| 5. 관절 게인 | 세션 설정 `caps.json`의 `i` | 하중 관절 I 게인 | 정지 시험(감독) |
| 6. 점검 | `cell_calibrate.py check` | 남은 할 일 없음 | 없음 |

- 사람이 정하는 것: 인쇄물 부착(D-933), 바닥을 낮출 사각형의 승인(`limits.low_zones`), 동작마다 스위치 확인.
- 숫자를 손으로 고치지 않는다. 다시 재야 하면 그 단계를 다시 돌린다.

## ChArUco 렌즈 보정

Fleet의 `rosy-charuco-7x10-20mm.pdf`를 100% 크기로 인쇄한 판을 사용한다. 7×10칸, 칸 20 mm, 마커 15 mm, `DICT_4X4_50`이며 인쇄된 50 mm 막대를 자로 재서 실제 길이를 기록한다. 사람이 카메라 앞에서 판을 여러 위치와 20~40도 각도로 보여 주는 동안 다음 명령은 RGB 프레임만 읽고 팔 명령은 보내지 않는다.

촬영 예: 카메라 화면을 3×3으로 생각하고 보드 무늬의 중심을 왼쪽 위→가운데 위→오른쪽 위→왼쪽 가운데→정중앙→오른쪽 가운데→왼쪽 아래→가운데 아래→오른쪽 아래로 천천히 옮긴다. 각 자리에서 1초쯤 멈추고 중앙에서는 보드를 좌우·앞뒤로 20~40도 기울인다. 무늬가 화면 좌우·상하 가장자리 근처에도 들어와야 한다. 판은 팔이 정지한 동안만 들고, 팔을 움직이기 전 손과 판을 작업 구역 밖으로 뺀다. 2026-11-13 현장 측면 56장은 좌우 범위만 채우고 무늬가 화면 아래 절반에 닿지 않아 거절됐으며, 위쪽 60장은 거의 같은 위치여서 거절됐다.

```sh
python3 deploy/robot/omx/cell_checkerboard.py intrinsics \
  --config <cell-config.json> --camera top --out <top-intrinsics.json> \
  --scale-bar-mm <measured-50mm-bar> --frames 30 --timeout-s 180
```

측면 렌즈는 같은 명령에서 `--camera side --out <side-intrinsics.json>`으로 별도 촬영한다. `cell-pipeline.example.json`의 `side` 역할은 현장 `/frame/side.jpg`를 가리킨다. 각 카메라의 수용 결과와 원본 프레임을 따로 보존한다. 이 단계의 측면 내부값은 측면 카메라의 팔 좌표 자세나 적층 높이를 증명하지 않는다.

원본 JPEG와 카메라 시퀀스·시각·해시는 `<top-intrinsics>-frames/`에 남는다. 이 폴더의 JPEG와 같은 이름의 출처 영수증 JSON을 함께 보존한 경우에만 `intrinsics-from-frames <frames-dir> --camera top --scale-bar-mm <mm> --out <intrinsics.json>`으로 다시 계산한다. 영수증이 없거나 카메라 역할·해시·프레임 순서가 맞지 않으면 수용하지 않는다. 25장 미만의 유효한 서로 다른 영상, 화면 위치·기울기 부족, 재투영 RMS 0.5 px 초과, 인쇄 막대 오차가 있으면 `accepted: false`와 실패 이유를 기록하고 종료 코드 1을 반환한다. 촬영 폴더가 있으면 덮어쓰지 않고 새 출력 이름을 사용한다.

`accepted: true`는 해당 카메라 해상도의 **렌즈 내부값·왜곡**만 확인한다. 팔 좌표 자세는 베이스·그리퍼 마커와 감독하 FK 관측으로 `cell_frame.py learn`을 별도로 실행하고, 이후 `check`와 현장 위치 오차로 수용한다. 현재 보이는 OMX 받침판 CAD 치수는 확인점 후보지만 현장 설치 자세와 영상 특징점 대응이 검증되기 전에는 팔 좌표의 참값으로 쓰지 않는다. 해상도·초점·카메라 장착이 바뀌면 관련 보정을 다시 확인한다.

## 측면 적층 Z 기준 설치와 수용

적층 높이를 측면 영상에서 판정하려면 **움직이지 않는 기준물**이 매 프레임 보여야 한다. 측면 카메라가 보는 고정 패널에 서로 다른 ID의 fiducial 두 개를 수직으로 떨어뜨려 부착한다. 설치 전 팔·집게·컨테이너의 전체 계획 경로와 정지 여유를 현장에서 확인하고 기준물이 그 밖에 있도록 한다. 두 마커가 모든 적층 높이에서 가려지지 않아야 한다. 손으로 든 ChArUco 판, 컨테이너 태그, 받침판의 CAD 높이, 한 영상 에지에서 만든 여러 점은 이 고정 기준물을 대신하지 못한다.

1. 실제 테이블 또는 적재판의 Z 영점을 정하고, 각 마커의 네 모서리 위치와 중심 높이를 **그 영점에서 실측**한다. 마커 간 높이 차이와 기준 패널에서 적층 대상 평면까지의 깊이 오프셋도 실측하여 측정 방법·출처·오차를 기록한다. 예상 치수나 예시 숫자를 설정에 복사하지 않는다.
2. 위 절의 ChArUco 절차로 측면 카메라의 `accepted: true`인 K·왜곡값과 원본 프레임을 확보한다. 카메라 해상도·초점·장착 자세가 바뀌면 다시 측정한다. 측면 영상에서 두 고정 마커의 ID와 네 모서리를 **각각 독립 검출**하고, 실측 3D 모서리와 K·왜곡값으로 현재 프레임의 카메라 자세를 푼다. 재투영 오차, 두 마커 모두 보이는지, 저장된 설치 자세와의 차이를 검사한다.
3. 현재 자세에서 적층 대상 평면으로 광선을 투영해 해당 열·행의 픽셀 높이를 Z로 바꾼다. 패널의 픽셀/mm를 깊이가 다른 적층 평면에 그대로 쓰지 않는다. 별도로 실측한 높이 게이지를 적층 평면에 놓고 세 높이에서 Z 오차를 확인한다. 목표 허용 오차인 3 mm를 넘거나 마커·게이지·깊이 오프셋의 불확실성이 이를 보장하지 못하면 수용하지 않는다.
4. 같은 관측 시점의 위쪽 RGB·Z16 정렬, 판 높이, 측면 두 마커와 적층 높이를 함께 기록한다. 프레임 출처·시각이 불명확하거나 정렬이 실패하면 적층 판정은 `UNKNOWN`이다. 기준물이 가려지거나 움직였을 때도 `UNKNOWN`으로 되돌린다. 실제 1·2·3층 수용은 각 층의 놓기·손 뗌·안정화 후 새로 촬영한 영상과 높이 증거로 별도 판정한다.

현재 `cell_z_profile._current_frame_calibration_checks`는 독립적인 측면 Z 기준이 없어 `ok: false`를 유지한다. 위 측정과 현장 검증을 마치기 전에는 저장된 `measurement_calibrated` 값만으로 이 판정을 열지 않는다.

## 두 팔

- 세션 잠금은 팔마다다(`joint_tune.session_lock(arm)`, `record_session --arm`).
- 움직이기 전에 경로 점검(`cell_corridor`)과 통로 예약(`cell_space`)을 거친다.

## 실측 요청

사람만 확인할 수 있는 것(줄자 거리, 감독 시험으로 보는 자세)은 엔진 `deploy/robot/omx/cell_requests.py`가 요청으로 연다([D-951 덧붙임 2026-11-09](../../docs/adr/D-951-rosy-calibration-application.md)). 요청은 후보마다 예측값을 적고, 사람의 답은 어느 후보를 지지하는지만 정한다. 값을 직접 바꾸지 않는다.

```
python tools/sim/omx_real2sim.py request belt RUN       # 벨트 요청 (실물↔시뮬 루프의 RUN 폴더)
python3 deploy/robot/omx/cell_requests.py list
python3 deploy/robot/omx/cell_requests.py answer <id> --value <mm> --by <이름> [--note ...]
```

이 앱의 화면(아래)이 이 목록을 보여 주고 답을 받는다.

## 화면

실측 요청 화면이다([D-1004](../../docs/adr/D-1004-calibration-screen-and-operate-capability.md)). 서버는 `calibration_web.py`(stdlib, 127.0.0.1:8776), 페이지는 `web/`(번들러 없음). 저장소는 엔진 `cell_requests`가 유일한 작성자이고 화면은 `cell_requests.answer`만 부른다.

```
python3 applications/calibration/calibration_web.py --store ~/.local/state/rosy/cell-requests --account-config <receiver.json> --port 8776
```

- `--store` 기본은 `ROSY_CELL_REQUESTS`. `contracts/foundation`은 체크아웃에서 스스로 찾는다.
- `--profiles <json>`(또는 `ROSY_CALIBRATION_PROFILES`)을 주면 `모눈종이 · 프로파일` 탭이 열려 각 로봇(`arm_a`, `arm_b`, `arm_s` 등)의 호모그래피·LOO 잔차·`pivot-near` bias·시차 투영(`z_view`/`surface_z`)·실시간 TCP/hold 상태를 읽기 전용으로 점검할 수 있다(`GET /api/calibration/v1/profiles`, `.../profiles/<id>/frame/reference|live`). Account 설정이 있으면 이 경로도 로그인 세션이 있어야 열린다.
- 관제 PC의 시스템 python3에는 Account 토큰 검증에 쓰는 `joserfc`가 없다(2026-11-13 확인, 로그인 callback에서 서버가 죽었다). 유닛은 전용 venv로 돈다: `python3 -m venv --system-site-packages ~/.local/share/rosy/calibration/venv && ~/.local/share/rosy/calibration/venv/bin/pip install joserfc==1.7.5 cryptography==50.0.0` (pydantic은 시스템 것, `python3-venv` 필요).
- 읽기 전용 확인: `--account-config` 없이 띄우고 `ssh -L 8776:127.0.0.1:8776 <관제 PC>`로 연다. 이때는 로그인이 없어 답을 받지 않는다.
- Account 설정이 있으면 목록·상세·그림도 그 site의 로그인 세션이 있어야 보이고, 답은 site 권한 `calibration.operate`가 있어야 한다. 답의 누가는 세션의 이름이다.
- API: `GET /api/calibration/v1/requests`, `.../<id>`, `.../<id>/image`, `POST .../<id>/answer {value|result, note}`(같은 출처 필수; 409 이미 답함, 422 잘못된 값).

운영 단계(2026-11-09 상태):

1. HTTPS 앞단: 관제 PC `tailscale serve --bg --https=9449 http://127.0.0.1:8776`(tailnet 전용). 했다.
2. Account: client `rosy-calibration`(resource `site:<id>`, callback `https://<관제 PC tailnet 이름>:9449/api/account/callback`)을 R 호스트의 Account에 등록하고, receiver 설정을 관제 PC `~/.config/rosy/calibration/receiver.json`에 둔다(세션 키는 다시 만들지 않는다). 했다. 관제 PC는 Account에 SSH 터널(`rosy-account-tunnel.service`)로 닿는다. R의 443 방화벽은 손대지 않는다(점검이 실패하면 site proxy가 멈춘다).
3. 배포: 착지한 sha를 `tools/remote/omx_hotfix.py`로 관제 PC에 풀고(이 앱이 포함된다), 위 venv를 만든 뒤 사용자 유닛 `rosy-calibration-web.service`(이 폴더)를 `~/.config/systemd/user/`에 **복사**해 켠다. 링크하면 systemd가 버전 폴더(`omx-tools-<sha>`)로 풀어 다음 갱신 뒤 깨진다. 2026-11-13 배포함(그 전까지 미설치, issuer·`/etc/hosts`가 옛 이름이었다).
4. 권한: 모든 receiver를 새 `calibration.operate` 목록으로 먼저 배포한 뒤(옛 receiver는 모르는 capability의 토큰을 거절한다, D-990) 답할 사람에게 관리자가 부여한다. 그 전에는 로그인한 사람도 보기만 한다.

## 작업 API (D-1035)

`--cells <cells.json>`을 주면 켜지고(없으면 404), 구현은 `calibration_jobs.py`다. 앱은 셀 값을 쓰지 않고 엔진(`cell_calibrate.py`)을 팔 리스 아래에서 돌린다.

```
{"tools": "<omx tools 루트, 예 ~/rosy-test/omx-tools-current>", "python": "<엔진 python>", "work": "<작업 기록 폴더>",
 "arms": {"arm_b": {"config": "<셀 설정 json>", "session": "<with-session 래퍼 또는 빈 값>", "env": {}}}}
```

- `GET /api/calibration/status`: 팔별 리스, incident(읽기 전용 `omx_incident.py status`), 설치 리비전, 자리별 지도(점 수·LOO·지문)·면 높이·바이어스.
- `POST /api/calibration/jobs {arm, step, targets, person_at_switch}`: 단계는 `check`, `depth-verify`, `pivot-near`, `remap`만(그 밖은 422). 팔을 움직이는 `pivot-near`·`remap`은 `person_at_switch: true`가 없으면 422(D-911). 리스를 다른 주인이 쥐면 409. 202와 작업 기록; `GET /api/calibration/jobs`, `.../jobs/<id>`(로그 끝 4000자)로 본다.
- `POST /api/calibration/assessments {arm, verdict: clear|hold, reasons, evidence[{kind: frame|joints|torque, ref, sha256?}]}`: `<work>/assessments.jsonl`에 쌓는다.
- `POST /api/calibration/incidents/<arm>/clear`: 10분 안의 최신 판정이 `clear`이고, 다른 주인의 리스와 실행 중인 `record_session`이 없을 때만 `omx_incident.py clear`를 부른다(측정이 먼저, 모델 판정만으로는 해제하지 않는다).
- 쓰기 경로는 모두 같은 출처 + `calibration.operate` 세션이 필요하다.
