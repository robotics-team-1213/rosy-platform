# 차선 keep 측면 뒤집기 수정 실기 배포 — 2026-10-06

## 결과

Pinky `9dfk`에 서명 릴리스 **2026.10.06-043**을 배포했다. 설치·실행 source revision은
배포 revision `5bc111a98ceb988bac8d85bc862eb332b0d296a3`이다. 포함 내용: keep 경계의 추적 측면이
반대쪽에 머무르면 최대 SIDE_FLIP_FRAMES(4) 프레임 뒤에 지면 기준 측면으로 되돌리는
수정(`8be56d0f4`), junction HOLD 규칙 분리(`ada948ac0`), CSS 토큰 수정. 장치 자체
재생으로 수정 동작을 확인했다. **DEVICE 소프트웨어 설치·정지 관측·장치 재생 PASS,
실제 keeper 제어·현장 주행은 HOLD.** 이번 설치 중 주행·E-Stop 해제·hardware
commissioning·keeper 모드 활성화는 수행하지 않았다.

## 진단 요약

20261005T134540Z(9dfk 조종 녹화) 329–367프레임: 로봇이 왼쪽 줄 위를 따라가며
추적 측면 `'left'`가 y −0.05…−0.07(실제로는 오른쪽)에 유지되어 편측 목표가
오른쪽 테이프 너머(−0.148 m)에 놓이고 error가 +1.0으로 고정됐다. 학습 페인트는
무관했다(당시 `paint_source=threshold`). 장치 보정 기하(pitch 0.2115 rad,
height 0.0549 m)는 LiDAR 벽 맞춤(11.9도)으로 검증됐으므로 삭제하지 않는다.

## 소스와 배포 경로

- ARM64 payload build `37351864765` (release 2026.10.06-043): success, source SHA 일치.
- Main CI `37350809917` (5bc111a98): success. 중간에 깨진 한 차례(red)는 동료의
  `review_app_web/app.css` literal opacity 위반이었고 동료가 동일 내용으로 선수정하여
  rebase 시 내 중복 커밋을 skip했다.
- Tarball SHA256: `9361e5664abe324d3fc18062382064652e81ae5259f946df920033f85c14b298`.
- 9dfk ABI 일치(공유 ros-jazzy 패키지), 2,949개 파일 서명 검증, signed tar 3,315 members.

## 실제 실행 확인

| 장치 | readback UTC | CORE | 실제 CORE cwd | 정지 상태 |
|---|---|---|---|---|
| 9dfk | 2026-10-05T18:04Z | active | `/opt/rosy/releases/2026.10.06-043` | IDLE, line-follow OFF, v=w=0 |

- 설치된 `lane_keep.py` SHA256: `c4b1303faf3082f0f4d5d3aa3954f4b8385da3e937015275daa60c469d25a496` —
  git의 source blob SHA256과 일치한다(바이트 동일).
- Image-layer는 `rosy_auto_update.py` 한 파일만 교체했다. backup 000011을 만들고
  109파일 unchanged, 추가 live unit restart 없음이다.

## 장치 자체 재생 (설치된 keeper, 녹화 329–372프레임, 장치 보정 기하)

| 프레임 | 구 코드 | 설치 코드 | 비고 |
|---|---|---|---|
| 338–342 | +1.000 | +1.000 | 줄이 실제로 카메라 아래를 통과 중 |
| 344 | +1.000 | **+0.023** | 측면이 `right`로 복귀 |
| 350–372 | +1.000 | −0.2…−0.4 / both 짝짓기 | 차선 복귀 조향 |
| 포화 44프레임 중 | 24+ | **9** | |

CORE readiness PASS. 실제 제어를 새 keeper로 전환한 증거는 아니다. 8kcn에는
배포하지 않았다(요청 범위: 9dfk).

## 증거

원본 로그·JSON·tarball은 `X:/DevTemp/lane-side-deploy-20261006/`에 보존한다.
실제 주소·인증 값은 공개 문서에 넣지 않는다.

| 파일 | 공개 SHA256 |
|---|---|
| `prepare.txt` | 기록 시점의 출력 전문 |
| `push-9dfk.txt` | push 전문(claim·activate·readiness 포함) |
| `device-replay.json` | 설치 모듈 재생 44행 |
| `lane-final.txt` | 차선 관련 278 passed/11 skipped |
| `push-gate-final.txt` | fast gate 490 passed/2 skipped |
