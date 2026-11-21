## 2026-11-21 · uncommitted · Control-unit scope: R, cell and standalone Fleet each show their own screens (slice 13 of #378)

- 변경: Fleet state now carries fleet.scope (role, drive, arms, children, enrollment) from the control-unit manifest; unit-scope.js turns it into html flags and fleet-header.css hides blocks tagged data-unit-scope that the unit does not own (Pinky formation and platoon on a cell, the cell work screen on a unit with no arm, child stop requests on a cell without child units). The header E-stop is never tagged. No scope from an older server keeps every block. arm-transfer-view lets the owning cell's operator approve and keeps R read-and-relay. The scope also carries `enrollment`, but the install screen is not tagged here: hiding the enrollment panel would also hide the release-code action for already enrolled robots, so that waits for slice 17 with the tab fix. The rail map link waits for slice 10. A unit with child units only relays their arm jobs (the relay has no admit or recovery route).
- 증거: node unit-scope test; test_control_unit_credential_scope; lab affected run and browser run test_unit_scope_browser (see PR body)
- gate 변화: 없음
- 결정: D-960 4, D-974
- 교훈: 없음
