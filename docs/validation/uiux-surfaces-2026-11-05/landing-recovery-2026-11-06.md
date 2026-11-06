# 착지 복구와 로그 epoch 선행 조건 — 2026-11-06

## 범위와 현재 판정

원래 30개 UI 카드 범위는 그대로다. [기존 완료 후속](completion-followup-2026-11-06.md)과 당시 README·표면 카드·경합 기록을 고치지 않고, 공식 151711의 두 소스 시기와 후속 registry/로그 보존 수정을 추가한다. 아래 실행들은 소스별 근거이며 합산한 FULL이나 실제 UI main 수용이 아니다.

외부 원본은 작업공간 `Rosy/docs/workspace-records/2026-11-05/ui-map/` 아래 있다. 아래 artifact 이름은 그 기준 상대경로이며 접속값·개인 경로·토큰은 전사하지 않는다.

## 공식 151711: 원래 FULL과 이후 실패를 분리

초기 prepared commit d2bb9492b3e26a9d31e4b543045c0593a6f93a35는 main commit 5a9f54262e3e6ac91f5e8dc3af1633fa90599bc6 위에서 native `tier: full`·원래 계획 40 invocation·성공 producer 72개/분류 NEW 0으로 준비됐다. 이는 그 D2 소스의 준비된 FULL이며 실제 main 착지가 아니다.

이후 round1은 main commit 0468b182a7bca9bebb4d764c990bcad678d2ce79를 기준으로 commit 63fa4da2824fffff39aaab75ebd7cc09cef2c2d7을 실제 실행했다. cache 후보 selector의 “guards only/FULL through main” 메시지와 달리 fresh matrix도 실행됐고, 성공 producer 116개 뒤 registry 실패·취소·STOP이 남았다. D2의 qualifying record를 이 새 소스의 FULL로 바꾸지 않는다.

| 최종 원본 | 보존한 실제 결과 |
| --- | --- |
| `run-pre-128.txt` | `test/test_browser_scope.py::test_full_registry_keeps_browser_files_after_splitting_them`, 1 FAIL/24 PASS, 0.80초 |
| `alone-pre-pre-128-1.txt` | 같은 직접 node의 단독 FAIL, 0.16초 |
| `run-gpre-2.txt` | `tools/collect_alone.py::test_runs_alone[test/test_browser_scope.py]`, 1 FAIL/273 PASS/1 skip, 222.26초 |
| `alone-gpre-gpre-2-1.txt` | 같은 isolation wrapper 단독 FAIL, 196.52초 |

두 실패 관측은 같은 registry 단언을 노출한다. native event의 188 pass/66 cancelled/1 tests-new, 별도 confirmed failure 2개와 STOP/no-landed를 그대로 구분한다. 새 unchanged-main 비교 실행은 없으며 main PASS를 만들어 넣지 않는다. `review-reports/official-failed-evidence-review-151711.md`와 `official-ui-151711-failed/receipt.json`이 최종 소스·argv·분류·원본 지문을 결속한다. 이 gate는 UI를 main에 수용하지 않았다.

## 원본 보존 한계와 normal merge

안정된 branch 임시 루트에서 여러 preparation이 같은 `run-pre-N`/`run-gpre-N` 이름을 다시 써 과거 원본 경로가 덮였다. 기존 `official-ui-151711-in-progress/`의 엄격한 pytest 4개·별도 lint와 `official-ui-151711-phase-snapshot-20261105T173404023953Z/`의 성공 원본 129개는 그대로 보존했다.

최종 `official-ui-151711-failed/`는 현재 참조된 raw 145개·최종 wrapper·native FULL record, 총 147개 artifact의 바이트/해시를 확인했다. wrapper 329,536바이트의 SHA256은 `541a8fbbb0a76fcfd220a1e13ec9225a83793a2607ba94de6d90532a54b2142e`다. 초기 D2 성공 row 72개 중 원본 13개는 보존 위치에서 확인되며 59개 지문은 현재 경로와 조사한 보존본에서 일치 바이트를 확보하지 못했다. 전 세계의 모든 복사본이 없다고 단정하지 않으며, console text로 원본을 재생성하거나 다른 소스 raw를 옛 D2로 바꾸지 않는다. 수정은 이 과거 공백을 복구하지 못한다.

commit 86e39240a034fdb97887800b823db5c4a52825fe는 UI의 b8 문서 소스와 실패를 실제 시험한 63fa를 정상 병합했다. commit faf3490cc79295d4cedc2b7138e9fdbf36da2f74는 그 위에 main의 registry 수정 commit 9a2c103d6a8d512b219540a036f54b6bc2e6a767을 정상 병합했다. registry 수정은 빠졌던 `test/test_fleet_manual_control_browser.py` 한 항목을 정본 FLEET 목록에 넣는다. c489의 역할 closure/범위 문구와 b8의 문서 기록은 보존하되, 각각의 160 PASS와 145 PASS를 새 병합 소스의 결과로 소급하지 않는다.

## Registry 보완의 실제 실행

commit 14823a62910abb39fce697cf596c437c45b3a460, AI run `14823a6291-fd5e1b`의 직접 registry 25개와 요청한 runs-alone 1개는 실제 26 PASS/0.97초/NEW-known-flaky 0이다. 같은 실행의 빈 미사용 collection parameter `test_collects_alone[NOTSET]` 1개는 skip이며 PASS로 세지 않는다. `[isolation] complete: 1`은 요청한 runs-alone의 범위다. 새 unchanged-main 비교는 실행하지 않았다.

