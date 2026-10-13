## D-469 검수 웹은 원본 이미지를 ETag 재검증으로 다시 받고, 미분류 승인을 화면에서 먼저 막는다

**Status:** Accepted (2026-10-05, 사용자 웹 성능·오류 안내 개선 및 ADR 기록 요청). 반복 검수 체감 개선 결정이며, 착지·push·실행 상태는 이 문서가 아니라 커밋과 테스트 결과에서 확인한다.

### Context

D-459/D-461/D-462의 검수 앱에서 반복 작업 규모가 커졌다(355 표현 / 353 영상). 점검 결과 세 가지 반복 비용과 두 가지 안내 공백이 확인됐다.

- 모든 응답이 `Cache-Control: no-store`라 원본 사진을 매 요청마다 전체 재전송한다. 픽셀 검수 저장 후 재진입, 객체 검수의 저장·이동마다 사진과 thumbnail이 다시 내려온다.
- 픽셀 브러시는 포인터가 움직일 때마다 원본 크기 전체 `getImageData` 순회와 지우개용 오프스크린 캔버스를 다시 만든다. 대형 사진에서 브러시가 끊긴다.
- 객체 검수 사이드바는 상태 하나가 바뀔 때마다 thumbnail DOM을 전부 다시 만들어 위 재전송을 유발한다.
- 서버 검증 오류("known object class required" 등)가 영어로 그대로 노출된다. 학습 작업 화면은 한국어 매핑이 있는데 객체·픽셀 화면에는 없다.
- 미분류 박스는 캔버스에서 같은 색으로 그려져 구분되지 않고, 승인 시점에야 서버 영어 오류로 발견된다.

D-465 계획(2026-10-05 model-pc-pixel-label-pipeline) Task 3/7이 같은 파일을 수정할 예약이다. 이 결정은 그 계획이 정한 기능(초안 임포트 표시 등)을 침범하지 않는 국소 변경이다.

### Decision

1. **이미지 GET은 저장 후 재검증이다.** `GET /api/images/<index>`, `GET /api/mask-images/<index>`는 `no-store` 대신 `Cache-Control: no-cache`와 ETag(원본은 `image_sha256`, 마스크는 인코딩된 PNG 바이트 sha256)로 응답한다. 서버는 매 요청마다 디스크 바이트를 읽어 hash를 검증하며 일치하면 304로 본문을 보내지 않는다. 변조 감지 시점과 강도는 그대로 두고 전송만 줄인다. 나머지 응답(JSON API·정적 파일)은 기존 `no-store`를 유지한다. query의 `?v=` 버전 파라미터 관행은 그대로다.
2. **렌더링 계층을 클라이언트에 캐시한다.** 픽셀 검수의 마스크 오버레이 채색은 (마스크 version, 불투명도, 테마) 키로 캐시하고 지우개 획은 하나의 스크래치 캔버스에 합성한다. 포인터 이동마다 전체 픽셀 순회를 반복하지 않는다. 모든 좌표는 기존대로 원본 이미지 좌표다.
3. **사이드바 목록은 구성원이 같으면 다시 만들지 않는다.** 필터로 보이는 사진 목록이 바뀔 때만 thumbnail DOM을 다시 구성하고, 상태 변경·저장 후에는 배지와 선택 상태만 갱신한다.
4. **오류 안내는 한국어로, 승인 차단은 화면에서 먼저다.** 서버 영어 검증 메시지는 객체·픽셀 화면에서 한국어 안내로 매핑한다(학습 작업 화면 `readableError` 패턴 확장). 미분류 박스가 있으면 승인 버튼을 사전에 막고 이유를 보여주며 캔버스에서 다른 색으로 그린다. 서버 검증은 최종 방어로 변경 없음이다.
5. **계약 문서를 같은 변경에 맞춘다.** `learning/training/perception/docs/review-app.md`의 이미지 응답 설명에 재검증 캐싱을 반영하고, `review_app.py` docstring의 깨진 `review_app.md` 참조를 실제 문서(`docs/review-app.md`)로 바로잡는다.

| 기존 구조 결정 | 이번 적용 |
|---|---|
| D-427 learning/operations/middleware | 소스는 기존 `learning/training/perception/dataset`와 그 테스트에 둔다. 새 최상위 파트를 만들지 않는다. |
| D-429 판단·제어·통신 관심사 | 로컬 검수 도구의 화면 동작만 바꾼다. CORE API·통신 계약은 변경하지 않는다. |
| D-430 안전 분리 | safety anchor·cmd_vel·E-stop을 만지지 않는다. host 결과는 DEVICE/FIELD 수용이 아니다. |

### Consequences

- 반복 검수에서 사진 재전송·재변환이 사라져 저장 직후 반응과 브러시 부드러움이 좋아진다. 원본 무결성 검증은 요청마다 그대로 실행되므로 변조된 파일은 여전히 승인·전송에서 거부된다.
- 새 엔드포인트(thumbnail·리사이즈 API)는 만들지 않는다. thumbnail은 여전히 원본 바이트를 내려받되 304로 재전송을 피한다.
- 브라우저 시험(`test_review_flow_browser.py`)의 필터·되돌리기·stale 탭 흐름과 `pageerror` 0 요구는 그대로 유지한다. 서버 304 경로는 host pytest로, 화면 동작은 browser suite(환경이 허락할 때)로 검증한다.
- D-465 계획 Task 3/7과 같은 파일(`review_app.py`, `pixels.js/html`)을 만지므로 diff는 국소로 유지하고, 그 계획의 소유 범위(초안 임포트·학습 화면 확장)는 침범하지 않는다.

### Alternatives and consequences

`no-store` 유지는 반복 검수 체감 문제를 그대로 두므로 기각했다. `max-age` 캐싱은 재검증 없이 지난 기간의 변조를 숨길 수 있어 기각했다. 서버 메모리 이미지 캐시는 검증 우회 우려와 관리 비용으로 기각했다. 새 thumbnail API는 HTTP 계약 확장이고 D-465 계획과 같은 영역을 미리 침범하므로 이번 범위에서 제외했다.

### 실행 계획

1. `test_review_app.py`에 이미지 ETag 304 재검증 시험을 먼저 추가해 실패를 확인한다.
2. `review_app.py`의 이미지 GET에 `no-cache`+ETag+304를 구현한다.
3. `pixels.js` 오버레이 캐싱·지우개 합성, `app.js` 목록 부분 갱신·오류 매핑·미분류 사전 차단과 캔버스 강조를 구현한다.
4. `learning/training/perception/test` 전체와 known_failures 비교, 가능하면 browser suite를 돌린다.
5. `docs/review-app.md`와 docstring 참조를 갱신하고, ADR 파일·Log 행과 함께 커밋한다.
