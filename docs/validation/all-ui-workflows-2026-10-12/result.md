# 전체 활성 UI/UX 정보 배치·작업 흐름 검증

## 첫 로그인·기본 내 프로필 — D-686/D-689

사용자는 팀원 네 명에게만 사람 계정을 발급하고 초기 비밀번호를 로그인 ID와 일치시키되 첫 로그인에서 반드시 변경하도록 요청했다. 기본 프로필은 표시 이름 수정·현재 비밀번호 확인 변경·ID/이메일/권한 조회로 확정했다. 기존 기계·운용·AI 자격은 보존하며 실제 명단·자격을 이 문서에 기록하지 않는다. 서버는 초기 쿠키의 운용 API 접근을 거절하고 기존 SQLite에서 자격·프로필·세션 회전을 관리한다. 네 문서 우상단의 내 프로필은 Map/Cell 새 탭으로 입력을 보존한다.

| 증거 | 결과와 범위 |
|---|---|
| `3704d9615` G1 영향 gate | 첫 묶음 6,511 passed / 1,049 skipped / 2 NEW, 둘째 521 passed / 48 skipped / 3 NEW. 버튼 disabled 사유, Fleet 크기 재판정, 문서 credential 오검출, 새 자산 3개 추가에 따른 wheel/sdist closure 기대를 수정 중이다. 착지되지 않았다. `logs/land-g1/uiux-header-all-surfaces/` |
| `afe5873f1` 강제 변경 UI RED | 2 NEW/known 0. 미구현 서버 전제의 강제 변경 시나리오와 D-686 prose 오검출을 확인했다. 같은 묶음의 지도 충돌 3개 크기·사유·wheel/sdist 검사는 통과했다. `logs/first-login-ui-red/run-1.txt` |
| `a7cf1b28a` 통합 첫 변경 | 2 NEW/known 0. 브라우저의 암시적 단일-page context와 long-ID 시험 fixture가 scanner에 걸린 것을 수정했다. 전체 묶음은 통과로 표시하지 않는다. `logs/first-login-integrated/run-1.txt` |
| `7ae3c7a67` 프로필 UI RED | 서버를 합치기 전 6 NEW/known 0, 네 진입 경로/비밀번호/실패 복구 시나리오의 미구현 endpoint를 확인했다. `logs/self-profile-ui-red/run-1.txt` |
| `73b23b956` 프로필·전체 인증/문서 호출자 | 적정 AI PC 22 cores/9 GB에서 173 passed, 종료 0, NEW 0. `logs/profile-green/run-1.txt` |
| `70e970acb` 잘못된 Unicode 입력 수정 | 같은 자격 원격 PC에서 프로필 20 passed, 종료 0, NEW 0. 단일 surrogate 거절과 기존 이름 보존, 정상 한국어/emoji 수용. `logs/profile-surrogate/run-1.txt` |
| 독립 검토 | D-686 원본 설정 변경 세션 무효화, D-689 Unicode 경계, 키보드 초점, 만료 시 비밀 삭제와 타 탭 계정 변경을 발견하고 수정했다. 수정된 서버 명세/품질과 UI에 추가 blocker 없음. 실제 시험과 배포 증거를 대신하지 않는다. |

`83c2a49fd` 통합 브라우저/인증/자산 검사는 통과했으나 비밀 탐지 1 NEW가 남아 전체 실패였다. 변수 참조와 이미 허용된 합성 fixture 표현을 정리하고 탐지 기준을 유지했다. `e592eb8e8` 최종 인증/프로필/실제 Chromium/disabled 사유/비밀 탐지/P6는 143 passed, 종료 0, NEW 0이다 (`logs/profile-final/run-1.txt`, 적정 AI PC 22 cores/9 GB). 최신 main 영향 gate·해당 SHA CI·서명·설치·실제 팀원 발급은 아직 확인하지 않았다. 당사자 대신 최종 비밀번호를 정하지 않았고 실제 첫 변경·실물 수용을 완료로 추정하지 않는다.

## 계정 규칙 후속 정리 — D-683

