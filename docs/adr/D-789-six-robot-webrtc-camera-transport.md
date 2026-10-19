## D-789 6대 로봇의 실시간 카메라는 별도 영상 서비스를 통한 H.264 WebRTC로 전환한다

**Status:** Accepted (2026-10-17, 사용자 결정). 전환 구현 착수 결정이며 SOURCE·ARTIFACT·DEVICE·FIELD 통과나 설치 완료를 뜻하지 않는다. Decision 3의 사이트 계정 금지는 [D-801](D-801-site-console-robot-video-site-grants-and-hybrid-topology.md)이 사이트 발급 읽기 위임으로 대체했다(2026-10-18).

### Context

사용자는 카메라를 송출하는 로봇 총 6대를 전제로 WebRTC 전환을 시작하고 ADR과 실행 계획으로 구체화하도록 요청했다. 기존 전방 영상은 CORE의 HTTP JPEG 조회와 운전자 전용 MJPEG다. `middleware/core/api/core_api_web/api/v1/vision.py`에 두 경로가 있고, Pilot `vision.js`의 폴링 하한은 420ms다. `middleware/perception/front_camera/perception/road.py`는 미리보기 발행을 최대 2fps로 제한한다. 따라서 MJPEG 라우트의 존재가 D-368의 12fps 발행 상향 구현을 뜻하지 않는다. 실물 배포 버전과 6대 무선 성능은 이번 결정에서 확인하지 않았다.

JPEG를 UDP로 옮기는 것만으로 프레임 간 압축, 혼잡 제어, 인증, 다중 소비자 송출량 문제가 해결되지 않는다. 6대의 지속 영상은 기존 단일 운전자 예외와 별도 예산·수용 기준이 필요하다.

### Decision

1. **실시간 영상의 목표 경로를 H.264 + WebRTC로 정하고 구현을 시작한다.** 로봇의 별도 native 미디어 프로세스가 기존 카메라 생산자에서 프레임을 받아 한 번 인코딩하고 사이트 영상 서비스로 한 번 송출한다. 카메라 장치를 두 번째로 열지 않는다. raw ROS Image는 로봇 밖으로 내보내지 않는다. 메타데이터에는 robot ID, source, capture sequence/time을 결합한다. 프리뷰·전송 프로세스가 인식 또는 제어 콜백을 막아서는 안 된다.
2. **사이트 영상 서비스는 MediaMTX, 로봇 미디어 엔진은 GStreamer `webrtcbin`을 선택한다.** 로봇→사이트는 WHIP, 사이트→브라우저는 MediaMTX의 WHEP 인터페이스를 사용한다. WHIP는 RFC 9725를 따르며 WHEP는 선택한 MediaMTX 버전의 인터페이스로 취급한다. MediaMTX는 재인코딩 없이 분배한다. Ubuntu 24.04 ARM64에서의 플러그인·H.264·인증·WHIP 호환과 라이선스를 첫 구현 과제로 확인하고 버전·digest를 잠근다. 실패하면 무단 대체하지 않고 차단 근거를 기록하고 본 결정을 보완한다.
3. **영상 서비스는 Fleet·CORE와 별도 프로세스 및 자원 경계다.** 같은 사이트 PC에 둘 수 있지만 Fleet이 미디어 프록시가 되지 않는다. CORE가 허용한 로봇별 읽기 권한을 좁은 영상 세션으로 위임하고, publish와 read 권한을 분리한다. 사이트 계정만으로 로봇 영상을 열지 않는다. CORE의 기존 최종 명령·안전 판정은 유지한다. WebRTC DataChannel로 명령을 우회하지 않는다.
4. **첫 수용 프로파일은 로봇별 640×480·15fps, H.264 baseline, B-frame 0, 키프레임 간격 최대 1초다.** 대당 평균 인코딩 목표 0.8Mbps, 미디어 송신 상한 1Mbps, 6대 합계 상한 6Mbps를 적용한다. 합산 wire 트래픽(프로토콜·재전송 포함)은 지속 10초 창에서 8Mbps 이하여야 한다. 이 값은 달성 사실이 아니라 이번 전환의 검증 목표다. 기존 영상·벌크도 이 8Mbps 예산에 포함한다. 평시에는 영상 활성 구독이 있는 로봇만 발행하며 6대 보기는 여섯 발행을 활성화한다.
5. **품질 조절과 혼잡 처리는 발행자까지 전달한다.** 소비자 수가 늘어도 로봇 uplink 스트림은 한 개다. 구독자별 독립 고화질·simulcast·서버 트랜스코딩은 이번 범위에 넣지 않는다. 혼잡 시 15→10→5fps와 bitrate 하향을 적용하고, 상한을 지키지 못하면 발행을 중단한다. 인코더 입력은 최신 한 장 덮어쓰기, 인코딩 이후 큐는 시간 상한 200ms로 제한한다. 참조 프레임을 임의 삭제하는 대신 다음 IDR로 복구한다. WebRTC 사용만으로 이 정책이 구현되었다고 판단하지 않는다.
6. **인증·세션 회수를 미디어 경로까지 구현한다.** 전용 media 권한 서비스는 CORE가 발급한 좁은 위임만 검증하며 Fleet 원장을 쓰지 않는다. HTTPS 시그널링과 DTLS-SRTP 미디어를 사용한다. URL 토큰과 CORE 장기 토큰의 MediaMTX 전달은 금지한다. robot/path/action/audience가 묶인 최대 60초 세션 자격과 서버 측 활성 세션 종료를 사용한다. 만료·철회·로그아웃·원본 CORE 권한 상실 시 기존 미디어 세션도 5초 이내 종료한다. 신규 연결 검사만으로 철회했다고 보지 않는다. CORE가 닿지 않으면 새 권한·갱신은 거절한다. 운전자 교체는 제어 권한을 옮길 뿐, 별도 viewer 권한까지 자동 제거하지 않는다.
7. **사이트 LAN을 첫 지원 범위로 한다.** 사이트 PC는 유선 연결을 우선한다. ICE 주소·UDP 포트·인증 origin을 명시한다. 인터넷 노출과 외부 TURN 배포는 후속 요구 시 결정한다. LAN에서 UDP가 막히면 연결 실패를 표시하고 허용된 저주기 JPEG로 복귀한다. 6대가 동시에 고속 MJPEG로 복귀하는 동작은 금지한다.
8. **기존 JPEG 조회는 유지하고 MJPEG는 이행 기간에만 남긴다.** WebRTC 장애 시 JPEG 폴링 하한 420ms, 영상 나이 1초 초과 경고·정지 프레임 표시, 2초 초과 영상 숨김을 적용한다. 한 로봇에서 WebRTC와 고속 MJPEG를 동시에 활성화하지 않는다. 1대 DEVICE 검증 뒤 6대 FIELD 검증을 통과한 배포 단위부터 WebRTC를 기본으로 한다. MJPEG 삭제는 호출자·녹화·Android 회귀 확인 뒤 별도 변경으로 한다. 사이트가 없는 로컬 사용은 기존 JPEG로 남긴다.

