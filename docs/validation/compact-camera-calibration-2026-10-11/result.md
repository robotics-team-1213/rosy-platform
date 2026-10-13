# 소형 카메라 교정과 지도 관측 영역 검증

2026-10-11 · branch `fix/fleet-map-pose-stability` · tested source `ade31911c0`.

## 구현

- D-636과 `operations/vision/docs/compact-camera-calibration.md`에 따라 `rosy-camera-calibrate` CLI를 추가했다. 3×3 30 mm 태그 판은 186×186 mm, 2×2는 147×147 mm다. SVG/PNG/치수 manifest를 생성하며 최소 3개 완전한 태그로 부분 판 관측을 측정한다. 검출 corner는 subpixel로 다듬는다.
- pinhole/fisheye 내참수 후보는 학습 영상과 독립 검증 영상의 SHA-256 계보, source와 명시한 촬영 geometry, 재투영 오차를 기록한다. 원본/보정 영상/mask를 출력하고 별도 undistorted-pixel 바닥 등록과 단일 inverse remap으로 지도 미리보기를 만든다. 현행 승인 tracking record와 sighting은 교체하지 않는다.
- AI 요청은 측정 실패에도 생성한다. 허용된 재촬영·검토 권고와 설명만 검사해 advisory로 보관한다. 좌표·계수·승인·map 활성화·명령 필드는 거부한다. 자동 provider 호출은 추가하지 않았다.
- 현행 map-plane JPEG는 시야 밖·horizon 반대편·bilinear 경계를 mask/hatch로 표시한다. `X-Frame-Observed-Fraction`은 같은 출력 plane/crop의 원본 유효 픽셀 비율이며 Console과 지도 편집 화면에 표시한다. 기준 2D 지도와 유효 로봇 위치의 수명은 별도다.
- D-625~630의 새 폴더 구조를 작업 브랜치에 병합했다. `World`의 map pose 구현과 Fleet 호환 identity를 유지했다. 문서 충돌은 양쪽 기록을 보존하고 기존 로그의 제어문자도 원문으로 복구했다. 이미 병합된 ADR의 예약 gap을 제거했다.

## 검증

출력·원격 로그는 `X:/DevTemp/projects/rosy-platform/2026-10-11--132845--fleet-map-stability--65ca1e/`에 있다. 임시 생성물은 저장소에 넣지 않았다.

| 대상 | 실행 증거 | 결과 |
|---|---|---|
| 최종 Vision 전체, remote runner, World, Fleet 지도 프로필·pose, harness·문서 배치 | `calibration-green/run-1.txt`, committed `ade31911c0` | 841 passed, exit 0, known_failures NEW 0 / known 0 |
| Console ES modules | `calibration-node-final.txt` | 286 passed, exit 0 |
| 실제 Chromium: map plane 75% 표시·revision 불일치·409 fallback 및 하단 좌표 만료/복귀 시 레이아웃 유지 | `calibration-browser/run-1.txt`, `8f3ade4f24` | 2 passed, exit 0, NEW 0 |
| 합성 pinhole/fisheye/부분 판·floor survey | 최종 Vision 시험에 포함 | 재투영 p95 < .01 px, 정상 floor max < 1e-5 m fixture assertions; 물리 정확도 의미 없음 |
| 인쇄 표적 생성 | `aprilgrid-3x3/target.svg`, `target.png`, `target.json` | CLI exit 0, PNG 육안 확인; 인쇄 실측은 미실행 |
| 독립 리뷰 | reviewer `calibration_review`, fixes `aab24e8ce` | 재사용된 metre anchor, lens 후보 누락, outlier의 horizon reference 영향을 수정하고 재리뷰에서 확인 |

첫 실패를 기존 실패로 처리하지 않았다. CLI export fixture 누락은 fixture를 갱신했다. USAC_MAGSAC의 metre 단위 작은 좌표에서 outlier scoring이 잘못된 모델을 선택하는 fixture를 재현하고, 내부 mm 좌표/20 mm threshold로 맞춘 뒤 H를 metre로 변환했다. 현장 허용 오차를 이 threshold로 선언하지 않는다.

원격 시험기는 unconstrained OpenCV 5.0을 설치해 첫 fisheye 시험이 실패했다. 기존 Vision 배포 pin `opencv-contrib-python-headless==4.12.0.88`을 읽고 dependency hash에 반영하도록 수정했다. 장치 고정 dependency를 제외하는 기존 처리를 Fleet/Vision 양쪽에 적용해 pydantic 2.13.5 장치 pin과 2.13.4 서비스 pin 충돌을 방지했다. 최종 시험은 Vision pin을 사용했으며 해당 변경의 cache-key 회귀 시험도 포함했다. 다른 세션의 기존 venv를 변경하지 않았다.

## 수용 경계

SOURCE와 원격 합성/브라우저 증거다. 공유 main 착지·push·CI·새 Fleet/Vision image 배포·실물 AprilGrid 촬영·프린트 치수·고정 렌즈 조건·독립 측량·실제 로봇 위치 오차는 이번 결과로 수용하지 않는다. 기존 D-633의 «알고리즘 구현 전» 기록은 당시의 문헌 조사 상태이며, 이 결과에서 오프라인 구현과 표시 경로를 추가했다. 운영 measured calibration admission과 실물 정확도는 별도다.
