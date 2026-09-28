## D-323 원격 조종 표면은 CORE가 same-origin으로 서빙하는 정적 PWA Rosy Pilot(src/hmi/pilot)이며 기기 종류별 드라이버 확장점을 v1 Pinky 주행과 함께 선행한다

**Status:** Accepted (2026-09-29, 설계·소스 배치 결정). 구현·장치·현장 수용은 별도 HOLD.

## Context

기기(Pinky·OMX)를 브라우저·휴대폰에서 직접 조종할 전용 표면이 없다. 기존
operator dashboard는 기기 1대당 관제 콘론솔(D-23, D-243)이라 조종 surface 로는
무겁고, `src/hmi` 조례(web_common 토큰·template)를 그대로 쓸 새 자리가 필요하다.
외부 클라이언트는 ROS를 말할 수 없고(CORE SRS §1.3) CORE의 `/api/v1`·`/ws/*`
WS teleop·watchdog·감사 로그(SAF-002), capability 게이트(409
`CAPABILITY_WITHHELD`)가 이미 존재한다. OMX는 별도 정지·명령 경계라 팔 최종
명령이 OMX 로컬 컨트롤러 소유여야 하고(D-296) 지금은 허가된 운영 API가 없다.
Fleet 중앙 서버·인터넷 경유 중계는 v1 범위가 아니다.

## Decision

1. 새 HMI 표면을 `src/hmi/pilot`(ROS 패키지 `pilot`, ament_cmake 정적 자산)에
   둔다. 제품명은 **Rosy Pilot**. `core_api_web`이 dashboard와 같은 방식으로
   `/pilot/`을 same-origin 서빙하고 Node·별도 서버 프로세스는 만들지 않는다
   (D-23). CORS 신규 개방도 하지 않는다. 앱은 이미지와 함께 배포되므로 앱↔CORE
   API 버전 정합성이 이미지 단위로 보장된다.
2. 통신은 기존 `/api/v1`·`/ws/*`만 쓴다. WS auth 첫 프레임·4401/4403·백오프
   1s→30s, 토큰 저장 규칙(D-193), hold-to-drive(~100ms) 원칙을 dashboard
   패턴 그대로 계승한다. 조종 중 capability 박탈(409)은 즉시 조종 중단과 이유
   표시로 이어진다. e-stop 문구는 소프트웨어 정지 사실을 유지한다(triage 규칙).
3. v1 조종 대상은 Pinky 주행 1대다. 대신 `drivers/registry.js`(기기 종류 →
   드라이버 인터페이스)를 선행해, OMX 로컬 컨트롤러의 teleop API가 API Ref
   사이클로 확정되면 `drivers/omx_local.js`·`screens/arm.js` 추가만으로
   확장된다. pilot은 어떤 기기 종류도 ROS를 몰라야 한다.
4. 주행 화면은 전방 카메라 풀블리드 + HUD(web_common tokens 만)의 게임식
   구성으로 한다. 입력은 가상 스티어링 패드·홀드 페달(클릭/터치), Gamepad API,
   키보드를 같은 hold-to-drive 원칙 아래 두고, 축 매핑·데드존·감도 곡선·스케일
   같은 입력 조정은 브라우저 localStorage(개인 선호)에 둔다.
5. 카메라는 기존 인증 JPEG 프레임 폴링(`/api/v1/vision/front/*`), 클라이언트
   바운드 녹화(5분/60MB), 서버 bounded evidence 저장을 재사용한다. 새 영상
   전송 경로(MJPEG/WebRTC), Fleet 중계, 인터넷 직접 노출은 열지 않는다.

**보강 평가(2026-09-29, 원형 휠·녹화 실현성 검토):**

- **원형 휠 조종(NFS 계열) — v1 채택.** 좌측 원형 휠에서 Pointer Events 로
  터치점의 각도를 잡아 조향(`steer`)으로, 우측 페달 홀드로 전후(`linear`)로
  쓴다. 표준 브라우저 API 만으로 충분하고(1차 기기 Lenovo 태블릿 1200×2000
  지원), 매핑은 이미 계약화된 `{kind:"pedals", forward, reverse, steer}` 를
  그대로 재사용한다. 위험(손끝 이탈·멀티터치·각도 폭주)은 손을 떼는 즉시
  0·데드존·기본 저속 프리셋으로 이미 완화돼 있다. 회전 각도는 조향 클램프로
  묶는다.
- **조종 중 카메라 녹화 — v1 채택(기존 자산 재사용).** JPEG 폴링 미리보기 +
  MediaRecorder 녹화(5분/60MB 바운드)는 dashboard 실측 경로 그대로라 태블릿
  하드웨어 인코딩 부담 안에서 돈다. 스냅샷·클립 다운로드와 서버 증거 업로드도
  재사용. **후순환:** WebRTC급 30fps 스트리밍(신규 전송 경로 — 비목표 유지),
  HUD 오버레이 합성 녹화, 오디오.

## Consequences and rollout

dashboard(관제)와 pilot(조종)의 역할 구분이 명시된다. 구현은
[Rosy Pilot 설계 문서](../plans/2026-09-29-rosy-pilot-teleop-app-design.md)를
실행 계획으로 풀고, ROS-free pytest·Playwright(가짜 CORE)로 SOURCE/SIM 증거를
먼저 만든 뒤 실기 Pinky(DEVICE)·현장(FIELD) 수용을 별도 게이트로 둔다. 실기
주소·계정·채운 설정은 `private/`(D-226) 규칙을 따른다. 원격(외부망) 접속 수요가
커지면 catalog 출처만 확장하고 최종 명령 소유는 기기 로컬에 남긴다(D-12).

**Related:** [D-1](D-1-rclpy-uvicorn.md), [D-2](D-2-cmd-vel.md),
[D-23](D-23-rosy-os-fastapi.md), [D-193](D-193-login-code-and-credential-lifecycle.md),
[D-226](D-226-document-placement-and-publication-criteria.md),
[D-275](D-275-web-surface-and-video-runtime-ownership.md),
[D-296](D-296-device-middleware-and-site-orchestration-terminology.md).

---
