# 심한 렌즈 왜곡·부분 시야 카메라 교정 조사

조사일: 2026-10-11. 기준 소스: `c2cf4bd14`. 렌즈 모델 조사와 부분 시야·지도 등록 조사를 병행하고 원논문·공식 문서를 대조했다. 이 기록은 문헌·소스 조사이며 실제 렌즈의 교정 결과나 현장 정확도 증거가 아니다. 후속 설계는 [D-633](../../adr/D-633-measured-camera-calibration.md).

## 현재 ROSY와 개선 지점

| 현재 경로 | 소스에서 확인한 사실 | 개선 대상 |
|---|---|---|
| `operations/vision/rosy_vision/rectify.py::rectify_jpeg` | 미리보기에서 수동 `fx/fy/cx/cy`와 5개 왜곡계수로 `cv2.undistort`, 이어 네 모서리 perspective warp | 측정 내참수 추정·모델 비교·유효 영역 검증 |
| 같은 파일 `map_plane_jpeg` | 승인 `image_to_map`을 원본에 `warpPerspective`, 시야 밖은 단색. 지평선 마스킹은 아직 shortcut | 렌즈 모델과 지도 평면의 합성, 지평선·유효 샘플 마스크 |
| `track/calibration.py::from_record` | source/map/lens와 화면 비율을 확인하고 승인된 3×3 행렬을 크기에 맞춰 사용 | crop/zoom/출력 처리 계보, 비선형 렌즈 좌표 모델 |
| `map_register.py` | 기존 차선 페인트 검색·ECC homography 개선·recall/precision·coverage·cut sides 판정 | 이 기존 무마커 경로를 재사용하되 교정된 좌표 공간에서 검증 |
| Cam `camera/JpegEncoder.kt` | YUV 버퍼 전체를 JPEG로 인코딩, 픽셀을 회전하지 않음. `CameraController.kt`의 `cropRect`는 밝기 측정에 쓰임 | ISP/CameraX의 실제 출력 변환을 계측해야 함. 현재 잘림이 앱 crop 때문이라고 확정할 근거 없음 |
| D-515·D-560 | 기존 지도 평면은 렌즈 왜곡 모델을 제외한 표시용 변환 | 과거 한 렌즈에서 얻은 결과를 모든 광각 카메라에 일반화하지 않기 |

## 알고리즘 비교