### 기존 결정과의 관계

**예산 측정 경계:** 위 8Mbps는 로봇 6대의 무선 인터페이스에서 사이트로 향하는 영상·벌크와 그 연결의 반환 제어/재전송 wire 트래픽 합계다. 로봇 NIC와 사이트 수신 지점에서 측정하고 중복 합산하지 않는다. 사이트→뷰어 유선 egress는 별도 지표로 기록한다. 뷰어가 같은 AP의 Wi-Fi를 사용하면 그 downlink와 airtime도 별도 기록하고, 총 무선 점유율 증가로 제어·영상 수용 기준을 깨면 배포를 거절한다. 미디어 demand/budget controller가 JPEG 폴백·벌크를 포함해 로봇별 송출 허용량을 집행하며 여유가 없으면 JPEG 조회도 지연한다.

**세션 수명과 장애 종료:** 입장용 자격은 최대 60초이고, 연결 뒤에는 동일한 실제 MediaMTX session ID에 묶인 최대 60초 서버 lease를 20초마다 재인가하여 연장한다. 입장 자격 만료와 갱신된 활성 lease 만료는 구분한다. 갱신 없는 기존 연결은 lease 만료 뒤 5초 안에 끊는다. 원본 권한은 1초마다 재검사하고 철회·CORE 단절을 알면 5초 안에 실제 세션을 종료한다. 사이트 supervisor는 권한 서비스 heartbeat를 1초마다 검사하고 3초 부재 시 MediaMTX를 종료하여 5초 상한을 지킨다. supervisor 사망 시 child process/cgroup도 종료하도록 묶는다. 재시작 시 이전 연결·자격을 무조건 재사용하지 않는다.

