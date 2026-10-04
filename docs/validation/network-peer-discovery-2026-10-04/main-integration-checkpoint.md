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

뒤이어 들어온 중앙 DELETE 추가안은 일반 Admin 권한 부재와 영구 등록 정리
소유자 우회가 독립 검토에서 확인돼 활성 경로로 반영하지 않았다. 추가 이력은
보존하며 중앙 조회·실제 객체 보완과 기존 등록 해제 경로를 유지한다. 이 판단과
후속 Admin·EnrollmentService 소유 조건을 D-454에 기록했다.

실제 앱·로스터의 중앙 DELETE 미마운트·등록 정보 불변 회귀를 추가하고 중앙
조회·기존 등록 해제·페어링 40 PASS를 확인했다. 미등록 중앙 DELETE 요청은 기존
GET 경로의 method-not-allowed(405)로 종료하며 로봇 호출이나 등록 변경이 없다.
생산 코드와 승인·영구 등록 소유자는 이전 검토본 그대로 유지된다.

G2 startup 추가안 `4941cfb4f995e894ba33717306ad9c790483ae06`의 자동 home 제출은
초기 UNKNOWN LocalStop을 우회하고 homing 중 StopLocal IPC가 열리지 않는 문제가
독립 검토에서 확인돼 그대로 활성화하지 않았다. 통합 fallback은 자동 home을
제출하지 않고 ActionRunner의 제출을 비활성화하며 기존 StopLocal·상태 조회
IPC를 제공한다. 시작 결과는 `STARTUP_AUTHORIZATION_REQUIRED` HOLD이고 runner는
그 기록을 확인하면 rearm·admit 요청 전에 종료한다. 기존 stop latch를 초기화하거나
자동 rearm하지 않으며 Pilot HTTP 제어와 pending Action 진행도 시작하지 않는다.

이 fallback의 독립 SPEC·Quality·Safety 검토는 PASS다. 시작 homing 완료나 G2
수용을 뜻하지 않는다. 추후 실행에는 명시적인 startup 승인, 기존 열린 authority
epoch·dispatch generation의 최종 `run_if_open` 제출 fence, 정확한 startup goal의
StopLocal 취소 연결이 모두 필요하다. ROS 성공 뒤 신선한 관절 측정과 안정성을
확인하는 기존 helper 검증 10개는 보존했다. fallback 회귀는 실제 ActionApi·
LocalStop·ActionRunner로 승인된 열린 상태에서도 제출 차단·stop 상태 불변·
StopLocal 처리·조회 가능·driver 미제출을 확인했다.

적용된 통합 worktree에서 G2 startup·camera boot guard·native systemd 세 파일을
실행해 206 PASS·기존 Windows POSIX signal 1 SKIP·NEW 0을 확인했다(2.72초).
native systemd는 카메라 11개만의 실행이 아니라 전체 파일 실행이다. 카메라의
독립 검토 범위 9개 boot guard·11개 관련 계약 검증과 이 통합 실행을 중복 합산하지
않는다. 실행 당시 HEAD는 `59f716387960fe6b37adfaf934ad65b8c66ce43c`이고
494 snapshot의 병합과 fallback이 worktree에 적용된 상태였다. 실제 ROS startup,
카메라 boot, 이미지 설치, 원격 CI와 물리 수용은 이 결과로 확인하지 않았다.
정확한 실행 로그는 private `X:/DevTemp/rosy-ui-ship/core/g2-final-applied/run.log`다.

추가 main `36ecf380c`의 학습 계약·정책 설치·Fleet 유지보수 변경을 통합했다.
기존 G2 startup HOLD, 중앙 DELETE 미제공, 승인된 장비 식별과 SSH 신뢰 경계를
유지한다. 학습 등록이나 서명 확인만으로 실행 승인·물리 수용을 부여하지 않는다.
실제 통합 소스의 정책 설치·owner session·중앙 조회·G2·크기 검사 116 PASS를 확인했다.

학습 입력 영상이 export 뒤 바뀌어도 원본 provenance만 확인하던 문제를 보완했다.
실제 reader가 소비하는 프레임을 resize 전에 원본 PNG와 대조하며, 같은 원본 bytes의
해시를 행의 고정 해시와 확인한 뒤 디코딩한다. 기존 RGB 평균 오차 8 허용 범위는
유지한다. 영상 교체와 PNG·영상 동시 교체를 거부하는 반례를 확인했다. 실제 통합
소스의 관련 학습·CI wheel 검사 15 PASS·NEW 0이다. 실제 LeRobot/PyTorch 학습이나
정책 실행·기기 수용은 이 검사로 확인하지 않았다.

CI의 wheel 목록에는 새 learning 계약 패키지를 포함하고 실제 프로젝트 버전에
맞춰 설치하도록 수정했다. 별도 X: 환경에서 실제 wheel 12개 빌드·오프라인 설치·
의존성 검사와 설치된 ROS-free 모듈 import를 확인했다. 이전 버전 핀의 설치 실패를
보존했다. Ubuntu·ROS overlay·최종 커밋의 원격 CI는 별도로 통과해야 한다.

