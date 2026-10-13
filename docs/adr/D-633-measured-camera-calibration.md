## D-633 심한 렌즈 왜곡과 부분 시야를 위한 측정 카메라 교정

**Status:** Proposed

**날짜:** 2026-10-11. 사용자는 심한 왜곡·잘린 영역을 처리할 알고리즘 조사와 병행 ADR 기록을 요청했다. 조사 완료는 구현 승인·현장 정확도·배포 완료가 아니다.

### Context

현재 미리보기는 수동 pinhole 계수와 네 모서리 warp이며, 지도 평면은 승인된 homography로 원본을 편다. D-515의 특정 렌즈 관찰과 D-560의 렌즈 모델 제외를 모든 카메라의 교정 보증으로 확대할 수 없다. 곧은 선의 렌즈 왜곡, 바닥의 원근, 출력 crop, 입력 시야 밖, 가림, 로봇 마커 높이는 원인과 처리법이 다르다.

두 조사 작업을 병행한 근거·소스 경로·알고리즘 비교는 [조사 기록](../validation/camera-calibration-research-2026-10-11/result.md)에 있다. 이 ADR은 조사에 따른 후속 설계 제안이다. 기존 승인 교정과 공개 프로토콜을 이번 문서 작업으로 교체하지 않는다.

### Decision — 제안

