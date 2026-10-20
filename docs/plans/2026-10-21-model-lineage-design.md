# 모델 출처 조회 계약

2026-10-21 · B1 구현 범위. 조회는 기존 owner의 파일을 읽으며 승인·승격·전달을 수행하지 않는다.

## 확인한 후보와 공백

모델PC의 기존 `lane-seg-20261004-3170974c`는 model manifest에서
`store:d379-auto-lanes-v2`의 content revision을 참조한다. 입고 보고서는 같은 후보의
파일 해시와 evalset content SHA를 보유하지만 `tool_commit`은 null이다. 관측한 dataset과
evalset은 자동 라벨 builder의 산출물이다. 과거 pass를 사람 검수 또는 현재 수용으로 해석하지 않는다.
일부 다른 후보의 보고서는 접근 권한이 없어 확인하지 않았다. 현장 주소와 원본 증거는 외부 작업 기록에 둔다.

## 파일과 인터페이스

`learning/registry/perception/model_lineage.py`의
`inspect_model(models, store, revision, *, journal=None) -> dict`와 같은 인자의 CLI를 추가한다.
`--models`는 기존 intake 출력 루트, `--store`는 기존 Store 루트, `--revision`은 정확한 후보다.
선택적인 `--journal`은 기존 `pointer_changes.jsonl` 파일이다. JSON은 이 조회 도구의 사설 출력이며
public API/schema를 추가하지 않는다. CLI exit 0은 조회 성공, 2는 입력/무결성 오류다.
누락이 있어도 읽을 수 있는 연결은 반환하며 `missing` 배열에 빠진 증거를 적는다.

| 출력 | 읽는 정본 / 책임 | 확인 범위 |
|---|---|---|
| model | export의 `model_manifest.json` 및 named model files | 기존 `load_manifest`, `verify_files`, 파일 해시 |
| dataset | manifest의 `dataset.repo`와 `dataset.revision` | `store:<name>`과 64hex의 정확한 경로, 기존 `read_fixed_manifest` |
| eval | intake의 `eval.set.path/content_sha` | evalsets 아래 name/SHA로 현재 store에서 해시 검증; 옛 절대 경로는 읽지 않음 |
| intake | `<models>/<revision>/intake_report.json` | model revision 및 files 일치, 보고서 자체 SHA; verdict는 기록된 값 |
| delivery | 명시한 기존 pointer journal | 같은 pointer revision의 행만, 기존 schema 확인; consumer 불일치를 match로 바꾸지 않음 |

dataset/eval manifest의 sources와 builder는 **선언된 메타데이터**로 표시한다.
원본 촬영 파일, 사람 검수 권한, 학습 job receipt는 이번 입력으로 검증할 수 없어 항상 누락으로 남긴다.
`tool_commit`이 없으면 추가 누락이다. 새로운 DB, owner 검색, READY 생성, 서명/품질 판단,
훈련 job 경로 추측, 로봇 접속, 기존 전달 CLI 변경은 범위 밖이다.

## 실패와 보존

후보 revision의 경로 탈출·symlink, 파일/고정 자료의 해시 변조, 다른 후보의 입고 보고서,
입고 files 불일치, malformed JSON은 오류다. 외부 절대 경로를 자료 위치로 신뢰하지 않는다.
명명된 자료 부재는 누락이며 다른 후보/다른 이름을 대신 연결하지 않는다.
출력은 실행 시점의 진단이며 여러 owner 원장의 원자적 snapshot이나 현재 운영 상태가 아니다.
어떤 입력도 쓰거나 이동하지 않는다. 출력 보존은 호출자가 기존 외부 증거 경로로 담당한다.

## 계약 검토 및 완료 조건

D-427의 기존 learning registry 책임, D-516 호스트 역할, 기존 intake/Store와 pointer journal을 유지한다.
recording catalogue 및 signed source import를 수정하지 않는다. CORE 명령·admission 경로가 없고
새 public 계약이 없어 ADR/API 예약은 필요하지 않다.
`test/learning/perception/test_model_lineage.py`에서 한 후보 조회, 누락, 다른 후보 receipt,
모델/dataset/eval 변조, 경로 탈출, journal 불일치와 read-only CLI를 원격 RED→GREEN으로 확인한다.
