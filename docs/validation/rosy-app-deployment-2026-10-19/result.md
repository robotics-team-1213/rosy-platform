# ROSY 앱 이름 변경 배포

후속: [2026-10-20 Learning 키 재발급·배포 완료 기록](../rosy-app-deployment-2026-10-20/result.md). 아래 Learning 키 대기 상태는 10월 19일의 이력이다.

## Fleet / Cell

- 이름 변경만 원격 main 기준으로 분리해 [PR #117](https://github.com/robotics-team-1213/rosy-platform/pull/117)로 게시·병합했다. 다른 로컬 미게시 기능은 포함하지 않았다.
- 검토·게시 head: commit `8944d13758bc82c86073e2a7b61b26e531bd103c`. 원격 main 병합 SHA: `38f0c452e410fca6c2c8fc72f45c3c250751d58f`.
- 독립 검토: names_review, 최종 발견 사항 없음. 새 실패 0. 기존 픽셀 사진 높이 실패 1건은 변경 전·후 같은 위치와 크기로 재현됐다.
- 원격 pre-push: fast 519 passed, affected 8,931 passed / 886 skipped, 별도 관측 721 passed. 실제 Chromium focused: 225 passed / 1 known failure.
- PR CI·Android 개별 검사 13개 성공. [병합 후 main CI](https://github.com/robotics-team-1213/rosy-platform/actions/runs/39241398705) 19개 잡 성공, Android 성공.
- [서버 후보 빌드](https://github.com/robotics-team-1213/rosy-platform/actions/runs/39241398733) 성공. 후보 태그: `site-38f0c452e410`.
- `gh attestation verify`로 workflow·main ref·정확한 source digest를 검증했다. 검증된 manifest SHA-256: `fba5c493d6a3450c2e98879b44c4c2ee6eab3546b53eb1365816998e79a6edcf`.
- 기존 현장 신뢰 키와 일치하는 `rosy-site-bench-20261003`으로 manifest를 서명하고 [후보 릴리스](https://github.com/robotics-team-1213/rosy-platform/releases/tag/site-38f0c452e410)에 `release.json.sig`를 게시했다. 키·신뢰 설정·HOLD는 변경하지 않았다.
- **현장 설치 완료:** 2026-10-19 20:34:41 KST. 기존 자동 업데이트 타이머가 서명된 `site-38f0c452e410`을 적용했다. 설치 상태의 전체 커밋은 commit `38f0c452e410fca6c2c8fc72f45c3c250751d58f`이며 Fleet·Vision·proxy 세 컨테이너 모두 같은 커밋 이미지로 healthy다. updater 결과는 `installed`/success이고 HOLD·미완료 switch·해당 후보 실패가 없다. 20:35 KST에 다시 확인했다.
- 실제 서버 `robttt@100.82.51.8`의 기존 HTTPS 포트 8443에서 읽기 전용 GET으로 확인했다. `/healthz`와 아래 일곱 페이지 모두 HTTP 200이다. 이 확인은 SSH 안에서 자체 인증서 검증을 생략한 HTTP 내용 검사이며, 클라이언트 인증서 신뢰 검증을 대신하지 않는다.

| 경로 | 실제 브라우저 제목 | 추가 확인 |
| --- | --- | --- |
| `/console` | Rosy Fleet | 관제 화면 제공 |
| `/console/cell` | Rosy Fleet — Cell | H1: 팔레타이징 작업 준비 |
| `/console/site-map` | Rosy Fleet — 현장 지도 | 지도 화면 제공 |
| `/console/accounts` | Rosy Fleet — 계정 관리 | 부모 앱 이름 적용 |
| `/console/login` | Rosy Fleet — 로그인 | 부모 앱 이름 적용 |
| `/console/profile` | Rosy Fleet — 내 계정 | 부모 앱 이름 적용 |
| `/console/policy` | Rosy Fleet — 학습 정책 승인 | 부모 앱 이름 적용 |

- 초기 확인에서 기본 443 포트로 보낸 요청은 TLS 오류였고, 파일 경로를 URL로 추정한 `/console/work/policy`는 404였다. 설정된 기존 포트 8443과 실제 공개 경로 `/console/policy`로 정상 응답을 확인했다. 서버 설정 변경은 하지 않았다.

## Learning

- 기존 모델 코드·검수 UI와 사람 라벨을 유지한다. 배포하지 않은 학습 코드 변경을 함께 적용하지 않도록 현재 설치 소스와 전체 tree가 동일한 재작성 기준 커밋에서 이름만 분리했다.
- 기준: commit `76ef95f4b4cbb54de00a6a66a8e222a790ec54af`, 현재 설치 소스 `faea4101cd68cbc45896ec74a564dae3927122e4`와 tree `3a92a57625e819752839c35c4e865f656b219d7a`가 같다.
- 준비한 소스: commit `9bafdf968277191b93171daf4f8740f240e9418e`, 브랜치 `uiux/learning-name-backport`. 기존 여섯 제목만 변경하고 `title_prefix`를 사용하며 새 `app_name`은 등록하지 않는다. 부가 변경은 이름 검사와 작업 로그뿐이다.
- 독립 검토 발견 사항 없음. 정확한 후보 커밋의 원격 검사 **254 passed / 0 skipped**, 기존 실패 비교 **0 NEW**.
- 올바른 미서명 후보: `C:/Users/SERIGGG/AppData/Local/Temp/rosy-learning-naming-d03d869688/narrow-unsigned-sequence-30-lf`.
- archive SHA-256: `d4413c470c1c7e51a345833bd6c4e3ee8ce01d08e3e51ecca7335a0ab4e46bc3`. manifest SHA-256: `853a508eb6deddcd6e3bde71eeea5ee70fbe21e3c341542045baa4354b85e4c8`.
- Windows Git의 줄바꿈 변환을 막는 실행별 `core.autocrlf=false`로 생성했다. 관련 없는 모든 archive 파일이 설치 기준 소스의 Git blob과 바이트까지 같음을 확인했다. 이전 broad/CRLF 후보는 폐기 대상으로 이 배포에 사용하지 않는다.
- **기존 `model-code-v1` 서명 키 경로가 필요하다.** 새 키 생성·다른 용도 키 재사용·신뢰 키 교체는 하지 않았다. 현재 sequence 29·검수 데이터·서비스는 그대로이며 서명·READY·전송·활성화는 수행하지 않았다.
- 후속 적용 전 현재 sequence와 환경 지문을 다시 확인해야 한다. 준비 시 sequence 30, 환경 지문 `97fab2525162e8b93ae730e6c1426ca7c84e07afc0821856ba4e31dccb1412eb`. 기존 신뢰 공개 키 파일 SHA-256은 `d0485ff364cba21dd68b23c53ac9167ac8ea65ae621bd3fa434e22db0a89c80d`다.
- 상세 준비 증거: 위 후보의 상위 폴더 `narrow-release-evidence.md`. 초기 역사적 runner의 exit 4는 미실행이며 통과 증거에 포함하지 않았다.

## Vault / Device / Games

- Vault·Device: 문서의 현장 PC와 현재 Windows PC에서 기존 설치·설정·서비스 또는 8102/8200 리스너를 찾지 못했다. 저장소에는 Device 서비스 예시와 Vault 실행 설명만 있다. 기존 운영 서버·설치 경로·서비스 또는 신규 설치 대상과 실제 설정이 필요하다.
- Games: 문서상 운영자 노트북의 기존 경기 설정으로 실행하는 localhost 앱이다. 현재 PC의 8765 리스너·Games 런타임·서비스 또는 비공개 운영 대상 매핑을 찾지 못했다. 운영 노트북과 기존 경기 설정 경로가 필요하다.
- 임의의 예시 장치·가짜 서비스·새 경기 호스트를 운영 배포로 만들지 않았다. 세 가지 누락 정보는 사용자에게 비동기로 확인 요청했다.

## 범위

이번 배포 검증은 표시 이름·서명된 서버 소스·서비스 상태·실제 제공 화면 범위다. 라벨 승인·학습 시작·모델 승격·로봇 이동·장치 실측은 실행하지 않는다. Robot·Pilot·Cam은 기존 표시 이름을 유지하므로 이름 변경을 위한 기기 런타임·APK 재배포는 하지 않는다.

## 남은 배포 재확인 — 2026-10-19 22:06 KST

- Learning의 현재 설치는 여전히 sequence 29 / commit `faea4101cd68cbc45896ec74a564dae3927122e4`다. 검수 서비스 active, 네 화면 HTTP 200이며 기존 `Rosy 개발` 제목이다. 새 이름의 배포 완료로 간주하지 않는다.
- 준비된 `9bafdf968277191b93171daf4f8740f240e9418e` worktree는 깨끗하다. 미서명 archive·manifest의 SHA-256을 다시 계산해 위 기록과 일치함을 확인했다. 서명과 READY는 여전히 없고 전송·활성화하지 않았다.
- 운영자 PC 임시 폴더의 제한된 파일명 검색과 모델 PC의 관련 사용자 디렉터리 검색에서도 모델 코드 전용 개인 키를 찾지 못했다. 모델 PC에서 확인한 키는 기존 공개 키다. 이 검색은 전체 디스크의 키 부재를 보장하지 않는다.
- Vault·Device 운영 설정, Games 경기 설정과 배포 대상도 추가로 확인되지 않았다. 남은 실행에는 **기존 model-code-v1 개인 키 파일 경로, Vault·Device 대상 PC/서버와 실제 설정, Games 운영 노트북과 경기 설정 경로**가 필요하다. 현재 PC에 신규 설치할 항목이 있다면 그 항목과 설정도 필요하다. 사용자에게 이 정보를 요청했으며 답변 전까지 기존 서비스를 유지한다.
