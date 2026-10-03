# 저조도 추가 회차

2026-10-04 source/host 검증. ARM64 설치·실제 조명 효과·주행 검증은 별도이다.

실제 조명 OFF 원본은 grayscale p90=34, p99=39, std=4.53이었다. 감마 Y 0.65는 p90을 69로 올렸지만 차선·중앙 원은 판독되지 않았다. CLAHE·Gaussian·NLM 비교도 복원 증거가 없었다. Windows OpenCV 5.0.0에서 median gamma 0.36 ms, CLAHE 0.95 ms, NLM+CLAHE 40.16 ms였으며 Pi 처리시간을 뜻하지 않는다.

원본 도로 ROI로 저조도를 판정한다. 밝은 천장 일부는 이를 해제하지 않는다. 새 촬영 시각의 원본 영상과 invalid 품질은 계속 전달하며, 전경 영역·차선·기존 learned mask를 추측으로 유지하지 않는다. CORE는 저조도에서 차선 손실 후 자동 후진 복구도 차단한다. 독립 검토에서 이 후진 경로를 재현한 뒤 수정했다.

`ROSY_LOW_LIGHT_ASSIST=true` opt-in에서는 기존 sole owner rosy-face가 흰 LCD, 전구 도형, steady white LED를 사용한다. fresh 근거가 이어지면 조명으로 시야가 개선되어도 같은 조명 세션을 유지한다. 오래된 근거·경보·업데이트·보정·충전·낮은 배터리는 이를 해제한다. IDLE/standby에서도 주행 모드 전환 없이 사용할 수 있다.

재검증: camera/node/preview 64 passed; native/Host 설치 306 passed, 8 skipped; API low-light 143 passed, 1 skipped 및 실제 API 9 passed; face/native/PIL/lamp 317 passed, 4 skipped. 독립 `lowlight_research` camera/CORE 검사 119 passed, preview/face 품질 31 passed, 1 skipped. Worker 원자 snapshot 회귀 23 passed, 1 skipped.

실기기에서는 정지·fresh velocity·보정 없음 조건으로 흰 LCD 명령과 촬영을 연결했다. 고정 노출 촬영 뒤 카메라만 재안정화하여 다시 촬영했지만 두 사진 모두 트랙 정보 개선을 입증하지 못했다. 사용자가 기기 앞에 없으므로 물리 화면·LED 성공이나 주행 성공으로 기록하지 않는다. 바퀴 명령은 보내지 않았다. 새 LED pattern은 ARM64 빌드·배포 후 별도로 확인해야 한다. 원본·비교 영상·측정·재현 로그는 X 드라이브의 임시 작업 세션에 보관했고 공개 기록에는 주소·토큰을 넣지 않았다.

공식 근거: [OpenCV CLAHE](https://docs.opencv.org/4.x/d5/daf/tutorial_py_histogram_equalization.html), [gamma/LUT](https://docs.opencv.org/4.x/d3/dc1/tutorial_basic_linear_transform.html), [denoising](https://docs.opencv.org/4.x/d5/d69/tutorial_py_non_local_means.html), [Picamera2 manual](https://datasheets.raspberrypi.com/camera/picamera2-manual.pdf). 보정본이 밝아진 사실만으로 차선 정확도나 야간 주행 합격을 판단하지 않는다.

독립 추가 안전 검토: `lowlight_research`가 도로 ROI·원본 전달·모델 reset·CORE 복구 차단·preview 품질 연결을 검토했다. 현장 임계값 정확도와 실제 조명 효과는 미검증이다.
