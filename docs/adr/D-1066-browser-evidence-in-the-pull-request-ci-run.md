## D-1066 브라우저 증거는 PR의 CI 실행이 맡고 랩은 러너가 못 돌리는 것만 남긴다

**Status:** Accepted (2026-11-21, 사용자 결정: "merge 로직 다시 보고 gha로 옮겨 개선", "바로 다 처리해"). [D-1055](D-1055-pr-merge-queue-only-merge-path-land-retired.md) 7항과 [D-1052](D-1052-self-review-and-zero-full-ci.md)가 브라우저 표면을 랩 증거로 정한 부분을 바꾼다. 켜는 것은 `ci.yml` scope 작업의 `ROSY_BROWSER_CI`다.

잇는 결정: [D-1055](D-1055-pr-merge-queue-only-merge-path-land-retired.md) · [D-1052](D-1052-self-review-and-zero-full-ci.md) · [D-1064](D-1064-main-push-run-on-a-commit-the-queue-run-passed.md).

### Context

- `test/browser_scope.py`의 경로를 바꾸는 PR은 그 브라우저 시험 파일을 실제 Chromium으로 돌려야 한다. `tools/pr_land.py --evidence`는 이것을 랩 PC에서 PR을 열기 전에 돌렸다.
- 측정: UI PR 하나(#378)가 증거 실행 한 번에 2~2.5시간, 다섯 번 돌려 약 8시간을 썼다.
- 랩 증거는 정확히 그 트리에만 유효하다. main이 병합될 때마다 다시 돌았다.
- CI 이미지에는 Chromium이 이미 있고 Fleet 브라우저 파일은 이미 CI에서 돈다.

### Decision

| 항목 | 결정 |
|---|---|
| 실행 위치 | `pull_request` 실행이 `browser-*` 작업을 더 싣는다. 파일은 `tools/harness/affected_browser.py`가 고른다. |
| 분할 | ROS 환경 묶음마다 최대 4개 작업, 작업당 약 12개 파일. 부하에 민감한 ALONE 파일은 작업 하나(`browser-alone`)에 모은다. |
| 엄격 모드 | `ROSY_BROWSER_STRICT=1`: 건너뛴 시험이 하나라도 있거나 통과가 하나도 없으면 실패다. |
| 랩에 남는 것 | LAB_ONLY 학습 venv 브라우저 시험, 시뮬레이터, OMX 어댑터 하드웨어 시험. `pr_land`는 `affected_browser.split`의 랩 몫만 요구한다. |
| 싣지 않는 실행 | merge queue와 push 실행. 랩 증거도 거기서는 돈 적이 없다. |
| 끄기 | `ci.yml`의 `ROSY_BROWSER_CI` 줄을 지우고 `pr_land`의 브라우저 chunk를 되돌린다. 한 커밋으로 한다. |

### Consequences

- UI PR의 브라우저 증거가 랩 대기 없이 PR 실행 안에서 나오고, main 병합마다 다시 돌지 않는다.
- 러너 시간이 늘어난다. 첫 UI PR들의 러너 분을 확인해야 한다.
- 랩과 CI 이미지의 Chromium이 다르다. 픽셀을 고정한 시험은 두 Chromium을 비교해 확인해야 한다.
- 밤마다 랩에서 전체를 훑는 방안을 제안했지만 만들지 않았다.
- 남은 확인: CI 이미지 Chromium 대 랩 Chromium(픽셀 고정), 첫 UI PR의 러너 분.
