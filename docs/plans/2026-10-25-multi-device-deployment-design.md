# 다기종 배포·SDK 연결 준비 설계

상태: 준비 설계 제안. 2026-10-25. 실행·비행 capability 승인 아님.

## 목표와 선택

기종을 추가할 때 ROSY 직접 설치 가능 여부와 외부 SDK 호스트 연결 가능 여부를 먼저 판정하고,
설치 가능한 산출물·실제 기능·수용 증거를 혼동하지 않게 한다. [배포 준비서](../deployment/multi-device-onboarding.md)가
현재 접수 절차와 Neo 2 공식 지원 판정의 정본이다.

기존 기체별 profile/adapter와 릴리스 신뢰 경계를 유지하는 경로를 선택한다.
모든 기체를 같은 SD 이미지로 처리하는 방식은 SDK 호스트의 OS와 제조사 firmware 경계를 표현하지 못한다.
기종별 별도 관제 앱을 만드는 방식은 인증·원장·상태를 중복하므로 선택하지 않는다.
공통 관제/명령 수명은 재사용하고 실제 장치 기능과 최종 writer는 기종별로 검증한다.

## 현재 근거와 간극

- RaspTank는 설정만 있는 `rasptank_metal` 소스 패키지다. 실제 I/O·native 설치·이미지·실물 증거는 HOLD.
- Pinky image manifest는 board를 고정하고 SD provisioning schema도 Pinky만 허용한다.
  지원 모델 목록 확대만으로 다른 기종의 package closure가 생기지 않는다.
- CORE의 절대경로 profile/capability 선택은 모델 조회를 우회한다. 제품 activation 결속은 후속 검증 대상이다.
- D-305의 드론 후보 경계를 유지한다. 아직 범용 flight action과 SDK 최종 owner는 없다.
- DJI Neo 2는 공식 SDK 미지원이다. 이를 제어 구현의 시험 기종으로 가정하지 않는다.

## 순차 실행과 완료 조건

| 단계 | 변경·검증 대상 | 완료 조건 |
| --- | --- | --- |
| P0 준비 기준 | 호환 목록, 직접 설치/외부 연결 분류, 기종 접수표, Neo 2 근거 | 기종별 설치 대상·공식 제어 가능성·ROSY 구현 상태를 분리해 확인 가능 |
| P1 무구동 기종 결속 | `core/node.py`, `core_common/profile.py`, 기존 모델/경로 시험 | RaspTank 선택+Pinky overlay, 미설치 package, 잘못된 내용의 설정을 제품 시작에서 거절. 기존 개발 overlay 호환은 별도 보존 |
| P2 두 번째 native 산출물 | 기존 Pinky image/native 경로와 RaspTank package closure | native ARM64 build/install, 모델별 required package·서비스·부팅 설정·서명 검증, 무구동 부팅/복구. Pinky 회귀 통과 |
| P3 외부 SDK 연결 표본 | 공식 지원 기종 1개와 실제 SDK 호스트 선정 후 해당 경계 설계 | 공식 예제로 읽기 전용 상태 조회, 버전·조종기·펌웨어 결속, 호스트 산출물 설치/readback. 선정 전 빈 어댑터 생성 안 함 |
| P4 기능 수용 | 기종별 최종 owner, 제어권 전환, 명령/결과/단절/복구 | replay/원격 시험 뒤 실제 장치 반례·기능별 수용. Neo 2는 공식 지원 변경 전 제어 HOLD |

P1 이후는 각기 별도 구현·독립 계약 검토로 진행한다. 이 문서에서 공개 API·필드를 선제 정의하거나
작동하지 않는 generic SDK 클래스를 추가하지 않는다. SDK 재배포 권리·키/identity·영상 출처를
기종 접수 단계에 포함한다. 단계별 SOURCE/ROS-SIM/ARTIFACT/DEVICE/FIELD 증거는 서로 대체하지 않는다.

## 검증·착지

P0 문서 연결·harness generate/lint와 committed SHA 원격 문서 계약 검증을 수행한다.
기존 RaspTank 계약 시험은 유지한다. 저장 공간/예약으로 시험 호스트를 사용할 수 없으면
로컬 pytest로 대체하거나 검증을 건너뛰어 착지하지 않는다.
SD 기록·기체 접속·펌웨어 변경·비행은 이 준비 작업에 포함하지 않는다.
