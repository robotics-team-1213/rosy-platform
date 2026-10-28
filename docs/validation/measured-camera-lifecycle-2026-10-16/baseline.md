# 카메라 교정 운영 연결의 변경 전 기준선

2026-10-16. 시험 revision: `89d3ba4d10`.
브랜치: `docs/camera-calibration-lifecycle`. 구현 계획 작성 중 기존 코드의 기준선을 확인했다.

실행은 기존 `tools/remote/remote_pytest.py`가 선택한 AI 시험 PC에서 수행했다.
모델 PC는 당시 pytest 여유 메모리 하한 미달이었고 현장 PC는 선택하지 않았다.
노트북에서 pytest를 실행하지 않았다.

```text
python tools/remote/remote_pytest.py --log-dir C:/DevTemp/camera-calibration/baseline -- operations/overhead/test/test_camera_calibration.py operations/overhead/test/test_overhead_track_calibration.py operations/fleet/test/test_overhead_tracking_calibration.py
python test/known_failures.py C:/DevTemp/camera-calibration/baseline/run-1.txt
```

| 항목 | 관찰 결과 |
|---|---|
| 원격 수집·실행 | 53 passed, 0 skipped, 0 failed, pytest 0.69 s |
| remote runner terminal exit | 0 |
| known_failures 비교 | 0 new, 0 known, 0 flaky; 목록 중 이번 선택에서 실패하지 않은 항목 5개 |
| 원시 로그 | `C:/DevTemp/camera-calibration/baseline/run-1.txt` |

기존 오프라인 pinhole/fisheye/floor 도구, 기존 tracking 교정 선택, Fleet 승인 저장의
선택한 회귀 범위다. 새 운영 묶음·목적별 승인·동시 수정·Vision session 확인·직접 미리보기·
브라우저 전체·실측 정확도·D-598 구현을 검증한 결과가 아니다. 이 시험 수를 이후 구현
revision의 시험 수로 합산하거나 DEVICE/FIELD 수용으로 쓰지 않는다.
