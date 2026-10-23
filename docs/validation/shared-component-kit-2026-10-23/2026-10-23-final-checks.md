# 공통 UI 조합 부품 — 최종 확인

2026-10-23. [앞선 구현 기록](result.md)의 후속 검증이다. 최종 실행 코드 `1610193d7d`는 `fix/component-menu-navigation`에 보존한다. main 착지·push·배포·실물 조작은 수행하지 않았다.

## 후속 수정과 시험

| 커밋 | 범위 | 관측 |
|---|---|---|
| `050c0da738` | 하네스 영향 선택 전체, 브라우저 명시 활성화 | 첫 실행 8,390 passed / 3 failed / 5 skipped / 39 warnings; 두 번째 378 passed |
| `3c5bb94860` | 영향 선택 후속 31개 경로 | 707 passed, 39 warnings |
| `df30912c5d` | Fleet·Robot 캡처 회귀 | 8 passed |
| `df30912c5d` | 설치 자산·문서 위치 | 12 passed |
| `df30912c5d` | 실제 Robot 셸의 합성 웨이포인트 저장·재조회 | 1 passed |
| `ea4e40a63c` → `1610193d7d` | 메뉴 목적지 초점·shared/web 전체 | 예상 1 failed → 391 passed, 1 skipped, 2 warnings |

전체 영향 실행에서 Fleet의 닫힌 스타일시트 목록이 새 `/common/component-controls.css`를 거절했다. 정확한 공통 파일을 등록하고 다른 제품의 CSS를 넣으면 계속 실패하는 음성 대조를 추가했다. 목록 검사를 느슨하게 하거나 실패 기준선에 넣지 않았다. 해당 모듈 4 passed와 후속 영향 선택 707 passed로 수정 검증했다.

나머지 두 실패는 `test_every_module_log_is_valid`와 `test_full_lint_including_git_history_checks`의 공통 로그 순서 검사다. `050c0da738` 이후 `829d9f9f44`에서 자신의 새 행만 파일 끝으로 옮긴 수정이 반영된 `3c5bb94860` 후속 실행에서 두 검사 모두 통과했다. 원래 로그의 known-failure 비교는 3 new / 0 known / 0 flaky이며, 후속 로그는 0 new / 0 known / 0 flaky다. 원래 실패를 통과로 바꾸어 기록하지 않는다. 건너뛴 5건은 FOLLOW가 한 대의 추종자만 지원하여 followers 2–6 조합을 제외하는 기존 geometry 조건이다.

메뉴 항목이 목적지에 초점을 보낸 뒤 닫힐 때, 열기 버튼으로 초점이 돌아가 목적지 이동을 취소하던 문제도 실패 재현 후 고쳤다. 항목 안에 초점이 남았을 때만 열기 버튼으로 복귀한다. 갤러리의 이동은 대상 영역에 초점을 명시한다.

native token export skip은 기존 별도 `ROSY_RUN_NATIVE_TOKEN_TESTS` 조건이며 브라우저 skip이 아니다. FastAPI/Starlette 사용 중단 경고와 하네스 상태·최신성 경고는 제거한 것으로 계산하지 않는다.

## 소스와 화면의 연결

증거는 저장소 밖 `Rosy/docs/workspace-records/2026-10-23/component-expansion-evidence/`에 보존한다. `manifest.json`은 소스의 Git blob SHA-256, Windows 체크아웃 SHA-256, 캡처와 로그 SHA-256을 따로 기록한다. 줄바꿈 차이로 체크아웃 바이트와 Git blob을 혼동하지 않는다.

변경한 실행 자산 19개 중 17개는 전체 영향 시험의 `050c0da738`과 같은 Git blob이다. 나머지는 `interaction-controls.js`와 견본 소비자 `component-gallery.js`이며, 최종 `1610193d7d`에서 shared/web 전체를 다시 검증했다. 8천여 건 전체를 최종 HEAD에서 다시 실행했다고 주장하지 않는다.

현재 화면 근거는 갤러리·확인 16장(`1610193d7d`), Fleet·Robot 적용 7장과 Robot 전체 셸 1장(`df30912c5d`)이다. 24장 모두 원격 원본과 회수본의 SHA-256이 일치한다. Robot 오류 캡처 한 장은 격리 패널이며 전체 셸 캡처와 구분한다. 이전 견본 32장도 별도로 보존한다.

독립 검토 범위는 앞선 기록의 `1f47f20905..006787ecb7`이다. 이후 수정은 실패 재현·GREEN 검증 근거이며, 최종 HEAD에 대한 별도 독립 재검토로 표현하지 않는다.

## 수용 범위

22개 계획 그룹은 기존 부품과 21개 조합 API로 제공한다. 제품 적용과 견본 검증의 구분은 앞선 대응표를 따른다. 합성 자료·호스트 브라우저 검증이며 실제 사용자 과업 G3, 실물 단말, 물리 정지, 현장 수용은 미실시다.

CE: 해당 없음 — 판단과 경계는 구현·회귀 시험·기존 지침으로 재현 가능하며, 별도 해결 교훈이 필요한 운영 장애를 해결한 작업은 아니다.
