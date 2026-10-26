# 로봇별 하중 특성·후보 평가·수동 관측 검증

## 구현과 검증 범위

장비·모터 그룹·하드웨어·보정·모델·설치·도구·보조 장치에 결속된 특성 JSON 저장/검증, 실측 범위에 대한 quintic 궤적 평가, 기존 모터 snapshot을 이용한 읽기 전용 감시를 구현했다. 사용법과 필드 계약은 [모듈 문서](../../../middleware/devices/omx/adapter/docs/load-aware-motion.md)에 있다.

모든 결과는 `motion_admitted=false`, `automatic_recovery_enabled=false`다. 명령 ID·시작 시각·궤적의 실행 소유자 receipt 결속은 아직 없어 `command_binding=caller_supplied_unverified`를 표시한다. 모터 상태 비교가 실제 실행 명령·보정·도구의 일치를 증명하거나 기존 owner의 정지·복구를 대신하지 않는다.

## 원격 시험 증거

기준 커밋은 `3125704e24244591d9e2e43032034d8efe14a6f2`다. 승인된 모델 PC/AI PC의 committed-revision remote runner를 사용했으며 노트북 pytest, 로봇 접근, 배포나 실물 동작은 하지 않았다. 시험 전 두 시험 PC의 저장 공간이 30 GiB 이상이고 사용률이 90% 미만임을 확인했다.

| 검증 | 커밋 | 결과 |
|---|---|---|
| 기존 real 하위 패키지의 크기 단위 등록 | `cfe161f333` | 원격 module structure 46건 통과, 새 실패 0 |
| JSON 계약·원자적 저장 | `a5802fb8cd` | 25건 통과; 선행 `ce469081ac`에서는 미구현 모듈로 예상 실패 |
| 계약·전 구간 후보 평가 | `793ad81bf2` | 56건 통과; 선행 미구현 상태의 예상 실패 확인 |
| 기존 생산자와 새 기능 통합 | `1e6e71dfca` | 110건 통과; native producer → snapshot reader → monitor를 합성 버스로 검증 |
| 영향 선택 58개 시험 경로 | `00581175c49704d48a2eeada711fd20486c620a8` | 2,079 통과, 22 skipped, 2 실패. 두 실패는 새 로그 제목 형식에 의한 harness 검사였다. |
| 로그 형식 수정·생성 색인·문서 배치 | `aec7f05a35` | 원격 harness/document placement/folder layout 122건 통과; 기준 실패 비교 0 NEW, 0 known, 0 flaky |

넓은 회귀 실행과 기록 수정 사이의 Python/JSON/YAML/XML/TXT 제품·시험 소스 diff는 비어 있다. 최종 두 실패를 고친 뒤 관련 기록·배치 시험을 다시 실행했으며 전체 58개 경로를 재실행했다고 주장하지 않는다. 22 skipped는 통과로 계산하지 않는다. 해당 실행의 `-rfE` 출력에는 개별 skip 이유가 없으므로 이 기록에서 임의로 분류하지 않는다.

영향 선택과 실행 방법:

```text
python tools/harness/rosy_harness.py affected --base 3125704e24244591d9e2e43032034d8efe14a6f2 --head 00581175c4 --json
python tools/remote/remote_pytest.py --sha 00581175c4 --log-dir <external-log-dir> --affected-json -
python tools/remote/remote_pytest.py --sha aec7f05a35 --log-dir <external-log-dir> -- test/test_harness_contracts.py test/architecture/test_document_placement.py test/architecture/test_folder_layout.py -q
```

두 번째 명령은 첫 명령의 JSON을 stdin으로 받았다. 모든 원격 로그는 외부 scratch의 `rosy-load-aware/` 아래에 보관했다. 최종 보존 위치는 Git 밖 작업 기록에서 관리하며 공개 기록에 실제 계정·호스트를 적지 않는다.

| 원본 보고서 | SHA256 |
|---|---|
| `final-affected/run-1.txt` | `11788caf0617e2c1be263555e292c30d5df64449131238a937e841a162d5c6da` |
| `final-record-check/run-1.txt` | `0bdff077b42f98662aa933c8907c7dc3a4049707b39d9d7c6d41a62b9981bb0f` |

추가 정적 검사: 새 Python 파일 flake8(120열) 통과, 기준부터 문서 초안 커밋까지의 13개 커밋 size-range 검사 통과. 프로젝트 의존성은 추가하지 않았다. CI, 전체 저장소 시험, ROS transport, ARM64 payload, 실물·현장 수용 증거는 아니다.

## 독립 검토와 수정

읽기 전용 독립 검토자는 실제 생산자→판독기→소비자를 추적했다. 아래 결함은 시험에서 먼저 재현한 뒤 수정했다.

- 기존 native 생산자에 오류·토크 상태가 없고 group과 owner가 달라 항상 미확인으로 끝남: 명시적 `motor_group` 결속과 기존 소유자의 RAM 상태 발행으로 수정했다. 버스 소유자를 추가하지 않았다.
- 같은 capture가 반복될 때 age 한계 이전에 gap 한계를 넘겨도 관측을 계속함: 중복 polling도 선택 그룹의 receipt gap과 age를 확인한다.
- 다른 팔만 갱신될 때 선택 팔 표본을 재소비하거나 정상 표본을 거절함: capture·signature·receipt를 관절별로 유지하고 같은 표본은 추종·진동 계산에서 다시 세지 않는다.

마지막 소스 `d19f57cf41` 재검토에서 이전 지적이 해소되었으며 새로 뒷받침되는 중대한 결함이 없다는 결과를 받았다. 이 검토는 독립 시험 실행이나 장치 안전 인증을 뜻하지 않는다.

## 남은 수용과 CE

실제 raw→radian 보정, 장비 신원 및 구성의 실행 receipt 결속, 인증된 자세·하중·COM·열·전압·반복 동작 영역은 아직 없다. native hook의 추가 RAM 읽기가 장치 제어 주기에 미치는 영향과 관측 주파수가 떨림을 포착하는지도 실물에서 별도로 수용해야 한다. 스톨 토크나 PWM 비율로 연속 토크를 만들어 채우지 않았다.

최종 자세를 버틸 수 없으면 경로 변경만으로 해결되지 않는다. 자동 정지·안전 내려놓기·대체 경로 실행은 활성화하지 않았다. 실제 owner 연동 전에는 이 결과를 실행 interlock으로 사용하지 않는다.

CE: 해당 없음 — 기존 처짐 교훈을 적용했다. 새 구현의 판단과 검토 수정은 계약·생산자/소비자 회귀 시험·모듈 문서에 남아 있어 별도의 교훈 문서가 필요한 비자명한 해결 지식은 없다. 물리적 처짐·떨림의 원인이나 해결을 검증했다고 주장하지 않는다.
