# 공용 폼 부품의 네이티브 유효성·초기화 검증

파일 선택 오류와 브라우저 폼 유효성을 일치시키고, 네이티브 폼 초기화 뒤 파일·날짜·검색 선택의 표시와 호출자 상태를 맞췄다. 현재 세 부품의 소비자는 컴포넌트 갤러리다. 실제 운영 화면·실물에서 발생한 장애로 해석하지 않는다.

## 변경

- 파일 형식·크기 오류를 `setCustomValidity`로 네이티브 폼 검사에도 연결한다. 올바른 파일과 선택 해제 시 오류를 푼다. 서버 검증은 유지한다.
- 공용 `afterFormReset`이 브라우저의 기본 초기화가 끝난 다음 작업에서 기존 검증·표시 경로를 호출한다. 초기화 취소, 다른 폼으로 옮김, `dispose()` 뒤에는 늦은 콜백을 막고 리스너를 해제한다.
- 검색 선택은 명시적인 미선택 기본 항목을 사용해 초기화가 첫 대상을 자동 선택하지 않게 한다. 호출자가 준 빈 값 항목의 이름은 보존한다. 현재 네이티브 선택을 읽어 초기화 이후의 더 새로운 명시적 선택을 덮지 않는다.
- 기존 파일·날짜 검증과 검색 `paint()`를 재사용했다. 새 의존성·자산·컴포넌트 종류·서버 API는 추가하지 않았다.

## 재현

`d5083dd93e`에서 JSON 파일 오류가 보이는데도 실제 form.checkValidity가 true여서 파일 회귀가 실패했다(NEW1).

`deaaa8f6e6`에서 form.reset 뒤 파일 오류와 선택이 남아 초기화 회귀 2건이 실패했다. 폐기 뒤 콜백 방지 사례 1건은 통과했다. 이 과정에서 `reset` 이벤트가 값 초기화보다 먼저 발생하므로 같은 이벤트 안에서 이전 값을 읽으면 안 된다는 경계를 반영했다.

## 최종 검증

검증 소스 commit: `92a3d65cfe89e79ffd35f8e7d3f7463009127a9f`.

```text
python tools/remote/remote_pytest.py --log-dir <external-log-dir> -- ROSY_RUN_BROWSER_TESTS=1 ROSY_JOB_CORES=1 shared/web/test/test_component_kit_browser.py -v
python test/known_failures.py <external-log-dir>/run-1.txt
```

승인된 원격 시험 PC의 실제 Chromium에서 **35 passed, 0 skipped, NEW0/known0/flaky0**이었다. `ROSY_JOB_CORES=1`은 직렬 브라우저 작업의 자원 예약이며 시험 선택·단언을 줄이지 않는다.

회귀는 형식 오류·크기 초과의 폼 차단, 수정·선택 해제·초기화 후 복구, 취소된 초기화 유지, 날짜 오류 해제, 선택 해제, 초기화 뒤 새 선택 보존, 초기화 직후 dispose의 늦은 콜백 차단을 포함한다. 나머지 기존 공용 부품 회귀도 같은 실행에서 통과했다.

재사용·품질·효율·회귀 가치의 독립 검토에 추가 지적은 없었다. 외부 원격 로그는 운영자 보관의 `rosy-file-picker-red/run-1.txt`, `rosy-native-reset-red/run-1.txt`, `rosy-native-controls-green/run-1.txt`다. 중간 75ad264d34 실행은 호스트 점검으로 미실행이었으며 통과 근거로 세지 않는다.

이 결과는 공용 부품과 해당 소스의 합성 브라우저 검증이다. 이후 main 통합 검사·실제 제품 채택·GitHub CI FULL·배포·장치·FIELD를 대신하지 않는다.

CE: 해당 없음. 값 초기화의 시점과 재검증·해제 조건은 공용 헬퍼 주석·부품 설명·회귀·이 검증 기록에서 복원할 수 있다.
