# Tool1 · main445 통합과 full carry 자격 회귀 (2026-10-27)

[이전 고정 검증 기록](../land-explicit-full-2026-10-27d/result.md)의 후속 실행이다. 기존 27·27b·27c·27d는 수정하지 않았다. 여기의 원격 시험은 커밋된 소스의 집중 검증이며, 정식 FULL·실제 Chromium·착지·게시·장치·충전 원인 해결 근거가 아니다.

## 소스와 검토 범위

- 보호된 commit `63a19bf9ca17eb4cd5ea0072d023fe2511072434`에 actual main commit `44511b1a055cedc00ad410ecd6d7cd14aea706cf`를 정상 병합했다. incoming MAINRED·publisher·재부팅 대기·SIM 변경과 peer camera browser mapping을 보존했다.
- Root가 실제 검토한 tree `4de2848e5b5228fad26291bb1f950a8e7f87adc5`를 known-RED checkpoint commit `2663fcfd9d89175b5ea4618dd8514628d275f9ba`로 남겼다. full carry veto는 이 단계에 의도적으로 없었다.
- 기존 CLI 상태 초기화·정규화·none 진단을 이미 착지한 `land_selection` 모듈의 새 `configure(land,args)` helper로 옮겨 `land.py`를 579→570행으로 줄였다. caller 참조 해제와 내부 False→main return2 대응 후 옛 블록 AST가 동일했다. `landed_copy` 전 순서·literal full·full+noqueue 거절·custom 추가 시험·skip-reason은 보존했다. 공백 압축이나 ratchet 증가는 없다.
- 실제 RED 뒤 Root가 tree `a5dff5ffe51acbe7ce9d4322e9130283152df8d3`를 검토했고 fix commit `1bdd41e94a2fb84bb4a7212242152a10765c27e8`로 남겼다. full만 active CARRIED와 carried summary를 모두 거절한다. live state가 비었어도 요약을 버리지 않는다. 실제 guard/body 결과는 save·witness 이전과 turn 검사에 전달된다.
- 두 writer는 같은 leaf tier 정책을 쓴다. auto의 active carry는 `carried`로 저장해 restart restore를 거절하며, 다른 LOAD-FLAKY/NARROW는 `None`의 기존 nonqualifying delta bridge를 유지한다. auto에 full 전용 summary veto를 확대하지 않아 나중의 clean pass/close 정책을 보존했다. full ALL·fresh guard clone·fresh-only report·현재 프로세스 witness·argv/env·최종 FF 전 검사는 유지했다.

## 실제 RED/GREEN

새 시험은 기존 full_case의 실제 selector·prepare·isolation 흐름을 사용하고 producer 반환 summary와 active state만 대조했다. 내부 원격 executor는 그 fixture의 시험 더블이다. 정식 FULL 실행으로 해석하지 않는다. guard/body 각각 summary-only·active-only·both의 6개 full 반례가 `DID NOT RAISE Stop`으로 실패했다. setup·import·수집 오류가 아니다. auto 우선순위 2개와 CLI 대조 3개는 통과했다.

| 실행 폴더 | source commit | quiet 진행 행과 판정 |
|---|---|---|
| `integration445-red` | `commit 2663fcfd9d` | 6 FAIL·5 PASS·0 SKIP, NEW6/known0/flaky0, official·outer·known exit1 |
| `integration445-green-controls` | `commit 1bdd41e94a` | 11 PASS·0 SKIP, NEW0/known0/flaky0, 세 exit0 |
| `integration445-green-tools` | `commit 1bdd41e94a` | owner 15파일 395 PASS·0 SKIP, NEW0/known0/flaky0, 세 exit0 |
| `integration445-green-selectors` | `commit 1bdd41e94a` | selector/actual architecture 5파일 299 PASS·0 SKIP, NEW0/known0/flaky0, 세 exit0 |

개수는 quiet 진행 행만 세었으며 출력되지 않은 시간 요약은 인용하지 않는다. controls 11개는 395개와 겹치므로 고유 시험 수로 합산하지 않는다. classifier의 listed-but-not-failing 1개는 추가 실행 근거가 아니다. 각 실행은 외부 qualified-labs wrapper의 fresh disk 기준(30 GiB 이상·사용률 90% 미만)을 통과한 model/AI에만 공식 runner를 보냈다. site·laptop fallback은 없었다.

공식 `remote_pytest.py --sha <위 commit> --log-dir <해당 폴더> -- <대상> -q`의 대상은 다음과 같다. RED와 controls는 같은 argv다.

```text
controls: test/test_land_mainred_flow.py::test_literal_full_prepare_rejects_carried_summary_or_active_state test/test_land_mainred_flow.py::test_auto_carried_tier_overwrites_old_full_before_unclean_tier_and_never_restores test/test_land_tests_flag.py

tools: test/test_land_selection.py test/test_land.py test/test_land_prepare.py test/test_land_tests_flag.py test/test_land_isolation.py test/test_remote_pytest.py test/test_land_browser.py test/test_land_record.py test/test_publish_main.py test/test_land_queue.py test/test_land_events.py test/test_land_mainred.py test/test_land_mainred_flow.py test/test_pre_push_hook.py test/test_doctor.py

selectors: test/test_affected_tests.py test/test_browser_scope.py test/test_harness_contracts.py test/architecture/test_safety_separation.py test/architecture/test_platform_parts.py
```

