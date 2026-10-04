---
module: fleet
---

# Cell 화면과 Isaac 무주행 graph 검증

2026-10-04 구현 작업 트리 기준 기록이다. 전체 D-450 완료나 운영 현장 수용을 뜻하지 않는다.

## Cell 구현과 관측

기존 Console 안의 `/console/cell`에서 recipe/cell 초안을 revision digest로 저장하고 정본 compiler로 검증·미리보기한다. 설정된 실제 service principal이 기존 proposal 원장에 제안한다. named operator의 별도 승인과 기존 dispatch generation fence를 유지한다. 별도 실행 원장이나 command writer를 만들지 않았다.

실제 compiler API 시나리오는 저장→18-transfer preview→service proposal→별도 승인 READY를 확인했다. 실제 Chromium 시험은 늦은 응답 무효화, generation 충돌 후 재조회, 조회 실패 시 승인 잠금, 취소 후 resume 잠금, JSON 파일 입력과 가이드 편집·재저장을 확인했다. desktop 및 390px viewport를 사용했다. 서버는 FakeRobot만 사용했고 실제 장치 전송을 하지 않았다.

API/store/기존 Cell Job API/browser 조합 19개가 통과했다. 독립 리뷰의 optional resolver import 회귀를 수정한 뒤 API 8개가 추가로 통과했다. 계약·구조·비밀정보 guard 집중 검사 116개가 통과했다. 최종 빠른 gate는 462 passed/2 skipped/12 existing warnings였다. 구조 예산 판정은 bounded module 분리와 독립 리뷰를 반영했고 기존 allowance를 늘리지 않았다.

## Isaac 실제 SDK 관측

모델 PC의 Isaac Sim 5.1.0.0, Python 3.11.17에서 검증했다. 기존 SDK·ML 환경·checkout을 보존하고 별도 검증 환경에 CPU Torch 2.7.0 계열을 설치했다. native RTX renderer/PhysX와 GPU Torch tensor 학습 준비 상태는 별개의 증거다.

SDK importer는 defaultPrim을 포함한 USD를 live stage에 참조했다. 격리 localhost DDS의 단일 simulated identity에서 graph callback 120회, 초기 재생 전 zero 1회, 최종 Gate output/USD wheel-target zero 확인 243회를 기록했다. 별도 읽기 전용 observer가 clock/odom 각 117개를 수신했다. Twist/CORE command publisher는 시작하지 않았다. 독립 리뷰가 raw log와 관측 JSON을 직접 대조했다.

SDK error와 traceback은 없었으나 main 및 SDK close 반환 후 interpreter가 120초 제한을 넘겨 exit 124로 종료됐다. 소유 프로세스와 SDK child가 남지 않은 것도 확인했다. 따라서 ROS-SIM은 HOLD다. 목표값 zero는 실제 joint velocity/이동량 또는 주행 중 명령 단절 정지의 증거가 아니다.

Host Isaac 시험은 33 passed/1 skipped다. skip은 Windows host의 ROS xacro overlay 부재이며 실제 모델 PC SDK 실행 결과와 구분한다. 최신 source와 watchdog/importer/shutdown에 대한 별도 reviewer 시험 25개도 통과했다.

Raw evidence는 작업 PC의 `X:/DevTemp/rosy-cell-isaac-20261004/` 아래 browser 및 isaac-worker에 보관했다. `runtime-receipt.json`은 실제 실행한 8개 source의 SHA-256, variant, 관측, timeout과 cleanup을 포함한다. 실제 호스트 주소·계정·인증정보는 공개 기록에 포함하지 않는다.

## 남은 수용

- G1: 실제 장치 티칭, 전체 정본 recipe 구조 편집, 지정된 독립 수용.
- G2: 모델 PC Gazebo/OMX 격리 owner 종단, 두 팔레트·두 층 box-only 실행.
- G3/C6: 원래 sheet 취급 목표와 도구 능력 불일치 해결.
- I1: 정상 종료 및 실제 CORE 주행·명령 만료/pause/reset 후 물리 정지.
- I2–I4: Nav2, 두 로봇 Fleet, 이동 후 정지 확인과 적재 연계.

후속 실제 준비에서 Docker·joint trajectory controller·CycloneDDS 설치, OMX vendor 8 packages 및 이미지 3개 빌드를 확인했다. 최초 실제 pytest collection 실패와 수정은 [Gazebo bootstrap 기록](gazebo-bootstrap.md)에 분리했다. 실제 fault 시험과 full G2는 아직 수용 전이다. 모델 PC의 webcam 때문에 native owner의 장치 차단 guard를 우회하지 않는다. 운영 robttt Fleet와 실제 로봇은 이 검증에 사용하지 않았다.