[공식 참고와 배치 근거](../../plans/2026-10-12-platform-ux-conventions-design.md)를 조사하고 [D-683](../../adr/D-683-fleet-account-entry-and-login-return.md)으로 Fleet 계정 진입 규칙을 채택했다. 네 문서의 우측 로그인/계정, `/console/login`, 허용된 업무 주소 복귀, 서버 세션 확인, 쿠키 로그아웃 결과 검증을 기존 인증 API로 구현했다. 지도·Cell 로그인은 새 탭으로 열고 원래 업무 입력을 보존한다. CORE 권한과 명령을 추가하지 않는다.

| 증거 | 결과와 범위 |
|---|---|
| `2180826c3` 원격 인증 회귀 | 21 passed / 2 failed. 옛 내장 폼 전제와 접힌 토큰 클릭을 수정했다. `logs/account-login-first/run-1.txt` |
| `ab05a034c` 원격 확장 | 66 passed / 2 failed. 390px 안전 그룹 오른쪽 정렬 결함과 지도 보기 선택을 수정했다. `logs/account-login-corrected/run-1.txt` |
| `b9145fa9b` 원격 인증·전체 지도·헤더·백엔드 | 169 passed / 8 failed, NEW 8. 인증/계정은 통과했으나 전체 묶음은 실패다. 재접속 후 편집 선택의 Apply gating 복원, 인증 확인 후 고급 접속 접힘, 새 계정 노드를 포함한 Node fixture를 수정했다. 충돌 초안을 버리는 옛 기대는 로컬 입력 보존과 기존 CAS 거절 검증으로 바꿨다. `logs/account-login-final/run-1.txt` |
| `b9145fa9b` 루트 관제 헤더·개발/paired 연결 | 4 passed, 종료 0, NEW 0. `logs/account-root-header/run-1.txt` |
| `d3dac3633` 전체 Console Node | 312 passed, 종료 0. `logs/account-node-all.txt` |
| `d3dac3633` 수정 후 인증·전체 지도·관제 헤더 | 95 passed / 1 failed, NEW 1. 반복 재접속이 끝나기 전에 펼침을 여는 경쟁 조건을 수정했다. `logs/account-map-restored/run-1.txt` |
| `440385e24` 같은 브라우저 묶음 | 95 passed / 1 failed, NEW 1. 실패는 대기 helper의 문자열 predicate가 CSP eval 거절을 받은 것이며 CSP를 유지하고 함수 predicate로 수정했다. `logs/account-map-settled/run-1.txt` |
| `0d01b320c` 재접속·편집 보존·충돌 최종 | 5 passed, 종료 0, NEW 0. 반복 재접속, 적용 전/후 편집 보존과 3개 크기 충돌 후 CAS 거절을 실제 조작으로 확인했다. `logs/account-reconnect-final/run-1.txt` |
| `06ce50c4a` Android proxy | JVM/assemble BUILD SUCCESSFUL, 실제 번들 proxy 브라우저 1 passed, 종료 0, NEW 0. 앞선 403은 시험의 고정 쿠키 이름을 앱의 세션별 이름으로 전달해 해결했다. Guard와 신원 확인은 보존한다. `logs/pilot-proxy-cookie/run-1.txt` |
| 독립 소스 검토 | `440385e24` 계정/편집 복원과 `06ce50c4a` proxy fixture에 추가 blocker 없음. 현재 검증된 역할로 편집 조작을 복원하며 원래 revision의 CAS를 보존한다. 읽기 전용 검토이며 배포/브라우저 통과를 대신하지 않는다. |

증거 경로는 공용 세션 `X:/DevTemp/projects/rosy-platform/2026-10-12--015344--fleet-header-proof--958a02/` 기준이다. `evidence/account-screens-final/`의 10개 PNG는 시험 서버의 로그인 및 네 계정 메뉴 320/1366px 관측이며 설치본 증거가 아니다. 해당 계정 시나리오는 `b9145fa9b`와 후속 묶음에서 통과했다. 실패한 전체 묶음을 통과로 합산하지 않으며, 나머지 95개 통과와 마지막 5개 재접속 통과를 각 SHA/범위로 구분한다.

현재 계정 변경의 main 착지·push·해당 SHA의 CI·서명·설치·실물 수용은 아직 확인하지 않았다. 아래의 과거 설치 관측과 혼용하지 않는다.

