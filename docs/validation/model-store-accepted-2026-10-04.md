# READY 후보의 accepted 이동과 장치 hold 확인

2026-10-04 KST. 이전 [모델 비교](perception-model-comparison-2026-10-04.md)에 이어
소형 후보 `lane-seg-20261004-f21a7a97`를 canonical store의 inbox에 배치했다.
실행 도구는 d78be8339 archive의 handover/store/intake/watch/deliver이며
학습 recipe 파일은 d003262b3와 같은 내용이다.

## 실제 READY 접수

READY 폴더 `lane-seg-20261004-f21a7a97__20261003T204104Z`.
content_sha `b3f04c467dc15cb055e11e30a10d529ce3caeeb93f326fb49bd164bf90e7d541`.
최초 wrapper가 handover의 inbox_dir 인자에 store root를 전달했다.
watcher는 그 위치를 보지 않아 아무 접수도 하지 않았다. 폴더의 manifest/READY를 확인한 뒤
정확한 models/inbox로 옮겨 실제 접수를 실행했다. 처음 exit 0을 접수 증거로 사용하지 않는다.

intake attempts 1 / pass / reasons 없음. 고정 평가 mIoU 0.50522,
같은 require_eval·class role·세션 비겹침·champion 하락 기준을 유지했다.
실제 models/accepted/lane-seg-20261004-f21a7a97/ 이동과 ONNX SHA 일치를 확인했다.

8kcn 전달 관측은 DNS failure exit 77이었다. watcher는 pending을 유지하고
push attempts 0, robot_failures.kind=dns를 기록했다. 장치 모델 쓰기는 없었다.

## 실제 장치와 기존 pin 확인

관제 PC의 현재 이름 해석과 모델 PC의 실제 로컬 네트워크 route를 조회했다.
이미 등록된 IP 기준 SSH pin으로 9dfk에 접속해 hostname=rosy-pinky-9dfk를 확인했다.
unknown key를 받거나 StrictHostKeyChecking을 완화하지 않았다.
그 기존 검증 pin의 동일 공개 키에 robot-id alias를 추가하고 원래 항목은 보존했다.
이후 strict HostKeyAlias=rosy-pinky-9dfk로 status를 다시 읽었다.
주소·계정·키는 private 설정에만 둔다.

관측 당시 9dfk:

- shadow `lane-seg-20261003-6e2e5640`.
- active/previous 없음.
- 기존 operator `codex-lane-diagnosis`의 manual push hold.
- 기존 history에 그 push 1건. hold를 해제하거나 수동 push로 덮어쓰지 않았다.
- robot state HTTP는 인증 없는 조회에서 401. 이 응답을 idle 증거로 사용하지 않는다.

원래 후보 설정/state는 보존하고 별도 9dfk probe 설정/state로 watcher를 실행했다.
실제 로그는 held by an operator. 9dfk push attempts 0 / pending, shadow map 없음.
실제 장치 shadow 교체·runtime load·rollback은 이 실행에서 하지 않았다.

## 증거와 남은 작업

모델 PC의 pipeline-closure-20261004/evidence/watch-qualified-base8.log,
watch-9dfk-held-probe.log, state.json, state-9dfk-held-probe.json과
canonical accepted 폴더가 원본 증거다. probe는 일회성이고 timer는 설치하지 않았다.
승인된 기존 hold 해제 및 인증된 idle/runtime 관측 뒤 shadow 전달·rollback을 검증해야 한다.
모델 PC system timer 설치의 sudo 조건도 남는다.
이 결과는 READY→accepted와 기존 hold 존중 증거이며 DEVICE/FIELD 수용은 아니다.
