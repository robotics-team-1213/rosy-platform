# Fleet UI 통합 검사 경로 보완

초기 [검증 기록](result.md)은 그대로 보존한다. 첫 공식 착지 후보 `commit ca2aea7909849d873ed728489564edb38718c4ed`의 전체 회귀에서 제품 코드의 추출을 따라가지 못한 Python 검사 두 곳이 실패했다. 이 기록은 그 보완과 집중 재검증을 다루며 최종 착지 완료를 선언하지 않는다.

- `test_document_imports.py`: DOM 없는 `trip-display.js`를 공유 목록에, `roster-presentation.js`를 Console 전용 목록에 추가했다. 다른 문서의 로스터 접근 금지는 유지한다.
- `test_trip_error_labels.py`: 실제 운행 오류 코드 전수와 비교할 표시 파일을 `shared/site-map-model.js`에서 새 소유자인 `shared/trip-display.js`로 바꿨다. 코드 추출식과 누락 금지 조건은 유지한다.
- `test_ui_contract_guards.py`: 설치 문서가 로스터 표시 모듈을 import하도록 주입하면 기존 소유 검사가 거절하는 대조 시험을 추가했다.

원격 시험 PC에서 커밋 `43bb63930c`는 기존 실패 두 건과 대조 시험까지 3 failed였다. 수정 커밋 `commit 9a2c0be21040f373fbc483ab7af7fbd5619677c7`에서 위 세 검사·소유 계약 두 건·Node wrapper를 실행해 **6 passed/2 warnings, 0 NEW**를 확인했다. known-failure 기준선이나 제품 동작은 바꾸지 않았다. 원시 로그는 Git 밖 작업 기록의 `fleet-ui-boundaries-evidence/logs/contract-red/`와 `contract-green/`에 보존한다.

수정된 전체 후보는 공식 FIFO 착지 검증에서 다시 검사한다. 첫 실행의 실패와 이후 통과는 별도로 기록한다. 배포·push·실물·현장 수용 범위는 늘리지 않는다.

CE: 해당 없음 — 이번 검사 소유 경로 수정과 금지 의존성 보존 판단은 코드·대조 시험으로 설명된다. 초기 기록의 부모 UTF-8 교훈은 별도로 유지한다.
