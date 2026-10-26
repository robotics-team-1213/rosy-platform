# Selector 분리의 전체 시험 실패와 교차 대조

2026-10-27 KST. [앞선 소스 기록](../land-selection-extraction-2026-10-26/result.md)의 후속 증거다. `select`/`browser_tier` 분리 소스는 변경하지 않았다. G2 구현·시험·종료 예산·known failure 목록도 변경하지 않았다. 이 기록은 실패 원인 해결이나 착지 완료를 뜻하지 않는다.

## 공식 실행이 중단된 지점

시험한 Git commit은 758f92b6207bb50002c3dba384e1f520e61b2388, 기준 main Git commit은 9972822e21cc370c9b10e72a24b742209bc2fa1e다. 분리 구현·시험 및 기존 validation은 직전 검토 소스와 동일하고, 들어온 Monitoring 변경도 그대로 보존됐다는 독립 검토를 받았다.

공식 actor6887은 exit1로 종료했다. 해당 prepare의 guard는287 PASS, Fleet은7031 PASS/389 SKIP였다. root 실행은1051.94초에6 FAIL/11447 PASS/1211 SKIP였다. 전체 본시험 단계는1111초였으며23개 invocation이 취소돼 전체 FULL 완료가 아니다. 앞선 다른 소스 회차의 통과를 이 결과에 더하지 않는다.

실패한 ID는 다음과 같다.

- `test/test_g2_diagnostics.py::test_acceptance_unknown_without_goal_keeps_uncertainty_and_safe_filename`
- `test/test_g2_diagnostics.py::test_diagnostic_count_and_positions_are_bounded`
- `test/test_g2_diagnostics.py::test_observer_does_not_wait_for_or_call_owner_public_snapshot_under_owner_lock`
- `test/test_g2_diagnostics.py::test_observer_does_not_wait_for_handle_public_getters_under_handle_lock`
- `test/test_g2_gripper_trace.py::test_read_preserves_canonical_object_and_records_same_joint_state`
- `test/test_g2_gripper_trace.py::test_read_preserves_original_exception_without_persisting_private_error`

6건 모두 observe/read 결과를 확인한 뒤 `close(timeout=1)` 또는 `close(timeout=1.0)`가 False여서 실패했다. owner/handle lock 시험은 lock 중 observer 완료 assertion을 이미 통과했다. 6건은 단독 자동 재실행 한도5를 넘었으므로 LOAD-FLAKY로 허용되지 않았다. 자동 main 대조는 같은6건을0.70초에 통과했지만, 전체 root와 선택·메모리·실행 맥락이 다르므로 변경 원인을 확정하는 대조가 아니다. 기존 NEW6 실패를 지우지 않는다.

## 조사한 경계

G2 diagnostics, gripper trace, 공통 `g2_ports.write_json` 및 두 시험 파일의 Git blob은 기준 main과 같다. 새 selector helper와 시험 모듈의 최상위는 표준 라이브러리 import·상수·정의이며 thread 생성, G2 호출, 전역 monkeypatch는 없다.

Terminal close는 최대1초를 snapshot lock 획득과 writer join에 나누고, Gripper close는 closing/wake 설정 뒤 writer를 기다린다. 공통 writer는 JSON 기록·flush·파일 fsync·chmod·디렉터리 fsync를 수행한다. 문서화된 bounded close는 파일 I/O 지연 시 False를 반환할 수 있다. 실패 로그에서 이전 Terminal daemon의 DRAIN_TIMEOUT 출력이 뒤쪽 Gripper capture에 나타났지만, 최초 지연 위치를 증명하는 writer stack은 없다.

가설은 scheduler/파일 동기화/stdio 지연 또는 전체 pytest 실행 중 잔류 thread·공유 상태다. 현재 증거로 특정 원인이나 부하 원인을 확정하지 않는다. [기존 교차 비교 교훈](../../solutions/workflow-issues/attribute-intermittent-failure-by-line-then-interleaved-comparison.md)을 적용했다.

## 같은 AI 호스트의 A–B–B–A 대조

