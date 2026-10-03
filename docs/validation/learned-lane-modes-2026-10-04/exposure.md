# 너무 밝거나 어두운 원본의 추가 회차

조명 OFF와 흰 LCD 재노출 비교에서 확인한 어두운 원본은 감마·CLAHE로 밝게 표시해도 차선·중앙 원이 복원되지 않았다. 밝은 사진이라는 사실과 정보가 남은 사진이라는 사실은 다르다. 원본을 보존하고 보정본은 따로 비교한다.

도로 ROI에서 grayscale 247 초과가 95%를 넘는 영상은 `overexposed` 관측으로 구분한다. 저조도 기준은 기존 ROI p90/p99이다. 이는 초기 보수적 정보 가용성 기준이며 lux나 노출 원인의 확정 판정이 아니다. 흰 빈 바닥과 센서 clipping은 한 장으로 구분할 수 없다. 작은 반사광과 밝은 흰 차선은 전체 차로를 못 보는 상태로 취급하지 않는다. HSV V의 단일 색 채널 포화를 흰색 clipping으로 오인하던 shortcut을 제거했다.

두 양극단 모두 새 시각의 원본을 계속 전달하고, 차선·learned mask·영역 추정을 reset한다. CORE는 0 속도 hold와 loss latch를 유지하고 자동 후진 복구를 우회한다. 과노출은 보조 조명 세션도 해제한다. 화면에는 저조도와 과노출 이유를 따로 표시한다. 어두움은 조명·노출 확보 후 다시 촬영하고, 밝음은 추가 조명을 끄고 낮은 노출에서 경계가 복원되는지를 확인하는 방향이다. 자동 카메라 제어 변경이나 이동 중 노출 재안정화는 이 회차에 추가하지 않았다.

집중 검사: camera/worker/node/preview 98 passed; clipping 경계·색 포화·작은 반사광 5 passed; CORE/Bridge/복구 91 passed; 원본 JPEG 양극단 2 passed; API/전달/face 품질 129 passed, 3 skipped. ARM64·실기 조명·밝은 현장·회전교차로 통과는 별도 검증이다.

독립 안전 검토 `lowlight_research`: camera/line/원본 JPEG/CORE/Bridge 84 passed, native face/경보 15 passed, 밝기 전달 2 passed. 별도 행동 검증 7건에서 색 포화·작은 반사광·흰 차선의 과잉 차단과 과노출 이후 기존 BACKING·오래된 이동 결정의 재사용을 확인했다. 현재 통합에 차단 지적은 남지 않았다.

공식 근거: [OpenCV 색 공간 변환](https://docs.opencv.org/4.x/de/d25/imgproc_color_conversions.html), [Picamera2 카메라 제어](https://datasheets.raspberrypi.com/camera/picamera2-manual.pdf). 원본 정보를 잃은 구간은 밝기 보정만으로 복구되었다고 주장하지 않는다.
