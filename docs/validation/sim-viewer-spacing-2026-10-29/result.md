# SIM 레인 뷰어의 공용 간격과 긴 결과 배치

2026-10-29 · `fix/sim-viewer-spacing` · 기준 `1bae8682470c` · runtime `a8ab9974ce00` · 최종 경계 시험 `61f475246c64`.

## 변경과 적용 범위

등록된 lane-live-view는 개발용 read-only 뷰어이며 제품 셸·명령 조작을 소유하지 않는다. 기존 구조에서 헤더·상태·카드·폼 없는 결과 표의 임의 간격52줄을 기존 space/gap/inset 역할로 치환했다. 일반 tag corner와 결과 행의 focus 폭·offset도 기존 토큰을 소비한다. 긴 실행 tag와 사유가 화면을 밀어내는 문제는 td/dd wrapping과 상세 grid의 minmax(0,1fr)로 고쳤다. 텍스트를 지우거나 가로 clipping으로 숨기지 않는다.

기존 HTML은 grandfathered856줄이며 전후856줄로 유지했다. script3블록·body 전체·map/runplot/spark의 SVG style22개가 기준과 동일함을 비교하고 해시를 보존했다. 상태·결과 reader·조회·좌표·경로·지도/영상 비율·명령 경로를 바꾸지 않았다. 새 공용 토큰이나 의존성은 없다.

의도된 예외의 owner는 SIM, 정본은 `shared/web/surfaces.yaml`의 lane-live-view와 해당 scripts다. 등록된1000/640px breakpoint, 최대1600px와7fr/5fr 배치는 개발 도구의 배치 제약이다. SVG 선폭·dash·표식·화살표·지도 좌표, spark/gauge/진행 막대의 크기와 corner, 범례 swatch, phase 연결선·상태 점은 도형 표현으로 유지한다. 남은 raw gap3px는 `.keys`의 구간 진행 도표다. 1px 선은 hairline이며 일반 focus 표시는 공용 토큰이다. NO DATA/stale 줄무늬는 영상 부재 표식이고, offline의 비활성 데이터 표현은 안내와 구분해 검토했다. 이를 일반 버튼·패널의 예외로 확장하지 않는다.

## 시험 기반 보완

기존 브라우저 fixture는 HTML 디렉터리만 제공해 /common 자산이404였다. 이제 production make_handler의 실제 `/`·manifest allowlist·커밋의 공용 자산·실제 결과 reader를 사용한다. 합성 fixture는 카메라 없이 MJPEG만503으로 즉시 닫고, CORE poll/ROS 노드/명령은 시작하지 않는다. 실제 YAML 지도를 읽되 경로 계산은 바꾸지 않는다. 서버 shutdown/close/thread join을 finally에서 수행한다.

긴 결과는 production reader가 받아들이는 mission 디렉터리와 results.json을 pytest 임시 경로에 만든다. 조회 실패는 runs.json 요청을 차단한 반례다. 기존 탭·진행률 검사는 유지하고 dark/light ×320/390/1280/2000 ×empty/long/error의24개를 추가했다. 공용 자산200·custom element 정의·48px 탭·탭/결과 행 키보드·전체 폭을 검사한다. 최종8개 긴 결과에는 자체 scroll width와 카드/viewport 경계 검사를 함께 적용했다. 기존 [자식 식별자 clipping 교훈](../../solutions/logic-errors/page-overflow-guards-miss-clipped-child-identifiers-2026-10-27.md)을 적용한 것이며 새로 일반화한 규칙은 없다.

## 원격 실행

원본 scratch는 `C:/DevTemp/rosy-ui-standardization/`이다. reports/captures manifests의 경로는 그 디렉터리 기준이다. 모든 pytest는 승인된 시험 PC에 커밋 SHA를 전달해 실행했다.

