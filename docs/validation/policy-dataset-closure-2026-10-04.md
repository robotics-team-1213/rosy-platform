# 정책 원장의 DatasetManifest·Episode 파일 교차검증

2026-10-04 KST. 기존 원장에서 참조만 보존하던 dataset revision을 실제
DatasetManifest·공통 Episode·원본 파일 snapshot에 연결했다. D-449 Proposed 후속이다.

## 실제 등록·재독출

seed42751 ACT dataset `8dda786b742bebbd5eae5453f2db60534a22984c5e1943a99de92bb7f0b608bf`의
**6 Episodes / 234 files**를 별도 CLI로 등록했다. DatasetManifest의 전체 files
SHA/bytes, 실제 공통 Episode manifest canonical revision 목록, 각 Episode
sources/streams/outcome evidence가 선언된 dataset files에 같은 SHA/bytes로
포함되는지 확인했다. 복사 뒤에도 closure와 원본 canonical metadata를 다시 비교했다.

원장: `X:/DevTemp/rosy-learning-audit-20261004/policy-registry/datasets/`.
별도 process 재독출:
`X:/DevTemp/rosy-learning-audit-20261004/policy-dataset-readback.json`.
실제 정책 `ede80a29f56e210bf814a4e888d931ed1462c2dc42eb374dfb0c611b0aa6dca9`가
참조하는 dataset revision과 매칭했다. 재등록은 idempotent이고 정책 stage는
**unregistered**, 기존 ACT 평가는 **reject** 그대로다.

## 검증·승격 전제 조건

SQLite 등록과 immutable 파일 snapshot을 구현했다. source 변조가 보존본에
영향을 주지 않고, 보존본 손상·미등록/잘못된 revision·누락 Episode나 undeclared
stream은 거절한다. 정책 promote와 과거 promote의 audit도 DatasetStore를 통해
모든 참조 dataset 파일을 재검증한다. dataset이 없으면 signed pass 보고서가
있어도 승격할 수 없다. 이 gate는 RED 재현 후 구현했다.

- dataset/registry/공통 계약: **42 passed**.
- 소유/import 방향·모듈 구조: **51 passed**.
- 독립 리뷰: **41 passed**, 실제 SQLite를 read-only로 열어 6 Episodes/234 files
  closure를 재검증했다. blocking/nonblocking findings 없음, 리뷰어 파일 변경 없음.
- dataset_store.py source SHA:
  `d52e8c17a99343d4d5747c60db2cc359dc2cd00ad2e9d94e6d4072dcb4da6d1c`.
- registry.py source SHA:
  `3407ce54f71c31c757e8e65fd5b84a404b019d0ca2222cb42e405fc7acb8d601`.
- 문서 배치/harness **65 passed**, generate 완료, lint **0 errors/기존 26 warnings**.
- 실제 snapshot/SQLite·재독출·실행 소스 bundle:
  `X:/DevTemp/rosy-learning-audit-20261004/policy-dataset-closure-evidence.zip`,
  1,191,906 bytes, SHA
  `f530825c415711a66af730ab62e7927259128a784764e06f8e912ec07d3bb29f`.

## 남은 범위

이는 metadata·실제 파일 무결성 증거다. stream sample body의 단위/시계/profile
validator 이동(Q6), 라벨/독립 과제 진위, split 설계의 충분성·모델 성능 수용을
인증하지 않는다. 원본 bytes는 그대로 보존한다. owner 실행/lease/generation/
stale/HOLD·stop-readback rollback·Pinky/Fleet/Isaac 연결은 남아 있다.
모델 PC 인증은 미해결이며 이전 SSH는 terminal 실패 상태다. 전체 목표는 active다.
