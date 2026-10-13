# 로그인·프로필·TLS 비실물 후속 검사

[이전 전체 UI 설치 확인](../all-ui-final-2026-10-12/result.md)의 남은 계정·TLS 검사를 수행했다.
실물 주행·현장 수용은 요청에 따라 제외했다. 실제 개인 계정의 비밀번호나 프로필을
시험을 위해 변경하지 않았으며 운영 계정을 추가하지 않았다.

## 확인한 결과

| 층위 | 실행과 관측 | 한계 |
|---|---|---|
| 원격 소스·실제 Chromium 회귀 | commit `32798ee0bebdb3169251a3026cbc56d2cf460e11` 에서 `test_self_profile.py`, `test_password_session.py`, `test_fleet_account_browser.py`, `test_password_login_browser.py`: **104 passed**, exit 0. `known_failures.py`: NEW 0 | 모델 PC, 2 cores/6 GB 하한을 충족한 배치. 가짜 로봇·격리 계정이며 실제 사용자 로그인 증거는 아님 |
| 실제 설치 이미지 | source `93aaf437ffb188ad0c69bd5aa4398b0de8e96922`, Fleet image ID `sha256:c0525fb08ed907f3ea66410f63031dae9d796806b2f9ad55fb12497f247f374b`. 동일 이미지의 일회용 컨테이너에서 최초 변경, 프로필 저장, 일반 변경, 옛 세션 거부, 앱 재생성 후 유지, 권한 주입 거부, 로그아웃 **PASS** | `--network none`, 운영 볼륨·비밀 마운트 없음, read-only root, 임시 DB, UID 10001, CPU 2/메모리 6 GB 제한. 운영 사용자 데이터가 아닌 격리 검사 |
| 설치 후보 CI | [CI 38207734288](https://github.com/robotics-team-1213/rosy-platform/actions/runs/38207734288), [사이트 후보 빌드 38207734299](https://github.com/robotics-team-1213/rosy-platform/actions/runs/38207734299): completed/success | 해당 설치 소스의 증거이며 이번 문서 변경의 CI로 대체하지 않음 |
| 실제 HTTPS | SSH의 별도 관리자 경로로 읽은 사이트 공개 CA를 사용하고 TLS 체인·유효기간·인증서 호스트 이름 검증을 켬. `/healthz`, `/api/fleet/auth/connection`, 네 Console 문서, 로그인·프로필 문서 총 **8개 HTTP 200** | 승인된 주소에 연결하면서 SNI/HTTP Host는 인증서 이름을 유지. 운영 PC의 자동 DNS나 브라우저 신뢰 저장소 증거는 아님. 폐기 상태는 별도 미확인 |
| TLS 거부 검사 | IP 이름 불일치와 신뢰 CA가 없는 SSLContext 모두 `SSLCertVerificationError`로 거부 | 인증서 검증을 끈 검사는 이 결과에 포함하지 않음 |

원격 회귀는 320px부터 데스크톱까지의 계정 진입, 네 문서의 로그인 복귀,
초안 문서의 별도 탭, 표시 이름 재조회, 현재 비밀번호 오류, 중복 제출 거부,
세션 만료·계정 변경, 실패 후 재조회, 명령 자동 재실행 방지를 포함한다.
배포 소스와 회귀 소스 사이 계정·프로필 구현과 해당 시험에는 변경이 없지만
Console 본문에는 다른 작업의 변경이 있으므로 전체 화면이 동일하다고 주장하지 않는다.

## 개선과 남은 조건

[운영 PC 접속 안내](../../../deploy/site/README.md#operator-pc-resolve-the-name-and-verify-trust-before-login)에
호스트 이름·DNS·공개 CA 등록·Windows Schannel 오류 분리·실제 계정 재조회를 추가했다.
검사한 Windows PC에서는 `.local` 이름 해석이 실패하고, 이름을 명시적으로 해석시키면
기본 Schannel 검사는 폐기 정보 부재 오류를 냈다. `--ssl-revoke-best-effort`를 붙인 진단은
체인·이름 검증을 유지한 채 HTTP 200이었다. 이는 DNS 복구나 완전한 폐기 상태 확인이 아니다.
현장 호스트 자체의 Avahi 이름 해석은 성공했다.

실제 사용자의 로그인된 브라우저는 연결 목록에 없었다. 사용자가 브라우저 연결을
준비 중이며 **실제 개인 계정의 프로필 저장·브라우저 경고 없는 접속은 미확인**이다.
Windows DNS/hosts 변경에는 관리자 권한이 필요해 이 비관리자 실행에서 시스템 설정을
수정하지 않았다. 계정 구현 회귀에서는 실패가 없어 인증 로직을 변경하지 않았다.

비공개 원본: `X:/DevTemp/projects/rosy-platform/2026-10-12--161614--account-tls-verification--cdd8e6/`의
`logs/account-regression/run-1.txt`, `logs/image-account.txt`, `evidence/tls-readback.json`.
주소·계정 정보·인증서는 이 공개 기록에 넣지 않는다.