1. **측정 기반 렌즈 모델을 먼저 고른다.** 실물 치수·ID가 있는 ChArUco를 여러 자세와 가장자리까지 촬영해 내참수 `K`와 왜곡계수를 추정한다. 부분보드 관측은 실제 검출된 점만 사용하며 검출되지 않은 점을 채우지 않는다. Aprilgrid는 대안이다. 일반 Brown/pinhole과 rational, OpenCV fisheye를 독립 검증셋에서 비교하고 오차·계수 식별성·매핑 유효성을 만족하는 가장 단순한 모델을 택한다. HFOV/렌즈 이름만으로 fisheye로 단정하지 않는다. [ChArUco](https://docs.opencv.org/4.13.0/df/d4a/tutorial_charuco_detection.html), [Kalibr targets](https://github.com/ethz-asl/kalibr/wiki/calibration-targets), [fisheye 모델](https://docs.opencv.org/4.13.0/db/d58/group__calib3d__fisheye.html)
2. **바닥 등록을 별도 추정한다.** 렌즈 교정한 좌표의 공간 분산 대응점에 USAC_MAGSAC 또는 지원되는 RANSAC을 적용한다. 픽셀/normalized 좌표와 오차 threshold 단위를 명시한다. 기존 D-375 차선 페인트 검색·ECC는 무마커 제안 경로로 재사용하고 반복 무늬의 방향·척도 모호성 검사를 유지한다. solver의 성공·낮은 학습 RMS만으로 승인하지 않는다. [USAC](https://docs.opencv.org/4.13.0/de/d3e/tutorial_usac.html), [calib3d](https://docs.opencv.org/4.13.0/d9/d0c/group__calib3d.html)
3. **좌표 변환은 물리 계보를 갖는다.** 원본 픽셀 → 승인 렌즈 ray → 바닥 평면/검증된 map 변환 → 공통 map(m) → 화면 순서다. 왜곡된 raw 픽셀의 위치를 교정 후 픽셀용 homography에 직접 넣지 않는다. 표시 영상은 목적지 map 평면에서 raw로 inverse map을 만들고 한 번 샘플한다. 바닥 밖 높이의 마커는 장착 높이·offset과 검증된 ray/3D geometry를 필요로 한다. [Homography](https://docs.opencv.org/4.13.0/d9/dab/tutorial_homography.html), [remap](https://docs.opencv.org/4.13.0/da/d54/group__imgproc__transform.html)
4. **잘림은 원인별로 처리한다.** 출력 교정 crop은 `alpha` 또는 fisheye `balance/fov_scale`·캔버스·ROI 선택으로 줄인다. crop offset·축척은 좌표 변환에 반영한다. 입력에서 없어진 픽셀과 시야 밖 바닥은 `unobserved`로 남긴다. 실제 보충은 원본 취득·카메라 재배치·같은 map에 등록된 다른 카메라 관측으로 한다. 가장자리를 복제하거나 생성형으로 채운 색은 위치 관측이 아니다. 기존 지도 선은 영상이 없는 곳에서도 지식으로 표시할 수 있으며 미관측 표시를 유지한다. [fisheye 출력 제어](https://docs.opencv.org/4.13.0/db/d58/group__calib3d__fisheye.html), [multi-camera 등록 조건](https://github.com/ethz-asl/kalibr/wiki/multiple-camera-calibration)
5. **유효성과 정확도를 따로 판정한다.** source remap의 interpolation footprint, 센서/입력 유효 마스크, ray/지평선, foldover·비유한 값, 독립 오차 검증 영역을 검사한다. 유효 픽셀이라는 이유만으로 지도 위치를 신뢰하지 않는다. 가장자리와 심한 확대 구역은 지역 Jacobian 오차 증폭과 독립 측량 오차로 판정하고, 기준 미달은 좌표 선택·관측 사용을 막는다. 미관측과 측정했지만 부정확한 영역을 구분한다. [렌즈 매핑의 단조성·일대일성 경고](https://docs.opencv.org/4.13.0/d9/d0c/group__calib3d.html)
6. **교정 프로필을 지도 프로필과 분리해 결합한다.** 후속 계약안은 source/물리 렌즈·실제 JPEG 픽셀 공간, 해상도·crop/resize/회전, zoom/초점·ISP 보정·안정화 상태, 모델/계수 규격, 내참수·지도 교정 리비전과 map 원본 계보, 학습/검증 manifest hash, solver 버전/옵션, 유효 영역·오차 보고서와 승인자를 보존한다. 같은 비율의 영상만으로 재사용하지 않는다. 확인 가능한 동일 출력에서만 명시적 scale/crop 변환으로 재사용한다. Camera2 sensor 계수를 JPEG에 직접 복사하거나 이미 보정된 영상에 중복 적용하지 않는다. 필요한 필드는 API/SRS·스키마 확장과 회귀 시험 후에만 도입한다. [CameraX](https://developer.android.com/media/camera/camerax/transform-output), [Camera2 계수 정의](https://developer.android.com/reference/android/hardware/camera2/CameraCharacteristics#LENS_DISTORTION)
7. **승인 후 결과를 고정한다.** D-595처럼 영상 폴링마다 교정을 다시 맞춰 지도를 흔들지 않는다. 새 맞춤은 리비전 있는 제안·진단으로 남기며 명시적 승인과 검증을 거쳐 교체한다. 입력 조건이 변하면 기존 측정 교정을 무효화하고 확인 사유를 보여준다. 무효화 시 새 intrinsics를 자동 추정한 결과를 운영 지도에 쓰지 않는다.
8. **화면과 권한.** D-631의 2D/오버레이/원본 표시를 유지하고, 후속 구현에서 렌즈만 교정한 전체 유효 시야·지도 평면·valid-only crop을 원본과 비교할 수 있게 한다. 전체 어안 확인용 panorama 투영을 사용한다면 metre 지도 평면과 다른 표시임을 분명히 한다. 변경하지 않은 원본은 별도 보존한다. 이번 제안은 사진·좌표 변환이고, CORE `cmd_vel`, Fleet admission, 위치 앵커·이름 확인 권한을 확장하지 않는다.

### Alternatives

| 후보 | 현재 선택 |
|---|---|
| 네 모서리 warp만 확대 | 곡선 렌즈 왜곡·측정 불확실성·미관측 영역을 해결하지 못하므로 새 교정의 근거로 불충분 |
| 렌즈 계수를 화면에서 임의 조절 | 비교 미리보기로 가능하나 측정 프로필 승인 근거에서 제외 |
| Mei/Scaramuzza/Double Sphere와 thin-prism/tilt를 모두 도입 | 기본 후보의 독립 잔차 또는 실제 광학 구조로 필요성이 확인될 때 추가. 초기 의존성과 과매개변수를 줄인다 |
| 생성형 복원·인페인팅으로 빈 바닥 채우기 | 원본에 없는 색은 관측 위치 증거로 인정하지 않는다 |
| 단일 프레임 선 직선화로 자동 완료 | 보조 제안 가능. 내참수 식별성·척도·높이·독립 측량 검증을 대체하지 못함 |

### Validation and stages

| 단계 | 수행 | 끝난 기준 |
|---|---|---|
| R0 | 문헌·현재 소스 조사 | 이 조사와 ADR. **완료 범위는 문서뿐** |
| R1 | actual JPEG 입력 계측·표적 데이터·독립 바닥 측량·오차 예산 | 모델 선택 근거와 보류 사유, 원본 계보. 허용 px/m 값은 아직 미확정 |
| R2 | Vision 오프라인 비교 prototype | 모델별 중앙/가장자리 held-out 잔차와 p95/max 지도 오차·오차 heatmap, remap 성능·메모리. 내참수 표준편차를 전체 지도 공분산으로 오인하지 않음 |
| R3 | 계약·승인 저장·표시/추적 소비 구현 | nonlinear 좌표 모델과 리비전·마스크·무효화의 API/SRS/스키마, 원격 계약·브라우저 회귀 |
| R4 | 실제 카메라 배포·독립 실측 | 원본/교정/지도 평면 비교와 재시작·렌즈 전환·crop·프레임 만료, 실제 위치·높이·가림 검증. 별도 DEVICE/FIELD 증거 |

합성 시험에는 radial/fisheye 왜곡, 부분보드·태그 절단, 외점·공선점, crop/resize/회전의 forward/inverse, 지평선·심한 stretching·미관측 마스크·잘못된 프로필·높이 시차를 포함한다. 이 시험 통과가 현장 측량을 대체하지 않는다. 위험 영역에서 오차를 평가할 수 없으면 미검증으로 남긴다.

### Existing decisions and ownership

| 기존 결정 | 관계 |
|---|---|
| D-318·D-375·D-457·D-484 | 원본 보존, 제안·승인, source/map/lens·신선도 검사 유지. 측정 내참수와 부분보드/유효 영역은 후속 추가 |
| D-515·D-560 | D-515의 렌즈 왜곡 확장 방향을 구체화하고 D-560의 렌즈 모델 제외 부분은 수락·구현 후 갱신하는 방향. 현재 Accepted 문서와 운영 교정은 이번 Proposed ADR로 변경하지 않음 |
| D-587·D-593·D-595 | 마커 장착 기하, odom 앵커, 승인된 고정 교정과 교정 변경 무효화 유지. 실제 소비 계약은 별도 갱신 |
| D-631 | 여러 지도 프로필과 표시 모드 유지. 같은 이름·map ID만으로 다른 측정 프로필을 자동 재사용하지 않음 |
| D-427·D-429·D-430 | 기존 Cam 원본 취득 → Vision 교정/관측 → Fleet 승인/표시의 소유를 유지. 새 서비스·최상위 구조·명령 발행자 추가 없음 |

### Consequences

실측 촬영과 가장자리 검증이 필요하며 원본에 없는 영역을 보여 주기 위한 새 카메라 설치가 필요할 수 있다. API의 단일 homography 가정을 확장해야 하므로 즉시 기존 `map_to_image`에 렌즈 계수를 숨겨 넣지 않는다. 실제 모델·허용 오차·프로토타입 수치가 없는 상태에서 "왜곡 해결" 또는 "좌표 정확"을 주장하지 않는다.
