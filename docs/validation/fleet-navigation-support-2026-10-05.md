# Fleet 목표·대형 주행 지원 검증

브랜치: `fix/fleet-navigation-support`. 범위와 남은 현장 작업은
[작업 계획](../plans/2026-10-05-fleet-goal-formation-support.md)을 따른다.

## 소스·호스트

- 기능 조회·전송·대형 세션·HTTP·UI 계약의 관련 Python 회귀: 180 PASS.
  `X:/DevTemp/rosy-fleet-browser/regression-ready.txt`.
- 표시 순수 함수 Node 시험: 3 PASS.
- 실제 로컬 Chromium에서 수동 전용 장치의 목표·대형 버튼 차단과 지원 장치의
  버튼 활성화를 확인했다(2 PASS). 기능 확인 함수를 무조건 허용하도록 변이하면 수동
  장치 시험이 FAIL한다. `browser-mutation.txt`에 1 FAIL·1 PASS를 보존했고
  원본 복원 뒤 `browser-restored-green.txt`의 2 PASS를 확인했다.
- 목표 기능 조회 중 대형 편입, 교체된 클라이언트의 표시 캐시 재등록,
  미지원 양보 지점 전송, ARMING 팔로워의 개별 목표 전송은 각각 RED를 먼저
  확인하고 수정했다. 새 코드에 맞춘 시험 대역은 상태·기능만 읽으며 동작을 숨기지 않는다.
- 독립 리뷰: 초기 세 경합/누락 수정 후 PASS. ARMING 예약 추가도 PASS이며
  독립 Python 회귀 54 PASS. 리뷰 범위는 소스 안전성이고 장치 수용은 NOT VERIFIED.
- 전체 Fleet 최초 실행: 2,140 PASS·28 SKIP·9 FAIL. 실패는 이번 변경에 따른
  시험 대역(CAP-001, 예약 팔로워)과 API Ref 버전 고정의 영향이었다.
  그 영향 범위 전체를 수정 후 재실행해 157 PASS, 0 NEW를 확인했다.
  문서 버전 관련 추가 회귀는 34 PASS다. 전체 suite를 처음부터 다시 실행한
  결과를 전체 PASS로 주장하지 않는다. 원본은 `fleet-full.txt`, 수정 후는
  `final-affected-green.txt`, 버전 회귀는 `api-version-green.txt`에 있다.
- Harness lint: 0 ERROR·21 WARNING(기존 검증 시점 경고). Fleet 전체 flake8은
  기존 파일 오류가 남아 PASS가 아니다. 이번 신규 Python 파일의 두 공백 오류는 수정했다.

PowerShell 리디렉션의 UTF-16 출력 때문에 UTF-8로 읽는 known_failures 도구가
실패를 0 NEW로 표시한 회차가 있었다. 그 값을 통과로 취급하지 않았고 pytest
실패를 직접 고쳤다. 보고서를 UTF-8로 변환해 다시 비교한다.
최종 관련 회귀는 실패 없이 180 PASS다.

## 통합 후 배포 전 확인

main 변경 통합과 origin/main 재정렬 후 pre-push fast gate는 487 PASS·2 SKIP·
3 FAIL이었다. 이번 문서 minor 변경에 필요한 FastAPI 설명 v1.105 정합은
RED 1 FAIL을 재현한 뒤 3 PASS로 수정했다. 나머지는 규모 재판정 누락이었다.

독립 검토의 물리 줄 측정은 Fleet 36,444, console.py 1,198, session.py 616이다.
기존 Fleet 36,234에서 증가한 210줄은 이번 변경 101줄과 통합 main 109줄이다.
transport의 CAP-001 조회, session의 대형 생명주기, console의 gather·dispatch와
UI readiness 책임을 유지한다. 따라서 Fleet는 기존 split 과제를 유지하고,
console은 mutable roster·목표 bookkeeping과 붙은 39줄을 accept 재판정하며,
session은 단일 생명주기 616줄을 accept로 기록한다. 독립 리뷰 source safety PASS다.

600/800/1000 기준, 1000 초과 파일의 성장 허용 0, 패키지 +150과 일반 파일
+150은 변경하지 않았다. 규모 판정은 threshold 완화나 현장 수용이 아니다.

## 실기

사이트 Fleet·Vision·proxy의 health, 두 로봇의 인증된 온라인 상태와 CAP-001을
확인했다. 기존 enrollment·credential을 유지했다. 두 장치의 짧은 수동 주행에서
엔코더 이동을 읽었고 최종 재조회는 모두 IDLE·linear 0·angular 0·E-Stop false다.
임시 장치 인증은 각 logout 204로 폐기했다. 이 조회는 새 주행 명령을 보내지 않았다.

새 후보는 사이트에 배포하지 않았다. navigation 서비스, 점유 지도와 공통 위치
증거가 없어 목표·대형 시험은 NOT_RUN이다. 독립 현장 수용은 HOLD다.
첫 장치의 브라우저 정지 지연 관측은 G4 한계 검증을 대신하지 않는다.
