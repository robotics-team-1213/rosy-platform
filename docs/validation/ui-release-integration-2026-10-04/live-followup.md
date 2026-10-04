# Android 실기 후속 확인 (2026-10-04)

이 기록은 같은 폴더의 README.md 이후 관측이며 이전 결과를 대체하지 않는다.

## Cam 화면 보호와 영상 지속

최종 진단 UI APK SHA-256: `6c297ace0ffc7c2f677f31baf35a0bc1086bfd77d327f61be2661ca974ada9ab`.
기존 서명을 유지해 업데이트했고 설치 전후 설정 파일 SHA-256이 같다.
실제 기본·진단 펼침 사진을 직접 확인했다. 경기장 전체 영상과 상태가 보이고
진단 버튼 및 하단 화면 끄기·설정·중지 접근이 유지된다.

이후 Android thermal status 3에서 화면 보호 안내로 전환되고 power 상태가
Dozing인 것을 관측했다. 이 상태를 깨우거나 설정을 바꾸지 않고 기존 CA를
검증하는 20초 runtime debug frame:read lease로 두 프레임을 조회했다.
독립 수신 확인은 HTTP 200/200, sequence 2126→2132, capture time +2.085초,
age 286/205 ms, 1280×720 및 rotation 90이었다. 두 이미지 모두 밝은 실제
경기장 영상이다. 화면 잠듦과 촬영·전송 지속을 각각 관측한 증거다.

사진과 원시 receipt는 X 드라이브의 `rosy-ui-ship/vision-live/thermal-sleep-*`에
보존한다. 수신기의 실행 revision은 기존 후보이며 이번 통합 소스의 사이트 배포
수락이 아니다. 일반 operator 인증 API 및 설정 화면 전체 점검도 별도다.
사진 이후 UI XML에서 화면 보호 전환이 관측되어 설정 화면 점검은 완료하지 않았다.

## 로봇 접속 경계

Pilot 연결 실패 후 카드 비활성 상태가 남는 문제는 목록 cache를 무효화하여
terminal refresh에서 현재 후보·TTL·주소 충돌·발열 정책에 따라 다시 구성하도록
수정했다. HTTP 후보에는 전원·같은 Wi-Fi·재시도 안내를 표시하고 secure 후보에는
기존 신뢰된 HTTPS 확인 안내도 유지한다. 신뢰 정책을 완화하지 않는다.

최종 Pilot APK SHA-256: `ebfc297a0332c4c366381e27374a18e5c256ca8fbebf40b82ff9fda8baef4701`.
JVM 46 PASS, 기존 서명, 공용 20개·Pilot 29개 자산 일치 및 설치 APK hash 일치를
확인했다. 독립 source SPEC·QUALITY PASS 이후 실제 실패→활성 카드→같은 카드
직접 재시도→다시 실패해도 활성 상태→다시 찾기로 목록 복귀를 확인했다.
실패 사진을 직접 확인해 안내가 잘리지 않고 HTTP에 HTTPS 주장이 없음을 확인했다.
페어링 코드 입력·생성이나 제어 시작은 실행하지 않았다. 원시 증거는 X 드라이브의
`rosy-ui-ship/pilot-discovery/connection-ux/`에 보존한다.

공통 반응형 규칙 정렬 후 Pilot APK를 다시 빌드·설치했다. 이 후속 설치의 APK
SHA-256은 `90e6ee38fe887062a815ab95fb5c893b9dcc797bef1027c21e8bc235455836e4`이며
설치 파일 hash, 기존 서명 및 공용 20개·Pilot 29개 자산 일치를 확인했다. Native
소스 6개는 이전 JVM 46 PASS 및 실패 재시도 검증과 동일하다. 실제 가로 목록에서
1대와 활성 카드를 확인했다. manifest는 가로 고정이며 실제 세로 화면은 미실행이다.
로봇 접속 실패로 Web gate에 도달하지 못해 CSS의 물리 화면 확인으로 주장하지 않는다.

반응형 실패 검사 1 PASS, 3개 상단바 × 639/800/1023/1200px의 12 DOM 측정에서
가로 넘침이 없다. Pilot/template는 실제 idle page이고 compatibility robot 상단바는
무인증 dashboard에서 숨겨지므로 원본 markup의 격리 정적 fixture로 측정했다.
실제 인증된 전체 화면 수락과 구분한다. 분기 정렬 이유는 D-359 추가 결정에 기록했다.

검색 광고 해석은 복구됐지만 PC·관제 PC의 key-only SSH와 같은 Wi-Fi 태블릿의
기존 광고 대상 TCP 연결은 시간 초과 또는 경로 오류였다. 목록 표시를 실제
CORE 연결이나 native payload 배포 성공으로 기록하지 않는다. 기존 장비 신원·키·
가입 정보를 유지하며 유지보수 검사를 통과하려고 정지 해제나 구동을 실행하지 않는다.

