# 현재 설치본 기본 프로필 후속 검증

[계정·TLS 검사](../account-tls-2026-10-12/result.md)의 후속 실행이다.
기본 프로필의 표시 이름 수정, ID·이메일·권한 확인, 비밀번호 변경 범위를 검사했다.
실물·현장 수용은 요청에 따라 제외한다.

## 대상과 결과

검사 대상 commit: `4e22542541b9de46f90e9c2b61aebe1146f483d8`.
해당 설치 소스의 [CI 38247266057](https://github.com/robotics-team-1213/rosy-platform/actions/runs/38247266057)와
[사이트 후보 빌드 38247266112](https://github.com/robotics-team-1213/rosy-platform/actions/runs/38247266112)는
completed/success로 확인했다. 이 CI는 후속 검증 문서 변경의 CI를 대신하지 않는다.

| 층위 | 검사와 관측 | 범위 |
|---|---|---|
| 정확히 같은 설치 이미지 | 일회용 컨테이너에서 최초 비밀번호 변경, 표시 이름 저장, 일반 비밀번호 변경, 옛 세션 거부, 앱 재생성 후 유지, 권한 주입 거부, 로그아웃 PASS | `--network none`, 운영 데이터·비밀·로봇 네트워크 마운트 없음, read-only root, UID 10001, CPU 2/메모리 6 GB 제한, 임시 DB |
| 원격 소스·실제 Chromium | 동일 commit의 `test_self_profile.py`와 `test_fleet_account_browser.py`: **40 passed**, exit 0, `known_failures.py` NEW 0 | 모델 PC의 2 cores/6 GB 자원 하한 충족. 가짜 로봇·격리 계정이며 개인 운영 계정의 실제 브라우저 저장은 아님 |
| 운영 계정 유지 | 사용자 5명, 서비스 principal 4개, 본인 operator 계정 유지 | 계정 추가나 비밀번호 재설정 없음 |
| 본인 프로필 저장 상태 | 애플리케이션 UID로 운영 DB의 해당 프로필 메타데이터만 read-only 조회. 사용자 지정 표시 이름 행은 없고 기본 로그인 ID를 사용하는 상태 | 세션·비밀번호 데이터 조회나 운영 DB 쓰기 없음. 사용자 지정 이름이 없다는 사실은 저장 실패 증거가 아님 |

Chromium 회귀는 네 문서에서 프로필 진입과 초안 작업 문맥 보존, 표시 이름 저장·새로고침,
현재 비밀번호 오류, 중복 제출 방지, 기존 세션 무효화, 저장 실패 후 재조회,
계정 전환·세션 만료 후 오래된 편집 거부, 최초 변경 및 요청 재조회 실패 복구를 포함한다.

## 남은 확인과 변경 범위

로그인된 사용자 브라우저 연결 목록이 비어 있어 실제 본인 계정에서의 화면 저장은
미확인이다. 브라우저 플러그인 검색에서도 기존 로그인 브라우저에 연결할 적합한
연결을 확보하지 못했다. 이 제한을 격리 시험 통과로 대체하지 않는다.

실패가 발견되지 않아 제품 코드와 운영 개인 프로필·비밀번호를 변경하거나
이 검사를 위해 재배포하지 않았다. 이번 커밋은 실행 증거를 저장소에 기록한다.

비공개 원본은 `X:/DevTemp/projects/rosy-platform/2026-10-12--161614--account-tls-verification--cdd8e6/`의
`logs/profile-browser-20261013/run-1.txt`, `logs/profile-image-20261013.txt`,
`evidence/owner-profile-metadata-20261013.json`, `evidence/accounts-profile-20261013.json`이다.
실제 주소·계정 ID·이메일·인증 값과 운영 데이터는 공개 기록에 포함하지 않는다.
