# 검색 선택의 표시와 호출자 상태 일치

공용 `createSearchSelect`에서 화면상 선택이 사라졌는데 호출자에는 이전 ID가 남는 문제를 수정했다. 현재 소비자는 컴포넌트 갤러리이며 실제 운영 화면이나 실물에서 발생한 장애로 해석하지 않는다.

## 변경

- 검색 필터와 자료 갱신을 기존 `paint()` 경로에서 처리한다. 유효한 선택은 순서·이름 갱신 뒤에도 유지한다.
- 화면에 남지 않는 선택은 내부 값도 비우고 DOM 반영 뒤 `onChange("")`로 알린다.
- 이미 빈 선택인 상태에서 같은 자료를 갱신하면 해제 알림을 반복하지 않는다. 별도 상태 조정 분기·설정·의존성은 추가하지 않았다.
- 같은 규칙을 `DESIGN.md`의 부품 사용 설명에 명시했다.

## 증거

수정 전 `a1f8376013121d1d5087fda75780be8e43b345d1`의 원격 Chromium에서 표시 값은 빈 값인데 이벤트에는 이전 `b`만 남았다. `test_search_choice_keeps_owner_and_visible_selection_in_sync`는 기대한 `['b', '']` 대신 `['b']`를 받아 실패했으며 NEW1/known0/flaky0이었다.

수정 소스 `9c909ff905a78189f8131459b07b7e63f5e8e7b6`에서 다음을 실행했다.

```text
python tools/remote/remote_pytest.py --log-dir <external-log-dir> -- ROSY_RUN_BROWSER_TESTS=1 shared/web/test/test_component_kit_browser.py -v
python test/known_failures.py <external-log-dir>/run-1.txt
node --check shared/web/form-controls.js
```

결과는 **31 passed, 0 skipped, NEW0/known0/flaky0**, 문법 검사 통과다. 회귀는 유효 ID 유지, 필터 해제, 자료에서 삭제, 이미 빈 값인 상태의 재갱신을 실제 브라우저의 선택 값과 호출자 이벤트로 확인한다. 원격 로그는 운영자 외부 보관의 `rosy-search-choice-red-alt/run-1.txt`와 `rosy-search-choice-green/run-1.txt`다.

독립 재사용·품질·효율 및 회귀 가치 검토에 추가 지적은 없었다. 이 기록은 해당 소스와 갤러리 경계를 검증한 것으로, 이후 main 통합 검사·제품 채택·장치 배포·FIELD의 근거를 대신하지 않는다.

CE: 해당 없음. 원인과 재발 조건은 공용 구현·회귀 시험·부품 사용 설명으로 복원할 수 있다.
