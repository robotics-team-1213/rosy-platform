# 6대 로봇 WebRTC 카메라 전환 실행 계획

> 구현자는 이 문서와 D-789를 읽고 `superpowers:executing-plans`로 순서대로 실행한다. 아래 체크박스는 아직 실행하지 않았다. ADR·계획 작성 요청에 따른 문서이며 코드·장치 설치 완료 기록이 아니다.

**Goal:** 6대 로봇의 카메라를 한 번씩 H.264 WebRTC로 송출하고 별도 사이트 영상 서비스가 인증된 브라우저에 분배한다.

**Architecture:** 기존 카메라 단일 생산자 → 로봇 native GStreamer 미디어 프로세스 → WHIP → 사이트 MediaMTX → WHEP → Pilot/사이트 화면. 별도 media 권한 서비스가 CORE 위임을 검증하고 MediaMTX 세션을 회수한다. Fleet은 영상 경로에 참여하지 않는다.

**Tech Stack:** ROS 2 Jazzy 로봇 내부 프레임, GStreamer `webrtcbin`·H.264 software encoder, MediaMTX, HTTPS WHIP/WHEP, 브라우저 RTCPeerConnection. 정확한 의존성 버전·digest는 T1의 Ubuntu 24.04 ARM64 검증 결과로 잠근다.

**Spec:** [D-789](../adr/D-789-six-robot-webrtc-camera-transport.md). 2026-10-17 사용자가 WebRTC 전환을 결정하고 ADR·계획 작성을 요청했다.

## 공통 제약과 완료 기준

- 모든 제품 변경은 전용 non-main 워크트리에서 한다. 이 문서의 브랜치는 `docs/webrtc-camera-migration`이다. 착지·푸시는 별도 사용자 지시를 따른다.
- 첫 구현부터 로봇 native 미디어 서비스와 사이트 영상 서비스를 분리한다. CORE/Fleet의 Python 프로세스에 encoder·MediaMTX를 넣지 않는다.
- 640×480·15fps, H.264 baseline/B-frame 0/GOP ≤1초, 대당 목표 0.8Mbps/상한 1Mbps, wire 합산 지속 10초 창 ≤8Mbps는 D-789의 수용 프로파일이다. UI 축소는 uplink 절감으로 계산하지 않는다.
- 기존 원본 카메라를 재개방하거나 인식·주행 입력 해상도·주기를 변경하지 않는다. 최대 2fps인 기존 preview 토픽을 고속 영상 입력으로 재사용하지 않는다.
- 권한·API의 최종 정의는 T2에서 API reference와 schema를 같은 커밋으로 갱신한다. 아래 함수·모듈 이름은 신규 내부 구현 제안이며 현재 존재하는 계약이라고 주장하지 않는다.
- 노트북 pytest·Gazebo는 금지다. 각 테스트 변경을 먼저 커밋하고 원격 runner에서 RED를 확인한 뒤 구현을 커밋하여 GREEN을 확인한다. 실행마다 `known_failures.py` 비교로 NEW 0을 확인한다.
- SOURCE 테스트와 ARM64 산출물, 실제 카메라/단말, 6대 FIELD 증거를 구분한다. 합성 6스트림은 실물 6로봇 수용이 아니다.

## 리뷰에서 빠뜨리지 않을 고장 조건

1. 연결 당시 권한이 유효해도 로그아웃·철회·CORE 단절 뒤 영상이 계속 재생되는 경우: T2/T4.
2. 태블릿 Android 프록시가 시그널링 origin·인증 헤더를 바꿔 ICE만 실패하는 경우: T4.
3. 미디어 서비스가 카메라를 두 번째로 열거나 죽은 뒤 다시 열지 못하는 경우: T3/T5.
4. 한 수신자가 느려 다른 뷰어·로봇 uplink에 프레임이 쌓이는 경우: T3/T6.
5. 6대 동시 연결 실패가 MJPEG 폴백 폭증으로 이어지는 경우: T4/T6.

## T1 — ARM64 의존성·전송 경로 검증 및 고정

