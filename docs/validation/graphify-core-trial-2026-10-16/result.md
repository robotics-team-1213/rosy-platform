# CORE Graphify 시범 파이프라인

## 문제와 판단

기존 Graphify 결과는 여러 경로에 흩어져 있었으며 현재 소스 revision의 결과인지 확인할 수 없었다. 실험실의 F:/X: 경로를 다른 개발 PC에 그대로 적용할 수도 없었다. 따라서 도입 판단은 Trial로 유지하고, 범위·revision·파일 해시와 생성·검증 단계를 함께 기록한다.

## 최초 로컬 실행 증거

- Graphify 0.9.91, Python 3.12, Windows. 소스 revision `436d52a55667093cc943589f516dba70c0c5d625`, 범위 `middleware/core`.
- 코드 394개를 분석했다. 문서 38개는 code-only 범위에서 제외했고 패키지 marker·`package.xml`·`setup.cfg` 등 13개는 미지원 형식이었다.
- 노드 9,661개, 관계 23,337개, 커뮤니티 388개. HTML은 커뮤니티 요약이며 JSON은 전체 그래프다.
- `CommandManager`, `SafetyManager`, `EventBus` 설명, `affected`, `god-nodes`의 종료 코드가 모두 0이었다. `CommandManager`의 생성 위치 `gateway/core/services.py:208`은 원본과 대조했다. 별도 query도 실행했으며 예산 1,500 토큰에서 250개 중 42개 노드만 표시됐으므로 검색 완전성의 증거로 쓰지 않는다.
- 생성 후 그래프 검사: 끊어진 endpoint 0, 자기참조 10. 이 검사는 추출 이전의 관계 손실을 증명하지 않는다.
- 분석 전후 소스 해시와 revision이 같았다. 최종 graph SHA-256은 `a7b1684da7c201255a9c5417387adbb6c0c674d601c4c9a675c34518ab956c2e`.
- 로컬 실행 폴더의 식별자는 `core-20261016`이다. 실제 bytes는 해당 PC의 사용자 캐시 `ROSY/analysis/graphify/` 아래에 있으며 저장소에 포함하지 않는다. 다른 PC에서는 공용 도구로 새 실행 폴더를 만든다.

## 재발 방지

첫 실행의 PowerShell stderr 경고가 Stop 정책에 걸렸다. 공용 도구는 subprocess 종료 코드로 판단하고 stdout/stderr를 단계별 로그에 함께 보존한다. 최초 detect가 소스 옆에 만든 stat cache는 외부로 이관했고 제거 후 Git 상태를 확인했다. 공용 도구는 CLI의 명시적인 `--out`과 자식 프로세스 환경으로 소스 옆 생성을 피한다.

팀 공용 명령과 단계별 실패 기준은 [분석 생성물 위치 안내](../../reference/analysis-artifact-locations.md)에 있다. 각 새 실행의 `provenance.json`과 `health.json`이 그 실행의 근거이며 위 숫자를 새로운 revision의 결과로 재사용하지 않는다.

## 공용 명령 검증

`tools/graphify_pipeline.py build --scope middleware/core/events`를 실행해 노드 248개·관계 595개를 생성했다. 끊어진 참조와 자기참조는 0개였고 HTML·보고서·주요 노드 조회가 모두 성공했다. `query ... EventBus` 실행과 저장소 내부 출력 거절을 확인했다. 이 결과는 파이프라인 실행 확인이며 CORE 전체의 품질 평가를 대신하지 않는다.

리뷰에서 상위 `.graphifyignore` 변경을 소스 해시가 놓치는 문제가 발견됐다. 상위 ignore 파일과 Git의 저장소·사용자 제외 규칙을 snapshot에 포함하도록 수정하고, 규칙 변경·소스 변경·오래된 그래프 거절·내부 출력 거절을 검사하는 `test/test_graphify_pipeline.py`를 추가했다. pytest와 착지 결과는 실제 원격 실행 뒤 기록한다.

## 남은 검증

검색 품질·기존 검색 대비 속도·갱신 비용 비교는 아직 수행하지 않았다. 현재 범위 밖의 ROS 패키지·배포 의존성, 문서·ADR 의미 관계도 검증하지 않았다. 무방향 그래프의 영향 후보는 테스트 범위나 명령 권한을 결정하는 근거가 아니다. 기존 harness·계약 테스트를 유지한다.
