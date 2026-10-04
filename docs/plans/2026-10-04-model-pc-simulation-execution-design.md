# 모델 PC 시뮬레이션을 에이전트가 직접 실행하는 경로

상태: 제안 설계. 실행 서비스·관리자 정책은 아직 구현하거나 설치하지 않았다.
사용자의 요청은 반복적인 터미널 대행을 줄이는 방향 수립과 교훈 기록이다.

## 문제와 확인한 조건

현재 SSH 접속과 사용자 파일 전송·상태 조회는 가능하다. 그러나 비대화형 sudo 인증은
통과하지 못하고, root 소유 Docker socket도 현재 SSH 사용자에게 쓰기 권한이 없다.
기존 사용자 systemd 서비스에는 승인된 특권 시뮬레이션 실행 경로가 없다.
그래서 prepare와 run마다 사용자에게 sudo 명령 실행을 부탁하는 흐름이 반복됐다.

D-434의 모델 PC·관제 PC 역할 분담을 유지한다. 이 설계는 모델 PC의 격리된 G2
시뮬레이션만 다룬다. 관제 사이트 서비스 변경이나 실물 로봇 제어 권한은 포함하지 않는다.
D-403의 Cell Job 경로, D-427의 소유권, D-430의 안전 경계를 우회하지 않는다.

## 선택지

| 방식 | 실행 및 권한 특성 | 판단 |
|---|---|---|
| 관리자 소유 전용 검증 worker | 고정된 검증 종류와 이미지·격리 정책으로만 job 처리 | 권장 |
| SSH 사용자에게 Docker 그룹 또는 포괄 sudo 허용 | 임의 컨테이너와 호스트 mount까지 허용 범위가 커짐 | 이번 목표에 과도함 |
| 사용자 rootless 실행 환경 | 기존 rootful 이미지·ROS·SDK·GPU 경로를 별도로 검증해야 함 | 별도 후보, 즉시 대체로 가정하지 않음 |

## 권장 데이터 흐름

1. 관리자가 한 번 검토·설치한 root 소유 worker와 정책 파일을 둔다.
   사용자 소유 `validate.sh`를 sudo 허용 목록에 넣거나 root로 실행하지 않는다.
2. 에이전트는 SSH로 source manifest와 job 데이터만 사용자 inbox에 제출한다.
   요청에는 검증 종류, candidate revision, 파일별 digest, 승인된 image ID가 들어간다.
   shell command, Docker 옵션, 임의 host 경로를 받지 않는다.
3. worker가 경로 탈출·symlink·extra/missing file·digest를 검사하고 source를
   root 소유 private job 디렉터리에 고정한다. 동시 변경된 입력은 거부한다.
   승인된 manifest와 image의 신뢰 기준은 root 정책으로 관리하며, 요청자 manifest만으로
   승인된 소스라고 판단하지 않는다.
4. 고정 argv로 prepare를 실행하고, 성공·정리를 확인한 job만 run을 허용한다.
   최초 profile은 현행 G2와 같은 network none, capability drop, 장치 전달 없음,
   읽기 전용 source/root filesystem, tmpfs, CPU·메모리·시간 제한을 보존한다.
   container 내부에서는 candidate 코드가 실행되므로 이 격리가 필수다.
5. Gazebo·Isaac·학습의 공용 예약을 확보한다. 충돌 시 BUSY를 반환하고 다른 작업을
   중단하지 않는다. GPU 접근이 필요한 Isaac은 별도 검토 profile로 남긴다.
6. 공개 상태 파일에는 candidate/image 식별, phase, 완료 개수, 종료 사유,
   cleanup 결과만 내보낸다. token, 전체 환경 변수, 임시 자격정보는 내보내지 않는다.
   원본 증거와 job ledger는 비공개로 보존한다.
7. agent는 상태와 결과를 읽어 완료·HOLD를 구분한다. HOLD/UNKNOWN이면 재실행하지 않는다.
   cleanup은 그 job의 exact container ID와 소유 process group만 대상으로 한다.
   timeout·worker 재시작·정리 실패는 UNKNOWN으로 보존하며 예약을 임의 해제하지 않는다.

## 구현 순서와 완료 조건

다음 구현은 요청 schema, root 정책, immutable job 복사, 고정 runner, 예약 ledger,
정리·상태 내보내기, 관리자 설치 패키지 순서로 진행한다. 설치 전에 변경 파일과
허용 권한을 검토할 수 있는 결과물을 만든다. 기존 SSH 권한만으로 관리자 설치를
수행할 수는 없으므로 최초 설치는 관리자 인증이 필요하다. 설치 후에는 승인된
검증 job의 제출→prepare→run→결과 조회를 에이전트가 직접 수행하는 것이 목표다.

검증할 사례는 정상 job, 입력 변조·symlink·경로 탈출, 임의 명령·mount 요청,
미승인 image/source, 동시 실행, prepare 실패, run HOLD, timeout, worker 재시작,
다른 job 보존, 자격정보 비공개, 정확한 정리다. 운영 적용의 증거는 실제 모델 PC에서
관리자 추가 입력 없이 제출부터 정리 readback까지 끝나는 한 번의 검증이다.
호스트 테스트만 통과한 상태는 직접 실행 경로의 설치·운영 수용이 아니다.

## 현재 G2 결과와 다음 조사

2026-10-04 r5 candidate `41d9b51e0`의 prepare와 cleanup은 exit 0이다.
run은 exit 1, `LOCAL_ACTION_HOLD`, `cleanup_verified: true`로 종료됐다.
초기 홈은 READY이며 첫 박스 placement receipt가 하나 남았다. 두 번째 박스의
attach receipt는 transport/response/attached echo가 모두 true였지만,
이송 중 `verify_held_object()`가 보유를 증명하지 못해 `item_lost_in_transit`으로
중단됐다. 원인이 실제 탈락인지 관측 binding/신선도인지 아직 확정하지 않았다.
다음 조사는 해당 action·attempt의 phase journal과 gripper 관측을 대조한다.
재부착·재이송으로 성공을 만드는 방식은 사용하지 않는다.

box16와 fault matrix는 수용되지 않았다. 자동 실행 경로가 생겨도 이 판정은 바뀌지 않는다.
