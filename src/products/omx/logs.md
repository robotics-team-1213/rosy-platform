# omx logs

추가만 한다. 형식: [module harness 설계](../../../docs/plans/2026-09-15-module-harness-design.md) §4.2.

## 2026-09-25 · uncommitted · refactor(products): OMX arm settings leave the adapter package (D-232)

- 변경: `omx.disabled.yaml`을 `src/devices/omx/omx_adapter/config/`에서 이 패키지의 `config/`로 옮겼다. 어댑터의 `adapter.manifest.yaml`과 검증 코드는 장치에 남는다
- 증거: `python -m pytest src/products/omx/test src/devices/omx/omx_adapter/test -q` (이 기록 직후 실행)
- gate 변화: 신규. SOURCE GO, LOCAL GO, ROS-SIM/ARTIFACT HOLD, DEVICE/FIELD N/A
- 결정: D-232
- 교훈: 없음
