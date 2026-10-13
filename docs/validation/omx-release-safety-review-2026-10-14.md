# OMX 후속 공개 검증과 안전 변경 이력 리뷰

날짜: 2026-10-14. 사용자 요청은 공유 main 전체 push·CI 확인이다.
리뷰 대상은 main `a39ee0f03`의 D-400 HOLD 변경이며, 최종 수정 후보는 `3f6c69245`다.
독립 검토자: Codex `/root/review_release_safety`. 검토자는 소스만 읽었고 시험·장치 조작은 하지 않았다.

## 발견과 수정

- CI 38435850880의 core-domain에서 accounts.html 체크박스 공용 클래스 누락 1건이 실패했다.
  `487d950e5`에서 label.ui-check와 input.ui-field를 적용했고 원격 공용 UI 시험 31개가 통과했다.
- 독립 리뷰에서 `100 → 100.4 → 100.3` 시계 역행이 HOLD로 남는 결함을 찾았다.
  예외를 내는 평가기의 완료 시간을 검사하지 않아, 첫 평가가 stale_hold_s를 초과해도 HOLD가 됐다.
  반복된 긴 평가의 실행 시간을 idle로 간주해 공백이 계속 새로 시작되는 문제도 있었다.
- `45af7175b` 원격 재현: 7 failed, 40 passed, NEW 7. 기존 실패로 분류하지 않았다.
- `3f6c69245`는 시작/완료 시각의 finite·순서와 이전 완료 이후의 역행을 검사한다.
  gap 나이는 완료 시각까지 세고, idle은 이전 완료부터 다음 시작까지 센다.
  첫 평가에서 한도를 넘겨 래치한 경우 HOLD 계수도 증가시키지 않는다.
- 독립 검토자가 수정과 계수 회귀를 확인했고, 아래 원격 GREEN을 조건으로 SOURCE 리뷰를 수용했다.
  수정 후 원격 322 passed, NEW 0: safety decision/shadow, control absorption/link/adapter,
  policy status, bridge timers, 구조 예산, safety-review, 공용 UI 시험.

## 이력 예외 근거

공유 main 이력은 재작성하지 않는다. 아래 정확한 커밋만 `safety_review.py`의 기존 EXEMPT
방식으로 기록한다. 이는 **수정된 후손 `3f6c69245`를 포함한 후보의 역사적 출처 검토**다.
중간 커밋 단독의 동작 승인이 아니며, baseline·safety 태그·향후 trailer 요구를 바꾸지 않는다.

| 커밋 | 검토 근거 |
|---|---|
| c9983d2fe | DTO/판정 검증 추출과 re-export; identity·finite·lease 검사 유지 |
| 1e8acc5dd | HOLD는 0만 반환; epoch/candidate/estop 경계와 stop·malformed·actuation 즉시 래치 유지. 시간 결함 수정 후손 필요 |
| ed8f61fbf | D-400의 50Hz 주기 기반 20ms 답 상한; evidence lease 및 별도 actuation 10ms 유지 |
| a23efed1f | HOLD 상태를 읽기 전용 property로 변경; 출력 권한 변경 없음 |
| 6a1011361 | 0.5초 idle reset과 복구 한계 명시; 평가 실행 시간을 idle과 구분하는 수정 후손 필요 |

## 증거와 한계

원격 로그는 X: omx-imitation 세션의 `logs/release-field`, `logs/gap-red`, `logs/gap-green`에 있다.
합성/단위 검증은 실제 ROS producer, 센서 지연, 정지 readback, SIM 또는 DEVICE 수용을 대체하지 않는다.
유효한 판정과 기존 candidate freshness 조건이 갖춰져야 HOLD 뒤 재개할 수 있다.
snapshot_missing은 무효화된 근거도 포함하며 D-400/D-740의 현장 제한은 유지한다.
E-stop reset·rearm·실물 motion·운영 활성화는 수행하지 않았다. 최종 push/CI 결과는 실행 종료 후 별도로 보고한다.