`review-reports/registry-merge-green-14823a-{wrapper-receipt.json,run-1.txt}`가 source/argv/run/종료를 기록한다. 3,459바이트 raw의 SHA256은 `dc6bea59dece9147d95f491dc0eb787530af70d2484a4836fe7f9f9f33ce01da`다. 이 focused 실행은 전체 UI나 공식 FULL 수용이 아니다.

## 로그 epoch 수정의 유효 RED/GREEN

먼저 commit 14823a62910abb39fce697cf596c437c45b3a460의 AI run `14823a6291-caa879`는 fixture generator에 `generated_targets`가 없어 1 FAIL/0.55초로 끝났다. `review-reports/log-epoch-invalid-fixture-14823a-*`의 raw SHA256은 `9bbcee684efd5afab698a6d0d30414062d411099969594fc08c55d31ba356124`다. 이 실행은 제품 RED로 세지 않는다. fixture를 바로잡은 뒤의 유효 RED/GREEN만 비교한다.

| 실제 실행 | 소스·AI run | 결과·원본 지문 |
| --- | --- | --- |
| 유효 RED | commit 74f37008a800dba51dd2a6f6207c6d490f98635b, `74f37008a8-050cdf` | 1 collected/1 FAIL/0 skip/0.73초, runner/classifier 1·NEW 1. `first_dir != second_dir`에서 기존 preparation 경로 재사용을 확인했다. raw SHA256 `a7e59c771b5ccf022b985e0acd88f879537689c97205bf1dbe62250660256d58` |
| focused GREEN | commit c01edde6dec95cf39408982aa58bf2b8a476da68, `c01edde6de-085ac2` | 7개 전체 파일의 301 unique PASS/0 skip/44.40초, runner 54초·runner/classifier 0·NEW-known-flaky 0. raw SHA256 `d67a628c2b56c32059f8b0570a78a452e586e362b21177c935da8baa5c9cdf00` |

정확한 7개 파일은 `test_land_prepare.py`, `test_land.py`, `test_land_isolation.py`, `test_land_cache_landed.py`, `test_land_record.py`, `test_publish_evidence.py`, `test_publish_main.py`이며 모두 `test/` 아래다. 각각 54/115/30/4/22/49/27 PASS다. 공백이 있는 parameter ID도 보존해 301개 고유 node를 확인했다. 원본·wrapper는 `review-reports/log-epoch-{red-74f370,green-c01edd}-*`, 독립 GO는 `prepare-log-epoch-code-review.md`와 `prepare-log-epoch-evidence-review-c01edd.md`에 있다.

commit e4b83523250cb6429a9c54f7da34427376cf0f6f의 `tools/land_prepare.py`와 `test/test_land_prepare.py`는 C01의 두 파일과 바이트가 같다. 승인된 production Git blob은 `6990bb856dd0838a5a5a2fd984f1f8d85be37ce9`다. `_prepare`마다 기존 branch 임시 루트 아래 고유 child epoch를 만들고 같은 preparation의 guard/primary가 이를 공유한다. leaf 이름·안정된 branch 루트·selector·guard 기준·cache 자격·FULL 정책·동시성·host 통제는 바꾸지 않는다. transport mock을 사용한 회귀는 실제 원격 transport/장치 수용을 대신하지 않는다.

재현은 승인된 외부 log 경로를 지정한 정본 remote runner로 한다. 아래는 문서용 명령이며 이번 문서 작성자가 실행하지 않았다.

```text
python tools/remote/remote_pytest.py --sha 74f37008a800dba51dd2a6f6207c6d490f98635b --log-dir <external-red-dir> -- test/test_land_prepare.py::test_repreparation_preserves_each_candidates_raw_logs_and_cache_hashes -vv -ra  # commit 74f37008a800dba51dd2a6f6207c6d490f98635b
python tools/remote/remote_pytest.py --sha c01edde6dec95cf39408982aa58bf2b8a476da68 --log-dir <external-green-dir> -- test/test_land_prepare.py test/test_land.py test/test_land_isolation.py test/test_land_cache_landed.py test/test_land_record.py test/test_publish_evidence.py test/test_publish_main.py -vv -ra  # commit c01edde6dec95cf39408982aa58bf2b8a476da68
```

## Main tooling 선행 조건과 수용 대기

native gateway는 main의 신뢰된 landing tooling을 실행한다. UI 워크트리에 같은 수정이 있어도 그 자체로 새 writer가 적용됐다고 볼 수 없다. 선행 gate `land/fix/ui-log-epochs-20261105183254`는 실제 prepared commit 71c4dd2b136ec02a830323e8fd088e7a15a1634f/main commit 2986d9b8ee67220424e7493f4152506abcab4b5f의 FULL admission 대기 상태다. **아직 main 수용이 아니다.** 원본을 건드리거나 cache를 승격/우회해 이 순서를 생략하지 않는다.

### 실제 수용 — 후속 날짜 기록 대기

선행 tooling의 실제 terminal·main ancestry, 그 뒤 UI의 새 source-bound G1/공식 FULL·실제 main 수용은 아직 이 기록에 없다. 게시·배포·물리/현장 수용도 별도다. 완료 때 새 날짜 수용 기록에 실제 소스·명령·원본 지문·종료·main 증거를 추가한다. 현재 progress/last_verified와 과거 실패를 수정하지 않는다.

CE: 해당 없음 — 원인과 예방은 고유 epoch 코드의 설명·유효 RED/GREEN·날짜별 검증에 남는다. 기존 덮인 raw 59개를 복구한 것처럼 새 교훈이나 원본을 만들지 않는다.
