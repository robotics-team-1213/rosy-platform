## 2026-11-26 · uncommitted · omx_hotfix deploy --link omx-bench-current restarts an idle bench

- 변경: tools/remote/omx_hotfix.py: after a bench link switch, read /api/arms on the cell; idle with no arm locked -> systemctl --user restart rosy-omx-bench-record.service and print is-active; busy or unreadable -> print 'bench restart held' and exit 3 (deploy stands). BENCH_RECORD_GUIDE.md section 3 drops the manual restart step.
- 증거: 2026-11-26: link switched 04:57 but the service kept old code from 03:59; test/test_omx_hotfix.py idle/busy/read-failure/cell-link cases
- gate 변화: 없음
- 결정: 없음
- 교훈: 없음
