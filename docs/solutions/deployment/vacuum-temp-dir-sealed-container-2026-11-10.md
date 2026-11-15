---
title: "Sealed maintenance containers need a temp dir beside the target for real-size VACUUM"
date: "2026-11-10"
module: "site ledger backup and maintenance (deploy/site/site_db.py)"
problem_type: runtime_error
component: deployment
severity: high
symptoms:
  - "The daily fleet-backup timer would exit on 'vacuum failed' against the real 665 MB ledger, skipping prune_ledger, _prune_backups and the WAL checkpoint, so backups grow unbounded."
  - "The maintenance CLI's own tests passed: their fixture databases are KB-sized and never exercise VACUUM temp demand."
root_cause: environment_assumption
resolution_type: code_fix
tags: ["site", "sqlite", "vacuum", "tmpfs", "fleet-backup", "retention"]
---

## 증상

`rosy-site-ledger-backup.timer`가 `site_db.py backup`을 실행할 때, 원장 크기가 커지면
`vacuum failed(DatabaseError)`로 exit 2한다. `main()` 순서상 vacuum이 prune·백업 정리·
WAL checkpoint보다 앞이라 정리가 전부 건너뛴다 — 백업 파일은 계속 만들어지므로
`/var/backups`가 무한히 찐다.

## 원인

SQLite `VACUUM`은 임시 복사본을 **temp dir**(`SQLITE_TMPDIR`/`TMPDIR`/`/tmp` 해석)에
만든다. fleet-backup 컨테이너는 `read_only: true` rootfs + 32 MB tmpfs `/tmp`라 실물
크기(수백 MB)의 temp 수요를 절대 맞출 수 없고 `SQLITE_FULL`로 실패한다. 시험 fixture는
KB급이라 temp 파일이 생기지 않아 이 조건을 재현하지 못했다.

## 해결 (2f66eddc4c)

`vacuum_database`가 `os.environ.setdefault("SQLITE_TMPDIR", str(target.parent))`로
temp를 대상 파일 옆 디렉터리에 둔다. 두 CLI 경로(타이머 백업본은 `/backup` bind,
`compact`는 DB 볼륨) 모두 그 경로는 쓰기 가능하고 용량도 있다. 운영자가 이미 준
`SQLITE_TMPDIR`은 존중한다. `test_vacuum_keeps_its_temp_copy_beside_the_target`가
이 계약을 고정한다.

## 다음에 적용할 조건

- 봉인된 컨테이너(read-only rootfs·작은 tmpfs)에서 크기 의존 동작(VACUUM·정렬
  spill·대용량 임시 파일)을 돌리는 도구는 temp 경로를 컨테이너 제약과 함께 확인한다.
- "실물 크기에서만 실패하는" 경로는 fixture 크기로는 검증되지 않는다 — temp·용량
  의존 변경은 실물 급 크기로 한 번은 확인하거나, 계약을 시험로 고정한다.
