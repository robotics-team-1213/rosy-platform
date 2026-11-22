## 2026-11-21 · uncommitted · Fleet E-stop route accepts a human viewer (D-1043)

- 변경: POST /api/fleet/estop uses require_viewer, refuses service and machine tokens (SitePrincipal.machine); site-map keeps the E-stop on a FORBIDDEN 403; release paths tested as viewer 403
- 증거: lab affected run, browser run, Codex safety review
- gate 변화: 없음
- 결정: D-1043
- 교훈: 없음