A는 위 시험 소스, B는 위 기준 main이다. 네 번 모두 같은 실제 AI 호스트와 env `bc752538299ca8d8`, freeze `279c2df20eca6924`를 확인했다. 매번 최소30GiB 여유·사용률90% 미만인 승인 lab만 사용했다. 노트북/site/로봇에서 pytest를 실행하지 않았다.

공식 runner에 source SHA를 명시하고 다음 선택을 전달했다. 전체 root를 수집하되 G2 두 파일에 해당하는 시험만 실행한다.

```text
test -k "g2_diagnostics or g2_gripper_trace" -o faulthandler_timeout=0.8
```

| 순서 | 소스 | PASS | root 수집 SKIP | deselected | 초 |
|---|---|---:|---:|---:|---:|
| A1 | A |21|7|12636|22.82|
| B1 | B |21|7|12625|17.87|
| B2 | B |21|7|12625|19.43|
| A2 | A |21|7|12636|19.39|

21개 선택 시험은 모두 실행됐다. 7개는 다른 root 모듈의 수집 skip이며 G2 선택 시험의 skip이 아니다. deselected 차이11은 이 분리의 새 selector 시험 수와 같다. 각 공식/outer/known exit는0이고 NEW0/known0/flaky0이다. faulthandler timeout dump는 없었다. 이 대조의 메모리·앞선 실행 이력은 원래 전체 root와 같지 않다. 따라서 전체 프로세스 맥락 가설과 NEW6의 원인은 미해결이다.

앞선 model 호스트의 두 파일 직접 선택도 A/B 각각21 PASS였으나, 실패한 AI 호스트·전체 수집과 다르므로 위 대조의 라운드로 합산하지 않는다. model의 busy 표시가 없어질 때까지 공식 runner가 기다렸으며 표시를 제거하거나 우회하지 않았다.

## 원본과 판정 범위

외부 증거 루트는 `%LOCALAPPDATA%/Temp/rosy-land-selection/`다. `failed-full-758/`의39개 파일과 console을 원본과 같은 해시로 보존했다. 일부 파일은 앞선 회차의 잔존물이다. 현재 실패 판정에는 해당 console 구간과 `run-gpre-1.txt`, `run-pre-13.txt`, `run-pre-23.txt`, `main-pre-pre-23.txt`만 연결한다. 옛 `alone-pre-pre-23-1.txt`는 이번6건의 재실행 증거가 아니다.

실패 console의 SHA256은 `E5DA1FFDDF01A75FFDE56CC9A3CEFCF40428385973DE6318F432885697324BE2`다. 교차 대조는 `g2-collect-ai-{a1,b1,b2,a2}/run-1.txt`와 각각의 runner/known 파일에 있다.

| raw | SHA-256 |
|---|---|
| 실패 root `run-pre-23.txt` |`0588d3c934680e8ad478f987350936dcf3fd42be0e896b2729936b0eea0034ad`|
| main6 대조 `main-pre-pre-23.txt` |`31a0dbe5b399174dfcf824f26f50b3fdcbbe1742a441730ab13c1cb0145743ed`|
| A1 |`3d19ebefb1c559b07049b84fd79d02ba8f69951e0102f34ce38a7afb14eb3c6c`|
| B1 |`b49d72b67a220e6594e6c3417462aaf679a5896fe4ac3ed84635c02b3e3f0f7d`|
| B2 |`4d96fcae4df648508c5be67ed6835528b3955197eebac2f2efd726869c5460da`|
| A2 |`5a1fd7c3841e64fafc82ad38f1335b8b51518312b5865362604e17c4cd0e3f43`|

제품 수정·실패 목록 등록·게이트 완화 없이 다음 공식 전체 실행을 준비한다. 새 전체 결과, 최종 receipt, 실제 main ancestry, 게시·배포·장치 수용은 이 기록 작성 시 미검증이다. 같은 실패가 재현되면 writer stack과 큐 상태를 관측해 지연 위치를 구분해야 한다. 이 대조의 통과를 원래 FULL의 성공으로 바꾸지 않는다.

CE: 미해결 — 기존 교훈을 적용했으나 G2 종료 지연 원인을 확정하거나 해결한 증거가 없다. 별도 해결 교훈을 만들지 않았다.
