# D-915 원본 물리 근거 인계 검증

코드 기준: `66ba49bef84fb393b527ab9bde5903248c736cdc`, API reference v1.330. 이 기록은 소스·계약·합성 HTTP fixture 검증이다. 실물·운영 생산자·장치 수용·배포·착지·push를 수행하지 않았다.

## 결과와 범위

| 확인 | 고정 source | 관측 결과 |
|---|---|---|
| 계약·World·observer·수출·기존 시간 초과 항목 | `ad164043f6` | 150 passed, skipped 0, NEW/known/flaky 0 |
| 구형 SIM Pydantic 2.11.7 schema/직렬화 | `66ba49bef8` | JSON Schema 생성, absent/null 생략, JSON 왕복, 실제 측정값 보존 assertion 통과; terminal 0 |
| 실제 Fleet HTTP·UDS와 Harbor 독립 소비자 | platform `66ba49bef8`, Harbor `ac2403834737f08363d99a33c5273b40a11cea05` | adapter 8 + HTTP 1 passed, terminal 0; SubmitAction 1/lookup 1, PRE/POST proof |
| FULL 영향 선택 | `66ba49bef8` | 4개 묶음 모두 terminal 0; 25,723 passed/1,296 skipped, NEW/known/flaky 0 |
| Harness lint | `66ba49bef8` | exit 0, errors 0, warnings 41; 기존 module 검증 시점·작업 공간 관련 경고 |

원본 proof는 변경되지 않은 receipt와 SHA로 결속되고 같은 read snapshot에서 반환된다. 기존 입력은 관절 사실이 없으면 원래 canonical bytes를 유지한다. 새로운 read는 관절 사실 없는 과거 receipt를 409로 거절한다. scope가 다른 service는 403이다. stale/future·partial·관절 순서 불일치·PRE source 재사용·stored proof 변조를 거절하며 추가 실행이나 claim 해제를 만들지 않는다.

FULL 각 묶음은 12,799/755, 516/5, 5,137/123, 7,271/413 (passed/skipped)이다. 선택한 파일을 제거하지 않았다. skip은 별도 브라우저·환경·artifact 수용을 통과한 것으로 세지 않는다. 알려진 theme browser 항목 하나는 이번 실행에서 실패하지 않았으며 새로운 baseline으로 바꾸지 않았다. Windows observer shell의 stderr redirection이 반환한 외부 exit 1과 별개로, native runner가 네 원격 invocation 각각에 `exit 0`을 기록한 것을 확인했다.

Harbor는 원문을 조회할 뿐 관측을 제출하지 않는다. 실제 HTTP 시험에서 마지막 한 이동의 확인 뒤 `AWAITING_FINAL_EVIDENCE`이고, 같은 근거로 최종 `finish()`를 시도하면 거절한다. HTTP/UDS는 실제 구현이지만 물체·link·관절·그리퍼는 명시적 합성 fixture다. 실제 Gazebo 측정을 증명하지 않는다.

## 발견한 회귀와 검증

- 최초 tests-only export RED: 11 failed. DTO·새 route 부재를 확인한 뒤 구현했다. 기존 observer/evaluator/World baseline은 64 passed였다.
- 독립 검토에서 PRE의 nested joint source ID/sequence를 POST에 재사용할 수 있음을 찾았다. assessment/closure가 공유하는 guard로 고쳤다. guard를 명시적으로 비활성화한 시험은 두 경우 모두 200 대신 409를 기대하며 실패했고, 복원한 suite는 13 passed였다. production flag는 없다.
- 기존 DTO dump에 `joints: null`이 추가되는 wire 회귀 여섯 건을 FULL이 검출했다. 없는 관절을 생략하고 DTO→World의 optional pop도 함께 고쳐 absent/explicit-null 모두 원문이 보존됨을 확인했다.
- 초기 생략 방식 `Field(exclude_if=...)`는 고정 SIM의 Pydantic 2.11.7에서 JSON Schema function 직렬화 오류를 실제로 재현했다. 기존 wrap serializer 패턴을 사용한 최종 코드에서는 schema·dump·왕복·측정값 보존이 통과했다. 최신 시험 PC의 Pydantic 통과를 구형 이미지 수용으로 대체하지 않는다.
- FULL의 기존 G1 timing 항목은 병렬 부하에서 실패했고 native 재시도는 fsync 한계로 skip이었다. 이 실패·skip을 통과로 바꾸지 않았다. 변경 전 main과 후보의 별도 timing suite는 각각 12 passed였다. 최종 FULL은 동일 네 묶음·동일 파일을 유지하고, timing 포함 묶음만 native `ROSY_BROWSER_ALONE=1 -n 0`으로 격리했다. 격리 묶음은 5137 passed/123 skipped, NEW/known/flaky 0이다. `tools/land_isolation.py`에도 timing 파일의 프로세스 경쟁 제약이 기록돼 있다.

## 근거 위치와 다음 게이트

외부 scratch 원본: `rosy-pipeline-g1-{baseline,export-red,export-green,source-order-mutation,source-order-restored,compat-green,full,full-final,full-compatible}/`, `g1-pydantic-{ad164043f6-544dd1,66ba49bef8-5366df}.log`, `harbor-g1-ac24038347-90f4f8.log`. 원래 실패 결과를 덮거나 known-failure 목록에 추가하지 않았다. 구형 의존성 assertion은 원격의 격리 환경에서 고정 source를 읽었으며 제품 의존성·시스템 설치를 바꾸지 않았다.

최종 FULL 원본 `run-1.txt`~`run-4.txt`의 SHA-256:

```text
1 a564733db0cac8a97bd0673f1d8ee91daab12dd5875f9843f1f442516b26fee8
2 dd2d38de06508a7c5d2c03eaec67d6ea37c412571ec898b863342d539c218f62
3 7e69240378c1db8cda0e1a1690fb8981d2b6004b7bae7d0baf2fc810994d96be
4 057cd5a6b6e674df4e556e344036b0acb8811cc89d25c282879e471ff8e00ad1
```

독립 contract/Safety 검토와 최종 branch 검토에서 A/B owner 대응·legacy 빈 binding·optional wire 변환·Pydantic 호환 수정 후 남은 material finding은 없었다. 소스 검토는 장치 안전 인증이 아니다.

별도 수동 Gazebo 진단에서는 원본 JointState/Pose_V/clock을 각각 8개 관측했으나 원본 stamp는 sim 시작 후 4~130ms였고 UTC가 아니었다. 검증된 UTC mapping·오차 한계·전체 link velocity/gripper/held 생산자는 아직 없다. D-915 UTC 계약을 수신 시각으로 채우지 않는다. 새로운 SIM source-clock/epoch·PRE/POST 인과 anchor 계약과 실제 전체 측정이 G1c의 다음 게이트다. 기존 source·하드웨어 활성화 경계는 유지한다.

CE: 해당 없음 — 해결한 판단은 D-915·회귀·이 검증 기록에 남긴다. 미해결 source-clock 결손은 해결 교훈으로 기록하지 않았다.