T1은 캡처 time/sequence/producer epoch의 작은 기계 판독 watermark를 인코딩 전 영상 모서리에 넣고 실제 브라우저 렌더 영역에서 읽는 경로도 입증한다. H.264 bitrate 하한·손실·정지 프레임 반복·재시작·재접속에서 identity가 일치해야 한다. 판독 실패는 신선도 불명이며 별도 heartbeat만으로 fresh로 바꾸지 않는다. 장치 간 시계 동기 오차를 측정하고 capture→render 측정 오차를 결과에 붙인다. 이 전달 경로가 입증되지 않으면 후속 통합의 신선도 완료 판정을 막는다.

**대상:** `deploy/site/compose.media.yaml`(신규), `deploy/site/mediamtx.yaml`(신규), `deploy/image/`의 현행 의존성 잠금·payload 목록, `test/test_webrtc_artifact_contracts.py`(신규). 기존 `deploy/site/compose.yaml`과 image 설치 스크립트를 먼저 읽는다.

- [ ] ARM64에서 H.264 encoder·`webrtcbin`·ICE 플러그인과 HTTPS WHIP 송출을 재현하는 최소 통합 시험을 작성하고 실패 증거를 남긴다. 의존성 부재와 코덱 불일치를 구분한다.
- [ ] MediaMTX 버전/image digest와 GStreamer 패키지·플러그인 버전, SBOM·라이선스를 잠근다. Ubuntu 기본 패키지에 없는 rswebrtc 기능을 있다고 가정하지 않는다. `webrtcbin`용 WHIP HTTP adapter를 사용하며 SDP offer/answer, ICE 완료, Location·DELETE를 검증한다.
- [ ] 합성 입력→WHIP→WHEP→대상 Chromium/Android에서 640×480·15fps H.264 영상을 확인한다. MediaMTX의 무재인코딩과 한 publisher/다중 reader를 확인한다. 의존성 검증용 환경은 원격 시험 PC에 둔다.
- [ ] 완료: pin된 ARM64 artifact와 한 스트림 재생 증거. 실패하면 T2 이후 통합을 막고 정확한 누락 패키지·기능을 기록한다.

## T2 — CORE 위임과 미디어 세션 권한 계약

활성 session lease는 최대 60초, 20초마다 원본 권한을 재인가하여 같은 MediaMTX session ID로 갱신한다. 입장 bearer 만료와 갱신된 session lease 만료를 혼동하지 않는다. WHIP와 WHEP 모두 30분 연속 재생과 두 번 이상의 lease 갱신을 시험하며 갱신 중 공백도 fps·지연 계산에 넣는다. 재검사는 1초, kick 완료는 철회/CORE 단절 뒤 5초 이내다. 별도 supervisor가 권한 서비스 heartbeat 3초 부재 시 MediaMTX를 종료하고, supervisor 사망 시 자식 프로세스/cgroup도 종료한다. 실제 영상 종료를 시험하여 단순 HTTP 거절을 종료 증거로 삼지 않는다.

인증된 viewer intent → 10초 demand lease → publisher ready → WHEP 연결 순서를 사용한다. WHEP ready 시 최대 60초 활성 demand lease로 전환하여 20초마다 갱신한다. controller→publisher heartbeat는 최대 1초 간격이며 5초 stale 시 발행을 중단한다. 첫 구독, 시작 중 취소, 마지막 구독 종료와 lease 만료를 각각 시험한다. demand/budget controller가 로봇별 영상+JPEG+벌크 예산을 함께 집행하고, 폴백 요청도 여유가 없으면 지연한다.

**대상:** `middleware/core/services/core_features/preview/media_grants.py`(신규), `middleware/core/api/core_api_web/api/v1/vision.py`, `contracts/`의 현행 API schema 소유 경로, `operations/site_ui/media/`(신규 별도 권한 서비스), API reference, `tools/harness/platform_parts.yaml`.

