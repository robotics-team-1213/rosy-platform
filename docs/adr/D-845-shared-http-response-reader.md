## D-845 공통 HTTP 전송 안에서 화면의 응답 해석을 유지한다

**Status:** Accepted for implementation (2026-10-22). 공유 모듈 후속 구현 지시와 구조·critic 독립 검토 2라운드를 반영한다. 실제 Fleet 소비자 전환·배포·장치 수용은 별도 증거다.

### Context

D-841은 camera-peer의 헤더 시점 권한 처리와 엄격 JSON 해석을 보존할 수 없어 1차 공통 요청 전환에서 제외했다. 기존 createRequest는 오류 응답을 포함한 JSON 파싱 실패와 204를 null로 반환한다. camera-peer는 401/403/404에서 본문을 읽기 전에 화면을 정리하고, 성공 본문의 파싱 실패를 오류로 처리한다.

### Decision

`shared/web/request.js:createRequest` factory에 선택적 `readResponse(response)` 함수 하나를 받는다. 지정하면 fetch 완료와 abort 검사 뒤, 기본 JSON/204/blob 처리보다 먼저 raw Response를 전달한다. reader의 결과는 기존 반환 객체의 body가 되며 오류는 그대로 전파한다. reader 완료 뒤 abort 검사와 timeout·부모 signal 구독의 finally 정리를 유지한다.

reader가 없는 호출의 JSON 오류·204·blob 의미와 반환 `{status, ok, body}`는 바꾸지 않는다. origin·credential·redirect·cache·취소·자동 재전송 없음은 기존 공통 전송의 소유다. 서비스 권한 판단과 오류 문구는 소비자 소유다. reader는 별도 전송 수단이나 실행 권한을 얻지 않는다.

camera-peer 후속 소비자는 요청별 reader closure에서 기존 capture의 `life.check()`를 헤더 처리 전에 호출한다. 부정 응답의 본문을 읽지 않고 기존 권한 정리·오류를 수행하며, 성공은 response.json()으로 해석해 malformed/empty 200·204의 오류를 유지한다. 여러 동시 요청의 lifetime을 하나의 mutable 변수로 공유하지 않는다.

공유 모듈 변경은 제품 소비자 변경과 분리한 main 기반 브랜치에서 먼저 FULL 검증·공식 착지를 수행한다. 기존 D-841 제품 브랜치와 증거를 보존하고 이후 최신 main과 통합한다. 작업 공간은 기존 한 슬롯을 재사용하며 대기열을 우회하지 않는다.

### Alternatives and consequences

기존 fetch 유지가 가장 작지만 전송 중복을 남긴다. strictJson·onHeaders를 각각 추가하면 조합과 호출 순서 계약이 늘어난다. 하나의 reader를 사용해 서비스 해석을 공통 전송의 timeout·취소 수명 안에 두되 해석 정책은 소비자에 남긴다. 잘못된 소비자 reader는 오류를 던질 수 있으며 그 실패를 성공/null로 바꾸지 않는다.

### Verification

기본 JSON/204/blob 호환, custom reader의 결과·오류 보존과 단일 POST, 본문 미소비 거절, 엄격 JSON·204 실패, reader 도중 부모 취소·timeout·구독 정리를 Node로 검사한다. 커밋 후 공식 원격 runner와 기존 실패 비교, 공유 자산 FULL 및 착지 절차를 따른다. Fleet 전환은 별도 실제 panel·브라우저 시험으로 검증한다. HTTP 시험은 물리 관측·실장치·현장 수용을 대체하지 않는다.
