# Pilot 영상의 카메라 실행 프로필 증거

기존 Pilot 세션은 `session.json.camera_profile_revision`이 빈 문자열이고, 원본 MCAP에도 카메라 실행 프로필을 보고하는 `camera/telemetry`가 없었다. 따라서 10/6·10/7 같은 과거 영상의 프로필 revision을 사후에 확정할 수 없다.

이 변경은 향후 Pilot 녹화의 원본 MCAP에 카메라 노드가 이미 발행하는 `camera/telemetry`를 추가한다. MP4 변환 sidecar와 MCAP 직접 추출은 각각 프레임의 **bag log time 이전**에서 최신 텔레메트리를 붙인다. 텔레메트리의 `profile_revision`과 `image_size`, 품질·지연 값은 카메라 실행 상태의 증거다. 후속 텔레메트리를 앞선 프레임에 붙이거나 빈 `session.json` 값을 임의로 채우지 않는다.

먼저 녹화 토픽·sidecar 테스트 2개가 실패하는 것을 확인했다. 변경 뒤에는 합성 MCAP에서 프로필 revision 두 값의 순서가 MCAP 직접 추출과 MP4 sidecar 경로에서 같은지 확인했고, 관련 세 묶음은 **91 passed**, `test/known_failures.py` **0 new**였다. 로그는 `X:/DevTemp/pilot-camera-telemetry/red.txt`와 `related.txt`에 있다.

**범위:** 텔레메트리에는 원본 영상의 header stamp가 없어 이 연결은 log time 기준의 직전 보고값이다. `null`은 그 프레임보다 먼저 보고된 값이 없다는 뜻이다. 프로필 이름만으로 카메라 외부 보정의 정확도나 활성 지도·로봇 위치를 승인하지 않는다. 과거 MCAP에 없는 값을 소급 생성하지 않는다. 로봇에 배포해 실제 새 세션으로 읽어 본 증거는 아직 없다.
