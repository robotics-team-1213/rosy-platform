# OMX 원관측 history 검증

2026-10-04, 기반 commit e9ab340dfa77b81be96c7285911c180e26fa1c20 이후 변경.
범위는 SOURCE/HOST이며 실제 ROS action/Gazebo 실행 또는 DEVICE/FIELD 수용이 아니다.

## 변경과 증거

기존 owner가 승인한 관절 관측을 기본 64개 bounded history에 보존한다.
후보는 원 sequence/관측 시각과 설치된 나이·시작 자세 허용 오차를 만족해야 한다.
최종 fence 내부에서 재검사하고 command에는 최신 자세 대신 실제 원관측 자세를 전달한다.
owner config/session을 고정하며 외부 provider 이후 설정 교체를 거절한다.

최초 RED: 정상 갱신 중 원관측 제출 2건과 신규 capacity 설정 미지원 등을 포함해 11 failed / 38 passed.
독립 리뷰에서 final authority callback의 tolerance 변경으로 delta .02가 설치 tolerance .01을
우회하는 dispatch를 재현했다. 추가 RED 1건으로 확인 후 pinned config와 provider 후 재검사로 수정했다.

최종 실행:

```powershell
python -B -m pytest middleware/execution/local/test/ src/products/omx/adapter/test/test_omx_command_owner.py test/architecture/test_safety_separation.py -q -p no:cacheprovider --basetemp=X:/DevTemp/rosy-policy-history-reviewed --tb=short
```

145 passed. 정상 갱신/최종 callback 갱신에서 원 시작 자세 보존, 오래된 원관측·허용 오차 초과·
시각 위조·eviction·capacity 입력·최종 tolerance 변경 거절과 기존 owner/설치/안전 경계 회귀를 포함한다.
action client와 authority는 host fixture이다. 실제 issuer/ROS 실행으로 해석하지 않는다.

rosy-execution-local 0.1.3 wheel을 X: source copy에서 빌드했다.
wheel SHA256: 434e54e1b5643ecd8a2e66238d4782713ff617f9afc5ef6dabccb71780ea6102.
wheel의 omx_policy.py와 policy_install.py bytes를 현재 source와 대조해 일치했다.
omx_policy.py SHA256: 7150d7bb3c3ac458313025c181815727d1564125dc02697471ce1f1ccd945f45.

독립 reviewer /root/policy_registry_review가 같은 source SHA를 재검토하고 focused 53 passed를
실행했다. 발견된 tolerance 우회와 final-fence stale/moved/evicted 회귀 통과 후 D-430 source
safety review를 승인했다. 승인 범위는 SOURCE/HOST fake transport이며 SIM/device/physical이 아니다.

## 남은 실행 공백

실제 issuer/capture/scheduler/ROS owner composition, 독립 SIM 과제와 정지 판정, 승격 trust,
Fleet 실제 receipt join, shadow/rollback 및 장치/현장 검증은 여전히 필요하다.
카메라 frame equality는 완화하지 않았다. 현 Gazebo world의 camera update_rate는 10Hz이며
기존 ACT 정책의 observation age budget은 50ms이다. 이 설정에서는 frame 사이 watchdog HOLD가
발생할 수 있으므로 실제 composition에서 확인해야 한다. 평가 기준을 임의로 늘리지 않는다.
전체 목표는 미완료이며 push/merge/deploy/물리 동작을 수행하지 않았다.