**내부 인터페이스:** `MediaGrantService.issue(token_id: str, robot_id: str, action: str, now: float) -> MediaGrant`; `revoke(session_id: str) -> None`. `MediaGrant`는 path·robot·read/publish action·audience·expiry·session ID를 포함한다. 세부 HTTP 경로/필드는 기존 인증 흐름을 읽은 뒤 API 버전을 도구로 선점하여 schema와 함께 확정한다. read는 CORE viewer 이상, publish는 해당 로봇의 전용 source 자격만 허용한다.

- [ ] RED: 잘못된 robot/path/action/audience, 만료, 무인증, viewer의 publish, 다른 사이트 위임, 인증 서비스 불가를 거절하는 계약 시험을 추가한다.
- [ ] CORE는 영상용 좁은 위임만 발행한다. 별도 media 권한 서비스가 서명·원본 권한 상태를 검증하고 MediaMTX HTTP auth와 세션 registry를 연결한다. CORE 장기 토큰·자격을 URL·일반 로그·MediaMTX로 전달하지 않는다.
- [ ] 입장 credential TTL ≤60초와 갱신 가능한 활성 lease를 구현한다. 최대 1초 간격의 원본 권한 재검사, 철회·CORE 단절·활성 lease 만료 후 5초 이내 실제 세션 종료를 검증한다. MediaMTX 연결 승인만 확인하지 말고 실제 재생 종료를 확인한다. 권한 서비스 restart 시 세션 registry 유실을 복구하고 이전 세션을 재검증 또는 종료한다.
- [ ] publish 중복 접속은 기존 producer를 임의 교체하지 않고 거절한다. 로봇 ID를 서비스가 발행 경로로 변환하며 요청자가 임의 URL을 지정하지 못하게 한다.
- [ ] 완료: API/schema/버전 일치, 권한·철회·비밀 로그 검사 GREEN, Fleet 비중계 시험 유지. 미디어는 명령 권한을 갖지 않는다.

## T3 — 로봇 프레임 분기·H.264·WHIP 발행

sender의 WHIP RTCP/queue 통계만 uplink encoder의 직접 혼잡 입력이다. WHEP feedback의 자동 전달은 가정하지 않는다. 별도 사이트 controller가 reader별 큐 지연을 조사하고 500ms 초과가 2초 지속되면 해당 reader만 종료한다. 느린 reader 1개와 정상 reader 1개를 동시에 연결하여 정상 reader의 render fps·지연과 로봇 단일 uplink를 유지하는 시험을 추가한다. 합산 8Mbps는 로봇↔사이트 영상·벌크 wire 경계이며 사이트 유선 egress는 별도 계측한다. 무선 viewer가 같은 AP를 사용하면 추가 airtime과 제어 영향도 함께 수용한다.

**대상:** `middleware/perception/front_camera/perception/media/`(신규: `source.py`, `pipeline.py`, `whip.py`, `policy.py`), 현행 camera producer wiring, `middleware/perception/test/test_media_source.py`, `test_media_policy.py`, `test_media_whip.py`(신규). producer 연결 위치는 `nodes/camera_detect_node.py`, `nodes/road_observer_node.py`와 설치 launch를 추적해 실제 단일 소유자를 선택한다.

**내부 인터페이스:** `LatestFrameSource.offer(frame: MediaFrame) -> None`, `take_latest() -> MediaFrame | None`; `MediaPublisher.start(config: MediaConfig) -> None`, `stop() -> None`, `stats() -> MediaStats`. 프로세스 간 프레임은 bounded shared memory + 작은 시퀀스 통지로 전달한다. 소유권·수명·stride·색상 변환은 source adapter 한 곳에서 처리한다. 복사/인코딩은 perception callback 밖에서 한다.