**무구독 시작:** viewer는 먼저 인증된 intent로 최대 10초 demand lease를 만든다. controller가 publisher를 시작하고 ready를 확인한 뒤 WHEP 연결을 연다. WHEP ready 시 초기 10초 demand를 최대 60초 활성 demand lease로 전환하고 20초마다 갱신한다. controller→publisher demand heartbeat는 최대 1초 간격이며 5초 stale 시 발행을 중단한다. 시작 취소·마지막 구독 종료·lease 만료 시 demand를 회수한다. 활성 viewer가 없는 publisher를 WHEP 성공만으로 시작하려는 순환 의존은 금지한다.

**프레임 신선도:** 첫 구현은 촬영 시각·sequence·producer epoch를 영상 모서리의 작은 기계 판독 watermark로 인코딩 전에 결합하고, 브라우저가 실제 렌더 프레임의 해당 영역을 읽어 검증한다. 메타데이터가 중계된다고 가정하지 않는다. T1에서 H.264 손실·낮은 bitrate·재접속 뒤 판독을 검증하고, 판독 불가 프레임은 신선도 불명으로 표시한다. 시계 오차도 측정하며 동기 검증 실패 시 capture age 수용은 HOLD다. 신선도 검증을 생략한 채 별도 heartbeat만으로 화면을 fresh라고 판정하지 않는다.

**혼잡 제어 소유자:** 로봇 sender의 WHIP RTCP·송신 큐 통계가 uplink encoder 제어 입력이다. WHEP downlink는 별도 연결이므로 feedback이 자동으로 sender에 전달된다고 보지 않는다. 사이트 controller는 reader별 통계를 검사하여 2초 이상 500ms 큐 지연이 지속되는 느린 reader만 종료하고 제한된 JPEG로 안내한다. 건강한 reader 때문에 설정한 공유 스트림을 느린 reader 하나가 강등시키지 않는다. 정상 reader도 나쁜 경우 uplink 제어 및 사이트 예산을 다시 평가한다.

| 결정 | 이번 변경 |
|---|---|
| D-139 | 목적이 없던 RTSP/WebRTC 보류를 6대 카메라 요구에 한해 대체한다 |
| D-136·D-152 | Fleet 비중계·raw DDS 외부 금지·예산 원칙 유지. 기존 동시 풀스트림 ≤2 기준은 이 ADR의 6대 WebRTC 프로파일이 수용된 배포에 한해 대체한다. 다른 영상의 무제한 확장은 허용하지 않는다 |
| D-275 | 별도 Vision 연산·배포 경계를 유지하고, 로봇 영상의 인증된 사이트 미디어 분배를 추가한다 |
| D-323·D-368 | MJPEG 전용 실시간 경로 및 WebRTC 보류를 단계적 WebRTC 기본 경로로 대체한다. 기존 라우트는 이행 중 호환 유지 |
| D-427 | 새 최상위 폴더 없이 perception·site_ui·deploy 내부에 구성하고 소유권 manifest·설치 계약을 함께 갱신한다 |
| D-429 | 현행 배포·소스 배치 계약을 우회하지 않고 미디어 의존성을 선택 설치로 닫는다 |
| D-430 | 영상 서비스의 명령 권한은 없다. 안전 태그 경로 변경은 해당 독립 리뷰·trailer 절차를 따른다 |

### Alternatives

- 토폴로지(Mesh·SFU·simulcast·MCU) 비교와 SFU 기본 + 사이트 PC MCU 모자이크 혼합 결정은 [D-801](D-801-site-console-robot-video-site-grants-and-hybrid-topology.md) 「토폴로지 선택」에 둔다(2026-10-18 부록).
- JPEG/MJPEG 유지: 즉시 호환되지만 독립 프레임 전송과 소비자 증가가 6대 송출 예산을 압박한다. 이행 폴백으로만 유지한다.
- 로봇↔브라우저 직접 WebRTC: 사이트 장애 경계는 작지만 뷰어·AI 소비자가 늘 때 로봇 송출과 세션 부담이 증가한다. 사이트 단일 uplink 분배를 선택한다.
- 직접 UDP JPEG 또는 RTSP만 사용: 손실·혼잡·브라우저 재생·인증 연결을 별도로 구현해야 한다. 이번 목표는 브라우저 실시간 영상이므로 채택하지 않는다.
- H.264 RTSP/SRT ingress + MediaMTX WHEP egress: 단일 uplink·브라우저 분배를 유지할 수 있는 유효한 대안이며 로봇의 outbound publishing도 가능하다. 이번에는 uplink도 DTLS-SRTP·RTCP와 WHIP 세션 인증으로 통일하여 별도 전송·인증 정책의 운영 비용을 피한다. WHIP adapter의 개발·ARM64 호환 비용을 감수한다. T1이 이 비용이나 호환을 입증하지 못하면 이 대안과 비교한 보완 ADR을 작성한다.

