# 학습 차선 선택과 관측 출처 검증

## 범위

운전 모드(수동·차선·지도 목표)와 차선 paint source(threshold·denoise·learned)를 화면에서 독립적으로 선택한다. 인식 변경은 관리자·fresh 정지·IDLE·line-follow OFF·보정 없음 조건에서만 받아들이며, 고정 모델 pointer의 서명과 파일 hash를 검사한다. 설정의 성공과 실제 프레임의 추론 출처는 별개다. 실제 추론 출처가 없으면 확인 대기로 표시한다.

미분류 카메라 규칙 영역은 `REGION UNCLASSIFIED/DARK`로 표시한다. `DET`와 객체 종류는 학습 객체 검출 결과가 연결될 때만 표시한다. 차선 모델은 객체 종류를 판정하지 않는다. LiDAR·차단 기준과 최종 CORE command authority는 바꾸지 않는다.

## 독립 안전 검토

- Reviewer: `lane_ui` (API/Host/ModeMachine 작성과 독립된 UI 레인).
- 수정 전: 정지 검사 이후 Host 카메라 재시작 동안 다른 접속자의 주행 시작이 가능했다. ModeMachine의 원자적 IDLE 예약과 REST/WS admission 검사를 추가했다. IDLE·비상정지는 계속 허용한다. 실패·예외 시 finally 해제한다.
- 수정 전: 보정 busy 검사와 session 생성 사이에 설정 예약이 끼어들 수 있었다. 보정 admission과 인식 설정 admission이 같은 별도 RLock을 사용한다. 내부 mode lock·docking listener 순서를 바꾸지 않는다. 멈춘 보정 admission을 재현한 시험은 수정 전 실패하고 수정 후 통과했다.
- 고정 경로·전용 CORE peer·lane-only Host allowlist·서명 검사·원자적 교체·실패 복구·native 설치 경로를 검토했다. 재시작 중 이동 경합을 재현하는 시험과 거부·예외 cleanup 시험을 포함한다.
- 카메라 4..8 Hz 선택은 기존 0.5 s frame-gap 및 마스크 age/generation 검사보다 느슨한 유효시간을 만들지 않는다. 기본 capture 8 Hz와 fleet paint threshold는 유지한다.

## 검증 경계

- Host/API/systemd/status/line-follow 관련 395 passed, 2 skipped; admission 추가 회귀 82 passed. 설치된 Host import smoke 포함 18 passed. API 문서 v1.90 정렬 7 passed.
- Pilot host 87 passed, 59 skipped; 기존 자동·hold·takeover browser 4 passed; 신규 Pilot/dashboard perception browser 2 passed; 지연 readback 회귀 1 passed; dashboard panel browser 13 passed.
- Sensing 전체 host: 2594 passed, 109 skipped와 기존 hotpath 목록 누락 1 failed. 설정 CLI는 ROS node가 아니므로 non-node 목록을 바로잡고 해당 suite를 재검증한다. 최종 capture-rate/overlay/preview 집중 검사는 83 passed, 23 skipped; classifier 회귀 63 passed.
- 실제 정지 프레임 비교: 학습 keeper 양쪽 경계 confidence 0.9, 밝기 규칙 왼쪽 경계 confidence 0.6. 이것은 실시간 처리율이나 실제 이동의 증거가 아니다.
- INT8 후보의 19개 영상 mask IoU 평균 0.9633은 사전에 정한 0.98 기준 미달이므로 운영 모델로 선택하지 않는다.
- ARM64 artifact·서명된 native 설치·실시간 learned/fallback readback·실제 주행은 별도 증거이며 여기서 완료로 주장하지 않는다. 실기 주소·로그·스크린샷·사용 가능한 credential은 공개 저장소에 두지 않는다.
