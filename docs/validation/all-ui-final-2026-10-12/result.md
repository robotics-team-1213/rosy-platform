# 현장 운용·오류 복구 UI 최종 설치 확인

[전체 화면·작업 흐름 기록](../all-ui-workflows-2026-10-12/result.md), [최초 사이트 설치](../all-ui-deployed-2026-10-12/result.md), [지도 저장 관측 보완](../all-ui-ci-map-save-2026-10-12/result.md)의 후속 실행이다. 과거 실패·승인 대기·설치 관측은 당시 결과로 보존한다.

## 요구와 증거 범위

| 요구 | 근거와 관측 |
|---|---|
| 현재 대상·확인된 상태·막힌 이유·복구 행동·실제 결과 | [현장 운용 목표](../../plans/2026-10-12-field-ui-recovery-brief.md), [확정 UX 규칙](../../plans/2026-10-12-platform-ux-conventions-design.md), D-683/D-686/D-689. 공식 디자인 시스템·접근성 근거와 화면별 정보 위치를 문서화함 |
| 모든 활성 표면의 본문·작업 흐름 | surfaces inventory에 따른 Fleet·Robot/Pilot·Learning·Cam·LCD·경기 보드 검토와 표면별 원격 회귀·캡처. 출처·초안 보존·권한·신선도·요청/완료 구분을 검사함. 변경하지 않은 매체는 유지 이유를 기록함 |
| 적정 원격 회귀·독립 검토 | 설치 후보의 pre-push 6,763 passed 및 독립 소스 검토. 지도 저장 관측 보완은 수정 전 NEW 재현 → 실제 Chromium 두 크기 2 passed → native_games_ui 독립 승인 → 통합 5,433 passed/282 skipped → pre-push 추가 291 passed. 종료 0·NEW 0을 각 로그로 구분함 |
| main 착지·푸시 | 지도 시험 보완 통합 commit `8977f25dad`를 정식 착지 도구와 설치된 pre-push를 거쳐 실제 push 종료 0으로 반영함. 이후 문서 커밋과 설치 소스는 구분함 |
| 동일 설치 SHA의 CI·서명·릴리스 | 현재 설치 source commit `6a73839f03b919bd7e35dbcb554b973d09af5d40`: [전체 CI](https://github.com/robotics-team-1213/rosy-platform/actions/runs/38189023185), [사이트 후보 빌드](https://github.com/robotics-team-1213/rosy-platform/actions/runs/38189023197) 성공. [릴리스](https://github.com/robotics-team-1213/rosy-platform/releases/tag/site-6a73839f03b9)의 서명 게시와 정식 updater 설치 상태를 확인함 |
| 실제 설치 화면·제공 자산 | 위 source commit의 실행 인증 모듈 네 개·공용 client·로그인/프로필/헤더 자산 일곱 개가 Git blob과 일치함. 적정 AI PC의 실제 Chromium에서 Fleet 네 화면 320/1366px 8조합, 로그인·미인증 프로필 두 크기, 첫 변경·제한된 네 화면·제한된 프로필을 다시 확인함. PNG 18개와 SHA-256 목록을 보관함 |
| 실물 미확인 표면 | Robot/Pilot/Cam/LCD의 실제 접속·송출·판독·주행·작업 수용을 GO로 표시하지 않음. 원격 소스·브라우저·APK/단위 검사 증거와 구분함 |

후속 지도 시험의 [전체 CI 38191711128](https://github.com/robotics-team-1213/rosy-platform/actions/runs/38191711128)는 모든 시험 matrix와 최종 ci-result가 종료 success로 확인됐다. 이전 commit `9076d86f28`의 CI 실패는 통과로 계산하지 않는다. 실제 설치본은 그 실패한 문서 commit과 다른 검증·서명된 source commit이다.

## 계정과 외부 연동의 현재 상태

새 팀원 네 계정은 operator 권한이며 초기 비밀번호는 각 로그인 ID와 같다. 현재 설치본에서도 네 계정 각각 로그인 204 → 변경 필요 세션 → 운영 상태·프로필 API 403 PASSWORD_CHANGE_REQUIRED → 로그아웃 204 → 세션 401을 다시 확인했다. 실제 첫 변경 화면은 빈 새 비밀번호·확인 입력, 입력 초점, 좁은 화면 가로 넘침 없음 및 원래 작업으로 복귀를 확인했다. 당사자의 최종 비밀번호는 설정하지 않았다.

앞선 사람 계정 정리에서 사용자 본인 기존 계정을 제외한 것은 잘못된 판단이었다. 현재 명단을 재조회하니 본인 계정은 기존 principal과 operator 역할로 다른 작업에서 이미 복구돼 있었다. 사람 계정은 팀원 네 명과 본인 한 명이며 기계 토큰 네 개도 유지된다. 복구된 본인 자격을 추가로 초기화하지 않았다. 본인 비밀번호를 알지 못하므로 본인 로그인 성공을 대신 주장하지 않는다.

명단 변경과 충돌했던 기존 Discord 설정도 다른 작업에서 복원되어 파일이 존재하고 replies_enabled가 true임을 읽기 전용으로 확인했다. 이 UI 검증에서는 설정을 재활성화하거나 외부 메시지를 보내지 않았다. 실제 Discord 메시지·사용자 작업 수용을 이 기록으로 대신하지 않는다.

## 원본 위치와 남은 수용 조건

비공개 증거 루트는 `X:/DevTemp/projects/rosy-platform/2026-10-12--015344--fleet-header-proof--958a02/`다. 최신 설치 화면·JSON·SHA-256 목록은 `evidence/deployed-6a/`, 이전 설치는 `evidence/deployed-7a/`에 있다. 실행 로그는 `logs/live-6a-public-screen.txt`, `logs/live-6a-team-screen.txt`, `logs/map-save-green/`, `logs/land-ci-build/fix-ui-save-proof/`, `logs/prepush-map-save-proof/`로 구분한다. 공개 기록에 명단·비밀번호·사이트 주소를 넣지 않는다.

TLS 인증서 신뢰는 확인하지 않았다. 사용자 최종 비밀번호 변경 뒤의 실제 개인 프로필 수정, 실물 Robot/Pilot/Cam/LCD 및 현장 작업 수용은 당사자·장치와 함께 확인해야 한다. 이 검증에서 실제 주행·E-Stop 해제·Cell 작업 제안은 실행하지 않았다. 대기 상태·요청 접수·시험 서버 성공을 실물 완료로 바꾸지 않는다.