### Consequences / Validation

Pi 5 H.264 소프트웨어 인코딩 부하와 사이트 장애 지점을 추가한다. 영상 서비스 장애는 영상만 중단해야 하며 CORE·Fleet을 재시작하지 않는다. 학습 원본·사진·녹화는 기존 파일/HTTP 경로를 유지하고 AI 운영 추론은 활성화하지 않는다. 필요 시 후속 AI 소비자를 미디어 서비스에 연결할 수 있지만 이번 수용에 포함하지 않는다.

실행·검증 순서는 [전환 계획](../plans/2026-10-17-webrtc-camera-migration.md)에 둔다. 6대 30분, 화면 지연 p95 ≤300ms, 6대 각 렌더 fps ≥12, wire 예산 ≤8Mbps, 기존 제어 deadline 위반 증가 0건을 함께 통과해야 기본값을 전환한다. 수치가 하나라도 실패하면 최적화·재시험하며, WebRTC 채택 결정을 자동으로 되돌리거나 성공으로 보고하지 않는다.

### 부록 (2026-10-18, 사용자 결정): 실물 측정 없이 WebRTC 기본 전환

1. 사용자는 실물 측정 없이 사람이 보는 로봇 영상 전체를 WebRTC로 전환하기로 결정했다. 계획 T6의 1대 DEVICE·6대 FIELD 수용과 Android 단말 수용은 생략하며 전환을 그 결과에 묶지 않는다. Decision 8과 Consequences의 "1대 DEVICE 뒤 6대 FIELD를 통과한 배포 단위부터 기본" 및 6대 30분 수치 통과 조건은 이 부록으로 대체한다.
2. 기본값: CORE에 사이트 영상 서버(`vision.media.site_url`)가 설정된 로봇은 WebRTC가 기본이고 `vision.media.enabled: false`로만 끈다. 사이트 설정이 없는 로봇은 영상 위임이 503이며 모든 뷰어가 기존 JPEG에 남는다. 로봇 발행 서비스는 `/etc/rosy/media/rosy-media.json`이 있을 때만 시작한다.
3. 측정은 하지 않았다. 640×480·15fps, 화면 지연 p95 ≤300ms, 렌더 ≥12fps, wire ≤8Mbps, 제어 deadline 위반 증가 0건의 달성은 확인되지 않았다. ARTIFACT·DEVICE·FIELD gate는 "measurement skipped by user decision 2026-10-18"로 HOLD다. 이 부록은 성능 수용이나 성공 보고가 아니다.
4. 사용자는 영상이 DDS로 기계 간 이동하지 않도록 요구했다. 로봇 영상은 로봇 안에서 카메라 소유자가 쓰는 공유 메모리 우편함(`/run/rosy-media`)을 미디어 프로세스가 읽고, 기계 밖으로는 WHIP(로봇→사이트)와 WHEP(사이트→브라우저)만 나간다. Decision 1의 raw ROS Image 외부 송출 금지를 재확인한다.
5. 폴백 규칙은 유지한다. WebRTC 실패 시 JPEG ≥420ms 폴링만 쓰고 고속 MJPEG로 자동 전환하지 않으며 두 전송을 동시에 열지 않는다. MJPEG 코드 삭제는 별도 변경이다.
6. 알려진 제한: 카메라 FrameRate는 인식 주기(기본 8fps)를 바꾸지 않으므로 미디어도 그 주기로 나간다. 15fps 프로파일은 카메라 주기 변경 결정 전까지 미달이다. 사이트 콘솔에는 로봇 실시간 영상 화면이 없어 이번 전환은 Pilot 주행 화면에 적용했고, 대시보드·연결 화면 미리보기는 JPEG다.

### References

- [WHIP RFC 9725](https://www.rfc-editor.org/rfc/rfc9725.html)
- [WebRTC media / congestion requirements](https://www.rfc-editor.org/rfc/rfc8834.html)
- [MediaMTX WebRTC 호환·네트워크 설정](https://mediamtx.org/docs/features/webrtc-specific-features)
- [MediaMTX 인증](https://mediamtx.org/docs/features/authentication)
- [GStreamer webrtcbin](https://gstreamer.freedesktop.org/documentation/webrtc/)
- [Pi 카메라 소프트웨어](https://www.raspberrypi.com/documentation/computers/camera_software.html)

외부 문서는 2026-10-17 조회 기준이며 선택 버전에서의 실제 호환은 T1에서 검증한다.
