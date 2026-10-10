# D-616 开発용 연속 차선추종 시험

## 구현과 검증

- `feat/lane-continuous-test`, 구현 commit `6562f685d`, ADR/harness 정렬 `7c8985c93`.
- `edge_drive.py drive --continuous-test`: 현장 감독을 전제로 전경 SSH 터미널에서 기존 operator hold lease를 유지한다. 시간·3초 무이동·CORE HOLD 사유로 OFF를 보내지 않는다. 관제 OFF, hold 거절, 상태 읽기 실패, Ctrl+C 또는 터미널 종료로 끝낸다. 자동 재무장이나 stuck 승인 요청은 보내지 않는다.
- CORE와 모델 runtime을 수정하거나 새 이미지를 빌드하지 않았다. 인증을 tokenless 개발 모드로 바꾸거나 CORE의 NOMINAL 지면·body/IR/E-Stop/횡단보도 보호를 해제하지 않았다.
- 원격 캡처 시험: 17 passed. 착지 검사: 366 passed, known_failures 0 NEW, lint 통과. harness 설정 gap 행 변경으로 FULL selector가 표시됐지만 실제 실행은 guards + mapped suites이며 FULL CI는 별도다. 노트북 pytest는 실행하지 않았다.
- 양쪽 장치 파일은 SHA-256으로 로컬과 일치했다: edge_drive.py sha256: `257890ef50f6aa1f1de69e3ae12782203394fdd100f83301ae9395ed500d4ff0`, bundle sha256: `6944ae553868b15c63d71b9d2448b6d3a4649fe103054f8438a2d1d3e3cd8512`.

## 실물 시작과 스냅샷

- 2026-10-10 09:11:45 UTC 9dfk, 09:12:14 UTC 8kcn 시작. 사용자에게 중지 가능한 전경 시험 창 두 개를 열었다. 숨긴 daemon/분리된 SSH 프로세스로 실행하지 않았다. 종료 시 runner는 token logout과 자동 업데이트 hold release를 수행한다.
- 시작 전 두 로봇 IDLE, 실제 속도 0, pose/velocity fresh, E-Stop false, recorder idle, 카메라 fresh/usable 확인.
- 실제 paint pointer는 둘 다 v2 `lane-seg-20261010-451f0f85`, shadow pointer는 원본 v1 `lane-seg-20261010-ede0ae96`였다.
- 09:12:40 UTC 부근: 9dfk CAMERA_LINE TRACKING, keeper v2 receipt age 0.002 s, 실제 선속도 0.0161 m/s·각속도 −0.0133 rad/s를 먼저 확인했다. 후속 스냅샷은 선속도 0.00109 m/s·각속도 −0.33796 rad/s, 명령 약 0.00083 m/s·−0.3 rad/s였다. 저속 회전과 confidence 0.37을 정상 코스 수용으로 판정하지 않는다.
- 8kcn은 CAMERA_LINE HOLD / lane_departure, stuck cause no_motion / WAITING_CONSOLE, local_enabled false, attempts 0을 관측했다. 명령 0, 측정치는 0.00065 m/s·0.01336 rad/s였다. 해당 시점의 learned receipt는 fresh 확인이 안 됐으므로 v2 pointer 선택과 fresh inference를 구분한다.
- 09:14:00 UTC 로그: 9dfk t=133.7 s TRACKING, 8kcn t=104.1 s HOLD, 모두 hold HTTP 200. 기존 45초 시험 제한과 3초 무이동 종료가 세션을 끊지 않는다는 실물 증거다. CORE HOLD를 강제 해제하지 않았다.
- 녹화: `20261010T091145Z_rosy_41`, `20261010T091214Z_rosy_40`. 기존 recorder의 각 job 최대 시간은 600초다. 이 한도가 연속 테스트의 시간 제한을 의미하지는 않으며, 녹화 한도 이후에도 상태 콘솔은 지속한다.

## 증거 위치와 범위

`X:/DevTemp/d616-continuous/`의 `9dfk-console.log`, `8kcn-console.log`는 실행 중인 로그다. frozen 스냅샷:

- 9dfk-live-status.json sha256: `9e8c106e43a19950e5ee108b1ccc7550d48187e57cb97d1a3422711ea26ed331`.
- 8kcn-live-status.json sha256: `99c325cdb56bd70e235f46c10847f82b8e646b2707492200a498a5d404667a7b`.

판정: **v2 적용·시험 모드 실행·횡단보도 인식/접근 정지·연속 관찰 기능은 확인한 범위에서 통과**. 전체 코스 주행, 횡단보도 clear 이후 재출발·완전 통과, 8kcn 회전 응답 결함 해결은 확인하지 않았다. Ctrl+C/관제 OFF/연결 손실의 정리와 무재무장은 합성 시험으로 검증했으며, 이번 진행 중인 연속 세션을 끊어서 물리 종료 시험을 추가하지는 않았다.

## 앞선 후속 시험

09:11 이전의 현장 요청 중 9dfk 8초 재시험은 odom 변위 0.0798 m 뒤 crosswalk_person_present 대기를 4.14초까지 관측했고, finally OFF·속도 0을 확인했다. `9dfk-camera-line-crosswalk-r2.jsonl` sha256: `67d163752447ac0e47f209608980a166ed874105462ceef7299983744ccf3a9b`.

보수적인 2초 재시험은 9dfk 약 0.0548 m 뒤 lane_departure, 8kcn 약 0.0086 m·yaw +0.17694 rad 뒤 측정 운동 한도 초과로 종료했다. 각각 `X:/DevTemp/d614-live/9dfk-camera-line-guarded-r3.jsonl` sha256: `a1a54c6520e19baaaf924efef0e49a3f0288e157cd2846812b7cad2225ef98dd`, `8kcn-camera-line-guarded-r3.jsonl` sha256: `8155a9c900eecbb349291bd93cf3e3ca5040edb9ef9f8882de8e19ee8317a924`. 두 장치 모두 OFF·속도 0을 확인했다. 이 짧은 중단이 현장 관찰을 끊는다는 사용자 요청에 따라 D-616을 만들었다. 8kcn의 앞선 명령/odom 부호 불일치를 해결했다고 기록하지 않는다.
