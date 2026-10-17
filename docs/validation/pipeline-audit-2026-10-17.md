# 공개·비공개 GitHub 파이프라인 점검 · 2026-10-17

**판정:** 코드 검사와 비공개 설정 검사는 정상이다. staging은 `HOLD`이고, 릴리스 게시 준비와 실제 배포·수용은 완료하지 않았다. 운영 절차의 기준은 [PR 파이프라인](../reference/pr-pipeline.md)이다.

## 범위와 근거

공개 소스 `e7720e29363d1cff49e44196a5c0870d23281b8e`와 비공개 운영 설정 `249861b7c1d37da8033dd01a710569178fdb3513`을 읽었다. GitHub API로 저장소 설정·ruleset 상세·Actions 기본 권한·환경·변수 이름·실행 결과를 조회했다. 비밀값은 조회하지 않았고 호스트에 접속하거나 빌드·릴리스·배포 워크플로를 새로 실행하지 않았다.

| 확인 대상 | 관찰 |
|---|---|
| 공개 main 보호 | 활성 ruleset `24502267`: PR, 필수 `ci-result`, 사람 승인 0, 미해결 검토 대화 해소, 삭제·force-push 제한. 관리자 우회는 PR 경로로 제한. 최신 main 반영 강제는 꺼짐 |
| 비공개 main 보호 | ruleset·branch protection 조회 모두 기능 업그레이드를 요구하는 403. 서버 강제를 전제로 삼지 않고 독립 검토·게시 담당의 수동 확인을 사용 |
| 두 저장소 병합 | squash만 허용, 병합 뒤 브랜치 자동 삭제, auto-merge 꺼짐 |
| Actions 기본 권한 | 두 저장소 모두 읽기 전용, PR 승인 권한 꺼짐. 각 잡의 명시적 권한이 우선하므로 모든 워크플로가 읽기 전용인 것은 아님 |
| 쓰기 권한 경로 | 사이트 후보 게시 `contents: write`, provenance `id-token/attestations: write`, builder 이미지 `packages: write`, 릴리스 게시 `contents: write`, 구조 보고 `issues: write` |
| 비공개 설정 CI | Python 3.12·고정 PyYAML·전체 SHA로 고정한 Actions, `contents: read`, 자격증명 미보존 checkout. SSH·외부 저장소 checkout·배포 단계 없음. Environments 목록 0개 |

## 실행 결과와 한계

| 증거 | 실제 결과 |
|---|---|
| 공개 [PR #74 CI](https://github.com/robotics-team-1213/rosy-platform/actions/runs/38995804135) · head `4d9e0dd9b4af685fbc59e1e736b04280b7abede8` | 개별 4개 잡 성공, affected 508 passed. 로그의 기존 실패 비교 0 NEW |
| 공개 [main CI](https://github.com/robotics-team-1213/rosy-platform/actions/runs/38996176789) · `e7720e29363d1cff49e44196a5c0870d23281b8e` | 보고용 modules 포함 개별 18개 잡 성공. colcon 26 packages, boot smoke·SaveMap guard 성공 |
| 같은 main 실행의 skip 예 | CORE 6,255 passed / 63 skipped, Gazebo 343 passed / 13 skipped. 전체 잡 성공을 모든 시험·시뮬·브라우저 실행으로 해석하지 않음 |
| 비공개 [main CI](https://github.com/robotics-team-1213/rosy-ops/actions/runs/38995663882) · `249861b7c1d37da8033dd01a710569178fdb3513` | 15개 시험과 HOLD 구조 검사 성공. 실제 설정의 소스·산출물·대상·검증 기록은 null |

공개 main 실행은 scope 시작부터 ci-result 종료까지 약 11분 17초였다. 가장 긴 `fleet-1of4` 잡은 준비를 포함해 약 10분 34초였다. 한 실행의 관찰값이며 후속 실행 시간의 보장이 아니다.

원격 시험 PC는 사용자의 접속 생략 지시에 따라 건너뛰었다. 노트북 pytest, 실제 staging 호스트, 운영망 격리, 실물 로봇, DEVICE/FIELD는 미실행이다. 비공개 링크는 저장소 접근 권한이 있어야 열린다.

## 다음 단계의 조건

| 항목 | 확인 결과와 다음 행동 |
|---|---|
| 릴리스 게시 준비 | `publish-release.yml`은 `release` 환경과 `ROSY_RELEASE_KEY_ID` 변수를 요구한다. 공개 저장소 환경 목록 0개, 해당 환경 조회 404, 저장소 Actions 변수 이름 목록 0개, 이 워크플로 실행 이력 0건이다. 릴리스 담당자가 환경 승인·대상 브랜치 정책·키 ID와 공개키를 확인하기 전에는 게시 준비 완료로 표시하지 않는다 |
| 사이트 후보와 주 CI | 후보 워크플로의 job 의존성은 자체 빌드·provenance이며 주 `ci` 실행에 연결되지 않는다. 후보를 선택할 때 동일 소스 SHA의 주 CI, digest·서명과 대상별 수용 근거를 따로 대조한다 |
| staging 기동 | 대상 호스트·담당자·접속 범위·격리 및 기능·복구 근거를 실제 값으로 확보한다. [D-784](../adr/D-784-public-source-private-ops-staging.md)와 비공개 `docs/staging.md`의 절차를 따른다. 지금은 설정·검사 CI 준비까지다 |

서버 설정이나 권한을 변경하지 않았다. 이 점검은 현재 파이프라인과 실행 증거를 문서에 반영하며 새 배포 승인을 만들지 않는다.