테마·뷰포트 캡처 도구의 로그인 화면 오인도 교정했다. 인증 후 콘텐츠가 표시되는
18개 화면에서 테마·가로 넘침을 확인했으나 합성 환경의 지도 API 404를 숨기지 않아
전체 판정은 LOCAL HOLD다. 해당 회차의 이미지·보고서·정정은
`docs/validation/web-theme-tiers-2026-10-04/`에 있다. 실제 운영자·장비 수용과 구분한다.

추가 D-455 합류 로직에서는 오프라인·상태 미확인·localization 유예 중인 장비를
통행 가능으로 간주하는 문제를 수정했다. 현재 Console 신뢰 판정과 원본 자세를
함께 확인하고, 동료의 위치가 불확실하면 문으로 복귀하는 YIELD·RESUME를 보류한다.
새 신뢰 상태 이후에만 보존된 계획을 판단하며 D-453 불확실 YIELD 재실행 금지는
유지한다. 실제 통합 검사 64 PASS와 알고리즘 17 PASS·NEW 0을 확인했다.
최초 명령의 존재하지 않는 파일 경로 오류는 검증 실패로 보존했고 통과로 합산하지
않았다. 장비 주행은 수행하지 않았다.

수동 ARM payload 벤치는 입력을 환경변수로 받아 검증하고, 정확한 성공 빌드의
소스·workflow·저장소·만료되지 않은 단일 artifact·manifest·checksum을 연결한다.
웹 검사는 같은 GET 응답의 상태·본문·CSP를 확인한다. 실제 통합 host 회귀는
15 PASS·NEW 0이다. 이 워크플로 자체의 최종 커밋 ARM 실행·서명 배포·실물 응답은
별도 검증이며 unsigned hosted process 관측을 기기 수용으로 승격하지 않는다.

추가 중앙 1c 변경 `02dc934a7`은 등록 identity를 직접 수정하거나 실제 연결·gate·
token을 폐기하지 않은 채 revoked로 표시하는 문제가 있어 적용하지 않았다.
검토된 중앙 조회 정본을 유지하고 새 쓰기는 미마운트 상태로 둔다. 새 회귀는 실제
앱·SiteRoster·EnrollmentService·암호화 SQLite로 자격 증명·감사·identity·endpoint의
불변과 로봇 미호출을 확인한다. 실제 통합의 중앙 조회·쓰기 보류·기존 등록 해제·
페어링 검사 49 PASS·NEW 0이다. 기존 실명 사이트 등록·페어링 소유자는 유지한다.

저장소 push 순서의 rebase에서 병합 해결 내용이 생략되어, 독립 검토된 `9be0520bd`
전체 트리를 복원했다. 복원 인덱스의 tree는 해당 검토본의
`5fa31ad82212f2981af0f5a08877c1f24852bb2c`와 정확히 같았고 독립 검토자가 이를
확인했다. 이후 추가 main 변경은 별도로 병합·검증하며 이전 결과를 새 기기 수용으로
확대하지 않는다. 원본 검토 이력은 `verify/ui-ship-reviewed-9be` 로컬 ref에 보존했다.


### LAN 수신 승인·목록 통합과 Fleet 크기 재판정

- D-456은 사용자 선택(LAN 즉시 발견, 최초 상대 승인, QR/코드 보조, 장기 오프라인 관계 보존)을 기록한다. 일반 수신 승인/key proof/로그인 갱신은 아직 구현됐다고 표시하지 않는다.
- 387b19841 통합에서 실제 동일 P6 filter의 Fleet 총계는 32,605행이다. 이전 32,162 대비 기존 307 + 합성 캡처 도구 136을 독립 분해 검토했다. 기존 split/B2·UI 자원 소유 이주 의무·파일 한도·+150 허용량은 유지한다. 기준만 정확한 현재 총계로 재판정하며 기존 실패나 allowance를 숨기지 않는다.
- 2150354e2 캡처 원본은 미렌더링·인증 대기 실패 관측으로 보존한다. 실제 PNG를 root와 독립 검토자가 확인했으며 정상 UX/G3는 HOLD다.


후속 구조 검사에서 캡처136행의 fleet→games 위반을 재현했다. tools/AGENTS.md의 교차 모듈 도구 규칙에 따라 root tools로 이동하고 Fleet 기준을 실제 이동 후 총계32,469로 기록한다. 기존32,605 관측은 잘못된 배치까지 포함한 중간 수치로 보존하며 split·허용량·방향 예외를 추가하지 않는다.


이번 적용 소스 결과: rooms API + P6 구조 + API 버전/Task 문서62 PASS, Mission 버전1 PASS, Native Pilot Kotlin 컴파일/JVM24 PASS, Chrome LAN 목록4 PASS, D-456 문서/위상85 PASS. 초기 소스 크기 실패(32469>32162+150)는 독립 재판정했고 이후 incoming capture의2구조 실패는 workspace tools 소유 경로로 바로잡았다. 일반 수신 승인/key-proof/session renewal과 실제 LAN·tablet·robot 재연결·서명 배포는 여전히 미완료이며 이 host 결과를 그 증거로 쓰지 않는다.
