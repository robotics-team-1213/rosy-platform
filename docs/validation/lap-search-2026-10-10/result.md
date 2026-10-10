# Bounded bidirectional lane search

- Branch: `fix/lap-search-reviewed`.
- Scope: one combined change reviewed as `d49e9740e`; frozen same-corridor bearing, opposite second candidate, unchanged authority, clearance, attempt and time bounds.
- Independent review: `/root/lap_review`, APPROVE WITH NOTES (2026-10-10). Earlier intermediate changes are retained on `feat/one-lap-current`; this branch records only the reviewed final diff.
- Remote evidence before integration: 128 passed, known_failures 0 NEW, `X:/DevTemp/one-lap/return-suite/run-1.txt`. Integration verification follows through `tools/land.py`.
- Device evidence: both supervised robots installed `2026.10.10-163`; this new search change has not yet been installed or accepted in the field.
- Remaining limitation: this small sensor search is not a junction pivot or a Fleet REALIGN PIVOT/KTURN. Large rotation requires measured swept-body space; existing local and Fleet guards remain.
- Physical acceptance: neither robot's complete lap has been proved.
