---
title: "A release script without its __main__ guard rolled back every robot with an empty error"
date: "2026-11-08"
category: deployment
module: deploy/robot/pinky_pro/native
problem_type: integration_issue
component: deployment
symptoms:
  - "updater last_result IMAGE_LAYER_SYNC_FAILED with an empty detail, outcome rolled_back"
  - "sync-image-layer.py --dry-run by hand exits 0 and prints nothing"
root_cause: logic_error
resolution_type: code_fix
applies_when:
  - "splitting or moving a script the updater or a unit runs as a program"
  - "a payload canary rolls back with IMAGE_LAYER_SYNC_FAILED"
---

# 실행 스크립트의 `__main__` 가드가 빠져 모든 기체가 롤백한 경우

## 증상

2026-11-08 릴리스 2026.11.07-175의 canary b8xy가 `IMAGE_LAYER_SYNC_FAILED: `(detail 빈 문자열)로
롤백했고, CD가 175를 withdrawn했다. 기체는 이전 릴리스 2026.10.29-001로 정상 복귀했다.
같은 무렵 battery_publisher traceback과 `/var/crash` 읽기 전용 오류가 보였지만, 활성화 중 SIGINT
종료와 unit 샌드박스의 부수 현상이었다. health 단계 전에 실패했으므로 롤백 원인이 아니다.

## 원인

D-949 분할 커밋 `0164fade8f`가 [sync-image-layer.py](../../../deploy/robot/pinky_pro/native/sync-image-layer.py)
끝의 `if __name__ == "__main__": raise SystemExit(main())`를 지웠다. 스크립트는 `main()`을 정의만 하고
부르지 않아 출력 없이 exit 0으로 끝난다. updater의 `_sync()`는 마지막 줄 JSON `ok:true`를 요구하므로
실패로 보고 롤백했다. stdout과 stderr가 모두 비어 detail도 비었다.

기체의 updater는 이미지에 남은 옛 판(10.29)이지만, sync 스크립트는 **새 릴리스의 것**을 실행한다.
그래서 이 결함은 그 커밋 이후의 모든 payload를 모든 기체에서 롤백시킨다. 모듈 import로 함수를 부르는
시험만으로는 드러나지 않았다.

## 수정과 검증

- 가드를 되살리고, 스크립트를 프로그램으로 실행해 JSON 결과를 확인하는 시험을 더했다
  (`test/test_image_layer_sync.py::test_script_run_as_main_prints_a_json_result`).
- 출력 없는 실패는 `IMAGE_LAYER_SYNC_FAILED: no output, exit <rc>`로 남긴다
  (`test/test_rosy_auto_update_apply.py::test_silent_sync_failure_names_the_exit_code`).
  이 문구는 수정이 든 릴리스를 받은 기체부터 나온다.
- 원격 시험 134개 통과(92ad923329). 장치 수용은 수정이 든 새 릴리스의 canary commit으로 확인한다.

## 복구

기체 쪽 수정은 필요 없다. 수정이 든 새 릴리스 id로 다시 게시한다. 175는 기체 updater 상태에
실패로 남아 같은 id로는 다시 받지 않는다.

## 다음에 적용할 조건

`main()`이 있는 기체 실행 스크립트를 옮기거나 쪼갤 때는 가드를 확인하고, 프로그램으로 실행하는 시험이
있는지 본다. canary가 `IMAGE_LAYER_SYNC_FAILED`로 롤백하면 새 릴리스의 sync 스크립트를 기체에서
`--dry-run`으로 직접 돌려 JSON이 나오는지부터 본다.