- [ ] RED: 100장 입력 뒤 한 장 최신값만 남음, producer restart/sequence reset, 잘못된 stride·색상·시각, 소비자 죽음에서 생산자 비차단, 원본 장치 1회 개방을 시험한다.
- [ ] 기존 원본 생산자가 640×480을 제공하는지 확인한다. 제공하지 않으면 기존 카메라의 독립 출력/원본 분기를 먼저 마련하고 인식 입력 회귀를 검증한다. 320×240 이미지를 확대하여 640×480 수용을 주장하지 않는다.
- [ ] H.264 baseline·B-frame 0·GOP ≤1초, `appsrc` bounded 입력과 200ms 출력 큐 상한을 구현한다. 초과 시 파이프라인을 복구하여 IDR로 재개하고 프레임 누적을 금지한다.
- [ ] WHIP 시그널링·인증 갱신·5초 상한 reconnect backoff+jitter·종료 DELETE를 구현한다. 활성 구독 없음 상태의 발행 중단과 새 구독 재개는 media 권한 서비스의 인증된 demand를 통해 전달한다. demand가 5초 이상 stale이면 발행 중단한다.
- [ ] 수신 피드백/queue age를 바탕으로 15→10→5fps와 bitrate 조절을 구현하고, wire 예산 지속 초과 시 중단한다. 실제 GStreamer 통계와 encoder 설정이 바뀌는 통합 시험을 둔다.
- [ ] 완료: 합성 source 시험 GREEN 및 실물 단일 카메라의 capture→사이트 영상 확인. 이 단계만으로 FIELD 승격하지 않는다.

## T4 — Pilot·사이트 뷰어 전환과 제한된 폴백

**대상:** `middleware/robot_ui/pilot/vision.js`, `shared/web/`의 기존 영상 공통 코드 아래 `webrtc.js`(신규), `operations/site_ui/console/`의 기존 패널, Pilot Android의 `PilotProxy.kt`, 기존 영상 녹화 호출자. 기존 파일의 실제 위치를 `rg --files`로 확인하고 중복 클라이언트를 만들지 않는다.

**내부 인터페이스:** `openCamera({robotId, grant, video, onState}) -> Promise<{close()}>`. `onState`는 transport·render fps·마지막 capture sequence/time의 신선도를 제공한다. WHEP 세션 정리와 인증은 공통 코드가 소유하고 UI는 권한을 우회하지 않는다.

- [ ] RED: WHEP 인증 실패·ICE timeout·403 갱신·화면 숨김·로봇 변경·로그아웃에서 연결/타이머/세션이 해제됨을 시험한다. 6개 화면이 6개 로봇 ID와 일치하는지 검증한다.
- [ ] WHEP `<video>` 재생을 연결하고 token은 Authorization 헤더로만 보낸다. Android 프록시에서 실제 origin, HTTPS, UDP ICE 연결, 앱 pause/resume을 검증한다. 프록시가 미디어 자체를 중계하지 않는다.
- [ ] capture time/sequence 메타데이터와 실제 렌더 프레임을 결합한다. 표시 fps는 수신 packet 수로 대체하지 않는다. 1초 초과 경고, 2초 초과 숨김, 최초·재연결 IDR 대기 표시를 구현한다.
- [ ] 폴백은 기존 JPEG ≥420ms와 새 sequence 조회로 제한한다. WebRTC 실패 시 자동 고속 MJPEG 금지, 폴백도 총예산에 포함한다. 두 전송이 겹치지 않는 시험을 추가한다.
- [ ] 녹화가 JPEG/canvas를 전제하는지 확인하고 WebRTC video→canvas 또는 기존 증거 경로를 연결한다. 파일/학습 원본 계약을 변경하지 않는다.
- [ ] 완료: Chromium 및 실제 Android 단말에서 재생·전환·로그아웃·stale·녹화 회귀 통과. skipped browser 시험은 미확인으로 남긴다.

## T5 — native 배포·자원 격리·복구

**대상:** `deploy/robot/pinky_pro/`의 현행 native service/payload 목록, `deploy/site/compose.media.yaml`, `deploy/site/README.md`, image 의존성 잠금, 관련 release/image closure 시험.

