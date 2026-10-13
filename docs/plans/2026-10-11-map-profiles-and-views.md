# 지도 프로필과 표시 모드 실행 계획

기존 지도 편집기, bounded API, SQLite와 승인된 camera-backdrop 변환을 재사용한다(D-631).

1. 프로필 저장·재시작·revision 충돌·권한·검증 회귀 시험 후 SQLite/API 구현.
2. 현장 지도 페이지에서 프로필 선택 미리보기, 초안 불러오기, 이름 저장, 규칙 JSON 작성과 파일 입력. 활성화는 기존 버튼만 사용한다.
3. 관제 2D 좌표·교정 영상 오버레이·원본 영상 선택 및 원본/교정 후 비교. 승인 교정/신선도 실패 시 교정 영상을 지운다.
4. Node 회귀와 원격 pytest, known_failures 비교, harness lint. 가능한 브라우저 확인. 배포·실물 미확인은 별도 기록.

도달 경로: site_map_store/routes, site-map.html/js, index.html, map-view/camera-backdrop, shared/styles.css, 해당 API·Node·브라우저 시험. 기존 active/draft와 카메라 교정 권한은 유지한다.
