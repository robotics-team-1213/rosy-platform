# OMX native 세 배치 확인 후 물체 유지 증거 부족

> Historical record recovered on 2026-10-19 from preserved work. Results below describe the cited source/run; this recovery does not rerun or extend that simulation evidence.

2026-10-17. 실행 source `7e62492aa`, nonce `3d22ab36825a`.
[초기화 타입 수정](../omx-native-clock-bootstrap-2026-10-17/result.md) 뒤 새 run을 한 번 시작했다.

실제 SDK에서 전용 시계 초기화와 startup READY, topic PROPOSED→READY를 확인했다.
독립 placement 목표는 **3/16**을 확인했고, 총 **15개 ROS phase가 SUCCEEDED**였다.
네 번째 transfer도 성공했지만 release 직전 held-object 검사에서
`ITEM_LOST_IN_TRANSIT`로 HOLD했다. 네 번째 release는 제출하지 않았다.

그리퍼 검사는 freshness 검사를 지나 CLOSED/present/object 일치 검사에서 실패했다.
SIM readback은 accepted recipe의 폭과 실제 gripper q로 present를 추론한다.
실패 순간의 q·반환 observation·TCP·해당 물체 pose는 기록하지 않았다.
따라서 실제 낙하, angle threshold 미달·초과 또는 OPEN 중 어느 원인인지 확정하지 않는다.
네 번째 SIM AID attach는 confirmed/service_ok=true, 약 6.07 ms였으며 detach 기록은 없다.
부착 ACK만으로 물체 유지 검사 성공을 대체하지 않는다.

시계 startup의 SDK 세 source hash 일치, 두 노드의 use_sim_time 고정, thread 생존과
발행기 한 개를 관측했다. graph가 보고한 GID는 `010f7f01e6398c320000000000001403`,
QoS는 RELIABLE/VOLATILE, history UNKNOWN/depth 0이었다. startup은 5 frame·4 advance,
2 ms delta, 역행·관측 오류 0, 수신 나이 약 1.17 ms다. 이는 startup 표본에 한한다.
종료 clock record는 없으므로 전체 실행의 역행 부재나 최대 수신 지연을 주장하지 않는다.

정리는 cleanup_verified=true, remaining_groups=[], cgroup 부재, MainPID=0 / 빈
ControlGroup과 실제 budget 파일 부재를 확인했다. ACK 뒤 같은 run·불명 Goal을 재전송하지 않았다.
private 운영 scratch `native-auto-deployment-13`에 원본과 제한된 diagnosis를 보존했다.

```text
archive_sha256 = 480dbf09d5d1dcd6861c699360b291d3a787faea5f764c2168a36ff2175ab896
extraction_map_sha256 = a0bcfbd32bb6a0fe97566e25ffd7b923b82613561344b18570a3961fdc4874e6
held_diagnosis_sha256 = ee5db4545eda9df0e7c7842e4a2232291a58e1e7aca352d0593e5700c99bec91
```

후속 실행은 canonical gripper readback의 동일 관절 표본·반환값을 관측해야 한다.
각도·freshness·목표 검사를 완화하지 않는다. 전체 작업·full G2는 HOLD이며
적격 실제 episode는 0개, 실제 ACT 학습은 미시작이다.