| SHA / 로그 경로 | 결과와 해석 |
|---|---|
| `7a445f049b`, sim-spacing-before/run-1.txt | browser 환경 플래그 미지정으로10 skip. 실제 렌더 통과로 세지 않음 |
| `189b9661f7`, sim-spacing-styled-before/run-1.txt | 명시 browser 환경에서10 pass. production handler의 실제 index route로 보완한 시험 |
| `1f54bbd171`, sim-spacing-after/run-1.txt | 간격 치환 후10 pass/0 skip |
| `1f54bbd171`, sim-spacing-affected/run-1·2.txt | Gazebo328 pass/12 skip, 공용 계약505 pass/45 warnings. 이후 추가한 긴 결과의 증거로 쓰지 않음 |
| `aa9ac1033c`, sim-spacing-long-red/run-1.txt | 긴 결과8 failed/18 deselected. 두 테마·네 폭 모두 페이지 가로 넘침 반례 |
| `a8ab9974ce`, sim-spacing-final/run-1.txt | 26 passed/0 skipped. 최종 캡처32장 |
| `a8ab9974ce`, sim-spacing-final-affected/run-1·2.txt | Gazebo328 pass/28 skip, 공용 계약505 pass/45 warnings. 합833 pass/28 skip이며 CI/FULL·실제 Gazebo 실행은 아님 |
| `61f475246c`, sim-spacing-card-bounds/run-1.txt | 8 passed/18 deselected/0 skip. 동일 runtime에서 카드 내부 clipping 경계 추가 |
| `61f475246c`, sim-spacing-skip-reasons/run-1.txt 및 sim-spacing-skip-details/run-1.txt·junit.xml | 각각328 pass/28 skip. skip 이유를 얻기 위한 재실행이며 통과 수에 합산하지 않음 |

통과 로그는 known_failures NEW0/known0/flaky0이며 부분8개와 전체26개·반복10개를 합산하지 않는다. `-rs` 출력만으로 이유가 나오지 않아 JUnit XML을 실제 회수해 확인했다.28 skip은 browser 환경 미지정26개와 test_gz_multi_core/test_gz_multi_run_spec의 collection skip2개다. 후자는 `launch`가 ROS 2 대신 이 패키지의 launch 디렉터리로 해석돼 기존 guard가 막은 것이다. 이를 ROS launch 검사 통과로 바꾸거나 guard를 약화하지 않았다. 브라우저26개를 명시 실행한 결과와 optional browser skip을 구분한다. reports17개와 PNG32개 해시를 원본과 대조한다.

## 독립 검토와 캡처

최종32장은 두 테마·네 폭마다 live/empty/error/long 한 장씩이며 fullpage로 보존했다. 캡처를 remote job 임시 경로 밖의 명시 디렉터리에 쓰고 로컬 복사와 해시를 확인했다. A는 source와 최종 경계 시험을 독립 검토해 추가 P1/P2를 찾지 못했다. B는32/32장을 직접 보고 좁은 화면의 긴 이름·사유, 넓은 두 열, 빈 결과/오류 구분, 탭과 결과 행 초점을 확인했으며 필수 수정할 P1/P2는 없었다. Root도 dark320 긴 결과와 light1280 라이브를 직접 확인했다.

B의 최종 detector는 실제 실행 exit0/warning0/advisory4다. radius3건은 범례·분포·진행 막대의 데이터 도형이고, stripes1건은 stale/NO DATA 표식이다. /common CSS 경로를 로컬 detector가 해석하지 못해 색·custom property 검사는 불완전하며 전체 디자인 검사 통과로 부르지 않는다. 실제 자산과 스타일은 브라우저와 공용 계약에서 따로 확인했다. fullpage 캡처만으로 실제 스크롤 조작·전체 키보드 순서·복구 성공을 주장하지 않는다.

## 게이트와 CE

소스와 합성 HTTP/Chromium 근거다. 실제 ROS·Gazebo 미션·CORE·로봇·장치·FIELD·설치/배포·착지·공개 push/merge 수용은 아니다. native/LCD 전체 계약과 생성/설치 소비자·최종 전수 이행표·브랜치 통합 검증은 남아 있다.

CE: 해당 없음 — 기존 clipping 교훈을 경계 시험에 적용했고, 간격·wrapping·실제 자산 fixture의 원인과 해결은 코드·회귀·이 기록에서 복원된다. 중복 교훈은 만들지 않는다. Questions skipped: 사용자가 전수 개선을 이미 요청했으므로 다음 범위는 기존 이행표를 따른다.