- [ ] RED: 미디어 미설치에도 CORE 시작 가능, worker crash가 CORE/Fleet 재시작을 유발하지 않음, camera 단일 소유, 서비스 권한·secret mount·포트 allowlist를 검증한다.
- [ ] 로봇 media native systemd에 별도 cgroup·MemoryMax·CPUQuota·restart backoff를 둔다. 초기 quota는 1 CPU 상당/메모리 256MiB로 시작하며, 부하 시험에서 프레임 목표와 제어 여유를 함께 확인한다. 올려야 하면 자원 예산을 변경 기록으로 남긴다.
- [ ] 사이트 MediaMTX와 media 권한 서비스를 Fleet과 다른 container/service로 설치하고, digest pin·HTTPS·LAN ICE 후보·read/publish 경로·관리 API 비공개 설정을 적용한다.
- [ ] 카메라/MediaMTX/권한 서비스/로봇 worker 각각을 재시작하고 재연결과 세션 종료를 측정한다. site 미설정 로봇은 JPEG만 제공한다.
- [ ] 완료: 서명 ARM64 payload 설치 파일·digest와 실제 Pi 서비스 readback. 설치는 승인된 장치 절차로 수행하고 이 계획을 로봇 이동 승인으로 해석하지 않는다.

## T6 — 1대→6대 수용과 기본값 전환

**대상:** 원격 통합 시험 도구 `tools/media/webrtc_bench.py`(신규), `docs/validation/`의 커밋·artifact 결합 결과, 적용 모듈 progress/logs, rollout 설정.

- [ ] 동일 카메라 장면·AP·단말·주행 부하로 기존 JPEG/MJPEG baseline을 먼저 기록한다. 이후 1대 WebRTC DEVICE, 합성 6입력 사이트 부하, 실제 6대 FIELD 순서로 수행한다.
- [ ] 6대·각 640×480·15fps 발행, 6분할 화면 1개 + 두 번째 뷰어 1개를 30분 유지한다. 렌더 fps는 각 로봇 ≥12, capture→display p95 ≤300ms, wire 트래픽은 10초 창마다 ≤8Mbps여야 한다. 두 뷰어여도 로봇별 publisher 수는 1이다. 각 수치의 표본 수·p95 계산·미측정 구간을 기록한다.
- [ ] 지연은 촬영 장면의 시계/LED를 고속 외부 카메라로 화면과 함께 측정하거나 검증된 시각 동기와 렌더 메타데이터를 쓴다. 왕복 RTT나 브라우저 jitter만으로 end-to-end 지연을 대체하지 않는다. 로봇 CPU·온도·메모리·drop·큐 나이·인코딩 시간·AP retransmit를 수집한다.
- [ ] 기존 제어 loop·heartbeat deadline의 현재 상수를 먼저 확인하여 동일 값으로 측정한다. 시험 중 deadline 위반 증가 0건, 제어 지연 p95가 baseline보다 10% 이상 악화되지 않아야 한다. 안전 정지·통신 watchdog 동작은 승인된 장치 시나리오로 따로 확인한다.
- [ ] 손실 1/3/5%, 가용 대역 8→4Mbps, UDP 차단, AP 재접속, 한 뷰어 정지, 동시 로그아웃, media 권한 서비스 중단, CORE 재시작을 주입한다. 정상 프로파일의 12fps 기준과 강등 상태를 구분하고, 혼잡 시 bitrate/fps 하향→필요 시 발행 중단·JPEG 제한 폴백, stale 표시, 제어 경로 유지가 합격 조건이다.
- [ ] 기준 미달은 FIELD HOLD로 기록한다. 통과 후 1대 canary→나머지 5대에 WebRTC 기본값을 적용한다. 오류 시 해당 rollout 설정을 JPEG 모드로 되돌리고 media 서비스를 중단하며 CORE/Fleet은 유지한다. MJPEG 삭제는 소비자 회귀가 끝난 별도 변경으로 남긴다.
- [ ] 완료: 정확한 git SHA·ARM64/site digest·장치/브라우저 버전·AP 조건·30분 원본 로그·고장 주입 결과·롤백 결과가 결합된 수용 기록. 장치가 6대 준비되지 않았으면 6대 수용은 미확인이다.

