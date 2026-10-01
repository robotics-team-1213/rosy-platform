# 추종 표시 구현 및 검증

설계: [follow-preview-design](2026-10-01-follow-preview-design.md).

1. ROS-free `follow_preview.py`: 촬영 시각 조인, 추종·객체 영역 표시, 도로 shadow 평면도.
2. `road.py` 미리보기: 페인트와 실제 목표 분리, 신뢰도·거리 유무 표시, LIGHT 이름.
3. `road_observer_node`: 기존 관측 토픽 구독, 제한된 프레임 캐시와 타이머 출력.
   `line_observer_node`의 내부 keep 진단에 영상 크기·지면 출처 추가.
4. `test_follow_preview.py`, 도로 인식·노드 wiring·keep 회귀 및 sensing 전체 시험.
5. 녹화 영상으로 렌더링 비교. 일회성 실행 스크립트·PNG·provenance는
   `X:\DevTemp\rosy-follow-preview`에만 보관한다.

새 객체 분류 모델이나 객체 이동 추적·모터 경로 예측의 활성화는 이 변경에 포함하지
않는다. road_state 미실행 시 unavailable 표시를 유지한다. 실기 배포는 수행하지 않는다.
