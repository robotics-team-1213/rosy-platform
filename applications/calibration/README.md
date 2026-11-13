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
- 관제 PC의 시스템 python3에는 Account 토큰 검증에 쓰는 `joserfc`가 없다(2026-11-13 확인, 로그인 callback에서 서버가 죽었다). 유닛은 전용 venv로 돈다: `python3 -m venv --system-site-packages ~/.local/share/rosy/calibration/venv && ~/.local/share/rosy/calibration/venv/bin/pip install joserfc==1.7.5 cryptography==50.0.0` (pydantic은 시스템 것, `python3-venv` 필요).
- 읽기 전용 확인: `--account-config` 없이 띄우고 `ssh -L 8776:127.0.0.1:8776 <관제 PC>`로 연다. 이때는 로그인이 없어 답을 받지 않는다.
- Account 설정이 있으면 목록·상세·그림도 그 site의 로그인 세션이 있어야 보이고, 답은 site 권한 `calibration.operate`가 있어야 한다. 답의 누가는 세션의 이름이다.
- API: `GET /api/calibration/v1/requests`, `.../<id>`, `.../<id>/image`, `POST .../<id>/answer {value|result, note}`(같은 출처 필수; 409 이미 답함, 422 잘못된 값).

운영 단계(2026-11-09 상태):

1. HTTPS 앞단: 관제 PC `tailscale serve --bg --https=9449 http://127.0.0.1:8776`(tailnet 전용). 했다.
2. Account: client `rosy-calibration`(resource `site:<id>`, callback `https://<관제 PC tailnet 이름>:9449/api/account/callback`)을 R 호스트의 Account에 등록하고, receiver 설정을 관제 PC `~/.config/rosy/calibration/receiver.json`에 둔다(세션 키는 다시 만들지 않는다). 했다. 관제 PC는 Account에 SSH 터널(`rosy-account-tunnel.service`)로 닿는다. R의 443 방화벽은 손대지 않는다(점검이 실패하면 site proxy가 멈춘다).
3. 배포: 착지한 sha를 `tools/remote/omx_hotfix.py`로 관제 PC에 풀고(이 앱이 포함된다), 위 venv를 만든 뒤 사용자 유닛 `rosy-calibration-web.service`(이 폴더)를 `~/.config/systemd/user/`에 **복사**해 켠다. 링크하면 systemd가 버전 폴더(`omx-tools-<sha>`)로 풀어 다음 갱신 뒤 깨진다. 2026-11-13 배포함(그 전까지 미설치, issuer·`/etc/hosts`가 옛 이름이었다).
4. 권한: 모든 receiver를 새 `calibration.operate` 목록으로 먼저 배포한 뒤(옛 receiver는 모르는 capability의 토큰을 거절한다, D-990) 답할 사람에게 관리자가 부여한다. 그 전에는 로그인한 사람도 보기만 한다.
