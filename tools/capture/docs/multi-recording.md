# 여러 카메라·로봇을 함께 녹화

`multi_record.py`는 현장의 Fleet가 설치된 **관제 PC에서 실행하고 저장한다**. 작업 노트북은 배포·확인만 하며 운영 녹화의 저장 주체가 아니다. 설정·원본·위치·분석 DB·MP4를 모두 같은 관제 PC의 세션 폴더에 둔다. 선택한 Rosy Cam 소스와 로봇 전방 카메라를 함께 녹화한다. 소스 수에 따라 화면 칸을 늘린다. 많은 소스는 화면을 세로로 늘려 스크롤하고 합성 영상도 같은 높이로 만든다. 기존 Fleet 영상 중계 금지 계약을 유지하며 관제 PC가 각 로봇 CORE에서 직접 영상을 받는다.

## 실행

CA와 Viewer 토큰은 기존 등록 절차에서 준비한다. 설정은 공개 저장소 밖에 둔다. `token_file`·`ca_file`은 절대 경로를 권장한다. URL은 인증서의 호스트 이름을 쓴다. 이름 해석이 안 되는 PC에서는 `connect_host`에 IP를 별도로 넣는다. 인증서는 URL의 이름으로 계속 검증한다.

```json
{
  "site": {
    "url": "https://<site-host>:8443",
    "ca_file": "<site-ca.pem>",
    "token_file": "<site-viewer.token>"
  },
  "sources": [
    {"id": "overhead_north", "kind": "site", "source_id": "<approved-camera-source>"},
    {"id": "front_a", "kind": "robot", "robot_id": "<enrolled-robot-id>",
     "url": "https://<robot-host>:8080", "ca_file": "<robot-ca.pem>",
     "token_file": "<robot-viewer.token>"},
    {"id": "front_b", "kind": "robot", "robot_id": "<another-enrolled-robot-id>",
     "url": "https://<another-robot-host>:8080", "ca_file": "<another-ca.pem>",
     "token_file": "<another-viewer.token>"}
  ]
}
```

다른 카메라나 로봇은 `sources`에 행을 추가한다. `id`는 표시 이름과 저장 폴더에 쓰는 영숫자·`_`·`-`로 된 고유한 이름이다. `robot_id`는 기존 등록 ID를 쓰고 해당 로봇의 인증서·토큰과 연결한다. 로봇만 녹화할 때도 `site`를 지정하면 Fleet가 확인한 위치를 함께 저장할 수 있다. 저장된 이름은 설정에 따른 이름이며 미확인 검출의 신원을 이 도구가 추측하지 않는다.

```bash
# Ubuntu 관제 PC에서 실행한다. 각 실행에 새 세션 이름을 쓴다.
python3 tools/capture/multi_record.py record --config "$HOME/.local/share/rosy/capture/config/sources.json" --out "$HOME/.local/share/rosy/capture/sessions/<new-session>" --duration 60
python3 tools/capture/multi_record.py render --session "$HOME/.local/share/rosy/capture/sessions/<session>" --out "$HOME/.local/share/rosy/capture/sessions/<session>/combined.mp4"
```

시작하면 관제 PC의 `127.0.0.1` 화면을 연다. 브라우저 창 열기가 오래 걸려도 수집은 별도로 진행한다. 지정 시간 또는 Ctrl+C로 종료한다. 다른 PC에 HTTP 화면을 공개하지 않는다. 종료한 세션은 MP4로 재생·공유한다. `--no-open`은 화면을 열지 않는다. 기존 세션 폴더와 MP4는 덮어쓰지 않는다.

## 저장과 분석

- 소스별 `frames/`: API에서 받은 원본 JPEG.
- `capture.sqlite3`: `frames`(원본·수신 시각, sequence, SHA256, 파일), `positions`(Fleet tracking 시각·위치), `events`(시작·종료·소스 끊김).
- `session.json`: 토큰·URL을 포함하지 않는 세션 요약.
- 사이트 카메라의 `calibration.json`: 시작 시점의 승인된 보정 레코드.
- 합성 MP4와 `.mp4.json`: 프레임 수·시간 범위·합성 방법·SHA256.

이 DB는 **PC 분석용 DB**다. Fleet의 `core_event_audit`에 합성 세션을 추가하는 구현은 아니다. 로봇 네이티브 녹화는 기존 도구로 별도 실행하며 CORE 녹화 이벤트는 Fleet가 기존 방식으로 저장한다. 이 도구는 주행·녹화·E-Stop 변경 API를 호출하지 않는다. 사이트 preview lease만 요청하며 로봇 API는 GET만 사용한다.

## 영상과 위치의 의미

로봇 preview는 API 계약의 최대 2 FPS이며 네이티브 MCAP의 고속 영상을 대체하지 않는다. raw가 없으면 영상 없음으로 표시하며 주석 영상을 원본으로 대체하지 않는다. ROS/source clock과 수신 시각을 함께 보존한다. UTC와 대응하지 않는 로봇 시각은 합성에 수신 시각을 쓰고 `receipt`로 표시하므로 엄밀한 동기화 증거가 아니다. 2초를 넘긴 프레임은 합성에서도 빈 칸으로 만들고, 위치가 오래되면 미확인으로 표시한다. `NO_POSE`와 미할당 검출을 로봇 지도 위치로 추측하지 않는다. 보정 레코드·등록·안전 상태는 변경하지 않는다.

한 소스의 끊김은 다른 소스의 기록을 멈추지 않는다. 저장 디스크에 필요한 공간을 확보한다. 합성에는 기존 Pillow와 `ffmpeg`가 필요하며 원본 해시가 다르면 실패한다. 세션에는 현장 영상·위치가 포함되므로 공유 범위를 확인한다.
