# 관제 위임 파이프라인 공식 검증·로컬 main 착지

**판정:** D-855의 유한 navigation 소프트웨어 파이프라인을 공식 검증하고 로컬 main에 병합했다. 구현 commit `d154853fc894711dffd080f610e7ad41e09af189`의 main 포함 관계를 확인했다. push·실물·배포 수용 기록이 아니다.

독립 unit과 R→A→A1의 3수준 중첩에서 영속 후보 위임, 하위 기명 승인, 기존 Fleet Task·CORE 실행 결과, 원래 시도의 취소·단절·재시작/재연결, UI·기동 구성을 연결했다. 상위·service principal이 하위 사람 승인을 대신하지 못한다. 취소는 원래 위임과 native boot/run/correlation에 한정하며 기존 비상정지 권한은 각 unit·CORE 범위에서 유지한다. D-851 전체는 여전히 Proposed다.

이 문서는 최종 공식 실행의 새 기록이다. 이전 [집중 검증 당시 기록](../control-unit-pipeline-2026-10-24/result.md)의 대기 판정과 관측값을 다시 쓰지 않았다.

## 공식 실행과 source

명령은 `python -X utf8 tools/land.py --tests auto --no-prune`, 실제 `land_exit=0`, 결과는 `landed (not pushed)`다. pytest는 모두 공식 remote runner로 시험 PC에서 실행했다. [실행 색인](landing-invocation.json)은 native 출력에서 작성한 metadata이며 자동 CI receipt가 아니다. private host/path가 있는 원본은 외부에 보존했다.

| 단계 | 실제 source와 범위 | 관측 |
|---|---|---|
| FULL 사전 검사 | commit `d2d7f57d78b1ddc40a3311ae76af137b8d5a1068`, 기준 main commit `c440db31f3e59f686c15d162f3bfa3462c1a3310` | 공식 선택의 27개 호출, 로그별 인자·결과·sha256을 색인에 보존 |
| 최신 main 통합 | main commit `992242d14d2c042eb2df902725164939f85cbbb8`을 합친 구현 commit `d154853fc894711dffd080f610e7ad41e09af189` | 양쪽 누적 기록을 보존하고 생성 색인을 갱신 |
| 통합 guard | 같은 통합 commit, architecture·harness | 273 PASS, NEW 0 |
| main 변경 영향 검사 | 같은 통합 commit, 도구가 선택한 17개 경로 | 505 PASS, NEW 0 |
| 로컬 착지 | 위 구현 commit을 main에 fast-forward | 공식 종료 0, ancestry 확인, push 안 함 |

FULL의 주요 개별 결과는 root 9,666 PASS/1,132 SKIP, Fleet 6,212 PASS/336 SKIP, CORE·공유 묶음 7,290 PASS/91 SKIP이다. 호출 범위가 겹치므로 합산하지 않는다. SKIP은 실행·통과·장치 검증으로 세지 않는다. FULL candidate와 통합 뒤 검사 source를 한 SHA의 전체 재실행으로 바꿔 쓰지 않는다.

FULL 이후 main 변화에는 영향 범위 검사를 적용했다(D-803). 검토한 Fleet runtime·UI·sample·matrix·위임/scoped schema·CORE 취소 경로는 앞서 독립 검토한 commit `0adf983ba22a2e1af9a911edb3acc4ac4e760755`와 동일했다. 고정 통합 head의 독립 재검토에서 추가 중대 finding은 없었다.

## 실패·재시도와 미확인 원인

첫 FULL browser 호출에서 기존 `test_site_map_body_keeps_usable_columns_beside_the_sub_nav[360-740-1-1]`이 SVG label 높이 0px로 실패했다(같은 호출 208 PASS/1 FAIL). 공식 도구가 같은 case를 단독 재시도했고 1 PASS/3.48초였다. D-790에 따라 LOAD-FLAKY 후보로 기록하고 착지를 진행했다. 처음부터 모두 통과한 실행으로 바꾸지 않았으며 known-failure·quarantine 목록이나 측정 기준을 완화하지 않았다.

- 증상: 전체 browser 실행의 한 viewport에서 label 높이가 0으로 관측됐고 단독 재시도는 통과했다.
- 가설: 렌더링·폰트·layout 준비와 측정의 경합 가능성이다. 원인은 입증하지 못했다.
- 다음 확인: 같은 source·viewport에서 font 준비, SVG visibility·bounding rect, 스크롤 전후 시점과 host 부하를 함께 수집해 구분한다. 실제 결함인지 확인하기 전에 timeout·기준·quarantine을 바꾸지 않는다.

이번 root FULL의 G1 타이밍 시험은 통과했다. 위 SVG 재시도 결과는 물리 정지 시간이나 현장 화면 수용의 증거가 아니다.

## 범위별 증거와 한계

[이전 실행 색인](../control-unit-pipeline-2026-10-24/integration-invocations.json)의 HTTP 17·sample 52·controls/Chromium 77 PASS는 모두 명시 commit과 실제 raw/transcript hash에 연결된다. 실제 TestClient의 통과 응답 6개만 HTTP receipt로 등록했다. sample은 독립 process-local unit과 기존 합성 Work Task이며, 실제 R/A/A1 HTTP·재시작·CORE 소프트웨어 종단과 서로를 대신하지 않는다.

실행 경로·증거·권한을 독립 검토했다. 최신 12개 합성 capture의 화면 판정은 ship이며 전용 UI 검토 역할이 제공되지 않아 같은 검토 계약의 일반 독립 검토자를 사용했다. 기존 DESIGN은 유지했다.

실제 actuator·물리 정지·현장 네트워크·운영 PC 화면·ARM64 이미지·배포·원격 CI는 수용하지 않았다. 정책·모델 dispatch 권한을 열지 않았다. 활성 복구는 직렬이며 256개 전체의 처리율 보증은 아니다. 느린 이웃은 stale로 보존한다. [기동 안내](../../deployment/control-units.md)를 따른다.

CE: 미해결 — 기존 지도 SVG 측정 간헐 실패의 원인은 미확인이다. 증상·가설·다음 확인과 공식 재시도 결과를 보존했으며 해결 교훈으로 쓰지 않았다. 구현 수정은 코드·회귀 시험으로 남기고 기존 공개 해시 표기 교훈을 적용했다.