## 원본 위치와 바이트 결속

기준 위치는 `%LOCALAPPDATA%/Temp/rosy-land-explicit-full/`이다. 각 폴더 아래 `runner.txt`, `run-1.txt`, `run-1-known.txt`의 실제 바이트 SHA-256이다. 이전 formal archive는 건드리지 않았다.

| 실행 폴더 | runner.txt | run-1.txt | run-1-known.txt |
|---|---|---|---|
| `integration445-red` | `sha256:4bf52dff1fe335b34209deff6b72708707e927cc41f669612f8fc076174f405e` | `sha256:8141bd06893bba9ace01e877d688641df2d85fa25b98fca943f7e15367f6fa48` | `sha256:c73e0a96b63871679a403e0efe2136964c5b143c9b38e2293c0ef647c79fa46c` |
| `integration445-green-controls` | `sha256:de256df02711f4ac44aee2a605fbb888d18fe79c9c465d341656bbff6d7cb3db` | `sha256:959c1ad825998c794d84300069622881dbba8056e23875405377472292227ff5` | `sha256:c596e65a18fcf0e24850d24002104b5e2a9f97bbd8ab2b700423efa308b46c6e` |
| `integration445-green-tools` | `sha256:de33e2e7003c45be70b94e7abff7c2eb8eff5c7ad1dd74ff74cd2048d476490f` | `sha256:7287684518a491132514a5ad196119c6a7b4c79372841f09c3c065b009813b57` | `sha256:c596e65a18fcf0e24850d24002104b5e2a9f97bbd8ab2b700423efa308b46c6e` |
| `integration445-green-selectors` | `sha256:d6386ccf20597997d3bc2a18decf9c5532ff2b2edadb4678cf1876278f706c94` | `sha256:4f3ce877b767c863f9e2b15eb46b69a35351ec539e56401f8597254b873f7200` | `sha256:c596e65a18fcf0e24850d24002104b5e2a9f97bbd8ab2b700423efa308b46c6e` |

같은 기준 위치의 source-only/정적 proof도 다음 hash로 결속한다. 미래 docs HEAD를 포함하지 않아 문서 tree와 순환하지 않는다.

| proof 파일 | SHA-256 |
|---|---|
| `integration445-cli-move-proof.json` | `sha256:be7c543de076c28441d8516d894dea5ce193adad828cd86c67468ca8fb1d6c2c` |
| `integration445-line-endings-proof.json` | `sha256:d888519ba7cfe2ac5af5784690c4a381d64c500205a37059818946595ca7ccb9` |
| `integration445-red-preservation.json` | `sha256:6b88616bb13ed7f60c8899bfb1c4260047d7a190b16e44df9ee18c5702000a6d` |
| `integration445-fix-review.json` | `sha256:492b83c94069c11efd7fcfcb3dcacde43748961db71469f70a88e448622a9f7e` |

## 정적 검사와 남은 관문

source까지 `63a19bf9ca..1bdd41e94a` D766 16커밋과 native lint가 통과했다. 원래 plain staged diff-check는 CR-at-EOL 541개를 표시했다(미변경 incoming 167+244행, 주변 형식을 유지한 flow 130행). Root 판단에 따라 peer CRLF를 정규화하거나 config를 바꾸지 않았다. 명령 한정 `git -c core.whitespace=blank-at-eol,blank-at-eof,space-before-tab,cr-at-eol diff --cached --check`와 incoming445 기준 owned 검사로 실제 space/tab/EOF 위반이 없음을 확인했다. 이는 blanket whitespace 무시가 아니다. fix 3파일의 plain diff-check는 통과했다. 최종 docs HEAD의 전체 범위·generate/lint·scan·dry-run·clean 상태는 후속 외부 handoff에서 별도로 확인하며 여기서 미리 완료로 쓰지 않는다.

이 집중 GREEN이나 과거 controller가 summary를 버린 bootstrap FULL record는 v3의 clean Tool1 qualification이 아니다. 실제 Tool1 착지 뒤 새로운 실제 validation 문서 변경을 가진 후보에서, 실제 Tool1 정본의 queued literal `--tests full`로 guard/body·ALL browser·현재 report를 검증해야 한다. `base==sha` no-op receipt나 과거 부적격 기록으로 대신하지 않는다. 공개 CI·게시 SHA의 요청 기능 포함·산출물·현장 수용도 별도다.

CE: 해당 없음. live state와 반환 summary의 차이는 기존 leaf 코드·6개 반례·실제 RED/GREEN과 새 기록이 설명하며, CLI 분리와 CRLF 보존 근거도 이 기록에 남겼다. G2 timeout·assertion·quarantine·장치 소스는 수정하지 않았다.