## 범위와 정보 위치

사용자 요청은 Fleet 네 화면의 공용 헤더에서 모든 활성 UI의 본문·작업 흐름까지 확대되었다. 기준은 `shared/web/surfaces.yaml`, D-658, 기존 표면별 계약이다. 변경은 `uiux/header-all-surfaces`에서 통합했다. 공유 main의 다른 작업은 수정하지 않았다.

| 화면 | 정보가 그 자리에 있는 이유 | 이번 변경 또는 유지 근거 |
|---|---|---|
| Fleet 관제·설치·지도·Cell | 상단의 제품·현장은 작업 대상을 식별하고, 연결·권한은 가능한 행동을 설명한다. 알림·접속은 보조 조작이며 비상 정지는 계속 노출된다. 본문은 각 역할의 작업을 맡는다. | 기존 D-658 공용 헤더를 네 화면에서 검증했다. 명시된 아이콘 전용 속성을 보존하도록 공용 부품 회귀를 고쳤다. |
| Cell 준비·저장·미리보기·제안 | 단계 안내는 다음 작업을 설명한다. 미구성 안내와 비활성 이유는 서버 작업을 다시 눌러도 해결되지 않는 원인을 알려 준다. | 미구성 응답 뒤 서버 작업을 차단하고 구성 확인 사유를 표시한다. 로컬 입력·접속·비상 정지는 유지하며 정상 재접속 뒤 복구한다. |
| Robot 접속·운용·작업 준비·설치 정비 | 제품·화면 이름은 현재 역할, 권한 표시는 가능한 작업, 본문의 실패 안내는 재시도 경로를 설명한다. | 역할 이름과 접근성 설명을 정리했다. manifest 실패에 수동 재시도를 제공하며 좁은 화면에서 권한 표시 잘림을 막았다. |
| Pilot 웹 접속·조종 | 대상·비상 정지는 가장 먼저 보인다. 연결·지도 근거와 접속 안내는 다음 줄, 현재 대상과 로그인은 최근 기록보다 먼저 둔다. | 잘못된 최근 기록과 다른 대상 기록을 제외하고 이전 토큰을 제거한다. 지연·끊김·증거 없음은 현재 정지로 표시하지 않는다. 안전 정지 보고는 safety evidence로 판정한다. 연결 상태와 검색 요약의 겹침을 막았다. |
| Learning 작업·객체·픽셀·자료 | 첫 줄은 자료 검수의 역할과 화면 설정, 둘째 줄은 작업 전환이다. 본문은 출처·초안·저장·승인을 구분한다. | 320px에서 세 줄로 늘어나던 헤더를 두 줄로 정리하고 픽셀 화면의 테마 설명을 맞췄다. 기존 검수·승인 흐름을 회귀 검사했다. |
| Pilot Android | 로비는 대상 발견·선택·접속을 담당한다. 함께 조종 버튼 바로 아래는 차단 이유와 다음 행동을 설명한다. | 기존 활성 조건과 같은 연결 가능 수·발열 상태로 안내를 표시한다. 좁은 로비에도 Pilot 정체성을 남긴다. |
| Cam Android | 영상이 중심이고 송출 상태·설치·복구는 기존 전용 영역에 둔다. | 역할별 소스 검토 후 기존 배치를 유지했다. 실물 송출·승인 확인은 별도다. |
| 경기 보드 | 경기 단계·수신 근거는 상단, 점수·관측은 본문, 두 로봇 정지와 요청 결과는 고정 조작 영역에 둔다. | 기존 역할과 지연·끊김·정지 요청/확인 구분을 유지하고 브라우저 회귀에 포함했다. |
| 로봇 LCD | 작은 표시 장치에서 로봇 정체성·부팅·로그인 코드를 판독하도록 기존 표시 문법을 쓴다. | 소스 검토와 기존 그림 회귀에 포함했다. 입력 권한이 없는 매체에 웹 조작을 복제하지 않았다. |

PARKED 진단과 개발용 시뮬레이터를 활성 제품 화면으로 바꾸지 않았다. 상세 native 검토는 `docs/validation/uiux-native-games-2026-10-12.md`에 기록했다.

