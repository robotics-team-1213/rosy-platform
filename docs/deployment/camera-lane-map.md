# 카메라 차선으로 Fleet 지도 초안 만들기

`rosy-lane-map`은 실제 카메라 영상의 흰 차선 경계 사이에서 중심선과 교차점을 추출한다.
CAD 없이 실행하며 Fleet의 `rosy.site_map/1` 초안 JSON을 만든다. 설치 후 명령을 쓰거나
Vision 패키지 환경에서 `python -m rosy_vision.lane_map`을 실행한다.

## 입력 준비

- 원본 JPEG/PNG. Vision 직접 프레임도 가능하다. 화면 보정 미리보기는 입력으로 쓰지 않는다.
- 현재 카메라·렌즈·원본 크기에 맞는 확인된 미터 좌표 보정 JSON:
  `image_size: [width, height]`, `image_to_map: [[...], [...], [...]]`.
  선택 `bounds_m: {min_x, max_x, min_y, max_y}`로 측정된 작업 영역을 제한한다.
  선택 `white_value_min`(80–255 정수, 기본 180)은 넓은 흰 테두리 검출의 밝기 기준이다.
  선택 `road_seed_m: [x, y]`에 실제 도로 위 미터 좌표를 지정하면 그 점과 연결된 관측 도로만
  추출한다. 도로 밖 흰 무늬가 있는 현장에서 사용한다. 가림으로 끊긴 구간은 자동 연결하지 않는다.
- 측정한 차로 폭(m). 현재 트랙 예시는 0.185 m이며 다른 현장은 직접 측정한다.

승인된 Fleet 카메라 기록을 쓰려면 `image.width/height`를 `image_size`로 옮기고,
`map_to_image` 9개 값을 3×3으로 만들어 역행렬을 `image_to_map`에 쓴다.
`track_bounds_m`은 `bounds_m`으로 옮긴다. 기록의 렌즈·크기·카메라 설치가 현재와 같아야 한다.
저장된 보정의 display-only 상태나 현장 수용 수준이 이 변환으로 올라가지는 않는다.

## 생성과 검토

Fleet 현장 지도에서 카메라를 선택하고 `직사각형 평면 영상 불러오기`를 누른다.
같은 지도 ID의 등록된 표시용 보정이 있어야 한다. `평면 지도 좌표 확인`을 켜고 영상 위를
누르면 미터 좌표를 표시한다. 초안에서도 확인할 수 있으며 운행 목적지로 전달하지 않는다.
영상은 불러온 시점의 스냅샷이다. 다시 불러오기로 갱신하며 지도 보정·현장 수용은 별도다.

Windows에서는 관리 도구로 생성한 X: 세션의 evidence 폴더를 쓴다.

```powershell
rosy-lane-map --image "$env:DEV_SESSION/evidence/camera.jpg" `
  --calibration "$env:DEV_SESSION/evidence/calibration.json" `
  --lane-width-m 0.185 --map-id camera-observed `
  --output "$env:DEV_SESSION/evidence/camera-draft.json"
```

직접 최신 카메라를 읽을 때는 `--image` 대신 `--frame-url <HTTPS 원본 frame URL>`과
`--ca <site-ca.crt>`를 쓴다. 기존 preview lease는 `ROSY_VISION_LEASE` 환경 변수로 공급한다
(`--token-env`로 이름 변경 가능). 인증서·source-scoped lease 검사는 유지하고 redirect를 거절한다.
프레임 나이와 원본 여부가 확인되지 않으면 생성하지 않는다.

출력은 `camera-draft.json`과 `camera-draft.evidence.json`이다. 기존 출력은 덮어쓰지 않는다.
근거 파일에 프레임 해시와 보정이 남는다. 토큰과 URL은 남지 않는다.

1. Fleet `/console/site-map`에서 운영자로 접속한다.
2. **카메라에서 생성한 지도 초안** 파일을 고른 뒤 **카메라 지도 초안 가져오기**를 누른다.
3. 차로 중심선, 교차 연결, 가림으로 끊긴 곳, 도로 밖 무늬, 주소와 통행 방향을 검토한다.
   기존 초안이 있으면 교체 확인을 받는다. 서버가 잘못된 스키마와 stale revision을 거절한다.
4. 필요하면 기존 편집 기능으로 이름·방향·속도를 고친 뒤 저장한다.
5. 검토를 끝낸 뒤 별도 **초안 활성화**로 활성 지도 버전을 바꾼다.

흰 경계·단일 차로 폭이 첫 버전의 적용 범위다. 가림을 임의로 메우지 않으므로 지도는 부분적으로
끊길 수 있다. 차선 그래프는 Nav2 점유지도나 장애물 지도가 아니며 생성·가져오기는 로봇을 움직이지 않는다.

## 모델 PC에서 생성

모델 PC는 생성 작업을 맡고 관제 PC는 카메라 수신과 Fleet 초안 검토를 맡는다.
기존 D-446 실행기로 같은 알고리즘을 실행하며 GPU 환경이나 학습 모델을 바꾸지 않는다.
확장된 고정 controller를 후보 밖에 먼저 설치하고, 모델 코드 전용 키로 서명한 후보를
공급한다. 사이트 후보 서명 키를 모델 코드 키로 재사용하지 않는다.
자세한 절차는 [모델 코드 업데이트](../../deploy/site/model-code-update.md)를 따른다.

```bash
python3 -I "$HOME/.local/lib/rosy-model-code/rosy_model_code.py" \
  --config "$HOME/.config/rosy/model-code.json" exec camera_lane_map.py \
  --image /outside/candidate/camera.jpg --calibration /outside/candidate/calibration.json \
  --lane-width-m 0.185 --map-id camera-observed --output /outside/candidate/camera-draft.json
```

원본·보정·출력은 후보 밖에 둔다. 직접 HTTPS 입력도 같은 CA·lease·나이 검사를 사용한다.
생성 JSON을 Fleet 지도 화면에서 가져와 검토한다. 모델 PC가 꺼져 있거나 작업 중이면
그 PC의 설치·실행을 완료했다고 기록하지 않는다. 관제의 CLI 경로도 유지한다.
