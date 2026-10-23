---
title: PWM 캡의 절반만 쓰고 멈추는 팔로워 관절은 캡 부족이 아니라 처짐이다
date: 2026-10-23
category: runtime-errors
module: deploy/robot/omx (guarded_native.py GuardedMotion, two_arm_pipeline.py align)
problem_type: runtime_error
component: development_workflow
symptoms:
  - "align이 'alignment deadline exceeded before command commit'으로 끝나고 관절은 목표에서 2.99° 모자란다"
  - "PWM 캡을 120에서 300으로 올려도 Present_PWM은 -170에 머문다(캡의 57%)"
  - "같은 관절이 2026-10-22에는 캡 400에서도 -170에 머문 채 2틱만 움직였다"
root_cause: missing_validation
resolution_type: workflow_improvement
severity: medium
tags: [omx, dynamixel, pwm-limit, follower, gravity-droop, guarded-motion, device-diagnosis]
---

# PWM 캡의 절반만 쓰고 멈추는 팔로워 관절은 캡 부족이 아니라 처짐이다

## 문제

두팔 파이프라인의 `align`은 팔로워를 리더 자세로 1°/s로 옮기고, 모자란 관절이 있으면
하중 진단을 남긴다. 2026-10-23 실물에서 `arm_a`의 `shoulder_lift`(XL430-W250)가 목표 689에
실제 723, 즉 2.99° 모자란 채로 반복해서 멈췄다. 첫 가설은 공통 PWM 캡 120이었다. 관절별 캡을
300으로 올리는 변경(D-847)을 배포했지만 관절은 여전히 3°를 남겼다.

## 증상

- `align`의 출력은 `reason: blocked_by_load`, `stop_joint: null`, `error: alignment deadline exceeded
  before command commit`, `gap_degrees.shoulder_lift: -2.988`였다.
- 같은 순간 `pwm_limits`는 `{shoulder_pan: 120, shoulder_lift: 300, elbow_flex: 120, wrist_flex: 120,
  wrist_roll: 120}`이었고 `Present_PWM`은 −170이었다. 캡의 57%다.
- 2026-10-22 세션에서는 같은 관절이 캡 400에서도 −170에 머문 채 2틱만 움직였다.
- `align`은 실패 경로에서 영수증 파일을 남기지 않는다. 위 값은 표준출력과 관측 기록에서 읽었다.

## 시도했지만 통하지 않은 것

- **캡을 올렸다.** 120 → 300. 캡에 붙어 있던 −120은 사라졌지만 −170에서 3°가 그대로 남았다.
  이미 400에서도 같았으므로 값의 크기 문제가 아니었다.
- **캡과 토크 상태를 EEPROM에서 확인했다.** 관절별 캡 300 적용, 시험 종료 뒤 휴지 캡 20 복구,
  토크 OFF가 모두 정상이었다. 설정은 의심할 곳이 아니었다.
- **실패를 "느린 램프"로 읽었다.** 문구는 기한 초과지만 원인은 속도가 아니라 도달 불가다.
  그 문구만 보고 속도·시간 상한을 늘리면 같은 자리에서 또 멈춘다.
- **가드의 하중 정지를 기다렸다.** 가드의 정지 조건은 `guarded_native.py:226`의
  `error > 2 and abs(pwm[name]) >= 0.9 * self.pwm_limits[name]`이고, 57%에서는 절대 걸리지 않는다.
  가드가 조용했다는 사실은 하중이 없다는 증거가 아니다.

## 해결

한계값을 바꾸기 전에 **그 관절이 실제로 상한을 쓰고 있는지**를 먼저 계산한다.

1. 1초 남짓의 `Present_PWM`과 `PWM_Limit`을 같은 관절에서 읽어 `|PWM| / cap`을 본다.
2. 비율이 0.9 미만이면(특히 0.6 미만) 서보는 포화가 아니다. 캡을 올려도 움직임은 늘지 않는다.
   원인은 자중·마찰·접촉이고, 대응은 팔 지지·자세 변경·게인 조정이다.
