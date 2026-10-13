# 042 배포와 자동 추종 시작 결과

2026-10-05 UTC 실기 기록. 이전 `result.md`의 NOT_RUN은 이전 시험 시점의 판정이다.

## 배포

- 릴리스: `2026.10.05-042`, source `07dc89f20d681e581277d84d3cd38ebd7ddffea7`.
- CI run `37282901412`, native ARM64 build run `37282981358`: success, 동일 source.
- 서명 payload SHA256: `a689d7b5f284dbd18110dd89bd0da6e93fdfa83c37fa31991d015436ec9fa740`.
- 릴리스의 ROS Jazzy 패키지 342개, 필수 ROSY 패키지 검증 통과. 양 장치 공유 ABI 314개 일치. 서명 파일 2929개 검증.
- 9dfk와 8kcn 모두 preview 후 승인된 배포 도구로 활성화. CORE·camera 실제 프로세스 cwd는 042이고 CORE·camera·IO active.
- 설치된 line-follow UI SHA256: `11e4668807814778894664f209c601098238a8b025ee3a3083b780de88fa177d`.
- 설치된 keeper SHA256: `def75b21bf6f5b5533fd09b9a597f3dd52c48b97322254cd3c5184fbc8c80050`.
- 학습 설정, 관측 overlay, shadow/lane_current/hold 포인터 파일의 전후 존재·경로·바이트 해시 일치. 모델 가중치 전체 검증이나 실제 학습 추론 증거는 아니다.

## 수동 실기와 자동 모드의 구분

042 배포 전 040의 9dfk에서 실제 카메라를 확인하고 대시보드 수동 조작을 수행했다.
좌회전 0.548초: yaw +2.180도. 우회전 0.545초: yaw -1.597도.
직진 0.03 m/s, 1.031초: 오도메트리 0.030281 m 이동.
도구의 정지 속도 허용 오차 도달 시간은 각각 0.299, 0.301, 0.307초이며 물리 정지 거리 실측이 아니다.
이는 자동 조향이나 자동 차선 주행 성공 증거가 아니다. 8kcn은 주행시키지 않았다.

## 042 자동 추종 실제 요청

9dfk의 keep/threshold/NOMINAL 설정과 최신 카메라 원본을 확인했다.
배포 후 정지 관측 10초에서 원본 80프레임, keeper debug 80건, final cmd 500건 모두 0.
운용 콘솔은 차선 추종 탭을 제공하지 않았다. 따라서 UI 시작 성공으로 기록하지 않는다.
시작 버튼 자체의 구동 준비 조건 수정과 런타임 manifest의 탭 제공 조건은 별개이며 후자는 미해결이다.

인증된 정식 CORE API `PUT /api/v1/line-follow/mode`에 `{mode: CAMERA_LINE}`을 요청했다.
HTTP 200으로 WAITING을 반환한 뒤, 각 250ms 대기 후 수행한 8개 robot/state readback 모두
CAMERA_LINE/HOLD, `nominal_ground_requires_driver`, 선속도·각속도 0이었다.
차선 confidence 0.9, error 0.050311, age 0.11초였다. 검출 정확도나 완주 성공률은 아니다.
`hold_s`를 보내거나 사람의 진행 확인을 에이전트 타이머로 대체하지 않았다.
OFF 요청 후 IDLE/OFF와 정확한 속도 0을 확인했다. 두 관리자 세션은 logout 204 후 폐기했다.

판정: signed 배포 및 실제 자동 모드 요청은 확인. **자동 이동·자동 조향·FIELD 수용은 미확인**.
실측 카메라 보정과 D-344 진행 확인 조건이 필요하다. 이 시험에서 보호 조건을 해제하지 않았다.

## 증거

`X:/DevTemp/line-remote-20261005/`의 `prepare.txt`, `run-37282901412.json`,
`run-37282981358.json`, 양 장치 `*-deploy.txt`, `deployed-042-*.json`,
`before-*-preservation.json`, `after-*-preservation.json`, `left-result.json`,
`right-result.json`, `forward-result.json`, `post-042-rosy-pinky-9dfk-camera.json/png`,
`auto-result.json`, `auto-operation.txt`, `logout.json`.
개인 접속 정보와 인증 자료는 공개 문서에 포함하지 않는다.
