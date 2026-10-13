# D-691: Rosy Cam은 Rosy가 영상을 읽는 동안만 보내고, 그 뒤 30초를 유지한 다음 센서를 끈다

**Status:** Accepted (2026-10-12, 사용자 결정: Fleet만이 아니라 다른 Rosy의 요청에도 보내고, 요청이 끊겨도 바로 끄지 않고 일정 시간 영상을 유지한다.)

잇는 결정: [D-261](D-261-overhead-camera-app-skeleton.md) · [D-318](D-318-site-camera-preview-rectification.md) · [D-472](D-472-rosy-cam-map-and-lamp-identity.md).

**Context:** Rosy Cam은 페어링되면 화면이 꺼져 있어도 센서를 열고 JPEG를 계속 보낸다. 현장 화면을 보는 Rosy가 없을 때도 같다. 사용자는 이유 없이 켜 두지 말고, Rosy Fleet이 볼 때 보내되 Fleet만의 특례로 두지 않으며, 요청이 끊기자마자 끄지 않기를 원했다.

**Decision:**

1. **요청은 제품 이름이 아니라 인증된 미리보기 읽기다.** Vision preview lease로 `frame`, `field-proposal`, `map-proposal`을 읽는 Rosy는 그 source의 영상을 요청한다. Fleet 콘솔, 설치 화면, Robot, Pilot, 녹화·보정 도구가 같은 문을 쓴다. 401과 잘못된 경로는 요청이 아니다. 프레임이 없거나 오래됐거나 429여도 그 읽기는 요청이다. Vision 내부 추적은 그 자체로 센서를 깨우지 않는다.
2. **유지 시간은 30초다.** 마지막 인증 읽기부터 `stream_hold_s`(공유 벡터) 동안 `wanted`는 true다. 그 시각을 포함하면 false다. 유지 중에 다시 읽으면 그 시각부터 30초를 다시 센다.
3. **하향 메시지는 `demand`다.** `{"type":"demand","wanted":true|false}`. `wanted`는 JSON boolean만 인정하고, 그 외는 무시한다. 모르는 키는 무시한다. hello 직후 `config` 다음에 현재 값을 보내고, true로 바뀔 때 바로 보내며, 유지가 끝나면 상태 주기 안에서 false를 보낸다. 소켓은 끊지 않는다.
4. **폰은 그 값을 따른다.** `wanted` true면 센서를 열고 JPEG를 보낸다. false이고 앱 화면이 없으면 센서를 끄고 보내지 않는다. 앱 화면이 열려 있으면 맞추기용 미리보기만 하고 보내지 않는다. 심한 발열은 요청과 미리보기보다 먼저다. PowerManager 열 상태가 SEVERE 이상이거나, 열 상태를 모를 때 배터리 온도가 45°C 이상이면 센서와 JPEG를 멈춘다. 화면을 끄는 기준과 같고, 조명을 막는 43°C보다 늦다. 열이 LIGHT 이하이거나, 열 상태를 모를 때 배터리가 41°C 이하로 내려오면 다시 요청을 따른다. 그 사이 소켓과 wake lock은 유지한다. `demand`를 모르는 이전 앱은 계속 보낸다. `demand`를 보내지 않는 이전 Vision에 붙은 새 앱은 연결 뒤 2초 동안 메시지가 없으면 예전처럼 보낸다.
5. **대기 중에도 링크는 유지한다.** 부분 wake lock과 Wi-Fi lock은 그대로 둬서 다음 요청의 `demand`가 바로 도착하게 한다. 줄이는 것은 센서와 JPEG 송출이다.

**Consequences:** 새 Vision과 새 앱이 같이 있어야 대기가 된다. 한쪽만 새것이면 오늘처럼 계속 보낸다. 콘솔을 닫아도 30초간 프레임이 온다. 그 사이 추적도 그 프레임을 쓸 수 있다. 30초가 지나면 최신 프레임은 오래되고 미리보기는 404가 되며, 다음 읽기가 센서를 다시 연다. 카메라가 열리는 동안의 첫 읽기는 프레임이 없을 수 있다. 심한 발열로 멈춘 동안에도 미리보기는 비고, 식으면 요청이 아직 유효할 때 다시 보낸다.

**Validation:** `operations/vision/test/test_stream_demand.py`, `test_protocol.py`의 `demand` 벡터, 앱 JVM `CaptureGateTest`·`CaptureCoolingPolicyTest`·`ProtocolTest`. 2026-10-12 Galaxy S21에 이 브랜치의 디버그 APK를 같은 서명으로 설치했다. 현장 Vision은 `demand`를 보내지 않아 연결 약 2초 뒤 기존 송출로 붙었고, Fleet lease로 받은 `ceiling_north` JPEG는 1280×720, 순번 1285에서 1289로 늘었다. 화면을 끈 뒤에도 순번 1434가 왔다. 그때 배터리는 36.2°C라 발열 정지는 기기에서 확인하지 않았다. 대기 전류와 요청 뒤 첫 프레임까지의 시간은 측정하지 않았다.
