# D-427 wave5 원격 반영과 ARM64 빌드 시작

기록 시점의 후보 소스는 `1722ca6ec6d7`이다. 이 문서는 원격 반영과 CI 실행의 완료 증거 및 빌드 시작 증거를 구분한다. 아래 빌드 링크의 후속 성공만으로 이 기록 시점에 artifact 또는 기기 수락이 있었다고 해석하지 않는다.

## SOURCE와 로컬 push 검사

- wave 3b–4e와 이동 직후 안전 수정에 이어 wave5 정리가 원격 `main`에 반영됐다. `git ls-remote origin refs/heads/main`으로 위 후보를 확인했고, 소유 worktree는 clean이었다. 공유 main checkout은 변경하지 않았다.
- D-442·D-443의 Accepted 상태와 ADR Log 정합성을 보존했다. 매니페스트의 비유예 pending root는 0개이며, 현재 colcon root는 여섯 개다. 안전 소유 목록·anchor와 한 release 동안 유지하는 legacy 잔여 검사는 보존했다.
- push12의 lint는 0 errors/13 freshness warnings, 빠른 계약 시험은 462 passed/2 skipped, 영향받는 모듈 시험은 3667 passed/151 skipped였다. 알려진 실패 비교는 NEW 0이었다. 시험이나 gate를 면제하지 않았다.
- source 통합은 독립 APPROVE를 받았다. peer의 변경 경로 17개 중 `docs/logs.md`·`docs/index.md`를 제외한 15개 파일은 원격과 byte 동일하며 원격 로그 prefix와 소유 append를 보존했다. 소유 실행 코드는 앞서 독립 리뷰한 후보와 동일하다.
- 실제 Ubuntu/OpenCV 4.6 호스트 perception 시험은 2588 passed/107 skipped였고, x86 ROS 호스트 빌드는 26개 패키지가 완료됐다. 이것은 ARM64 또는 기기 증거가 아니다. 자세한 범위는 [최종 호스트 검증](wave5-final-host-verification-2026-10-04.md)을 따른다.

## GitHub 전체 CI

[전체 CI 37180311184](https://github.com/livsbittt/rosy-os/actions/runs/37180311184)는 위 소스에서 completed/success였다. aggregate 결과와 별개로 다음 10개 matrix 작업이 모두 success인지 확인했다. 보고 전용 sensing 작업도 실제 success이며, 실패를 허용한 결과를 통과로 간주하지 않았다. scope와 ci-result 역시 success였다.

| 작업 | 확인 결과 |
|---|---|
| sensing | success |
| core-domain | success |
| fleet | success |
| site-vision-cell | success |
| gz-sim | success |
| hardware-safety | success |
| build-smoke | success |
| root-test-1of3 | success |
| root-test-2of3 | success |
| root-test-3of3 | success |

## 035 ARM64 빌드

직전 서명 정규 릴리스는 033이다. 034는 기존 unsigned native 빌드에서 사용됐다. 원격 payload tag와 최근 native artifact 이름에서 다음 정규 후보 `2026.10.04-035`가 사용되지 않았음을 확인했다. 배포 대상의 기존 release 디렉터리 확인은 접속이 확보된 뒤 별도로 필요하다.

| 빌드 | 기록 시점 | 소스 |
|---|---|---|
| [native payload 37180857889](https://github.com/livsbittt/rosy-os/actions/runs/37180857889) | in_progress | `1722ca6ec6d7` |
| [SD 이미지 37180861394](https://github.com/livsbittt/rosy-os/actions/runs/37180861394) | in_progress | `1722ca6ec6d7` |

workflow를 요청한 사실에 그치지 않고 두 실제 run의 headSha가 CI 후보와 같은지 확인했다. 빌드 완료, archive checksum, 설치된 Skill/Motion 계약과 import 증거, 033 대비 패키지·설치 파일 비교, SD mounted-image 검증, 서명 및 canary ABI 확인은 후속이다. 현재 ARTIFACT_EQUIVALENT를 주장하지 않는다.

## 안내와 외부 작업의 경계

- 저장소 밖 umbrella AGENTS의 control/Fleet 소유 경로와 시험 안내를 현재 배치에 맞췄다. 추가 시험 안내 수정은 comment와 pytest 두 줄, 총 세 줄뿐이다. 여섯 시험 경로가 존재하며 sensing의 별도 호출과 다른 bytes가 보존됐음을 독립 리뷰했다. 저장소 밖 수동 안내이므로 Git 커밋 대상이 아니다.
- canary의 읽기 전용 SSH 확인은 주소 접속 시간 초과와 기존 호스트 이름의 DNS 해석 실패였다. 실제 기기 상태·ABI·현재 release는 이번 확인에서 미검증이며, 이전 033 정상 기록을 현재 상태로 사용하지 않는다.
- site PC model-watch는 대상 identity와 접속 정보가 확정되지 않아 NOT_RUN이다. 기존 설정·자격증명·등록을 보존한 채 설치·timer·journal readback이 필요하다.
- peer rebase 안내는 준비했으나 실제 Rosy 세션 채널과 delivery/ack를 확인하지 못해 NOT_SENT다. Git worktree 목록과 다른 서비스의 세션 도구를 활성 Rosy 세션이나 로봇 사용 조율의 증거로 사용하지 않는다.
- 릴리스는 아직 발행하지 않았다. 발행 전 현재 로봇 사용 조율·접속·calibration/maintenance guard를 확인한다. firmware의 S7 bad_cycle/uint32 수정은 다음 개정이며 이번 작업에서 flash·motion·E-Stop reset을 실행하지 않았다.
