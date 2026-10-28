# Learning·Pilot 상태와 조작 일관성

기준 `ed62eb6f5e`, 화면 동작 소스 `948ebd2723`, 시험 보완 `11074b355e`·`f7eaca4b3b`, Pilot 캐시 버전 `cdbab06b42`다. `fix/robot-pilot-learning-ux`에서 작업했다. 기존 공용 `ui-status`·`ui-button`·`ui-actions`, 폼·오류 소유 패턴을 사용하며 새 토큰·의존성·API·ADR은 추가하지 않는다.

| 발견 | 수정 |
|---|---|
| 사진·지문·관절을 바꿔도 이전 녹화 가능 판정과 측정값이 남음 | 입력 변경 즉시 판정·수치를 지우고 재판정을 안내한다. 기준 변경도 진행 중 응답을 무효화한다. |
| 사진 디코딩/서버 응답 중 입력을 바꾸면 이전 결과가 새 입력을 설명함 | 첫 await 전에 기준·파일·지문·관절을 묶고 generation이 같은 결과만 표시한다. 판정 중 중복 제출을 막고 입력 변경 시 새 판정을 허용한다. |
| 카메라·평가 조회 실패 뒤 확인 중 상태가 남고 복구 동작이 없음 | 같은 다시 확인 버튼과 pending→error/empty/ready 흐름을 제공한다. 재조회는 폼의 최신 입력을 보존하고 POST를 재실행하지 않는다. |
| 승격 요청의 실패·성공 문구가 이전 시도와 섞임 | 조회 오류와 요청 오류를 따로 소유한다. 새 요청은 이전 결과를 숨기며 성공 시 이전 요청 오류를 지운다. 후속 평가 근거 조회가 끝나기 전에는 요청 버튼을 활성화하지 않는다. |
| Pilot 설정 변경이 패널 전체 DOM을 바꿔 키보드 초점을 잃음 | 같은 버튼에서 pressed·라벨만 갱신한다. 열기 시 현재 프리셋으로 초점을 옮기고 Escape로 도구에 돌아간다. 입력 매핑·명령·상한은 유지한다. |

## 검증

pytest는 승인된 시험 PC의 커밋에서만 실행했다. 사람 라벨·실물·운영 서비스는 사용하지 않았으며 임시 합성 ReviewStore, 합성 사진, HTTP 지연/오류 fixture를 썼다. 기존 CV2 알고리즘·승격 HTTP 핸들러를 합성 입력으로 검사하는 브라우저 회귀도 포함한다.

| 실행 | SHA | 결과 |
|---|---|---|
| 정상 fixture RED | `ffe32ff816` | 34 failed, 2 passed. 기존 기준 변경 무효화2건은 원래 정상이며 나머지 상태/초점 실패를 재현 |
| 느린 평가 조회 RED | `0b8b469870` | 1 failed, 26 deselected. 활성 버튼 무응답 구간 |
| 최초 GREEN | `948ebd2723` | 35 passed, 6 failed. 6건은 닫힌 details 안의 필드를 채우려던 fixture timeout |
| 집중 GREEN | `11074b355e` | 42 passed, skip0, NEW0. 카메라 읽기 중 최신 편집 보존과 기존 정상2화면 포함 |
| 공식 영향 | `948ebd2723` | 3994 passed, 601 skipped, NEW0/known0/flaky0; affected, FULL escalation/미매핑 없음 |
| 최초 공식 브라우저15파일·8묶음 | `948ebd2723` | 418 passed/6 failed/skip0. 7번의 닫힌 폼 fixture6건을 미수용으로 보존하고 아래 전체 재검증으로 대체. 나머지7묶음은392 passed |
| 7번 묶음 전체 재검증 | `f7eaca4b3b` | 33 passed, skip0, NEW0. 닫힌 폼을 실제로 열고 오류를 화면에 보이게 촬영하며 추가 동시 편집 시험 포함 |
| Pilot 셸·서빙 | `cdbab06b42` | 7 passed, skip0. 기존 캐시 버전을 바꿔 설정 수정 자산을 다시 설치하도록 함 |

유효한 최종 선택의 합계는425 passed, skip0, NEW0/known0/flaky0이다. 7번 전체를 교체했으며 최초 실패를 삭제하거나 같은 로그의 끝에 성공 결과로 덮지 않았다. `948ebd2723`과 최종 시험의 HTML·JS·CSS 소스는 같고 기존 assertion은 유지한다.

최초 `db213a478f`의25 failed에는 PNG fixture의 잘못된 IDAT CRC가 섞여 있었다. 기존 합성 scene을 `cv2.imencode`로 만들어 정상 입력에서 RED를 다시 재현했다. 원본 `red/`, `valid-red/`, `promotion-red/`, `green/`을 덮어쓰지 않았다. `948ebd2723` 이후 화면의 HTML·JS·CSS는 같고, 후속 제품 변경은 `sw.js`의 캐시 키 한 줄이다. 나머지는 fixture·추가 검사·촬영 위치이며 기존 assertion을 유지했다.

원본 로그와 캡처는 외부 `C:/DevTemp/rosy-ui-product-consistency/`에 보존한다. `green-final/`, `affected/`, `browser/`, `browser-corrected/`를 별도 원본으로 취급한다. 영향 검사의601 skipped는 브라우저 opt-in·환경 조건 등의 미실행 검사이며 통과 건수에 넣지 않는다.

## 독립 점검과 범위

impeccable의 A 설계/소스와 B detector/화면 평가는 분리했다. A는 카메라 입력·응답과 읽기 실패 상태, B는 Pilot 키보드와 승격 요청 안내를 지적했다. 구현 검토에서 느린 후속 조회 중 활성 버튼도 찾아 수정했다. 최종 `ed62eb6f5e..11074b355e` 소스 검토에는 남은 P1/P2가 없었다.

B는 최종 PNG41/41장 전체(Camera 입력 무효화8·Camera 오류/복구12·평가 오류/복구12·Pilot 키보드9)를 실제 확인했다. Camera 오류 캡처는7번 재검증에서 오류를 화면 안으로 가져온 뒤 다시 받았다. 작성자도 Camera403/390px와 Pilot320px 프리셋 초점을 직접 확인했다. 검토 범위에서 남은 P1/P2는 없었다. 초점 테두리와 상태의 시각 검증은 위 기능 시험과 구분한다.

최초와 최종16 markup detector는 모두 warning5/advisory1(exit2)였다. 동적 이미지 자리4건과 Robot styleguide에 한정된 유형/문구 권고였고, 공유 stylesheet 경로 해석 제한이 있어 운용 화면 결함으로 간주하지 않았다. 원본은 `detect-final.json`·stderr·exit로 보존한다. `captures.sha256`·`reports.sha256`는 외부 PNG와 최종 수용 로그의 바이트 해시다.

CE: 해당 없음 — 상태 수명·입력 snapshot·DOM 보존의 판단을 코드·회귀·이 기록에서 복구할 수 있다. 기존 카메라 readiness 교훈은 실물 producer 소유의 조건이며 이번 합성 UI 검사를 장치 수용으로 확대하지 않았다.

카메라 기하·판정 알고리즘·라벨 정본·승격 자격·명령 owner를 변경하지 않았다. 실제 녹화·장치 정지·모델 평가·HF 쓰기·APK/ARM64 빌드·배포·병합/게시 수용은 수행하지 않았다.
