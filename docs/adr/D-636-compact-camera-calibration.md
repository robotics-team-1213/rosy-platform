## D-636 소형 AprilGrid 측정 교정과 지도 관측 영역 및 AI 보조 검토

**Status:** Accepted (2026-10-11, 사용자 구현 요청; 실측·배포 수용 별도)

### Context

사용자는 좁은 공간에서 AprilGrid 등을 사용한 교정, 알고리즘 구현과 불확실할 때 AI 보조 구조를 요청했다. D-633 문헌 조사를 실제 사용 가능한 오프라인 측정 도구와 지도 표시로 구체화한다. 도면·좌표 규칙·저장 프로필은 카메라 밖 지도도 표시할 수 있다. «촬영되지 않은 영역을 복원할 수 없다»는 말은 지도 자체를 못 그린다는 뜻이 아니라 현재의 로봇 관측을 만들어 낼 수 없다는 뜻이다.

### Decision

1. Vision에 소형 AprilTag 36h11 grid 생성·부분 태그 관측·pinhole/fisheye 모델 비교·검증 보고·교정 미리보기 도구를 추가한다. SVG 치수는 metre에서 mm로 정확히 변환하고 PNG와 target JSON을 함께 만든다. 출력물은 인쇄 후 다시 실측한다. 온전히 검출된 태그만 쓰며 외부·중복 ID는 교정 데이터로 대체하지 않는다. 태그 전체가 잘린 것과 판 일부가 화면 밖인 것을 구분한다. [Kalibr target 안내](https://github.com/ethz-asl/kalibr/wiki/calibration-targets), [OpenCV fiducials](https://docs.opencv.org/4.13.0/d9/d6a/group__aruco.html).
2. training과 validation 원본을 분리하고 동일 이미지 재사용·source/픽셀 기하 혼합을 거부한다. 여러 위치·기울기 관측과 화면 가장자리 범위를 보고한다. 후보의 수치 잔차와 독립 측량 오차는 다른 것이다. 데이터 부족·조건 불량·원본 계보 불명은 승인 성공으로 변환하지 않는다.
3. 교정 후보는 raw→calibrated ray→floor/map 변환을 별도로 다룬다. 별도의 undistorted-pixel 바닥 등록으로 지도 평면을 출력하며 raw-pixel H를 렌즈 교정 뒤에 재사용하지 않는다. 원본은 보존하고 valid mask와 비교 영상을 만든다. 현행 승인 tracking record 형식과 sighting을 이 도구가 자동 교체하지 않는다.
4. 현행 지도 평면 warp는 지평선 반대편·시야 밖·보간 경계에 valid mask를 적용한다. 응답 헤더 `X-Frame-Observed-Fraction`은 동일 출력 plane/crop의 유효 원본 픽셀 비율(0..1)이다. 렌즈·지도 오차나 물리 가림 정확도 지표가 아니다. Console은 알려진 2D 지도를 유지하고 영상의 관측 비율을 구분한다. 미관측은 회색 hatch로 표시하며 실제 영상으로 해석하지 않는다. 구버전 응답의 coverage 부재는 미확인이다.
5. 측정 보고에는 부족한 자료·확인할 source/geometry·태그 검출·validation·경계 관측을 담은 AI 검토 요청을 만든다. AI 응답은 정해진 촬영/검토 권고와 설명만 허용한다. 좌표·렌즈 계수·교정 승인·map 활성화·로봇 명령은 금지한다. AI 답을 못 받으면 기존 지도와 측정 상태를 유지한다. 기존 advisory 역할과 CORE 단독 cmd_vel 권한은 바꾸지 않는다.

### Consequences

작은 판을 위치·기울기를 바꿔 촬영할 수 있고, 판 전체 시야가 확보되지 않아도 부분 태그가 측정에 참여한다. 한 장의 작은 정면 판으로 전체 광학 모델·척도·바닥 자세를 보증하지 않는다. 현장 영상 수집과 측량은 필요하며 도구의 합성 검증을 물리 정확도 증거로 보고하지 않는다. D-633 Proposed의 전체 운영 교정 계약 승격과 자동 AI provider 활성화는 별도 수용으로 남긴다.
