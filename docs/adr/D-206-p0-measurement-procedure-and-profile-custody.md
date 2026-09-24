## D-206 P0 실측의 실행 절차와 확정 카메라 프로필 보관

**Status:** Proposed (2026-09-24). [D-205](D-205-real-lane-mission-transition-order.md) P0을 실행하는 절차·기록·판정과
확정 프로필의 보관을 정한다. 측정 기록지와 임시 보관 규칙을 만들며 내린 판단을 결정으로 승격한다. 잇는 결정:

- D-205(Proposed): P0–P6 실행 순서와 게이트. 이 ADR은 P0의 실행 세부만 담고 단계·게이트를 바꾸지 않는다.
- D-199(Proposed): 카메라 인식 계약. `CameraProfile` 계약은 P1에 온다. 이 ADR은 계약을 미리 정의하지 않는다.
- D-196(예약, PR #36): 기종 설정은 `src/robots/pinky_pro/config/`에 둔다.
- D-186: 수집 데이터는 주인 폴더에만 둔다.

**Context:**

1. **P0은 "사용자가 잰다"이지만 재는 법은 정해지지 않았다.** D-205은 항목 여덟(차선 간격·테이프 폭·횡단보도
   막대·링 지름·매트 외곽·벽 높이·렌즈 높이·렌즈 앞 오프셋)만 나열한다. 2026-09-24에 측정 기록지를 만들었다
   ([p0_track_measurements.md](../validation/perception-real-video/2026-09-24/p0_track_measurements.md)).
2. **카메라 프로필 초안에는 축척 퇴화(height↔scale)가 남아 있다.** 초안 `draft-2026-09-24`의 렌즈 높이는
   66–69.4 mm로만 좁혀졌다. 렌즈 높이 실측 한 값이 퇴화를 푼다. fx 피팅은 CAD 막대 비율(26×121 mm, 피치 40 mm)에
   척도를 뒀으므로 실측 피치가 다르면 fx·높이를 같은 척도로 다시 맞춰야 한다.
3. **D-205이 지목한 보관 자리가 아직 없다.** `src/robots/pinky_pro/config/`은 D-196(PR #36, 미병합)이 예약했고
   로컬·origin 어느 main에도 없다. 지금 만들면 예약 구조와 충돌할 수 있다.
4. **P0 게이트 판정에는 지금 프로토타입밖에 없다.** 검토된 재생 도구는 P2에 온다. `camcal/bevfinal.py`는
   검토 전 도구지만, 판정 대상은 카메라 파라미터의 기하(재생 BEV의 차선 간격)지 인식 품질이 아니다.

**Decision:**

1. **측정의 표준은 기록지다.** 항목·재는 법·단위(mm)·직선 3곳 반복·참고값은
   `docs/validation/perception-real-video/2026-09-24/p0_track_measurements.md`를 따른다. 값은 기록지 표에 직접
   적거나 대화로 전달한다(에이전트가 옮겨 적는다).
2. **확정 프로필의 revision은 `measured-YYYY-MM-DD`다.** 확정본은 같은 폴더에 두고, 초안 `draft-*`는 어떤
   게이트의 기준으로도 쓰지 않는다(D-205 규칙 유지). 막대 피치 실측이 CAD 40 mm에서 벗어났으면 확정 전에
   `camcal` 체인을 실측 치수로 다시 돌아 fx·높이를 다시 맞춘다.
3. **`src/robots/pinky_pro/config/`은 지금 만들지 않는다.** D-196이 머지되면 확정 프로필을 그리로 옮긴다.
   P1의 `CameraProfile` 로더는 경로가 아니라 revision으로 프로필을 찾는다(D-205의 "경로에 매이지 않는 로더"를
   계약으로 이어받는다). 옮길 때 revision은 바꾸지 않는다.
4. **게이트 판정 절차를 고정한다.** 확정 프로필로 `camcal/bevfinal.py`를 돌려 `out/bev_check.json`의 c-c
   간격(전방 0.2/0.3/0.5 m 지점)을 낸다. 세 지점 모두 실측 차선 간격(기록지 1번) ±5 mm 안이면 통과다.
   판정은 기록지의 결과 표와 `src/core/control/logs.md`에 남긴다.
5. **판정 도구는 프로토타입 `camcal/bevfinal.py`를 쓴다.** P2의 검토된 재생 도구가 들어오면 확정 프로필으로
   같은 BEV 간격을 재현하는지 교차 확인한다. 재현되지 않으면 그때 재판정한다.

**Validation:**

- 이 ADR은 절차 결정이다. 게이트 증거는 아직 없다(측정 대기). 판정 결과는 기록지 결과 표에 채운다. 절차는
  측정 결과와 무관하므로 판정 뒤에도 Status를 바꾸지 않는다.
- 기록 형태: ADR Log 표 D-206 행, `control/progress.md`의 `adrs`에 D-206 추가 후
  `test/test_harness_contracts.py`·`test/test_network_topology_contracts.py`를 돌린다.

**Consequences:**

- 측정값이 오면 문서를 더 만들지 않고 프로필 확정 → 게이트 → 기록 순으로 간다.
- 실측값이 CAD와 크게 달라도(D-205 Context 4의 약 10%) P0 게이트의 기준은 실측값이다. P4 세계 현실화도 같은
  실측값을 쓴다.
- 측정값은 사람이 잰 판독이다. 판독 오차가 게이트 ±5 mm과 견줘 만만치 않으면(예: 같은 항목 세 값이 5 mm
  넘게 벌어짐) 재측정을 먼저 요청한다.
- D-196 머지 전까지 확정 프로필은 validation 폴더에 산다.

**References:** [D-205](D-205-real-lane-mission-transition-order.md),
[측정 기록지](../validation/perception-real-video/2026-09-24/p0_track_measurements.md),
[카메라 프로필 초안](../validation/perception-real-video/2026-09-24/camera_profile_draft.json),
[D-199](D-199-camera-perception-contracts-and-backends.md), D-186, D-196(PR #36 예약),
[`tools/perception/prototype/`](../../tools/perception/prototype/README.md).
