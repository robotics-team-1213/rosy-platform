# 최신 main 통합과 명령 소유 경계 보완

main commit `2ad04760205a3a485f18aeede44ff57b92c20297`의 Cell 편집·수동 checkpoint·
D451/D453을 D452와 함께 보존했다. API Ref는 각 분기의 v1.94/v1.95에서 통합
v1.96으로 정렬하며 envelope 1.0을 유지한다. 양쪽 journal의 모든 비어 있지 않은
줄이 원래 순서대로 남는지 대조했고 생성 index를 다시 만들었다.

독립 실제 구조 계수는 Fleet 32162, CORE features 12926이었다. Fleet main의
실제 31786은 오래된 verdict 30998보다 788 크며, 새 meet owner653과 기존
resolver/transport wiring135로 설명된다. Cell377·D452376의 독립 소유 근거를
함께 유지했다. CORE의 이전 verdict12723 대비203은 D452 discovery93과
D453 recovery/wiring110이다. 파일별 새 예산 초과는 없으며 기존 600/800 제한·
1000줄 zero-growth·패키지 +150 allowance·B2/UI 분할 의무를 바꾸지 않는다.

독립 Safety 리뷰에서 불확실한 YIELD 재전송과 활성 구간 기한 초기화 위험을
발견했다. Fleet의 unknown/cancel escalation fence와 CORE active guard를
추가했다. 이 보완의 생산 코드 증가는 Fleet7·CORE3이며 기존 allowance 안이다.
최종 actual count는 각각 32169·12929다. 실제 구동이나 E-Stop 해제는 하지 않았다.

병합 후 실제 Cell·chooser 브라우저 16 PASS, 문서 pin3 PASS, CORE 발견 관련
94 PASS였다. 양보 안전 보완 focused Fleet74 PASS/CORE115 PASS이며 통합 담당자
관련 합동 검증과 최종 필수 gate는 별도로 기록한다. 원격 CI·서명 배포·운영자 로그인·
실제 다른 망 및 로봇 연결은 이 source checkpoint의 수락 범위가 아니다.

통합 담당자가 양보·meet·transport의 관련 9개 suite를 별도로 실행해 236 PASS
(13.79초), SKIP 0·NEW 0을 확인했다. 독립 최종 SPEC·Quality·Safety 리뷰는 PASS다.

필수 검사에서 Cell 체크박스의 공용 필드·터치 표면과 검색 중 버튼의 비활성화
이유 누락을 확인해 보완했다. 검색 버튼은 현재 요청이 끝날 때만 이유를 지우며
이전 epoch의 응답이 새 요청을 해제하지 않는다. 수동 절차 테스트의 import는
같은 다섯 경로와 순서를 각각 명시해 목록 문자열을 경로 결합으로 오인하지 않게
했다. 경로 검사기와 allowlist는 변경하지 않았다.

적용 후 공용 UI·수동 절차·원래 경로 검사 45 PASS, Node 요청 수명주기 10 PASS,
Cell·장비 선택·진입 흐름의 실제 브라우저 19 PASS를 확인했다. 이 결과는 소스
회귀 검증이며 새 원격 CI·서명 배포·실제 장비 연결 증거를 대신하지 않는다.

D-454의 초기 중앙 등록 뷰를 통합하며 실제 로스터 property·등록 여부·발견
snapshot의 인터페이스에 맞췄다. 등록되지 않은 장비는 404이고 발견 주소는 기존
승인 endpoint와 유일하게 대조되는 표시 정보만 사용한다. 기존 등록·페어링 경로의
권한과 호출 순서를 유지해 조립을 옮겼다. API Ref v1.97은 opt-in GET 두 경로만
구현으로 표기하고 나머지 중앙 쓰기·명령·미션은 미구현으로 유지한다.

추가 원격 실패 보완: Android의 기존 Gradle property로 runner 임시 경로를
지정했으며 실제 wrapper 인자를 검증했다. 두 Isaac 테스트의 UTF-8 BOM만 제거해
관련 27 PASS였다. CELL_TRANSFER의 initial·reopen fixture는 실제 제어 소유자와
공용 승인 객체를 연결해 33 PASS였고 Pilot 점유 시 grant·journal·phase 미생성을
확인했다. 런타임 승인 가드는 변경하지 않았다. API 문서 관련 8 PASS를 확인했다.

중앙 뷰 관련 첫 실행은 110 PASS·타임스탬프 비교 1 FAIL이었다. 실제 저장 스냅샷과
대조하도록 그 테스트를 보완한 뒤 중앙 뷰 12 PASS를 확인했다. 이를 전체 111개
재실행 결과로 합산하지 않는다. 각 변경의 독립 SPEC·Quality·Safety 소스 리뷰는
PASS이며 원격 Gradle 실행·새 CI·서명 배포·실장비 수락은 별도 증거가 필요하다.

최종 중앙 조립 앱은 586줄이고 Fleet 실제 생산 코드 계수는 32286이다. 기존
verdict32162·allowance150의 상한32312 안이며 26줄 여유다. 이 보완은 D-454
들어온 소스 대비 생산 코드 순증가0이며 기존 두 조립 호출의 AST 인자 값·순서와
공용 권한을 유지한다. 최종 5개 파일 lint 오류0과 독립 해시 대조 PASS를 확인했다.
