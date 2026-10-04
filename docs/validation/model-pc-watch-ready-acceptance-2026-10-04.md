# 모델 PC 실제 watcher: READY → accepted → HOLD 보류

## 실행 입력

D-434에 맞는 모델 PC의 별도 CPU venv와 검증된 source archive에서 watcher를
직접 실행했다. systemd 상시 설치와 별개의 user 실행이다. 원래 canonical intake
이력은 전체 파일 SHA를 대조해 별도 실행 폴더로 snapshot했으며 원본은 변경하지 않았다.
기존 store의 최고 모델 READY inbox를 실제 watcher 입력으로 사용했다.

- revision: lane-seg-20261004-ed0f9e71
- READY/content SHA: 55dd32b799d67a644e6ffb3948751322833d7593c7c921dffe1a469aff4fa692
- training dataset: d379-auto-lanes-v2@a302ec2d53b248c32b60a8cc8c2ce9ec40080cb1b264c1324d6205efcf9abc79
- fixed eval: pinky-heldout-20261001@0260507375e43354aadbdded329c8b5bd21e12fcbd3c4035e97ee3745b389094
- 기존 동일 eval의 최고 passing 이력과 shared classes 비교를 유지했다.

## 실제 결과

380 recorded replay frames와 고정 eval126 frames를 처리했다. 학습·평가 세션은
disjoint true, nonfinite0, eval mIoU0.5185248134695789, lane_line IoU0.7242653772798793이다.
watcher intake PASS 뒤 inbox를 accepted로 이동했다. 이동 후 content SHA와 READY를
다시 대조했다. 원래 canonical history snapshot도 원본과 다시 대조해 그대로임을 확인했다.

첫 로봇 관측은 시간 초과로 watcher exit78이었다. 로봇은 pending/attempts0,
robot_failures에 unreachable이 기록됐다. 두 번째 실행도 접속 실패였으며
증거 수집기가 manifest 이름을 잘못 지정해 마지막 읽기에서 실패했다. 실제 store 파일
이름 model_manifest.json을 확인하고 수집기를 수정했다. watcher를 재시작한 증거가 아니라
종료된 별도 CLI 실행·수집 실패다.

수정된 재실행은 실제 로봇 연결 후 기존 운영자 HOLD를 읽어 전달을 보류했다.
watcher exit0은 HOLD 처리 완료이며 전달 성공이 아니다. intake timestamp/횟수와
report SHA fc6f3f92ec3e8726753655d9c56b206ff5ffd4327fbb1a8fbf80e958ddb18deb가
그대로여서 재학습/재평가가 없음을 확인했다. 접속 성공 후 robot_failures는 지워지고
delivery pending/attempts0은 유지됐다.

이어 실제 deliver status를 모델 PC의 등록된 전용 robot key와 strict host pin으로
읽어 exit0을 확인했다. 기존 진단 작업의 manual push HOLD와 이전 shadow 모델을
확인했다. HOLD 해제·shadow pointer 변경·rollback·물리 명령은 실행하지 않았다.

## 범위와 남은 조건

store READY→intake→accepted와 재시도/HOLD 동작은 실제 모델 PC에서 확인했다.
systemd 계정/sandbox에서의 실행, 관리자 설치, 로봇 shadow loader/rollback와 FIELD
증거는 아니다. stop_line/crosswalk 정답 부족 및 roundabout entry 판단 미검증은 남는다.
사람 라벨·새 홀드아웃·policy trust/owner/Fleet 인증 결과도 미완료다.

Windows private evidence: X:/DevTemp/rosy-learning-audit-20261004/model-watch-data-binding-v1.
model PC 주소·계정·key 경로·전체 HOLD 기록·실행 설정은 private 자료에만 보존했다.
