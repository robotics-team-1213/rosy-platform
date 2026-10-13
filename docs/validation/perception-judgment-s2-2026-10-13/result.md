# S2 Perception 기능 holder 검증

상태: SOURCE 구현, 원격 검증·local main 착지 대기.

14개 파일의 이동 전후 SHA-256과 전체 bytes가 같다. 기존 control.* 설치 이름과 ROS wire/CORE 최종 명령 권한을 유지한다. localization(3), graph_health(2), vision/object_observation(2), sensors/line_observation(5), snapshots(2). D-747과 실행 계획이 경계를 정한다.

보정 명령·transport·storage, 기록 process·file/eviction, executor/TF/web 조립은 S3에 남는다. source-path 합성, standalone sdist/wheel와 canonical source inventory를 재사용한다. active source consumers와 ceiling 예외 경로를 옮기며 숫자와 historical verdict는 보존한다.

증거 세션: X:/DevTemp/projects/rosy-platform/2026-10-13--190909--perception-judgment-s2--0cb381. moves.json에는 14개 이전·현재 경로와 hash를 기록한다. push/CI/ARM64 image/Jazzy graph/장치/현장 수용은 미확인.

## 첫 원격 gate와 수정

후보 f380d7b971의 auto-selected 원격 suite는 6775 passed, 384 skipped, 3 failed(62 subtests passed), 별도 capture steer는 9 passed였다. known_failures는 NEW 3, known 0이며 착지하지 않았다. 실패는 dynamic source 경로를 읽는 capture/learned shutdown 비교 시험 2건과 control 구조 재심사 기준을 8줄 넘은 1건이다. 이 실패를 기존 실패 목록에 넣지 않았다.

두 source 시험은 기존 source_path를 사용하도록 수정했다. authority_review는 같은 구조 계산식으로 잔류 234파일·35183줄, 등록 vision 제외 66파일·13431줄, 중복 0을 독립 확인했다. 증가 158줄은 기존 safety kernel/admission 150과 S2 mapping/setup/provenance 8이다. baseline만 재심사하고 모든 예산·+150·unit·SPLIT 의무는 유지했다. [dated 구조 기록](../../plans/2026-10-11-platform-structure-migration.md)을 함께 반영했다.

이후 main의 D-744를 branch에 합쳤다. perception 및 여섯 counted Drive holder의 production 내용은 f380d7b971과 동일하다. landed D-744의 예약 gap 행을 제거했다. 새 후보의 정상 종료·NEW 0·main 착지는 재검증 후 확정한다.