## 원격 회귀와 검토

시험은 커밋된 HEAD를 원격 시험 PC에서 실행했다. 브라우저 시험은 `ROSY_RUN_BROWSER_TESTS=1`로 활성화했고, 적정 CPU·메모리 placement만 허용했다. 각 종료 로그에 `test/known_failures.py`를 적용했다. 노트북 pytest는 실행하지 않았다.

| 대상 | 커밋 | 결과 | 증거 |
|---|---|---|---|
| Fleet 헤더·역할·Cell / 공용 아이콘 / Learning 검수·픽셀 / 경기 보드 / LCD | `fbd51016f9` | 342 passed, 종료 0, NEW 0 | 공용 세션 `logs/combined-fixed/run-1.txt` |
| Robot/Pilot 전체 관련 회귀 | `039bbbffa` | 176 passed, NEW 0 | Robot/Pilot 작업 세션 원격 로그 |
| Pilot 상태 신선도·잘못된 기록·토큰 제거 | `e01abed518` | 27 passed, NEW 0 | Robot/Pilot 작업 세션 원격 로그 |
| Learning 네 화면 작은 헤더 + Cell 미구성·복구 캡처 | `70cf1fd7c8` | 9 passed, NEW 0 | 아래 공용 세션 `logs/captures-fixed/run-1.txt` |
| Pilot Android 단위 검사·APK | `b3b44ca1a`의 native 변경 | BUILD SUCCESSFUL, 106 tests, 0 failures/errors | `X:/DevTemp/native-ux-a1f3c9/gradle.txt`, XML 및 debug APK |

독립 검토는 Cell·공용 변경과 Robot/Pilot 변경을 각각 검토했다. 오래된 속도를 현재 정지로 단정하던 발견 사항은 기존 `HeadlessState`를 재사용해 수정했고 재검토에서 차단 사항이 없었다.

초기 실패도 보존했다. Cell 재접속 시험의 접힌 접속 버튼 클릭은 기존 펼침 helper로 수정했다. 캡처 실행의 잘못된 원격 사용자 홈 경로는 임시 실행기에서 수정했다. 둘 다 NEW로 분류했으며 기존 실패 목록에 추가하지 않았다. 자원 기준 미달 fallback 실행은 적정 자원 확인 증거로 계산하지 않는다.

## 변경 후 화면 캡처

공용 증거 세션은 `X:/DevTemp/projects/rosy-platform/2026-10-12--015344--fleet-header-proof--958a02/`다. `evidence/shots/`의 Learning 네 화면 320×568·390×844와 Cell 390×844·1440×900을 보관했다. Learning 320px 작업·픽셀 화면과 Cell 390px 화면을 직접 열어 역할·다음 행동·서비스 미구성 안내를 확인했다. 파일별 SHA-256은 같은 세션의 `evidence/capture-sha256.csv`에 기록한다.

## 실제 설치본 확인과 남은 경계

현재 사이트의 Fleet 컨테이너 source revision은 `5f4040f306bf076648993376ed85834824e8d744`였다. 해당 설치본 `/console`, `/console/install`, `/console/site-map`, `/console/cell`을 1366px·320px에서 직접 열었다. **8 조합**에서 네 헤더 영역, 가로 넘침, 48px 정지·이동 조작, 글자/여백, 브랜드 자산 응답을 확인했다. `evidence/live/result.json` 및 8 PNG가 관찰 기록이다. TLS 인증서 신뢰 확인을 생략하는 브라우저 옵션을 사용했다. 이 기록은 새 변경의 배포 증거가 아니다.

이번 브랜치의 main 착지·push·CI·서명 릴리스·새 설치는 수행하지 않았다. 저장소 「같이 하는 깃」 6항의 명시 지시가 필요하다. 로봇 접속 실패와 ADB 기기 부재 때문에 실물 Robot·Pilot·Cam·LCD 및 실제 작업 수용은 미확인이다. 비상 정지 해제·주행·페어링·Cell 작업 제안 같은 운영 변경으로 화면 검사를 대신하지 않았다.

## 최종 후속 검증

