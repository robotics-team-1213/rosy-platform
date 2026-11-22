## 2026-11-21 · uncommitted · records bot folds a late-merged log shard at its dated position, not at the end

- 변경: new_record consolidate inserts each log shard after the last entry dated <= its own, so the log-order check passes for late older-dated shards (bot PR 397)
- 증거: test_records_fragments log-fold tests; consolidate on bot-branch fragments then log order check clean; lint 0 errors
- gate 변화: 없음
- 결정: D-1061
- 교훈: 없음
