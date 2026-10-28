# OMX 파이프라인 착지 검증 근거

FULL 검증 commit: `8e25dee1c8c5c24a40231e7d2d6664a05378bb4f`.
검증 당시 main commit: `fb5070705be1aaffff2f91bc8cf863cdba1814b0`.
후속 표기 정정 commit: `8a94e894661f2e6b6de670cf75eab90ec62f6688`.

이 기록은 [배포 준비 결과](result.md)의 후속이다. 사용자는 로컬 커밋·머지를 요청했고,
배포 대상과 승인된 정책은 없다고 답했다. 물리 실행·장치 설치·push는 수행하지 않았다.

## 실제 실행 결과

| 범위 | 결과 |
|---|---|
| 구조·harness 선행 검사 | 247 passed, 0 skipped |
| FULL 22개 분할 | 27,760 passed / 1,918 skipped / 2 failed (실행 건수, 중복 가능) |
| 명시적 브라우저 4개 실행 | 45 passed, 0 skipped |
| 시간 측정 실패의 단독 재실행 | 1 passed, 3.76초 |
| 문서 비밀 검사 단독 재실행(정정 전) | 1 failed, 원래 문서 표기를 다시 검출 |
| 변경 전 main에서 두 실패 항목 비교 | 2 passed, 27.95초 |

정확한 로그 SHA-256·검증 commit·기존 실패 비교 결과는
[landing-logs.json](evidence/landing-logs.json)의 30개 기록에 있다.
원시 로그는 저장소 밖 `%LOCALAPPDATA%/Temp/rosy-land/feat-omx-core-lerobot/`에 있다.
자동 착지는 두 실패 때문에 중단됐으며, 이 기록은 그 실행을 성공으로 바꾸지 않는다.

## 실패 처리

`test_coordinated_pairs_pass_both_barriers_within_the_proposed_bounds`는 전체 실행에서
관측 p99 1.669327초가 제안 상한 0.5초를 넘어 실패했다. D-790에 따른 동일 commit의
단독 재실행은 통과했다(`alone-1-20-1.txt`). 따라서 이 항목은 **LOAD-FLAKY**로 분리한다.
상한·시험·coordinator 코드는 고치지 않았고 baseline/quarantine에도 추가하지 않았다.

`test_no_secrets_in_tracked_files`는 검증 기록 6행의 Git commit ID를 고엔트로피
토큰으로 읽었다. 중복을 제외한 네 값 모두 `git cat-file -t`에서 commit 객체임을 확인했다.
원문 식별자·관측 결과·원시 로그 hash는 유지하고, 공개 commit임을 명시했으며 JSON의
`fix`를 `fix_commit`으로 정정했다. scanner·검사·허용 목록은 바꾸지 않았다.

첫 연동 기록의 브라우저 예시 명령은 45건의 전체 원명령을 보존한 것이 아니어서
그 명령의 출처 주장을 정정했다. 당시 45 passed 로그와 hash는 유지한다.
이번에는 다음 실제 브라우저 실행을 각각 기록했고 합계 45건 모두 통과했다.

```text
ROSY_RUN_BROWSER_TESTS=1 middleware/robot_ui/robot/test/test_role_g2_browser.py
ROSY_RUN_BROWSER_TESTS=1 middleware/robot_ui/robot/test/test_dashboard_entry_browser.py
ROSY_RUN_BROWSER_TESTS=1 middleware/core/api/test/test_d283_console_browser.py
ROSY_RUN_BROWSER_TESTS=1 middleware/robot_ui/robot/test/test_calibration_chip_browser.py middleware/robot_ui/robot/test/test_surface_viewport_budget_browser.py
```

## 후속 검증과 수동 착지 조건

독립 `core_arm_review`는 공개 commit 표기 정정과 기록 보존이 적절하며,
`shared-checkout.md` 6절의 수동 절차가 아래 조건을 충족하면 가능하다고 검토했다.
이는 소스·계약 검토이며 새 시험 결과를 대신하지 않는다.

- FULL 이후의 변경은 이 검증 기록과 provenance 표기뿐이다. 코드·설정·시험·workflow
  tree는 FULL commit과 같아야 한다. 기존 FULL과 실패·재검증 로그를 보존한다.
- 정정한 기록이 포함된 커밋을 원격으로 보내 비밀·문서·구조·harness 검사를 통과시킨다.
- 안전 리뷰·크기·lint를 통과시키며, main이 위 검증 당시 commit 그대로인지 확인한다.
- 해결되지 않은 NEW 실패가 없고 공유 main의 동료 파일을 건드리지 않을 때만
  main 체크아웃에서 `git merge --ff-only feat/omx-core-lerobot`을 실행한다.

후속 문서 검사 명령과 로그 위치:

```text
python tools/remote/remote_pytest.py --log-dir <external>/manual-final -- test/test_release_boundary_guards.py test/architecture test/test_harness_contracts.py
python test/known_failures.py <external>/manual-final/run-1.txt
```

이 절차는 최종 문서 commit에서 FULL 전체를 다시 통과했다고 주장하지 않는다.
완료된 FULL, 시간 측정의 단 한 번의 단독 재검증, 문서 수정의 관련 검사라는
각각의 근거를 묶는다. 실물 policy runtime·live lease·D-793 승인·수용은 여전히 열리지 않는다.