- `a2357a8504`: responsive tiers, UI token contracts, document placement, folder layout 원격 **64 passed**, 종료 0, NEW 0. 공용 세션 `logs/contracts/run-1.txt`.
- Robot/Pilot 원격 세션: `X:/DevTemp/projects/rosy-platform/2026-10-12--020319--robot-pilot-ux--7d7d85/`. 위 176/27 결과의 정확한 위치는 `logs/browser/run-1.txt`, `logs/captures/run-1.txt`다.
- `ab2f331a4`: Robot 전체 캡처 **3 passed**. `432e39895`: Pilot 겹침·Robot 권한 잘림 회귀 **8 passed**. `855e5b46a`: Robot 입구의 권한 한 줄 회귀 **3 passed**. 모두 종료 0, NEW 0이며 각각 같은 세션의 `logs/robot-captures`, `logs/visual-final`, `logs/entry-final`에 있다.
- 마지막 캡처에서 Robot 입구 권한이 세로로 쌓이던 문제를 발견해 기존 공용 wordmark의 container sizing과 권한 nowrap으로 수정했다. 부모 통합 커밋은 `e6bcbb960`이며 후속 회귀가 해당 소스 변경을 검증했다.
- 같은 세션 `evidence/browser/`에 Pilot 4 화면 크기 × 빈 목록/읽기 실패 8장, Robot 입구·운용·작업 준비·설치 정비 320/390 총 8장을 보관했다. 통합 담당자도 Robot 입구·작업 준비 및 Pilot 실패 화면 320px를 직접 열어 권한 판독·본문 다음 행동·비상 정지 노출을 확인했다.
- 변경하지 않은 Cam·LCD·경기 보드의 기존 배치는 역할 검토를 통해 유지했다. 경기 보드·LCD의 초기 원격 호스트 미확인 기록은 이번 통합 회귀 342 passed의 범위에서만 해소되었다. 실물 장치와 설치된 게임 호스트 검증은 여전히 별도다.

## 승인 후 통합 검사와 발견 사항

사용자는 위 최초 기록 이후 main 착지·push·새 버전 배포 검증을 명시적으로 승인했다. 진행 목표는 `docs/plans/2026-10-12-field-ui-recovery-brief.md`의 현장 운용·오류 복구이며 추가 승인 대기 상태가 아니다.

- `80a12948c`의 적정 자원 전체 영향 검사에서 첫 묶음은 독립 검토의 공용 예외 보존 결함을 재현한 뒤 중단했다. 종료 2, 15 failed / 7204 passed / 68 skipped이므로 이 묶음 전체를 통과로 계산하지 않는다. 두 번째 묶음은 249 passed로 정상 종료했지만 도구는 착지하지 않았다. 원본은 공용 세션 `logs/land/uiux-header-all-surfaces/run-1-1.txt`, `run-1-2.txt`다.
- `known_failures.py`는 관측한 15건을 NEW로 분류했다. 위치 순서에 의존하던 로봇 조작 선택, 이전 헤더 접힘 가정, 지도 저장 응답을 기다리지 않던 관측, 공용 연결 오류의 변경된 안내를 실제 목적·계약과 맞춰 고쳤다. 기존 실패 목록에 추가하지 않았다.
- 공용 오류 어댑터의 null 취소 이유, frozen TypeError, read-only DOMException은 새 Node 세 사례에서 모두 실패했다. 예외 객체·취소·비재전송을 보존하는 수정 뒤 요청 계약 포함 36 passed다. 독립 검토는 동일 수정안을 재검토해 추가 차단 사항이 없음을 확인했다.
- Android 앱 proxy 시험은 Linux에서 Windows 전용 gradlew.bat·JAVA_HOME·X 경로를 사용해 PermissionError로 실패했다. 파일 blob은 기준·main·후보에서 같지만 깨끗한 main 실행 증거 없이 기존 실패로 승격하지 않는다. Linux의 기존 Java/Gradle wrapper는 확인했고 SDK/고정 의존 캐시 준비와 portable 실행 보완이 필요하다.
- Pinky 두 대 오프라인 및 ADB 연결 기기 부재를 다시 확인했다. 실물 화면·사용자 작업 수용을 완료로 표시하지 않는다.
