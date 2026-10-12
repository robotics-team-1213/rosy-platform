# 전체 UI/UX 배포·초기 계정 후속 검증

[앞선 소스·회귀 기록](../all-ui-workflows-2026-10-12/result.md)의 후속 실행이다. 이전 실패·설치 관측은 당시 결과로 보존한다. 정보 위치와 로그인·내 계정 규칙은 [확정 UX 설계](../../plans/2026-10-12-platform-ux-conventions-design.md), D-683/D-686/D-689를 따른다.

## 배포 후보와 검사

배포 source commit `7a03bf1bf08e74340220f6e88ce3766f1279f5f3`를 움직이는 공유 main과 별개로 `uiux/header-release-candidate`의 깨끗한 등록 worktree에서 검사·푸시했다. 이후 동료의 커밋은 설치본과 혼동하지 않는다.

| 증거 | 결과 |
|---|---|
| canonical G1 | 반복 회차 5,515 / 5,515 / 5,522 / 261 passed, 각 종료 0·NEW 0. 앞선 세 회차 Console Node 각각 318 passed. 마지막 회차에서 추가 동료 변경까지 통합·착지 완료 |
| 실제 후보 pre-push | 516 + 5,593 + 654 = **6,763 passed**, 각 종료 0·NEW 0, 실제 push 종료 0 |
| [FULL CI 38187980648](https://github.com/robotics-team-1213/rosy-platform/actions/runs/38187980648) | 전체 시험 matrix 및 최종 ci-result 성공 |
| [Android CI 38187980624](https://github.com/robotics-team-1213/rosy-platform/actions/runs/38187980624) | Cam·Pilot 모두 성공 |
| [사이트 후보 빌드 38187980695](https://github.com/robotics-team-1213/rosy-platform/actions/runs/38187980695) | provenance·unsigned 이미지 게시 성공 |
| 서명·설치 | `site-7a03bf1bf08e`의 release.json.sig 게시 뒤 정식 updater 설치 성공. 설치 상태의 commit은 위 전체 SHA이며 이전 버전은 보존됨 |
| 실제 실행 코드 | Fleet 컨테이너 app/password_session/site_auth/site_users 네 모듈 SHA-256이 후보 Git blob과 일치. 첫 비밀번호 변경 guard와 프로필 route 존재 확인 |

시험은 원격 적정 CPU·메모리 기준을 만족한 PC에서 수행했다. 노트북 pytest·브라우저·Gazebo는 실행하지 않았다. 각 pytest 종료 로그를 기존 실패 목록과 비교했다.

## 실제 화면과 계정

팀원 네 계정은 operator 권한으로 발급했다. 초기 비밀번호는 로그인 ID와 같고, 각 계정의 실제 HTTPS 로그인 204 → 세션 operator/변경 필요 → 운영 상태·프로필 API 403 PASSWORD_CHANGE_REQUIRED → 로그아웃 204 → 세션 401을 확인했다. 기계·AI·상태 확인·캡처 토큰 네 개는 변경하지 않았다. 당사자의 최종 비밀번호는 설정하지 않았다.

실제 브라우저에서 Fleet 네 화면을 320/1366px **8조합**으로 열어 identity/status/actions/safety 영역, 가로 넘침 없음, 48px 정지·이동 조작, 브랜드 자산 및 우상단 로그인 위치를 확인했다. 별도 로그인·미인증 프로필 화면은 두 크기로 확인했다. 첫 로그인 변경 form의 빈 입력·초점·320px 가로 넘침 없음, 네 화면의 비밀번호 변경 표시·프로필 링크 숨김, 제한된 프로필 화면 및 로그아웃 뒤 401도 확인했다. 로그인·프로필·공용 헤더 제공 자산 일곱 개와 공용 Fleet client는 후보 blob의 SHA-256으로 비교했다. 실제 설치본 PNG 18개를 보관했으며 좁은 관제·첫 변경 화면을 직접 열어 판독했다.

계정 명단 적용 후 재시작에서 기존 Discord 매핑이 이전 사람 principal을 요구해 Fleet 시작이 실패했다. 비밀번호 변경 전 운영 접근 guard를 완화하지 않고 기존 연동 설정을 보관·일시 중지해 Fleet을 복구했다. 설정 부재를 일반 사용자 권한의 파일 검사만으로 판단한 앞선 기록은 충분한 증거가 아니었다. 사용자 확인으로 해당 이전 계정이 사용자 본인임을 알았으며 본인 계정 복구 방식은 별도로 확인 중이다. 외부 메시지는 보내지 않았다.

## 증거 위치와 한계

공용 비공개 증거 루트는 `X:/DevTemp/projects/rosy-platform/2026-10-12--015344--fleet-header-proof--958a02/`다. `logs/prepush-ci-build/`, `logs/land-ci-build/`, `logs/live-team-screen.txt`, `evidence/team-initial-7a.json`, `evidence/deployed-7a/`에서 원본 로그·설치 상태·PNG를 확인한다. 공개 문서에 계정 명단·자격·사이트 주소를 넣지 않는다.

캡처 실행기의 잘못된 Playwright new_page 인자 및 한국어 predicate 실패는 별도 로그로 보존했다. unauthenticated Cell에서 합성 503을 관측하려던 추가 검사는 실행 경로가 성립하지 않아 통과로 계산하지 않는다. 서비스 장애 복구는 앞선 실제 브라우저 회귀 범위에서 검증했다.

TLS 인증서 신뢰는 확인하지 않았다. 사용자 최종 비밀번호 변경·그 뒤의 실제 개인 프로필 편집, 실물 Robot/Pilot/Cam/LCD 및 실제 작업 수용은 이번 설치 확인으로 대신하지 않는다. 실제 주행·E-Stop 해제·운영 Cell 제안은 실행하지 않았다.