3. 비율이 0.95 이상으로 붙어 있으면서 오차가 커지면 그때가 캡이 벽인 경우다. 그때만 올리고,
   올린 근거로 그 비율을 영수증에 남긴다.

이번 회차의 처리: 캡 300은 유지했다(서보가 −170을 낼 수 있어야 하므로 120은 실제로 부족했다).
관절을 더 조이지 않고, 지지·자세로 3°를 없애는 쪽으로 다음 시험을 옮겼다. 파이프라인은
`two_arm_pipeline.py:341`에서 `|PWM| >= 0.5 * cap`인 관절을 하중으로 지목하고
(`_diagnosis`), `align`·`drive` 행에 관절별 `pwm_limits`를 남기므로 다음에는 이 계산을
영수증만으로 할 수 있다.

## 왜 통하는가

위치 제어 루프는 오차에 비례하는 토크를 낸다. 중력 토크가 일정하면 관절은 "토크가 중력과 같아지는
오차"에서 정지하고, 그 오차에서의 PWM이 계속 유지된다. 그래서 관측은 **일정한 PWM + 일정한 오차**로
나타나며, 캡이 병목일 때의 **캡에 붙은 PWM + 계속 커지는 오차**와 구분된다. −170/300은 앞쪽이고,
−170/400에서도 같았다는 과거 관측이 이를 뒷받침한다.

부수적으로, 가드의 0.9 규칙과 진단의 0.5 규칙이 서로 다른 임계값을 쓴다는 점도 확인했다. 0.57은
가드에게는 하중이 아니고 진단에게는 하중이다. 이번에는 진단이 옳았지만, 두 임계값의 차이를 모르면
"가드가 멈추지 않았으니 하중이 아니다"라고 잘못 읽게 된다.

## 예방

- 정지·기한 초과를 만나면 **한계값 변경 전에 `|Present_PWM| / PWM_Limit`을 계산한다.** 이 한 번의
  읽기가 "캡 부족"과 "처짐"을 몇 초 안에 가른다. 캡은 토크 OFF에서만 바뀌고 되돌리는 비용도 크다.
- 가드의 하중 정지가 걸리지 않았다는 사실을 하중 없음으로 해석하지 않는다. 가드 규칙은 캡의 90%를
  요구하므로, 처짐처럼 낮은 PWM으로 버티는 하중은 원리적으로 보지 못한다.
  ([inability-to-check-recorded-as-clean-result](../workflow-issues/inability-to-check-recorded-as-clean-result.md)와 같은 실패 계열)
- 실패 단계도 영수증을 남기도록 고친다. 지금은 실패한 `align`의 `pwm_limits`·`reason`이 표준출력에만
  있어, 세션이 끝나면 근거를 다시 만들 수 없다.
- 호스트 pytest는 가짜 버스로 돌므로 이 처짐을 재현하지 못한다. 캡·하중 판단은 실물 `preflight` →
  `align` 한 회와 `pwm_limits`·`Present_PWM` 값으로 확인한다.
  ([dev overlay를 이미지 전에 실물로 검증하기](../workflow-issues/dev-overlay-validate-live-before-baking-the-image-2026-09-24.md)의 계열)
- 같은 관절이 관절별 캡의 첫 적용 대상이었다는 점도 기억한다. 캡이 관절마다 다르면 "어느 캡에서
  멈췄는지"를 영수증에서 확인해야 하고, 공통 캡 시절의 관측을 그대로 인용하면 안 된다.

## 관련 기록

- 결정: `docs/adr/D-847-omx-per-joint-follower-caps.md` (실물 측정 절)
- 코드: `deploy/robot/omx/guarded_native.py:226` (가드 하중 조건), `two_arm_pipeline.py:140`
  (`follower_limits`), `:341` (진단의 0.5 임계값), `:392` (`align` 결과의 `pwm_limits`)
- 실제 수용은 아직 아니다. 3°는 지지·자세로 없애야 하고, DEVICE/FIELD 관문과 D-430 독립 safety
  review는 그대로 남아 있다. 상세 현장 기록은 저장소 밖 비공개 세션 기록에 있고, 공개 문서에는
  위 수치만 남긴다.
