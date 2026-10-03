# 녹화 옵션 추가 회차

기기 Pilot MCAP과 브라우저 확인 영상 모두 원본을 기본으로 보존한다. `raw`는 표시 없는 원본이며 `annotated`는 원본에 별도의 검출 표시본을 더한다. 자동 표시는 `model_unreviewed` 출처이고 사람이 확정한 학습 라벨이 아니다. 기존 body 없는 녹화 시작 요청은 원본으로 유지한다. 새 typed ROS 시작 서비스가 없는 구형 실행물은 표시본 옵션을 지원한다고 광고하지 않는다.

브라우저의 원본과 표시본은 촬영 시각, 카메라 frame id, 크기가 같은 쌍이다. 원본 누락·오래된 촬영·다른 크기·다른 프레임은 대체하지 않고 녹화를 중단한다. 서버는 네 프레임, 최대 2초의 제한된 쌍 캐시를 사용한다. 원본 먼저 저장한 같은 그룹·시작/종료 시각·프레임 수를 확인한 뒤 표시본을 받아 두 파일을 보존한다. 웹 표시를 위해 밝게 렌더링한 픽셀은 원본 저조도 판정을 바꾸지 않는다. 촬영 지연과 수신 후 경과 시간은 함께 계산한다.

소스/host 증거: 실제 preview producer callback을 실행하고 JPEG를 디코딩한 검증에서 원본 밝기 20은 유지되고 표시본 밝기 255는 별도로 저장되었다. 두 영상은 같은 capture header와 크기를 가지며 품질은 어두운 원본에서 계산된다. RAW/wiring 검증 8 passed. API/typed transport/Guard/쌍/저장 출처 집중 검사 162 passed, 1 skipped. UI host 검사 43 passed, 후속 분리 검사 34 passed, shell import closure 4 passed. 브라우저에서는 Pilot 두 녹화 방식 및 옵션 2 passed, 기존 종료·hold·takeover 4 passed, 저조도 1 passed; Dashboard 쌍 저장·원본 누락·저조도·전체화면 3 passed.

조명 후속 변경은 기존 LCD/LED 소유자 안에서 IDLE와 MANUAL에만 허용한다. 경보, 충전, 보정, NAVIGATION과 오래된 근거는 우선한다. 예약된 하드웨어 테스트도 경보보다 앞서 실행하지 않는다. 전구 렌더러는 별도 순수 모듈로 분리했다.

독립 안전 검토 `lowlight_research`: API/쌍/저장/Bridge/Guard 107 passed, recorder 51 passed, native face/조명/경보 20 passed, 실제 JPEG 비교 1 passed. 원본 인코딩 실패는 callback 밖으로 전파하지 않고 원본 누락으로 처리하도록 수정한 것을 확인했다. 현재 통합 변경에 차단 지적은 남지 않았다.

이 문서는 source/host 회차이다. ARM64 생성 서비스 빌드, 기기 녹화 파일, 실제 LED 조명 효과와 중앙 원/회전교차로 주행 합격을 뜻하지 않는다. 임시 사진·로그는 X 드라이브에 두며 공개 기록에 기기 주소·토큰을 넣지 않는다.
