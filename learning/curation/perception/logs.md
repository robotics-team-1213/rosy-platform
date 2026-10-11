# perception_curation verification log

2026-10-11: D-637 folder move in progress; committed-SHA verification pending.

2026-10-11: source d4988bffba landed on local main after independent review, remote regressions/known_failures 0 NEW and installed wheel/sdist/HTTP proof. SOURCE/LOCAL GO only; CI FULL and ROS-SIM/ARM64/device/field remain unverified. See docs/validation/d637-remaining-folders-2026-10-11/result.md.

2026-10-11: D-663 semantic 보존/검증과 새 road_surface_v1 classes를 추가했다. 6353771b7 원격 builder/export/intake 관련 회귀 terminal exit 0, NEW 0. 실제 road_surface 독립 검수와 승인·새 dataset publication은 미완료다.

## 2026-10-12 · 5acb174a1 · fix(learning): 모바일 검수 헤더의 작업 영역 확보

- 변경: 320px 헤더에서 브랜드·현재 작업·화면 설정을 첫 줄, 네 화면 탐색을 둘째 줄로 배치한다. 픽셀 화면의 화면 설정도 같은 클래스를 사용한다. 본문의 검수 수정·승인·자료 준비·결과와 복구 경로는 유지한다.
- 증거: main 629cb923d의 Learning 320×568 원격 Chromium에서 헤더 145px로 첫 화면 20% 예산 초과를 재현했다. 기존 높이·넘침 검사에 제목/설정 비겹침과 탐색 최소 누름면 검사를 추가했다. 수정된 커밋의 적정 자원 통합 원격 회귀와 캡처를 별도 기록한다.
- gate 변화: SOURCE 개선이며 새 설치본·사람 작업 검토·모델 승격·장치 수용은 이 변경으로 입증하지 않는다.