## 검증 실행과 인계

각 태스크에서 변경한 시험 파일을 인자로 원격 실행한다. 아래는 이미 존재하는 SOURCE 회귀 명령이며 신규 시험은 생성한 뒤 같은 방식으로 추가한다. 로그 경로는 실험실의 사용 가능한 외부 scratch 경로를 사용한다.

```powershell
python tools/harness/rosy_harness.py lint
python tools/remote/remote_pytest.py --log-dir X:/DevTemp/webrtc-plan -- test/test_harness_contracts.py test/test_network_topology_contracts.py
python test/known_failures.py X:/DevTemp/webrtc-plan/run-1.txt
```

구현 브랜치는 태스크마다 명시 파일만 커밋하고 영향 시험을 원격 실행한다. 관련 기존 회귀는 `middleware/core/gateway/test/test_vision_stream.py`, `operations/fleet/test/test_no_video_relay.py`, `middleware/perception/test/test_road_perception.py`, Pilot의 `test/test_vision_stream_client.py`를 포함한다. 최종 affected selection이 요구하는 검사와 독립 계약·증거 리뷰를 수행한다.

문서 검토에서 발견한 변경점과 독립 리뷰 결과는 이 절 아래 기록한다. 구현 시점에 main이 바뀌면 호출 경로와 배포 목록을 재확인한다. 이 문서 자체의 검증은 lint·링크 확인·원격 문서 계약 검사이며, WebRTC 동작 검증과 구분한다.

### 계획 검토 기록

2026-10-17 독립 architecture·critic 1차 검토에서 예산 경계, 실제 렌더 프레임 메타데이터, 활성 세션 갱신·장애 종료, 첫 구독 demand, 분리된 WHIP/WHEP 혼잡 입력과 RTSP/SRT ingress 대안을 보완하도록 지적했다. 같은 ADR·계획에 반영하고 변경 계약을 다시 검토한다. 문서 리뷰는 실제 의존성·부하 시험을 대신하지 않는다.

2차 독립 검토는 주요 지적 해결을 확인했다. 시작 demand→활성 lease 전환, 원본 권한 1초 재검사 문구 통일, RTSP outbound 대안 설명 정정을 승인 조건으로 남겼고 모두 반영했다. 계획 수준의 검토 2회이며 구현·장치 성능 승인이 아니다.

### 구현 경로 보완 (2026-10-17, D-791)

T1/T3의 로봇 미디어 내부 구현과 시험은 `middleware/media/src/rosy_media_edge`, `middleware/media/test`에 둔다. 원래 계획의 `middleware/perception/front_camera/perception/media`는 기존 인식 크기 ratchet을 증가시켜 독립 선택 설치 프로세스의 소유권으로 바꿨다. 실제 image 경로는 `deploy/robot/pinky_pro/image`다. T2의 source/server 권한 서비스와 T1~T6의 동작·수용 기준은 유지한다. 실행 브랜치는 구현 단계에서 `feat/webrtc-camera-migration`으로 바꿨다.

### 측정 생략과 기본값 전환 (2026-10-18, D-789 부록)

사용자 결정으로 T6의 DEVICE·FIELD 측정과 Android 단말 수용을 생략하고, 사이트 영상 서버가 설정된 로봇에서 WebRTC를 기본으로 했다. T2 kick 결속(`rosy_media.main`), T3 카메라 분기·WHIP worker(`rosy_media_edge.camera_tap`, `worker`), T4 공통 WHEP 클라이언트(`shared/web/webrtc.js`)와 Pilot 주행 화면, T5 `rosy-media.service`·`deploy/site/compose.media.yaml`이 코드로 들어갔다. 체크박스의 장치·현장 완료 조건은 충족되지 않았고 gate는 HOLD다. 사이트 콘솔에는 로봇 실시간 영상 화면이 없어 T4 사이트 뷰어 전환은 대상이 없다. Pilot Android `PilotProxy.kt`와 녹화의 WebRTC 프레임 경로는 단말 검증 없이 남았다.