후속 key-only SSH에서 켜진 장비의 신원과 기존 릴리스를 읽는 데 성공했다.
접속은 여전히 간헐적이다. 실제 서비스는 activating/start-post, NRestarts 0이며
CORE 포트의 listener는 없었다. journal은 최근 두 부팅에 걸친 시작 기록을 보여준다.
왜 시작 단계가 완료되지 않는지는 별도 진단 중이며 안정된 연결·배포·동작 수락으로
기록하지 않는다. 재부팅이나 정지 해제·모드 변경 없이 상태와 시작 로그를 확인한다.

## 병합된 인식 변경의 증거 범위

이번 main 동기화는 기존 원격의 ArUco corner refinement radius 2를 보존한다.
이전 radius 3 검증을 최종 소스의 결과로 재사용하지 않는다. radius 2의 독립
OpenCV 5 / 실제 4.6 API·합성 pose 확인은
[원격 인식 수정 검토](../d427-source-migration/wave5-ci-fixes-independent-review-2026-10-04.md)에
기록돼 있다. 합성 fixture 결과는 실제 로봇 정확도 수락과 구분한다.

## 전체 웹 화면 점검의 실제 전제

기존 CA를 검증하는 사이트 HTTPS 조회에서 `/console`·`/console/install`은 200이며
무인증 `/api/fleet/session`은 401이다. 정상 named operator의 원본 token 또는
승인된 browser state가 없어 인증된 전체 운용 화면 평가는 보류한다. runtime debug
Vision lease를 operator 로그인 증거로 사용하지 않는다.

사이트 proxy에서 `/board`·`/games`·`/tools`는 404다. Games는 별도 laptop host의
`/` 또는 `/index.html`이 소유하며, 독립 `/tools` 웹 경로와 CORE styleguide 및
dashboard_drive CLI를 혼동하지 않는다. 6개 page owner·19개 CORE 작업의 소스/경로
목록과 브라우저 CA 지원 제한을 X 드라이브 `vision-live/walkthrough/`에 보존했다.
기존 CA를 우회하거나 자격증명을 발급하지 않았다. 이 public shell 확인은 새 통합
소스의 배포 증거나 인증된 전체 화면 UX 수락이 아니다.

## 영향 검사에서 발견한 실패의 수정

원본 broad pre-push 로그를 보존하고 확인된 실패 항목에 한정해 재현·수정했다.
대시보드 자산·확인창·SLAM·첫 조회·bridge 검사 6 PASS, Fleet queue/stylesheet 검사
2 PASS, 반응형 규칙 검사 1 PASS였다. 폐기 경로와 이전 구현 문자열을 현재 구조에
맞추면서 자산의 실제 응답·확인/취소·세 동작의 CORE endpoint·capability·조회 owner·
왼쪽 queue 배치·페이지별 정확 CSS 목록 조건을 유지했다. 독립 source 검토 PASS다.

모드 도구는 실제 확인창을 처리하지 못하는 동작 문제였으며 도구와 해당 검사만
수정했다. 전역 native 자동 승인을 제거하고 요청한 모드의 확인창·승인 버튼 자체를
고정한다. prompt와 소유권을 검사한 뒤 그 버튼만 클릭하고 결과를 조회한다.
검토에서 발견한 live locator 교체 문제는 실제 DOM 창 교체 회귀로 수정했다.
교체된 다른 창 승인 0·POST 증가 0, 확인 전/취소 POST 0과 IDLE 요청/readback을
검사해 최종 1 PASS, focused 0 NEW 및 독립 SOURCE Safety PASS를 확인했다.
실제 로봇의 모드·정지·구동 명령은 실행하지 않았다.

상세 원본·수정 로그는 X 드라이브 `core/`와 `fleet-cam/contract-tests/`에 보존한다.
이 focused 결과는 최종 전체 영향 검사·원격 CI·실제 운용 수락을 대신하지 않는다.

## 영향 검사 종료 및 추가 계약 회귀

원본 pre-push는 fast462 PASS/2 Linux SKIP 후 첫 영향 묶음에서12 failed/11858 passed/583 skipped, 인식·Vision 묶음2869 passed/109 skipped로 종료하여 push되지 않았다. 12건 모두 해당 원본 실패 로그에서 확인했다. 카메라 panel의 공유 evidence 정본 경로 회귀1 PASS, native confirm 금지와 recursive panel 공용·scoped 확인 소유자 정확 file/count 회귀3 PASS를 추가했다. 기존 확인/취소 동작 및 정지 권한은 유지한다. 이것은 수정 이후 최종 전체 영향 검사나 원격 CI 통과 주장이 아니다.
