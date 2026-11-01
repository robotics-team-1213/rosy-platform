# ROSY Monitoring 화면

독립 상태 화면의 소유 경로다. 수집·판정·권한·저장은
[ROSY Monitoring 서비스](../../operations/monitoring/README.md)가 맡는다.
계약은 [Monitoring API](../../docs/reference/rosy-monitoring-api.md), 구조는
[D-876](../../docs/adr/D-876-rosy-monitoring-independent-site-and-aggregate.md)을 따른다.

상태 화면과 scoped 조회·논리 그래프·변경 이력을 구현했다.
실제 backend의 브라우저/G1 검사와 G2 캡처·G3 검토는 [UI 검증 기록](../../docs/validation/uiux-surfaces-2026-10-26/monitoring/README.md)에 있다.
검증 상태는 [Monitoring 진행 기록](../../operations/monitoring/progress.md)이 정본이다.

화면은 허용된 사이트의 원천 판정·정보 나이·수집/보고 경로·확인된 실패 단계·변경 이력을 읽는다.
Fleet 종료 중에도 독립 서비스에 조회하며, 별도 Fleet 상태 polling이나 제어·복구 기능을 만들지 않는다.
UI 정본은 이 앱의 `web/`, 공용 시각·증거 어휘의 정본은 `shared/web/`다.
배포 시 고정 목록을 하나의 web-root로 조립하고 원본 파일을 앱 안에 복제하지 않는다.

기계 검사는 실제 backend를 쓰는 `test/test_monitoring_browser.py`를 원격에서 실행한다.
표면의 질문·상태·뷰포트는 [표면 기준](SURFACE.md)에 있다.
