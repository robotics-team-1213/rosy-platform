# Fleet 계정 영역의 표시·재조회 레이아웃 검증

2026-10-28. 제품 source commit `ae4771b936`, 기준 commit `b2b4beaaea`. 사용자가 제공한 ‘토큰으로 접속’ 줄의 화면별 출현과 버튼 조작 중 레이아웃 불일치를 조사·수정했다. 기존 임시 브랜치를 재사용했으며 이전 병합 요청은 별도 immutable snapshot이라 이 추가 수정이 자동 포함되지는 않는다.

## 원인과 수정

관제는 development 모드, 설치는 development 사용자, Cell/지도는 저장 토큰 존재 여부에 따라 같은 토큰 폼을 따로 숨겼다. 기본 마크업은 숨김 없이 시작했다. 공통 `showSession`은 같은 사용자 상태를 다시 읽을 때도 계정 상세를 닫았다. 따라서 같은 인증 상태에서도 화면별 표시가 다르고, 상태 재조회가 사용자가 열어 둔 영역을 접어 높이를 바꿀 수 있었다.

네 문서의 토큰 폼을 초기 hidden으로 통일하고 인증 완료/접속 해제 때의 표시를 공통 헤더가 관리하게 했다. 인증된 상태에서는 불필요한 토큰 폼을 숨기고 세션 해제 시 재접속 기능을 복원한다. 같은 사용자·역할의 재조회에서는 계정 상세를 유지하며 새 인증·사용자 변경 때만 접는다. 페이지별 중복 숨김은 제거했다. 사용자가 명시적으로 계정/접속 안내를 여는 동작과 Escape 초점 복귀는 유지한다. 인증 전송·권한·비상 정지 규칙과 CSS의 의도적 반응형 배치는 변경하지 않았다.

## 실제 검증

pytest는 모두 공식 원격 runner로 source commit을 전송해 승인된 모델/AI 시험 호스트에서 실행했다. 실제 운영 장치·토큰을 사용하지 않는 fixture HTTP 서버와 Chromium이다. 로그 루트는 `C:/DevTemp/`다.

| 범위 | 결과 | 로그 |
|---|---|---|
| 4문서×320/1440 인증 후 토큰 표시 RED | 8 failed / 3 deselected | fleet-account-layout-red/run-1.txt |
| 전체 공통 헤더·토큰 세션/만료·안전 표시·새 안정성 회귀 | 14 passed / skip0 | fleet-account-layout-green/run-1.txt |
| 비밀번호 로그인 | 1 passed / skip0 | fleet-account-password-green/run-1.txt |
| 공식 영향 선택53대상 | 8043 passed / 757 skipped | fleet-account-layout-affected/run-1.txt |

선택 명령은 `python tools/harness/rosy_harness.py affected --base b2b4beaaea --json`이며 affected/no escalation이다. 원본 선택은 `C:/DevTemp/fleet-account-layout-affected.json`, 실제 실행은 `remote_pytest.py --affected-json <selection> --log-dir <dir>`이다. Chromium 실행에는 runner의 `--` 뒤에 `ROSY_RUN_BROWSER_TESTS=1`을 지정했다. 세 GREEN 로그의 known_failures 비교는 모두 NEW0 / known0 / flaky0이다. 757 skip은 해당 실행에서 브라우저·SDK 등 조건부 시험을 실행했다는 뜻이 아니다.

새 회귀는 실제 토큰 로그인, 열린 계정의 동일 identity 재조회, 토큰 폼 숨김, 헤더 높이 변화<=1px, 가로 넘침 없음, Escape 초점 복귀를 네 문서/두 폭에서 확인한다. 첫 RED 뒤 재조회 fixture에도 명시적 Bearer를 보내도록 보강했으며 제품 인증 검사는 완화하지 않았다. 기존 개발 모드 헤더·여섯 크기·접속 상실·비상 정지 잠금 표시·재인증 시험도 유지했다. 실제 정지 명령의 장치 수용을 뜻하지 않는다.

## 화면·리뷰·한계

[PNG8장과 SHA](evidence/captures.md)를 보존하고 독립 에이전트가 전부 열어 확인했다. 320px에서도 상단 한 줄의 계정/비상 정지가 잘리지 않으며 네 화면에서 추가 토큰 줄이 없다. 1440px에서도 헤더 위치가 일치한다. 캡처는 Escape 뒤 닫힌 상태이므로 열린 메뉴의 높이 안정성은 기능시험 assertion 근거로만 판정한다. 독립 소스 리뷰에 추가 P1/P2 지적은 없다.

Source까지 size_range3 commits checked. 운영 서비스 설치·배포, 실물 비상 정지, 모든 Fleet 작업/전체 접근성 수용은 수행하지 않았다. 이 기록 이후 문서·생성 색인만 추가하며 최종 문서 검사는 작업 기록에 연결한다.

CE: 해당 없음 — 표시 소유권과 반복 인증 상태 유지 판단이 공통 코드·브라우저 회귀로 복원된다. 별도 해결 교훈을 늘리지 않는다.
