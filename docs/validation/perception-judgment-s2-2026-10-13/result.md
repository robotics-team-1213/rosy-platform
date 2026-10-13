# S2 Perception 기능 holder 검증

상태: SOURCE 구현·독립 source/Safety/구조 검토 완료. 수정 후 원격 재검증 NOT RUN. 사용자의 후속 요청에 따라 local main 머지만 수행하며 실제 착지는 Git readback으로 구분한다.

14개 파일의 이동 전후 SHA-256과 전체 bytes가 같다. 기존 control.* 설치 이름과 ROS wire/CORE 최종 명령 권한을 유지한다. localization(3), graph_health(2), vision/object_observation(2), sensors/line_observation(5), snapshots(2). D-747과 실행 계획이 경계를 정한다.

보정 명령·transport·storage, 기록 process·file/eviction, executor/TF/web 조립은 S3에 남는다. source-path 합성, standalone sdist/wheel와 canonical source inventory를 재사용한다. active source consumers와 ceiling 예외 경로를 옮기며 숫자와 historical verdict는 보존한다.

증거 세션: X:/DevTemp/projects/rosy-platform/2026-10-13--190909--perception-judgment-s2--0cb381. moves.json에는 14개 이전·현재 경로와 hash를 기록한다. push/CI/ARM64 image/Jazzy graph/장치/현장 수용은 미확인.

## 첫 원격 gate와 수정

후보 f380d7b971의 auto-selected 원격 suite는 6775 passed, 384 skipped, 3 failed(62 subtests passed), 별도 capture steer는 9 passed였다. known_failures는 NEW 3, known 0이며 착지하지 않았다. 실패는 dynamic source 경로를 읽는 capture/learned shutdown 비교 시험 2건과 control 구조 재심사 기준을 8줄 넘은 1건이다. 이 실패를 기존 실패 목록에 넣지 않았다.

두 source 시험은 기존 source_path를 사용하도록 수정했다. authority_review는 같은 구조 계산식으로 잔류 234파일·35183줄, 등록 vision 제외 66파일·13431줄, 중복 0을 독립 확인했다. 증가 158줄은 기존 safety kernel/admission 150과 S2 mapping/setup/provenance 8이다. baseline만 재심사하고 모든 예산·+150·unit·SPLIT 의무는 유지했다. [dated 구조 기록](../../plans/2026-10-11-platform-structure-migration.md)을 함께 반영했다.

이후 main의 D-744를 branch에 합쳤다. perception 및 여섯 counted Drive holder의 production 내용은 f380d7b971과 동일하다. landed D-744의 예약 gap 행을 제거했다. 새 후보의 정상 종료·NEW 0·main 착지는 재검증 후 확정한다.

## 통합 후보와 최종 중단 결과

D-745를 포함한 main d6d3addda296을 작업 브랜치에 합쳤다. 충돌한 test_model_review_release.py는 기능 holder 누락 거절과 peer의 private owner control unit 시험을 모두 보존했다. D-745 예약 gap을 제거하고 추가 whitespace를 정리했다. 통합 source 후보는 2b391c5349afc3114eb3cfbe4ec85b0a5f993853이다.

| 증거 | 결과 |
|---|---|
| 14 이동 파일의 Git blob | 기준 535edb5da의 원본과 완전히 같음 |
| 합친 Python 파일 AST 및 양쪽 release 필수 목록 | PASS; 이동 14파일 포함 |
| 충돌 해결의 두 시험 의도 | 모두 보존 |
| 최종 후보 lint | exit 0, errors 0, warnings 32 |
| 최종 후보 원격 영향 회귀 | NOT RUN; 등록 시험 PC 3곳 SSH 불가, 600초 재시도 뒤 exit 1 |
| local main 착지·push | 미실행 |

최종 원격 실행기는 `no test host reachable (D-584) after 600 s; the tests did not run`으로 끝났다. 첫 후보의 성공한 시험을 통합 후보의 PASS로 승계하지 않는다. 노트북에서는 pytest를 돌리지 않았다. main d6d3addda296과 다른 세션의 미커밋 5경로는 그대로 보존했다.

af7490945의 중간 재시험은 main의 관련 D-745 변경을 합치기 위해 중단했으므로 terminal PASS 증거가 아니다. 그 원격 작업의 lock 부재와 해당 cwd의 Python process 부재는 읽어 확인했으나, 잔여 임시 test directory 제거의 마지막 readback은 SSH 중단으로 확인하지 못했다. 복구 시 자기 작업 land-1-83f854만 확인·정리한다.

재개 순서: 시험 PC 연결 확인 → 현재 main 합치기 → 기존 budget/ADR gap·source mapping 확인 → tools/land.py --tests auto로 정상 종료와 known_failures NEW 0 확인 → local main ff-only → 착지 SHA 기록. S3는 S2 착지 뒤에 시작한다. 브랜치 refactor/perception-judgment-s2와 등록 worktree는 재개를 위해 보존한다. CI FULL, ARM64 image, ROS transport, 장치·현장 수용은 계속 미확인이다.

## 후속 사용자 지시 — local merge까지만

사용자가 원격 시험 PC의 주소 또는 VPN 설정 변경을 확인하고 `merge 까지만 해`라고 지시했다. 이 후속 지시에 따라 원격 재검증을 더 시도하지 않고 tools/land.py --tests none으로 lint와 local main ff-only까지만 수행한다. push는 하지 않는다. 앞의 원격 NOT RUN·첫 후보 NEW 3 기록은 그대로 유지하며 local merge를 검증 PASS나 배포 허용으로 집계하지 않는다. 착지 성공 여부·최종 HEAD·공유 WIP 보존은 세션 evidence/landing-readback.json과 Git ancestry readback에 남긴다. 이후 원격 검증에는 변경된 시험 PC/VPN 설정 확인이 필요하다.