| 문제 | 우선 검토 | 조건·한계 | 1차 출처 |
|---|---|---|---|
| 일반 렌즈의 방사·접선 왜곡 | Brown/pinhole; 필요 시 rational | 내참수와 왜곡계수를 실제 표적으로 추정. 중앙 평균 오차만으로 가장자리 품질을 판단하지 않는다 | [OpenCV calib3d](https://docs.opencv.org/4.13.0/d9/d0c/group__calib3d.html), [Zhang 연구](https://www.microsoft.com/en-us/research/wp-content/uploads/2016/02/tr98-71.pdf) |
| 강한 광각·어안 | OpenCV fisheye θ 다항식 | pinhole/rational과 분리 검증셋에서 비교. 렌즈 이름·추정 HFOV만으로 모델을 확정하지 않는다 | [fisheye](https://docs.opencv.org/4.13.0/db/d58/group__calib3d__fisheye.html), [Kannala–Brandt 원논문](https://users.aalto.fi/~kannalj1/calibration/Kannala_Brandt_calibration.pdf) |
| 기본 모델로 설명되지 않는 광학 구조 | Mei unified / OCamCalib / Double Sphere | 광학 구조·독립 가장자리 잔차가 근거다. 첫 구현에 모두 넣지 않는다. Double Sphere는 큰 FOV와 닫힌 역투영을 다루지만 현장 최적 모델이라는 보장은 없다 | [OpenCV omnidir](https://docs.opencv.org/4.13.0/dd/d12/tutorial_omnidir_calib_main.html), [저자 OCamCalib](https://sites.google.com/site/scarabotix/ocamcalib-omnidirectional-camera-calibration-toolbox-for-matlab), [Double Sphere 원논문](https://arxiv.org/abs/1807.08957) |
| 교정판 일부가 화면 밖·가림 | ChArUco, 대안 Aprilgrid | 보이는 ID/코너만 사용. 보드 일부 가림 허용은 잘린 개별 태그를 복원한다는 뜻이 아니다. 보드 물리 치수·평면성을 검증한다 | [ChArUco](https://docs.opencv.org/4.13.0/df/d4a/tutorial_charuco_detection.html), [Kalibr targets](https://github.com/ethz-asl/kalibr/wiki/calibration-targets) |
| 바닥 기준점의 오검출·클릭 외점 | USAC_MAGSAC / RANSAC homography | 최소 네 점보다 많은 분산된 대응점으로 외점을 배제. MAGSAC의 효율적인 종료 판단에는 근사 threshold가 권장된다(0이면 최대 반복까지 실행). 왜곡 제거를 대신하지 않는다 | [OpenCV USAC](https://docs.opencv.org/4.13.0/de/d3e/tutorial_usac.html), [Homography](https://docs.opencv.org/4.13.0/d9/dab/tutorial_homography.html) |
| 교정 출력에서만 생긴 잘림 | pinhole `alpha`, fisheye `balance/fov_scale`, 출력 캔버스·ROI | 주변부 보존과 빈 여백의 절충. 새 캔버스는 새 관측을 만들지 않는다. 실제 유효 영역은 remap 샘플·마스크로 판정 | [calib3d](https://docs.opencv.org/4.13.0/d9/d0c/group__calib3d.html), [fisheye](https://docs.opencv.org/4.13.0/db/d58/group__calib3d__fisheye.html), [remap](https://docs.opencv.org/4.13.0/da/d54/group__imgproc__transform.html) |
| 실제로 촬영되지 않은 바닥 | 입력 시야 재설정·카메라 재배치·추가 관측 카메라 | 합성된 색을 위치 증거로 쓰지 않는다. 상대 외부교정을 위해 겹친 시야 또는 독립 측량이 필요하다 | [Kalibr multi-camera](https://github.com/ethz-asl/kalibr/wiki/multiple-camera-calibration); 미관측 정책은 ROSY 설계 추론 |

## 적용 권고와 좌표 계보

다음은 문헌에서 도출한 **ROSY 설계 제안**이며 구현 사실이 아니다.

1. 내참수 교정과 지도 외부교정을 분리한다. 원본 JPEG의 실제 픽셀 공간 → 렌즈 역투영 ray → 승인된 바닥 평면 → 공통 map(m) → 화면 순서를 고정한다. 렌즈 역왜곡과 homography의 합성은 일반적으로 하나의 3×3 행렬이 아니다.
2. 표적은 여러 자세·거리·시야 위치에서 촬영하고 가장자리 관측을 확보한다. 내참수 학습 프레임과 독립 검증 프레임을 분리하며, 지도 기준점도 독립 측량 검증점과 분리한다. 같은 프레임의 점만 나누어 독립 검증이라고 하지 않는다.
3. 기준점 homography를 쓸 때 `undistortPoints`의 `P` 생략 출력(normalized coordinates)과 픽셀 좌표를 섞지 않는다. `P=K_new` 픽셀 공간 또는 normalized 공간 중 하나를 명시한다. 보정 후 선택 ROI/crop offset도 변환에 포함한다. [OpenCV calib3d](https://docs.opencv.org/4.13.0/d9/d0c/group__calib3d.html)
4. 목적지 map-plane 픽셀을 원본에 역투영하여 한 번의 `remap`으로 샘플한다. invalid 영역은 입력 범위, interpolation footprint, ray 유효성, 승인된 오차 검증 영역을 함께 검사한다. BORDER_TRANSPARENT만 쓴다면 목적지 버퍼를 초기화해야 하며 관측 마스크를 별도로 유지한다. [OpenCV transforms](https://docs.opencv.org/4.13.0/da/d54/group__imgproc__transform.html)
5. 잘림을 구분한다: 출력 ROI 잘림은 캔버스 선택으로 개선; 입력 hard crop은 원본 취득으로 개선; 실제 시야 밖·가림은 미관측. 반사 테두리·복제·인페인팅·생성형 채우기·검증 밖 외삽은 좌표 증거로 인정하지 않는다. 지도 자체의 알려진 선은 미관측 영역에서도 지식으로 그릴 수 있지만 영상 관측과 구분한다.
6. CameraX의 버퍼와 표시 변환은 별개다. 실제 JPEG 기준 calibration을 사용하며 sensor K를 무조건 붙이지 않는다. Camera2 계수는 좌표 정의·계수 순서·ISP 적용 여부를 확인해야 하고 장치에 없을 수도 있다. 이미 보정된 스트림을 중복 보정하지 않는다. [CameraX transforms](https://developer.android.com/media/camera/camerax/transform-output), [Camera2 lens distortion](https://developer.android.com/reference/android/hardware/camera2/CameraCharacteristics#LENS_DISTORTION)
7. 바닥 homography는 높이 있는 로봇 마커의 base 위치를 직접 보장하지 않는다. 내참수·외부 pose와 실제 마커 장착 높이/offset이 있으면 해당 높이 평면의 ray 교차 또는 검증된 3D pose로 분리한다. 수평면 가정이 실패하는 곳은 별도 모델이나 미확인으로 남긴다. [Homography tutorial](https://docs.opencv.org/4.13.0/d9/dab/tutorial_homography.html)

## 검증 항목과 미확인

학습 RMS뿐 아니라 시야 구역별 독립 잔차, p95/max 지도 오차(m), 곧은 선의 휨, 렌즈 매핑 단조성/일대일성, 지평선·foldover·외삽·유효 마스크와 coordinate round-trip을 기록한다. 정확도 예산은 차로·로봇 기하·위치 신뢰 계약과 실측으로 확정한다. 여기서 임의 px/cm 숫자를 현장 GO 기준으로 만들지 않는다. OpenCV가 내는 내참수 표준편차는 전체 결합 공분산 또는 실제 지도 오차 그 자체가 아니다. 해당 공분산을 얻지 못하면 0으로 가정하지 말고 frame-wise perturbation/독립 실측으로 불확실성과 편향을 평가한다. [OpenCV calibration 경고·출력](https://docs.opencv.org/4.13.0/d9/d0c/group__calib3d.html)

원본·렌즈 교정·지도 평면·2D 선 지도 비교, 재시작 후 동일 리비전 결과, 프레임 만료·렌즈/프로필 전환·crop 변경의 무효화, 처리시간·메모리 측정이 필요하다. 코드 의존성 범위는 `opencv-contrib-python-headless>=4.9,<5`지만 실제 배포 버전과 해당 solver 지원은 확인하지 않았다. 현재 현장 렌즈 계수·독립 측량 데이터·잘림의 실제 원인·새 알고리즘 정확도·배포는 미확인이다.

## 문서 검증 기록

`d1f956750`에서 network topology·harness·문서 배치·폴더 구조 계약을 원격 실행해 137 passed, exit 0을 확인했다. 로그는 X: 관리 작업 세션 `logs/calibration-docs/run-1.txt`에 보존했고 `test/known_failures.py` 비교는 NEW 0이다. 실행기는 여유 호스트 없음 경고 뒤 도달 가능한 시험 PC를 사용했다. 이 실행은 문서 계약 검증이며 교정 알고리즘 benchmark가 아니다. 렌즈 조사·기하 조사 담당의 독립 문서 검토에서 MAGSAC threshold의 권장/필수 표현과 D-515의 기존 확장 방향을 바로잡았다.
