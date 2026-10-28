# 모델 출처 조회 검증

2026-10-21 · SOURCE/native host 범위. 학습·모델 품질·로봇 수용은 HOLD.

계약: [설계](../../plans/2026-10-21-model-lineage-design.md).
기존 registry owner에 사설 읽기 전용 조회를 추가했다. intake pass는 기록된 값으로만 출력하고
source proof, human review, training receipt는 검증되지 않은 누락으로 남긴다.

| 코드 revision | 실제 native 실행 | 결과 |
|---|---|---|
| `c685d9489f` | lineage RED | 13 failed, 모두 아직 없는 model_lineage 모듈 호출에서 실패; collection 오류 없음 |
| `1b5abdaf12` | lineage/delivery/store | 127 passed, 3 skipped, exit0, known_failures NEW0 |
| `3d8442651d` | 같은 selection + 경로/JSON 거절 3개 | 130 passed, 3 skipped, exit0, known_failures NEW0 |

중간 요청은 존재하지 않는 `test_model_store.py`를 지정해 exit4/no tests였다.
올바른 `test_store.py`로 재실행한 위 결과만 검증으로 사용한다. 반복 실행 수를 합산하지 않는다.
3개 skip은 기존 store의 Windows 전용 긴 경로 회귀(absolute/relative/extended)이며,
Linux native 실행에서 검사한 것으로 세지 않는다.

한 후보의 model files, dataset/eval 내용 해시, intake 후보/파일 결속을 검사한다.
옛 eval 절대 경로는 현재 store 내 name/content SHA로만 연결한다. 다른 후보 receipt,
변조, symlink 탈출, 잘못된 eval 경로, JSON 오류를 거절한다. CLI 입력 파일은 변경하지 않는다.
pointer journal은 같은 후보 행만 반환하며 소비자 mismatch를 그대로 보존한다.

fresh-context 전체 브랜치 계약 검토(`model_lineage_branch_review`)는 실제
export/intake/Store/pointer producer 경로를 확인했고 Critical/Important/Minor 지적이 없었다.
리뷰 자체가 원격 시험을 재실행하거나 private 자료·장치를 확인했다는 뜻은 아니다.

이 기록은 새 후보 생성·READY 입고·실제 전달·장치 readback을 수행했다는 증거가 아니다.
현재 자료에서 독립 사람 검수·원본 증빙을 새로 만들어 주지 않는다. CI와 실기 검증은 별도다.
