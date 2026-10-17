# D-776: 설치된 충전 계측은 원본 수명과 출처를 가진 사실 포트로 연결한다

**Status:** Accepted (2026-10-16, 사용자 승인 D-772 운영 설정 구현). 설치 승인과 실측 장치 수용은 별도다.

## Context

현재 충전 실행기는 앱 factory와 명시적 SIM 콜백으로 연결된다. CLI 조립에는 실제 계측 source와 정책·경로 비용의 출처가 필요하다. 하드웨어가 미정이라는 이유로 전압을 SOH/용량으로 표시하거나 HTTP 수신 시각을 원본 계측 시각으로 바꿀 수 없다.

## Decision

한 로봇·한 스테이션의 명시적 설치 설정으로 기존 Fleet 소유 실행기를 조립한다. 설정이 없으면 기존 기본 비활성을 유지한다. 승인된 로컬 계측 어댑터는 기존 BatteryEnergyEvidence와 원본 motion/boot/map/odom/safety/dock 사실을 bounded strict JSON 파일로 원자적 교체한다. 원래 motion capture·expiry, source ID/epoch·증가 sequence와 배터리 자체 capture·expiry를 보존한다. 파일에는 명령·선택 작업·경로 예산·미래 session을 넣지 않는다.

파일은 승인된 POSIX writer UID와 그 UID가 소유한 비공유 쓰기 디렉터리에 둔다. reader는 directory/file descriptor에서 소유자·쓰기 권한·일반 파일·symlink 및 크기를 검사한다. writer는 같은 디렉터리에 완성한 파일을 rename하며 부분 JSON·중복 키·비유한 수·과대 자료·읽기 오류는 거절한다. 설정의 출처 선언과 OS 계정 신뢰는 센서 정확도나 실측 교정의 자동 증거가 아니다. 비밀은 JSON에 넣지 않는다.

Fleet는 사실 사용 전에 기존 SQLite에 sequence·payload hash·motion/battery 원본 capture/hash와 replay 거절 watermark를 원자적으로 저장한다. 동일 자료 반복 읽기는 최초 monotonic deadline을 연장하지 않는다. 동일 capture의 값/expiry 변경·역순·관측된 만료 자료의 복원·UTC/monotonic 역행은 거절한다. 재시작 후에는 보존 watermark보다 새로운 sequence와 원본 motion/battery capture가 있어야 한다. epoch 변경은 설치 재승인이며 자동 sequence 초기화로 취급하지 않는다. DB·source 오류는 WAIT/기존 안전 보류로 전파하며 blocking I/O는 async 실행 루프 밖에서 한다.

Fleet는 durable 선택 작업과 현재 World MapPose, 활성 경로 그래프에서 현재→작업·작업 끝→스테이션·현재→스테이션 경로를 계산한다. 승인된 비용 모델은 거리·시간·회전·대기·접안·reserve의 처리 범위를 명시하며 필요한 값이 없거나 지원하지 않는 작업이면 WAIT한다. task/request digest·map/pose/cost/policy revision을 최종 admission에서 재검사한다. 외부 파일은 budget이나 Task 선택 권한을 갖지 않는다.

새 세션 bootstrap은 생성된 실제 session과 승인 카메라 교정, 현재 boot/map/odom을 결속하는 명시적 포트다. 원본 motion evidence 이내의 capture/expiry를 사용하고 visible=False/pose=None으로만 만든다. 카메라 frame·착좌·충전 증거를 생산하거나 갱신하지 않는다. 기존 세션은 실제 ingress scope를 읽는다. 기존 CORE generation/native owner·실제 정지·capability/물리 수용 검사를 유지한다.

## 구조 결정 및 검증

| 결정 | 관계 |
|---|---|
| D-427 | 기존 Fleet ledger/source holder와 하나의 SQLite/transaction owner를 사용한다 |
| D-429 | 계측은 사실만 제공하고 World·Fleet·CORE의 권위를 보존한다 |
| D-430 | source/replay/정책 조립은 safety 독립 검토와 원격 시험 대상이다 |
| D-772 | 기존 station/charge DTO와 admission·접안·충전·이탈 경로를 조립한다 |
| D-774 | 카메라 실행은 기존 source-only 관측 CLI로 유지한다 |

source/time/restart/파일 경계 RED→GREEN 이후 실제 CLI→app factory→공유 실행기→CORE 경로를 검증한다. 설치 가능한 소프트웨어·합성 계측·실제 장치/현장 수용은 서로 다른 근거로 기록한다. 이 결정은 배포·실기 capability 활성화 권한이 아니다.
