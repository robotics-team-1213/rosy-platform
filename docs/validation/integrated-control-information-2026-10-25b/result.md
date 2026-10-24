# 통합관제 첫 FULL의 실패와 검증 도구 보완

[선행 집중 검증](../integrated-control-information-2026-10-25/result.md) 이후 source `42e079ef48`에서 공식 FULL27개 invocation을 실행했다. 모든 원본 run-pre 로그를 known_failures와 비교했다. 이 실행은 통과하지 않았고 최종 착지 증거로 사용하지 않는다.

| 범위 | 원래 결과 |
|---|---|
| Fleet | 2 FAIL, 6388 PASS, 362 SKIP |
| 공통 root | 4 FAIL, 10027 PASS, 1139 SKIP |
| CORE/공유 계약 그룹 | 1 FAIL, 7443 PASS, 91 SKIP |
| 명시 Chromium4그룹 | 각각118·181·121·143 PASS, SKIP0 |
| 나머지20 invocation | NEW0 |

Fleet 실패2건은 새 통합 화면의 Console 문서 소유 등록 누락과 그 선행 실패의 영향이었다. source `d73aede28c`에서 Console OWN에만 등록하고 기존/새 모듈의 install 금지-import mutation을 함께 검사했다. 집중3 PASS·SKIP0·NEW0이고 독립 검토는 경계 완화가 없음을 확인했다.

root 실패는 work 단위의 obsolete small 예외, 공유 정지 helper의 공개 safety anchor 누락, 공개 source 해시/동적 헤더 읽기의 비밀 탐지, 시간 민감 G1 검사였다. source `ac8d7d18f2`는 크기 예외를 줄이고 정확한 공개 진입점과7개 exact-line provenance만 등록했다. 독립 검토는 각 commit 객체와 줄 해시를 확인했다. 수정 후 구조/안전/비밀 검사72 PASS·SKIP0·NEW0이다. 시간 민감 원래 실패를 임의로 기존 실패나 해결로 분류하지 않는다.

공유 UI 실패는 checkbox label.ui-check 누락과 textarea class 설정의 원거리 배치였다. source `79ff20cc96`에서 표준 label을 적용하고 기존 field 설정을 생성 위치로 옮겼다. 해당 회귀1 PASS·SKIP0·NEW0이다. 검사 규칙·known failures·quarantine·시간 기준은 바꾸지 않았다.

## 서로 다른 SHA의 격리 재실행은 무효

원본 FULL을 수집하는 동안 이 브랜치에 수정 commit을 추가했다. 기존 도구는 격리 재실행에 HEAD를 넘겨 원본42e079가 아닌79ff20을 시험했고, 실제 수정된3개 실패를 LOAD-FLAKY 후보로 잘못 기록했다. 원래 FULL 로그는 별도로 보존하고, 이번 작업의 잘못된 후보3줄만 유효 목록에서 제거했다. 다른 작업의 후보는 유지했다. 실행 중이던 자체 land 프로세스를 중단하고 runtime이 main에 반영되지 않았음을 ancestry로 확인했다.

source `c9bc96fa26`의 두 회귀가 원격 RED2건을 재현했다. source `9d0ed0ca2d`는 원래 tested SHA를 격리 실행과 후보 근거에 전달하고, HEAD 이동을 판정·FULL 기록·병합 전에 거절한다. source `6a06333e92`는 primary/isolated 결과 목록이 불완전해도 거절한다. source9d의 전체 land 시험83 PASS, source6a의 전체85 PASS이며 SKIP0·NEW0이다. 시험은 SHA를 직접 확인하고 source에 따라 응답을 달리하므로 현재 fixture checkout의 우연한 통과를 증거로 삼지 않는다.

첫 FULL 보존본은 개발 PC `%TEMP%/rosy-integrated-runtime-first-full-source42/`이며 잘못된 후보의 원본도 함께 있다. 교차 SHA 격리 결과는 불안정 증거·quarantine 후보·통과 기록으로 재사용하지 않는다. 수정된 HEAD의 공식 전체 회귀와 최종 착지는 후속 기록에서 확인한다.

후속 독립 검토는 격리 실행 도중 known-failure 목록을 바꾸는 경합도 지적했다. source `b7ecaa0893`의 추가 RED1건으로 잘못된 known 판정과 캐시 승격을 재현했다. source `ea9591d4f5`는 각 verdict 전후·최종 반환 전에 HEAD를 확인하고, 격리 실행 뒤 HEAD가 바뀌면 후보 기록도 거절한다. 추가 시험 삽입 중 기존 unchanged-list assertion의 위치가 바뀐 시험 오류를 source `016f49d427`에서 원래 시나리오로 복구했다. 이 최종 source의 전체 land 회귀86 PASS·SKIP0·NEW0이고, 독립 소스 검토에서 추가 Important gate 이슈는 없었다.

선행 기록의 `test/test_control_unit_wire_transport.py` 표기는 오기다. 실제 TCP/TLS 회귀 파일은 `test/test_control_unit_tls_transport.py`다. 실제 Fleet backend browser는 이번 FULL의143 PASS 그룹에도 포함돼 원래 source42e079와의 실행 결속을 확인했다.

실제 PC 설치·LAN·장치와 물리 정지는 검증하지 않았으며 N1–N3은 남는다. CE: 해당 없음 — 혼합 source 거절의 판단·재발 방지가 source pin, drift guard와 명시 회귀·이 증거 기록에 직접 남는다.
